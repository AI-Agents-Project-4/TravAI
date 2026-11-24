"""Activities: Geoapify places -> LLM enrichment (English name, category, duration) -> price layers 1-4 -> schema items."""
from __future__ import annotations

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from . import sources
from .core import ApiError, CacheMiss, claude_json
from .security.budget import map_in_context
from .security.fetch_guard import BlockedURL, check_link_shape
import hashlib

from .pricing import WikivoyageIndex, haversine_m, make_price, name_score, now_iso, price_for, parse_price_text

CATEGORIES = ["culture", "history", "food", "nightlife", "nature", "outdoors", "shopping", "museum", "tour",
              "day_trip", "entertainment", "other"]

# (geoapify categories, how many to request, label)
GROUPS = [
    ("tourism.attraction,tourism.sights", 40, "sights"),
    ("entertainment.museum,entertainment.culture", 30, "museums"),
    ("religion.place_of_worship,heritage", 25, "heritage"),
    ("leisure.park,natural", 25, "nature"),
    ("entertainment.zoo,entertainment.aquarium,entertainment.theme_park", 15, "entertainment"),
    ("catering.restaurant", 25, "food"),
    ("catering.bar,catering.pub,adult.nightclub", 15, "nightlife"),
    ("commercial.marketplace", 10, "markets"),
]

# Layer 4: USD at cost tier 2 (mid-priced country); scaled by tier. Deliberately on the high side.
BASE_USD = {"culture": 12, "history": 12, "food": 28, "nightlife": 30, "nature": 8, "outdoors": 10, "shopping": 10,
            "museum": 16, "tour": 60, "day_trip": 70, "entertainment": 35, "other": 15}
TIER_MULT = {1: 0.5, 2: 1.0, 3: 1.4, 4: 1.8}
DEFAULT_MIN = {"culture": 60, "history": 60, "food": 75, "nightlife": 120, "nature": 90, "outdoors": 120, "shopping": 60,
               "museum": 90, "tour": 150, "day_trip": 480, "entertainment": 120, "other": 60}

ENRICH_SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["i", "english_name", "name_confidence", "category", "duration_minutes", "description", "keep"],
    "properties": {"i": {"type": "integer"}, "english_name": {"type": "string"},
                   "name_confidence": {"enum": ["high", "medium", "low"]}, "category": {"enum": CATEGORIES},
                   "duration_minutes": {"type": "integer"}, "description": {"type": "string"},
                   "keep": {"type": "boolean"}}}}}}

WEB_SCHEMA = {"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": {
    "type": "object", "required": ["id", "found", "amount", "currency", "source_url", "note"],
    "properties": {"id": {"type": "string"}, "found": {"type": "boolean"}, "amount": {"type": ["number", "null"]},
                   "currency": {"type": ["string", "null"]}, "source_url": {"type": ["string", "null"]},
                   "note": {"type": "string"}}}}}}


# ---------- opening hours ----------

_DAYS = ["mo", "tu", "we", "th", "fr", "sa", "su"]
_OUT = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_hours(s: Optional[str]) -> Optional[dict]:
    """Parse the simple OSM opening_hours forms. Returns None for anything complex rather than guessing."""
    if not s or re.search(r"PH|SH|sunrise|sunset|\[|week|\d{4}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec", s):
        return None
    if s.strip() == "24/7":
        return {d: {"open": "00:00", "close": "23:59"} for d in _OUT}
    out: dict = {}
    for rule in (r.strip() for r in s.split(";") if r.strip()):
        m = re.match(r"^([A-Za-z,\- ]+?)\s+(off|closed)$", rule, re.I)
        if m:
            for d in _expand_days(m.group(1)):
                out.pop(_OUT[d], None)
            continue
        m = re.match(r"^([A-Za-z,\- ]+?)?\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})(?:\s*,.*)?$", rule)
        if not m:
            return None
        days = _expand_days(m.group(1)) if m.group(1) else list(range(7))
        if days is None:
            return None
        o, c = _clock(m.group(2)), _clock(m.group(3))
        if o is None or c is None:
            return None
        for d in days:
            out[_OUT[d]] = {"open": o, "close": c}
    return out or None


