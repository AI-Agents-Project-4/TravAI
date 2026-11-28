"""TravAI research agent: request -> schema-valid research output.

Deterministic pipeline; `claude -p` is used only for judgment steps (resolve destinations, enrich places, web price search).
Every external call is cached, so `offline=True` replays a past run with zero API spend."""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from jsonschema import Draft202012Validator

from . import sources
from .activities import TIER_MULT, build_activities
from .core import ROOT, ApiError, CacheMiss, claude_json, set_cache_ttl
from .pricing import make_price, now_iso

SCHEMA = json.load(open(os.path.join(ROOT, "schema", "research_output.schema.json"), encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

RESOLVE_SCHEMA = {"type": "object", "required": ["origin_airport", "stops", "notes"], "properties": {
    "origin_airport": {"type": ["string", "null"], "description": "IATA code of the main airport for the origin, or null"},
    "notes": {"type": "array", "items": {"type": "string"}},
    "stops": {"type": "array", "items": {"type": "object", "required": [
        "query", "city", "country", "country_code", "airports", "local_currency", "advisory_country", "cost_tier",
        "daily_cost_usd", "wikivoyage_title"], "properties": {
        "query": {"type": "string"}, "city": {"type": "string"}, "country": {"type": "string"},
        "country_code": {"type": "string"},
        "airports": {"type": "array", "items": {"type": "string"}},
        "local_currency": {"type": "string"},
        "advisory_country": {"type": "string"},
        "cost_tier": {"type": "integer", "minimum": 1, "maximum": 4},
        "daily_cost_usd": {"type": "number"},
        "wikivoyage_title": {"type": "string"},
        "assumption": {"type": ["string", "null"]}}}}}}


class Ctx:
    def __init__(self, req: dict, offline: bool, now: datetime, progress=None):
        self.req, self.offline, self.now = req, offline, now
        self.progress = progress
        self.cur = req.get("currency", "USD")
        self.notes: list = []
        self.gaps: list = []
        self.fx = lambda a, b: sources.fx_rate(a, b, offline)

    def gap(self, category: str, reason: str, source: Optional[str] = None):
        g = {"category": category, "reason": reason}
        if source:
            g["source_attempted"] = source
        self.gaps.append(g)

    def log(self, msg: str):
        print(f"[agent] {msg}", file=sys.stderr, flush=True)

    def say(self, stage: str, message: str):
        """Report progress to the caller (for a UI progress screen). Never lets a callback error break the run."""
        self.log(message)
        if self.progress:
            try:
                self.progress(stage, message)
            except Exception:
                pass


def _empty(ctx: Ctx, status: str, rid: str) -> dict:
    return {"request_id": rid, "status": status, "generated_at": now_iso(), "currency": ctx.cur, "advisories": [],
            "flights": [], "lodging": [], "activities": [], "ground_transport": [],
            "feasibility": {"budget": float(ctx.req.get("budget") or 0), "estimated_minimum_total": None,
                            "verdict": "unknown", "reasoning": "Not computed."},
            "gaps": ctx.gaps, "notes": ctx.notes}


def validate_request(req: dict, today: date) -> Optional[str]:
    try:
        start = date.fromisoformat(req["start_date"])
    except (KeyError, ValueError):
        return "start_date missing or not YYYY-MM-DD"
    if start < today:
        return f"start_date {start} is in the past"
    if not req.get("destinations"):
        return "no destination given"
    if int(req.get("duration_days", 0)) < 1:
        return "duration_days must be at least 1"
    if int(req.get("travelers", 0)) < 1:
        return "travelers must be at least 1"
    if float(req.get("budget", 0)) <= 0:
        return "budget must be greater than zero"
    return None


# ---------- resolve ----------

def resolve(ctx: Ctx) -> dict:
    r = ctx.req
    prompt = (
        "Resolve this trip request for a travel research tool.\n"
        f"Origin: {r.get('origin')}\nDestinations (as typed): {r['destinations']}\n"
        f"Start point: {r.get('start_point')}  End point: {r.get('end_point')}\n"
        "Return one stop per destination, in travel order (start point first, end point last if given). "
        "A country or region name means its most-visited city; put the choice in 'assumption'. For an ambiguous "
        "name pick the most famous place and say so in 'assumption' (e.g. Paris -> Paris, France). "
        "airports: IATA codes of up to 2 airports with SCHEDULED COMMERCIAL passenger service today, nearest first; "
        "if the closest airport is closed or has no commercial service (war, remote island), list the nearest operating "
        "alternatives, even in a neighbouring country, and explain in notes; empty list if none exist. "
        "cost_tier: 1 cheap, 2 moderate, 3 expensive, 4 very expensive for a visitor. daily_cost_usd: food plus local "
        "transport per person per day for a mid-range traveller, set high rather than low. advisory_country: the "
        "country's name exactly as the US State Department travel-advisory list names it. wikivoyage_title: the exact "
        "English Wikivoyage article title for the city. origin_airport: IATA of the origin's main airport (or the origin "
        "itself if it is already an IATA code), null if the origin has no airport nearby."
    )
    return claude_json(prompt, RESOLVE_SCHEMA, offline=ctx.offline, timeout=180, max_budget_usd=0.5)


# ---------- flights ----------

def pick_flights(itins: list[dict], n: int = 6) -> list[dict]:
    """Give the planner a price/time trade-off: cheapest, fastest, fewest stops, and cheapest with at most one stop each way."""
    if not itins:
        return []
    dur = lambda i: sum(l["duration_minutes"] for l in (i["outbound"], i.get("inbound")) if l)
    mx = lambda i: max(len(l["segments"]) - 1 for l in (i["outbound"], i.get("inbound")) if l)
    by_price = sorted(itins, key=lambda i: i["price"]["amount"])
    picks = [by_price[0], by_price[1] if len(by_price) > 1 else None, min(itins, key=dur),
             min(itins, key=lambda i: (mx(i), i["price"]["amount"]))]
    one_stop = [i for i in by_price if mx(i) <= 1]
    if one_stop:
        picks += [one_stop[0], min(one_stop[:6], key=dur)]
    picks += by_price[2:5]
    out, seen = [], set()
    for p in picks:
        if p and p["ignav_id"] not in seen:
            seen.add(p["ignav_id"]); out.append(p)
    return out[:n]


def _segments(leg: dict) -> list[dict]:
    return [{"from": s["departure_airport"], "to": s["arrival_airport"], "depart_at": s["departure_time_local"],
             "arrive_at": s["arrival_time_local"], "carrier": s.get("operating_carrier_name") or s.get("marketing_carrier_code", ""),
             "flight_number": f"{s.get('marketing_carrier_code', '')}{s.get('flight_number', '')}"} for s in leg["segments"]]


def _google_flights_link(o: str, d: str, dep: str, ret: Optional[str]) -> str:
    q = f"Flights from {o} to {d} on {dep}" + (f" through {ret}" if ret else "")
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def build_flight(ctx: Ctx, it: dict, direction: str, observed_at: str, o: str, d: str, dep: str, ret: Optional[str]) -> dict:
    link, verified, note = None, False, None
    try:
        b = sources.ignav_booking(it["ignav_id"], ctx.offline)
        opts = [(l, l.get("price", {}) and l["price"].get("amount")) for bo in b["booking_options"] for l in bo["links"]]
        air = [l for l, p in opts if l.get("provider_type") == "airline" and p and abs(p - it["price"]["amount"]) <= 0.02 * it["price"]["amount"]]
        pick = air[0] if air else (min(opts, key=lambda x: x[1] or 1e12)[0] if opts else None)
        if pick:
            link = {"url": pick["url"], "provider": f"ignav:{pick['provider_name']}"}
            p = pick.get("price", {}).get("amount")
            verified = bool(p and abs(p - it["price"]["amount"]) <= 0.02 * it["price"]["amount"])
    except CacheMiss:
        raise
    except ApiError as e:
        note = f"booking-links failed ({e.status}); search link only"
    if not link:
        link = {"url": _google_flights_link(o, d, dep, ret), "provider": "google_flights_search"}
        note = note or "no direct booking link returned; Google Flights search link"
    out_leg, in_leg = it["outbound"], it.get("inbound")
    segs = _segments(out_leg) + (_segments(in_leg) if in_leg else [])
    stops = (len(out_leg["segments"]) - 1) + ((len(in_leg["segments"]) - 1) if in_leg else 0)
    f = {"id": f"fl-{it['ignav_id'][:14]}", "direction": direction, "segments": segs,
         "duration_minutes": out_leg["duration_minutes"] + (in_leg["duration_minutes"] if in_leg else 0), "stops": stops,
         "cabin": it.get("cabin_class") or "economy",
         "price": make_price(it["price"]["amount"], it["price"]["currency"], "live_quote", observed_at, target_currency=ctx.cur,
                             fx=ctx.fx, price_layer="api", basis="total_all_travelers"),
         "source": link, "confidence": {"level": "high" if verified else "medium", "verified": verified}}
    if note:
        f["confidence"]["notes"] = note
    if in_leg:
        f["return_segment_start_index"] = len(out_leg["segments"])
    return f


def _search_flights(ctx: Ctx, o: str, d: str, dep: str, ret: Optional[str], direction: str, n: int) -> list[dict]:
    adults = int(ctx.req["travelers"])
    try:
        data = (sources.ignav_roundtrip(o, d, dep, ret, adults, ctx.offline) if ret else sources.ignav_oneway(o, d, dep, adults, ctx.offline))
    except ApiError as e:
        ctx.gap("flights", f"Ignav {o}->{d} failed: HTTP {e.status} {e.body[:120]}", "ignav")
        return []
    its = data.get("itineraries", [])
    if not its:
        ctx.gap("flights", f"Ignav found no fares {o}->{d} on {dep}", "ignav")
        return []
    picks = pick_flights(its, n)
    with ThreadPoolExecutor(5) as ex:
        return list(ex.map(lambda it: build_flight(ctx, it, direction, data.get("observed_at", now_iso()), o, d, dep, ret), picks))


def flights_step(ctx: Ctx, stops: list, origin: Optional[str], start: date, end: date) -> list[dict]:
    if "flight" not in ctx.req.get("transport_modes", ["flight"]):
        return []
    if not origin:
        ctx.gap("flights", "Could not determine an origin airport", "resolve")
        return []
    out = []
    first, last = stops[0], stops[-1]
    if not first["airports"] or not last["airports"]:
        ctx.gap("flights", f"No commercial airport found for {first['city'] if not first['airports'] else last['city']}", "resolve")
        return []
    if len(stops) == 1 or first["airports"][0] == last["airports"][0]:
        for a in first["airports"][:2]:
            out += _search_flights(ctx, origin, a, start.isoformat(), end.isoformat(), "round_trip", 3)
    else:
        out += _search_flights(ctx, origin, first["airports"][0], start.isoformat(), None, "outbound", 3)
        out += _search_flights(ctx, last["airports"][0], origin, end.isoformat(), None, "return", 3)
    return out


# ---------- lodging ----------

HOTEL_TYPES = {"hotel": "hotel", "hostel": "hostel", "vacation rental": "apartment", "apartment": "apartment",
               "bed and breakfast": "guesthouse", "guest house": "guesthouse"}


def lodging_step(ctx: Ctx, stops: list, start: date, nights: list[int]) -> list[dict]:
    out, cursor = [], start
    for stop, n in zip(stops, nights):
        cin, cout = cursor, cursor + timedelta(days=n)
        cursor = cout
        if n <= 0:
            continue
        adults = min(int(ctx.req["travelers"]), 2)
        try:
            data = sources.serp_hotels(f"{stop['city']} hotels", cin.isoformat(), cout.isoformat(), adults, ctx.cur, ctx.offline)
        except ApiError as e:
            ctx.gap("lodging", f"SerpApi hotels failed for {stop['city']}: HTTP {e.status}", "serpapi_google_hotels")
            continue
        props = [p for p in data.get("properties", []) if p.get("gps_coordinates") and (p.get("rate_per_night") or {}).get("extracted_lowest")]
        if not props:
            ctx.gap("lodging", f"No priced hotels returned for {stop['city']}", "serpapi_google_hotels")
        for p in props[:12]:
            link = p.get("link") or ("https://www.google.com/search?q=" + urllib.parse.quote(f"{p['name']} {stop['city']} hotel"))
            direct = bool(p.get("link"))
            night = float(p["rate_per_night"]["extracted_lowest"])
            total = float((p.get("total_rate") or {}).get("extracted_lowest") or night * n)
            ts = now_iso()
            kw = dict(target_currency=ctx.cur, fx=ctx.fx, price_layer="api")
            lod = {"id": f"ho-{p.get('property_token', p['name'])[:14]}", "name": p["name"],
                   "type": HOTEL_TYPES.get((p.get("type") or "hotel").lower(), "other"),
                   "location": {"lat": p["gps_coordinates"]["latitude"], "lng": p["gps_coordinates"]["longitude"]},
                   "area": stop["city"], "check_in": cin.isoformat(), "check_out": cout.isoformat(),
                   "rating": p.get("overall_rating"), "review_count": p.get("reviews"),
                   "price": {**make_price(night, ctx.cur, "published_rate", ts, **kw), "basis": "per_night", "includes_taxes_fees": True},
                   "total_stay_price": {**make_price(total, ctx.cur, "published_rate", ts, **kw), "basis": "per_group", "includes_taxes_fees": True},
                   "source": {"url": link, "provider": "serpapi_google_hotels"},
                   "confidence": {"level": "medium", "verified": False,
                                  **({} if direct else {"notes": "no direct booking link; search link"})}}
            out.append(lod)
    return out


# ---------- advisories ----------

def advisories_step(ctx: Ctx, stops: list) -> list[dict]:
    try:
        feed = sources.advisories(ctx.offline)
    except (ApiError, CacheMiss) as e:
        ctx.gap("advisories", f"State Dept feed unavailable: {type(e).__name__}", "travel.state.gov")
        return []
    out, seen = [], set()
    for s in stops:
        name = s["advisory_country"].lower()
        if name in seen:
            continue
        seen.add(name)
        hit = next((a for a in feed if a["country"].lower() == name), None)
        if not hit:
            if s["country_code"].upper() != "US":
                ctx.gap("advisories", f"No US State Dept advisory entry found for {s['advisory_country']}", "travel.state.gov")
            continue
        conflict = bool(re.search(r"armed conflict|war|missile|military|drone|hostilit", hit["summary"], re.I))
        rel = "poor" if hit["level_num"] == 4 and conflict else "uncertain" if hit["level_num"] >= 3 else "good"
        out.append({"level": hit["level"], "region": s["advisory_country"], "summary": hit["summary"][:400],
                    "map_data_reliability": rel, "source_url": hit["link"], "retrieved_at": now_iso()})
    return out


# ---------- ground transport ----------

def _est(ctx: Ctx, usd: float, basis: str, method: str, **kw) -> dict:
    return make_price(round(usd, 2), "USD", "estimate", now_iso(), target_currency=ctx.cur, fx=ctx.fx, estimate_method=method,
                      price_layer="category_estimate", basis=basis, **kw)


def _r2r(a: str, b: str) -> str:
    return "https://www.rome2rio.com/map/" + urllib.parse.quote(a) + "/" + urllib.parse.quote(b)


def transport_step(ctx: Ctx, stops: list, origin_geo: Optional[dict], start: date, nights: list[int]) -> tuple[list, list]:
    legs, flights = [], []
    modes = ctx.req.get("transport_modes", ["flight"])
    trav = int(ctx.req["travelers"])
    days = int(ctx.req["duration_days"])
    # origin -> first stop by road
    if "drive" in modes and origin_geo:
        r = sources.route((origin_geo["lat"], origin_geo["lon"]), (stops[0]["lat"], stops[0]["lon"]), "drive", ctx.offline)
        if r and r["duration_minutes"] <= 16 * 60:
            legs.append({"id": "gt-origin-drive", "mode": "drive", "from": ctx.req["origin"], "to": stops[0]["city"],
                         "from_geo": {"lat": origin_geo["lat"], "lng": origin_geo["lon"]}, "to_geo": {"lat": stops[0]["lat"], "lng": stops[0]["lon"]},
                         "distance_km": r["distance_km"], "duration_minutes": r["duration_minutes"],
                         "price": _est(ctx, r["distance_km"] * 0.15, "per_group", "Fuel at about $0.15/km for one car; excludes parking and tolls."),
                         "source": {"url": _r2r(ctx.req["origin"], stops[0]["city"]), "provider": "geoapify_routing"},
                         "confidence": {"level": "medium", "verified": False, "notes": "Distance/time from Geoapify; cost is an estimate."}})
    # airport -> city
    if "flight" in modes:
        for s in stops:
            if not s["airports"]:
                continue
            g = sources.geocode(f"{s['airports'][0]} airport, {s['country']}", ctx.offline, s["country_code"])
            if not g:
                continue
            r = sources.route((g["lat"], g["lon"]), (s["lat"], s["lon"]), "drive", ctx.offline)
            if r:
                far = r["distance_km"] > 80    # the arrival airport is not really "in" the city (e.g. flying to a neighbouring country)
                if far:
                    price = _est(ctx, r["distance_km"] * 0.08 * TIER_MULT[s["cost_tier"]], "per_person",
                                 "Intercity bus/train estimate: $0.08/km scaled by cost tier. A taxi would cost far more.")
                else:
                    price = _est(ctx, (4 + 1.8 * r["distance_km"]) * TIER_MULT[s["cost_tier"]], "per_group",
                                 "Taxi estimate: $4 base + $1.80/km, scaled by country cost tier. Public transit is usually cheaper.")
                legs.append({"id": f"gt-apt-{s['airports'][0]}", "mode": "bus" if far else "taxi", "from": f"{s['airports'][0]} airport", "to": s["city"],
                             "from_geo": {"lat": g["lat"], "lng": g["lon"]}, "to_geo": {"lat": s["lat"], "lng": s["lon"]},
                             "distance_km": r["distance_km"], "duration_minutes": r["duration_minutes"], "price": price,
                             "source": {"url": _r2r(f"{s['airports'][0]} airport", s["city"]), "provider": "geoapify_routing"},
                             "confidence": {"level": "low", "verified": False,
                                            "notes": "Road route from Geoapify (may be inaccurate where map data is uncertain, and border waits are not included); fare is an estimate."}})
    # between stops
    cursor = start
    for i in range(len(stops) - 1):
        a, b = stops[i], stops[i + 1]
        cursor += timedelta(days=nights[i])
        r = sources.route((a["lat"], a["lon"]), (b["lat"], b["lon"]), "drive", ctx.offline)
        km = r["distance_km"] if r else None
        if "drive" in modes and r:
            legs.append({"id": f"gt-drive-{i}", "mode": "drive", "from": a["city"], "to": b["city"],
                         "from_geo": {"lat": a["lat"], "lng": a["lon"]}, "to_geo": {"lat": b["lat"], "lng": b["lon"]},
                         "distance_km": km, "duration_minutes": r["duration_minutes"],
                         "price": _est(ctx, km * 0.15, "per_group", "Fuel at about $0.15/km; excludes tolls and parking."),
                         "source": {"url": _r2r(a["city"], b["city"]), "provider": "geoapify_routing"},
                         "confidence": {"level": "medium", "verified": False}})
        if "train" in modes:
            dist = km or 0
            if dist:
                legs.append({"id": f"gt-train-{i}", "mode": "train", "from": a["city"], "to": b["city"], "distance_km": dist,
                             "duration_minutes": round(dist / 90 * 60 + 30),
                             "price": _est(ctx, dist * 0.14 * TIER_MULT[b["cost_tier"]], "per_person",
                                           "No live train data source. Estimate: $0.14/km scaled by cost tier; time at 90 km/h average + 30 min."),
                             "source": {"url": _r2r(a["city"], b["city"]), "provider": "estimate"},
                             "confidence": {"level": "low", "verified": False, "notes": "No live rail pricing; check the link."}})
            else:
                ctx.gap("ground_transport", f"No train data for {a['city']} -> {b['city']}", "estimate")
        if "flight" in modes and a["airports"] and b["airports"] and a["airports"][0] != b["airports"][0]:
            flights += _search_flights(ctx, a["airports"][0], b["airports"][0], cursor.isoformat(), None, "intercity", 2)
    if "drive" in modes and "flight" in modes and stops[0]["airports"]:
        days_total = max(1, days)
        s0 = stops[0]
        legs.append({"id": "gt-car-rental", "mode": "drive", "from": s0["city"], "to": s0["city"], "duration_minutes": 0,
                     "price": _est(ctx, 60 * days_total * TIER_MULT[s0["cost_tier"]], "per_group",
                                   f"Rental car estimate: $60/day x {days_total} days, scaled by cost tier; excludes fuel and insurance."),
                     "source": {"url": "https://www.google.com/search?q=" + urllib.parse.quote(f"car rental {s0['city']}"), "provider": "estimate"},
                     "confidence": {"level": "low", "verified": False, "notes": "Estimate only; no rental price source."}})
    return legs, flights


# ---------- feasibility ----------

def _norm(price: dict) -> float:
    return price.get("amount_normalized", price["amount"])


def feasibility_step(ctx: Ctx, out: dict, stops: list, nights_total: int) -> dict:
    trav, days = int(ctx.req["travelers"]), int(ctx.req["duration_days"])
    budget = float(ctx.req["budget"])
    parts: dict = {}
    reasons = []
    # flights: cheapest round trip, or cheapest outbound + cheapest return, plus cheapest intercity legs
    fl = out["flights"]
    rt = [f for f in fl if f["direction"] == "round_trip"]
    if rt:
        parts["flights"] = min(_norm(f["price"]) for f in rt)
    elif [f for f in fl if f["direction"] == "outbound"] and [f for f in fl if f["direction"] == "return"]:
        parts["flights"] = min(_norm(f["price"]) for f in fl if f["direction"] == "outbound") + min(_norm(f["price"]) for f in fl if f["direction"] == "return")
    inter = [f for f in fl if f["direction"] == "intercity"]
    if inter:
        legs: dict = {}
        for f in inter:
            k = (f["segments"][0]["from"], f["segments"][-1]["to"])
            legs[k] = min(legs.get(k, 1e12), _norm(f["price"]))
        parts["intercity_flights"] = sum(legs.values())
    # ground transport (cheapest per pair is hard to tell apart; count origin drive + car rental + one intercity leg per gap)
    gt = out["ground_transport"]
    road = [g for g in gt if g["id"] == "gt-origin-drive"]
    if road and road[0].get("price"):
        parts["driving"] = _norm(road[0]["price"])
    rental = [g for g in gt if g["id"] == "gt-car-rental"]
    if rental and rental[0].get("price") and "flight" in ctx.req.get("transport_modes", []):
        parts["car_rental"] = _norm(rental[0]["price"])
    # lodging: median of the three cheapest nightly prices (err high), rooms for 2 per room
    if nights_total > 0:
        rooms = math.ceil(trav / 2)
        by_city: dict = {}
        for l in out["lodging"]:
            by_city.setdefault(l["area"], []).append(_norm(l["price"]))
        if by_city:
            cost = 0.0
            for s, n in zip(stops, _nights_cache(ctx, len(stops), nights_total)):
                prices = sorted(by_city.get(s["city"], []))[:6]
                if prices and n:
                    cost += prices[len(prices) // 2] * n * rooms
            parts["lodging"] = cost
    # food + local transport
    daily = sum(s["daily_cost_usd"] for s in stops) / len(stops)
    parts["food_and_local_transport"] = daily * (sum(1 for _ in range(days))) * trav * ctx.fx("USD", ctx.cur)
    needed = {"flights": "flight" in ctx.req.get("transport_modes", ["flight"]), "lodging": nights_total > 0}
    missing = [k for k, need in needed.items() if need and k not in parts]
    parts = {k: round(v, 2) for k, v in parts.items()}
    total = round(sum(parts.values()), 2)
    if missing:
        return {"budget": budget, "estimated_minimum_total": None if not parts else total, "verdict": "unknown",
                "reasoning": f"Could not price: {', '.join(missing)}. Partial total of what was priced: {total} {ctx.cur}.", "breakdown": parts}
    ratio = total / budget
    # The estimate assumes mid-range food and a median-priced cheap hotel, so it is only good to roughly +/-15%.
    # Declare a trip impossible only when it is clearly over, not on a small overshoot.
    MARGIN = 1.15
    verdict = ("comfortable" if ratio <= 0.65 else "tight" if ratio <= 0.85 else "very_tight" if ratio <= MARGIN else "likely_impossible")
    biggest = max(parts, key=parts.get)
    reasoning = (f"Cheapest realistic combination comes to about {total:,.0f} {ctx.cur} against a budget of {budget:,.0f} "
                 f"({ratio:.0%}). Largest cost: {biggest.replace('_', ' ')} ({parts[biggest]:,.0f}). Flight and lodging use live prices; "
                 "food and local transport are estimates set high. Activities are not included.")
    if 1.0 < ratio <= MARGIN:
        reasoning += (" The estimate is slightly over budget but within its margin of error; it may only work with the cheapest "
                      "flights, lodging and meals, and the planner should say so.")
    return {"budget": budget, "estimated_minimum_total": total, "verdict": verdict, "reasoning": reasoning, "breakdown": parts}


_NIGHTS: dict = {}


def _nights_cache(ctx, n_stops, total):
    return split_nights(total, n_stops)


def split_nights(total: int, n: int) -> list[int]:
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


# ---------- main ----------

def run(req: dict, *, offline: bool = False, now: Optional[datetime] = None, progress=None,
        cache_ttl_hours: Optional[float] = None) -> dict:
    """Run the research pipeline.

    progress(stage, message): optional callback for UI updates (stages: resolve, search, flights, lodging, activities,
        transport, feasibility, done).
    cache_ttl_hours: cached API/LLM results older than this are refetched. None keeps everything (tests, replay);
        use ~24 in production so prices do not go stale. Process-wide: concurrent runs share the setting.
    """
    set_cache_ttl(cache_ttl_hours)
    now = now or datetime.now(timezone.utc)
    ctx = Ctx(req, offline, now, progress)
    rid = req.get("request_id") or uuid.uuid4().hex[:12]
    err = validate_request(req, now.date())
    if err:
        ctx.notes.append(f"Invalid request: {err}")
        ctx.gap("other", f"Request rejected before any search: {err}")
        return _finish(_empty(ctx, "error", rid))

    ctx.say("resolve", "Working out where you are going")
    res = resolve(ctx)
    ctx.notes += res.get("notes", [])
    stops = []
    for s in res["stops"]:
        if s.get("assumption"):
            ctx.notes.append(f"Assumption for '{s['query']}': {s['assumption']}")
        g = sources.geocode(f"{s['city']}, {s['country']}", offline, s["country_code"])
        if not g:
            ctx.gap("other", f"Could not locate {s['city']}", "geoapify")
            continue
        stops.append({**s, "trip_days": int(req["duration_days"]), "airports": [a.upper() for a in s["airports"] if re.fullmatch(r"[A-Za-z]{3}", a)], "lat": g["lat"], "lon": g["lon"]})
    if not stops:
        return _finish(_empty(ctx, "error", rid))

    start = date.fromisoformat(req["start_date"])
    days = int(req["duration_days"])
    end = start + timedelta(days=days)
    nights_total = days if days > 1 else 0
    nights = split_nights(nights_total, len(stops))
    ctx.notes.append(f"Dates: {start} to {end}; {nights_total} night(s) of lodging. Flight prices are totals for all {req['travelers']} traveler(s).")
    if int(req["travelers"]) > 2:
        ctx.notes.append("Hotel prices are per room for up to 2 adults; the feasibility estimate assumes ceil(travelers/2) rooms.")

    origin = req["origin"].upper() if re.fullmatch(r"[A-Za-z]{3}", req["origin"]) else res.get("origin_airport")
    origin_geo = None
    if not re.fullmatch(r"[A-Za-z]{3}", req["origin"]):
        origin_geo = sources.geocode(req["origin"], offline)

    out = _empty(ctx, "ok", rid)
    ctx.say("search", f"Searching flights, hotels and things to do in {', '.join(s['city'] for s in stops)}")
    with ThreadPoolExecutor(4) as ex:
        f_fl = ex.submit(flights_step, ctx, stops, origin, start, end)
        f_lo = ex.submit(lodging_step, ctx, stops, start, nights)
        f_ad = ex.submit(advisories_step, ctx, stops)
        f_ac = [ex.submit(build_activities, s, offline, ctx.cur, ctx.fx, ctx.notes, ctx.gaps) for s in stops]
        out["flights"], out["lodging"], out["advisories"] = f_fl.result(), f_lo.result(), f_ad.result()
        out["activities"] = [a for f in f_ac for a in f.result()]
    ctx.say("flights", f"Found {len(out['flights'])} flights")
    ctx.say("lodging", f"Found {len(out['lodging'])} places to stay")
    ctx.say("activities", f"Found {len(out['activities'])} activities")
    ctx.say("transport", "Checking how to get around")
    legs, inter_flights = transport_step(ctx, stops, origin_geo, start, nights)
    out["ground_transport"], out["flights"] = legs, out["flights"] + inter_flights
    if not any(l["mode"] != "taxi" for l in legs) and len(stops) > 1:
        ctx.gap("ground_transport", "No intercity routes found between stops", "geoapify_routing")
    ctx.say("feasibility", "Checking the budget")
    out["feasibility"] = feasibility_step(ctx, out, stops, nights_total)
    out["gaps"], out["notes"] = ctx.gaps, ctx.notes
    needs_flights = "flight" in req.get("transport_modes", ["flight"])
    if out["feasibility"]["verdict"] == "likely_impossible":
        out["status"] = "infeasible"
    elif not (out["flights"] or out["lodging"] or out["activities"]):
        out["status"] = "error"
    elif (needs_flights and not out["flights"]) or (nights_total > 0 and not out["lodging"]) or not out["activities"]:
        out["status"] = "partial"
    ctx.say("done", f"Research finished: {out['status']}")
    return _finish(out)


def _finish(out: dict) -> dict:
    out["_schema_errors"] = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:140]}" for e in VALIDATOR.iter_errors({k: v for k, v in out.items() if not k.startswith('_')})][:20]
    return out