def _clock(t: str) -> Optional[str]:
    """OSM allows 24:00 and times past midnight like 26:00 (= 02:00 next day). The schema wants HH:MM under 24;
    a close time earlier than the open time means the place closes after midnight."""
    h, m = int(t.split(":")[0]), t.split(":")[1]
    if h == 24 and m == "00":
        return "23:59"
    if h >= 48 or int(m) > 59:
        return None
    return f"{h % 24:02d}:{m}"


def _expand_days(spec: str) -> Optional[list]:
    days: list = []
    for part in spec.lower().replace(" ", "").split(","):
        if "-" in part:
            a, _, b = part.partition("-")
            if a[:2] not in _DAYS or b[:2] not in _DAYS:
                return None
            i, j = _DAYS.index(a[:2]), _DAYS.index(b[:2])
            days += list(range(i, j + 1)) if i <= j else list(range(i, 7)) + list(range(0, j + 1))
        elif part[:2] in _DAYS:
            days.append(_DAYS.index(part[:2]))
        else:
            return None
    return days


# ---------- gathering and ranking ----------

def rank_score(p: dict) -> int:
    raw = (p.get("datasource") or {}).get("raw") or {}
    s = 0
    s += 3 if (p.get("name_international") or {}).get("en") or raw.get("name:en") else 0
    s += 2 if p.get("wiki_and_media") or raw.get("wikidata") or raw.get("wikipedia") else 0
    s += 1 if p.get("website") else 0
    s += 1 if p.get("opening_hours") else 0
    s += 1 if p.get("name") else 0
    return s


def gather_places(lat: float, lon: float, offline: bool, notes: list, radius_m: int = 10000) -> list[dict]:
    def one(g):
        cats, limit, label = g
        try:
            return label, sources.places(cats, lat, lon, radius_m, limit, offline)
        except ApiError as e:
            notes.append(f"Geoapify places '{label}' failed: {e.status}")
            return label, []
    with ThreadPoolExecutor(4) as ex:
        results = map_in_context(ex, one, GROUPS)
    seen, out = set(), []
    for label, ps in results:
        for p in ps:
            if p.get("name") is not None:
                p["name"] = str(p["name"])        # OSM names can be bare numbers (e.g. "1803")
            if not p.get("name") and not (p.get("name_international") or {}).get("en"):
                continue
            key = p.get("place_id")
            if key in seen:
                continue
            seen.add(key)
            p["_group"] = label
            out.append(p)
    return out


def select_candidates(places: list[dict], per_group_cap: dict) -> list[dict]:
    by: dict = {}
    for p in places:
        by.setdefault(p["_group"], []).append(p)
    out = []
    for label, ps in by.items():
        ps.sort(key=rank_score, reverse=True)
        out += ps[:per_group_cap.get(label, 12)]
    return out


def enrich(places: list[dict], city: str, country: str, offline: bool) -> dict:
    """One LLM call per ~30 places. Returns {index: enrichment}."""
    def hints(p):
        raw = (p.get("datasource") or {}).get("raw") or {}
        return [x for x in [(p.get("name_international") or {}).get("en"), raw.get("name:en")] if x]

    def batch(chunk):
        lines = [f'{i}: local_name="{p.get("name") or ""}" english_hints={hints(p)} osm={p.get("categories", [])[:2]}'
                 for i, p in chunk]
        prompt = (f"Places near {city}, {country}. For each line return: english_name (the common English name visitors use; "
                  "use english_hints when present; romanize/translate otherwise; never invent a name), name_confidence "
                  "(high only if sure), category, typical visit duration in minutes, a one-sentence neutral description "
                  "(under 150 chars; say nothing you are not sure of), and keep=false for anything that is not a "
                  "visitor attraction/restaurant/bar (offices, private buildings, generic street furniture, unnamed "
                  "things). Echo the line number as i.\n" + "\n".join(lines))
        try:
            return claude_json(prompt, ENRICH_SCHEMA, offline=offline, timeout=240, max_budget_usd=1.0)["items"]
        except CacheMiss:
            raise
        except Exception:
            return []
    idx = list(enumerate(places))
    chunks = [idx[i:i + 30] for i in range(0, len(idx), 30)]
    with ThreadPoolExecutor(3) as ex:
        res = map_in_context(ex, batch, chunks)
    return {it["i"]: it for r in res for it in r}


def merge_wikivoyage(cands: list[dict], index: WikivoyageIndex, lat: float, lon: float, limit: int = 40) -> list[dict]:
    """Wikivoyage see/do listings are curated, so they rank above raw OSM results. Drop OSM duplicates of them."""
    wv = index.candidates(lat, lon, 15000)
    wv.sort(key=lambda l: (bool(parse_price_text(l.price_text)), bool(l.content)), reverse=True)
    wv = wv[:limit]
    pseudo = []
    for l in wv:
        pid = "wv" + hashlib.sha1(f"{l.page}|{l.name}".encode()).hexdigest()[:16]
        pseudo.append({"place_id": pid, "name": l.name, "lat": l.lat, "lon": l.lon, "website": l.url or None,
                       "categories": [l.kind, "wikivoyage"], "datasource": {"raw": {}}, "_group": "wikivoyage",
                       "_wv_page": l.page, "_wv_content": l.content, "name_international": {"en": l.name}})

    def dup(p):
        return any(haversine_m(p["lat"], p["lon"], q["lat"], q["lon"]) <= 200 and
                   max(name_score(n, q["name"]) for n in [p.get("name") or "", (p.get("name_international") or {}).get("en") or ""]) >= 0.6
                   for q in pseudo)
    return pseudo + [p for p in cands if not dup(p)]


DAYTRIP_SCHEMA = {"type": "object", "required": ["trips"], "properties": {"trips": {"type": "array", "items": {
    "type": "object", "required": ["name", "geocode_query", "round_trip_minutes", "time_on_site_minutes", "description"],
    "properties": {"name": {"type": "string"}, "geocode_query": {"type": "string"}, "round_trip_minutes": {"type": "integer"},
                   "time_on_site_minutes": {"type": "integer"}, "description": {"type": "string"}}}}}}


def day_trip_candidates(stop: dict, offline: bool, notes: list, n: int = 3) -> list[dict]:
    """Popular day trips from the city, as pseudo-places. Travel time is an LLM estimate and is labelled as such."""
    try:
        r = claude_json(
            f"Suggest {n} popular, genuinely doable day trips from {stop['city']}, {stop['country']} by public transport "
            "(or a standard organized tour). For each: the destination name, a precise geocoding query, realistic ROUND-TRIP "
            "travel time in minutes from the city centre (door to door), typical time on site in minutes, and a one-sentence "
            "description. Do not suggest anything that needs more than one overnight or a private charter.",
            DAYTRIP_SCHEMA, offline=offline, timeout=180, max_budget_usd=0.5)["trips"]
    except CacheMiss:
        raise
    except Exception as e:
        notes.append(f"day-trip suggestions failed: {type(e).__name__}")
        return []
    out = []
    for t in r[:n]:
        try:
            g = sources.geocode(t["geocode_query"], offline, stop["country_code"])
        except ApiError:
            g = None
        if not g:
            continue
        pid = "dt" + hashlib.sha1(t["name"].encode()).hexdigest()[:16]
        out.append({"place_id": pid, "name": t["name"], "lat": g["lat"], "lon": g["lon"], "website": None,
                    "categories": ["day_trip"], "datasource": {"raw": {}}, "_group": "day_trip", "name_international": {"en": t["name"]},
                    "_day_trip": t, "formatted": g["name"]})
    return out


# ---------- pricing layers 3 and 4 ----------

def _safe_link(url) -> bool:
    """A link the model found on the web is only shown, never fetched. It must be http(s) with no
    credentials, IP-address host or odd port (T3). Plain http is allowed because some official
    tourism sites have no https link."""
    try:
        check_link_shape(url or "", allow_http=True)
        return True
    except BlockedURL:
        return False


def web_prices(items: list[dict], city: str, country: str, offline: bool) -> dict:
    """Layer 3: Claude web search for official admission prices. Returns {id: result} for verified finds only."""
    def batch(chunk):
        lines = "\n".join(f'- id={c["id"]}: {c["name"]}' for c in chunk)
        prompt = (f"Find the current standard adult admission price for each place in/near {city}, {country} using web search. "
                  "Only report found=true when an official site or reputable ticketing/government page actually states the "
                  "price; give that page's URL as source_url and the price in the currency the page uses. Free admission "
                  "is amount 0 (only if the page says free). If a price depends on options, report the cheapest standard "
                  "adult ticket and say so in note. Never estimate or guess: if you cannot find a stated price, "
                  "found=false with null fields. Echo id exactly.\n" + lines)
        try:
            return claude_json(prompt, WEB_SCHEMA, web=True, offline=offline, timeout=420, max_budget_usd=1.5)["results"]
        except CacheMiss:
            raise
        except Exception:
            return []
    chunks = [items[i:i + 4] for i in range(0, len(items), 4)]
    with ThreadPoolExecutor(3) as ex:
        res = map_in_context(ex, batch, chunks)
    out = {}
    for r in (x for rs in res for x in rs):
        ok = (r["found"] and isinstance(r["amount"], (int, float)) and r["amount"] >= 0 and r["currency"] and
              re.fullmatch(r"[A-Z]{3}", r["currency"]) and _safe_link(r["source_url"]))
        if ok:
            out[r["id"]] = r
    return out


def estimate_price(category: str, tier: int, target_cur: str, fx: Callable) -> dict:
    usd = round(BASE_USD.get(category, 15) * TIER_MULT.get(tier, 1.4), 2)
    method = (f"Category estimate: ${BASE_USD.get(category, 15)} typical '{category}' cost x {TIER_MULT.get(tier, 1.4)} "
              f"for cost tier {tier}. No published price was found. Set high on purpose.")
    p = make_price(usd, "USD", "estimate", now_iso(), target_currency=target_cur, fx=fx, estimate_method=method,
                   price_layer="category_estimate")
    return p


# ---------- assembly ----------

def build_activities(stop: dict, offline: bool, target_cur: str, fx: Callable, notes: list, gaps: list,
                     web_limit: int = 12) -> list[dict]:
    lat, lon, city, country = stop["lat"], stop["lon"], stop["city"], stop["country"]
    raw_places = gather_places(lat, lon, offline, notes)
    if not raw_places:
        gaps.append({"category": "activities", "reason": f"Geoapify returned no named places near {city}", "source_attempted": "geoapify"})
        return []
    cands = select_candidates(raw_places, {"sights": 10, "museums": 8, "heritage": 6, "nature": 6, "entertainment": 4,
                                           "food": 8, "nightlife": 6, "markets": 4})
    index = None
    try:
        index = WikivoyageIndex(stop.get("wikivoyage_title") or city).load()
    except Exception as e:  # offline cache miss or network trouble: continue without layer 2
        notes.append(f"Wikivoyage unavailable for {city} ({type(e).__name__}); layer 2 skipped")
    if index:
        cands = merge_wikivoyage(cands, index, lat, lon)
    trips = day_trip_candidates(stop, offline, notes) if stop.get("trip_days", 0) >= 3 else []
    cands = cands + trips
    enr = enrich([c for c in cands if "_day_trip" not in c], city, country, offline)
    # map enrichment (indexed over non-day-trip cands) back, then give day trips fixed enrichment
    plain = [c for c in cands if "_day_trip" not in c]
    enr = {cands.index(plain[i]): v for i, v in enr.items() if i < len(plain)}
    for i, c in enumerate(cands):
        if "_day_trip" in c:
            t = c["_day_trip"]
            enr[i] = {"i": i, "english_name": t["name"], "name_confidence": "medium", "category": "day_trip",
                      "duration_minutes": t["time_on_site_minutes"], "description": t["description"], "keep": True}
    items = []
    for i, p in enumerate(cands):
        e = enr.get(i)
        if not e or not e["keep"] or not e["english_name"].strip():
            continue
        items.append((p, e))

    rows = []
    for p, e in items:
        hit = None
        try:
            hit = price_for({**p, "name_international": {"en": e["english_name"]}}, index, fx=fx, target_currency=target_cur,
                            local_currency=stop.get("local_currency"))
        except Exception as ex:
            notes.append(f"price lookup error for {e['english_name']}: {type(ex).__name__}")
        rows.append({"p": p, "e": e, "hit": hit})

    # Layer 3: web search for the best-ranked unpriced non-food places
    unpriced = [r for r in rows if not r["hit"] and r["e"]["category"] not in ("food", "nightlife")]
    unpriced.sort(key=lambda r: rank_score(r["p"]), reverse=True)
    web_targets = unpriced[:web_limit]
    found = web_prices([{"id": r["p"]["place_id"], "name": r["e"]["english_name"]} for r in web_targets], city, country, offline) if web_targets else {}

    acts = []
    for r in rows:
        p, e = r["p"], r["e"]
        w = found.get(p["place_id"])
        price, price_source = None, None
        if r["hit"]:
            price, price_source = r["hit"]["price"], r["hit"]["source"]
            price["price_layer"] = r["hit"]["layer"]
            layer, ambiguous, pnote = r["hit"]["layer"], r["hit"].get("ambiguous", False), r["hit"].get("notes", "")
        elif w:
            price = make_price(w["amount"], w["currency"], "published_rate", now_iso(), target_currency=target_cur, fx=fx,
                               price_layer="web_search")
            price_source = {"url": w["source_url"], "provider": "web_search"}
            layer, ambiguous, pnote = "web_search", False, w["note"]
        else:
            price = estimate_price(e["category"], stop["cost_tier"], target_cur, fx)
            layer, ambiguous, pnote = "category_estimate", False, "no published price found"
        raw = (p.get("datasource") or {}).get("raw") or {}
        osm_type = {"n": "node", "w": "way", "r": "relation"}.get(raw.get("osm_type"))
        link = p.get("website") or (f"https://www.openstreetmap.org/{osm_type}/{raw['osm_id']}" if osm_type and raw.get("osm_id") else None)
        if not link and p.get("_wv_page"):
            link = "https://en.wikivoyage.org/wiki/" + urllib.parse.quote(p["_wv_page"].replace(" ", "_"))
        provider = "wikivoyage" if p.get("_wv_page") else "geoapify_osm"
        if not link:
            link = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(f"{e['english_name']} {city}")
            provider = "google_maps_search"
        level = "low" if layer == "category_estimate" else ("medium" if (ambiguous or layer == "wikivoyage") else "medium")
        if e["name_confidence"] == "low":
            level = "low"
        translated = not ((p.get("name_international") or {}).get("en") or raw.get("name:en")) and (p.get("name") or "") != e["english_name"]
        notes_txt = "; ".join(x for x in [pnote, "name translated by LLM" if translated else ""] if x)
        a = {
            "id": f"act-{p['place_id'][:12]}", "name": e["english_name"].strip(),
            "name_source": "llm_translation" if translated else ("osm_name_en" if raw.get("name:en") or (p.get("name_international") or {}).get("en") else "original"),
            "category": e["category"], "description": e["description"][:200],
            "location": {"lat": p["lat"], "lng": p["lon"]}, "area": p.get("suburb") or p.get("district") or city,
            "price": price, "duration_minutes": max(15, int(e["duration_minutes"] or DEFAULT_MIN.get(e["category"], 60))),
            "requires_booking": None, "source": {"url": link, "provider": provider},
            "confidence": {"level": level, "verified": False, **({"notes": notes_txt} if notes_txt else {})},
        }
        if p.get("_day_trip"):
            a["round_trip_from_base_minutes"] = int(p["_day_trip"]["round_trip_minutes"])
            a["confidence"]["notes"] = (a["confidence"].get("notes", "") + "; travel time is an LLM estimate").strip("; ")
        if p.get("name") and p["name"] != a["name"]:
            a["name_local"] = p["name"]
        if price_source:
            a["price_source"] = price_source
        hrs = parse_hours(p.get("opening_hours"))
        if hrs:
            a["hours"] = hrs
        acts.append(a)
    return acts
