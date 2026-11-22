"""Synthetic flight and hotel responses for tests and CI. NOT real data.

Generated on demand from aggregate statistics (synthetic_data/params.json, made by scripts/fit_synthetic_params.py). Each
request seeds its own random generator, so the same request always returns the same response and every route, date and
party size is covered. No recorded fare, hotel name, id, link or flight number is reused.

Everything is labeled: ids start with "synthetic-", carriers and hotels are named "Synthetic ...", there are no booking
links, and research/sandbox.py returns every item as price_type "estimate" with a method saying it is generated test data.
Do not use it for the live demo or to claim anything about real prices.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from datetime import date, datetime, timedelta
from typing import Optional

from .core import ROOT

PARAMS_PATH = os.path.join(ROOT, "synthetic_data", "params.json")
GENERATED_AT = "2026-11-22T00:00:00Z"   # fixed so output is reproducible; it is the date the parameters were fitted
N_FARES = 14
ONE_WAY_FACTOR = 0.62                   # assumption (not fitted): a one-way fare is about 62% of a round trip
SEASON_AMPLITUDE = 0.12                 # assumption (not fitted): prices swing +/-12% across the year, peaking in summer
HUBS = ["ORD", "DFW", "ATL", "FRA", "AMS", "IST", "DOH", "DXB", "SEA", "SFO", "LAX", "JFK", "MIA", "MAD", "CDG", "LHR"]
CARRIERS = [("ZA", "Synthetic Air A"), ("ZB", "Synthetic Air B"), ("ZC", "Synthetic Air C"), ("ZD", "Synthetic Air D")]
HOTEL_TYPES_SYNTH = {"hotel": "hotel", "hostel": "hostel", "vacation rental": "vacation rental"}

_params: Optional[dict] = None


def params() -> dict:
    global _params
    if _params is None:
        _params = json.load(open(PARAMS_PATH, encoding="utf-8"))
    return _params


def available() -> bool:
    return os.path.exists(PARAMS_PATH)


def _rng(*key) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:16], 16))


def _season(d: date) -> float:
    return 1 + SEASON_AMPLITUDE * math.sin(2 * math.pi * (d.timetuple().tm_yday - 80) / 365)


def _haversine_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _tz_hours(code: str) -> int:
    return round(params()["airports"][code][1] / 15)   # rough local-time offset from longitude


def _leg(rng: random.Random, o: str, d: str, day: date, dist: float, stops: int) -> dict:
    p = params()["airports"]
    hubs = [h for h in HUBS if h not in (o, d)]
    chain = [o] + rng.sample(hubs, stops) + [d]
    air_minutes = dist / 850 * 60 + 35
    cut = [rng.uniform(0.7, 1.3) for _ in range(stops + 1)]
    seg_minutes = [max(45, round(air_minutes * c / sum(cut))) for c in cut]
    t = datetime(day.year, day.month, day.day, rng.randint(5, 21), rng.choice([0, 10, 20, 30, 40, 50]))
    code, name = rng.choice(CARRIERS)
    segs, total = [], 0
    for i, m in enumerate(seg_minutes):
        a, b = chain[i], chain[i + 1]
        arrive = t + timedelta(minutes=m + (_tz_hours(b) - _tz_hours(a)) * 60)
        segs.append({"marketing_carrier_code": code, "flight_number": str(rng.randint(100, 9899)), "operating_carrier_name": name,
                     "departure_airport": a, "departure_time_local": t.strftime("%Y-%m-%dT%H:%M:%S"),
                     "arrival_airport": b, "arrival_time_local": arrive.strftime("%Y-%m-%dT%H:%M:%S"), "duration_minutes": m})
        layover = rng.randint(70, 180)
        total += m + (layover if i < len(seg_minutes) - 1 else 0)
        t = t + timedelta(minutes=m + layover + (_tz_hours(b) - _tz_hours(a)) * 60)
    return {"carrier": name, "duration_minutes": total, "segments": segs}


def flights(origin: str, dest: str, dep: str, ret: Optional[str], adults: int) -> Optional[dict]:
    """A synthetic Ignav-shaped response, or None when an airport is unknown. Prices are totals for the whole party."""
    P = params()
    ap = P["airports"]
    o, d = origin.upper(), dest.upper()
    if o not in ap or d not in ap or o == d:
        return None
    dist = _haversine_km(ap[o], ap[d])
    f = P["flights"]
    route = f["routes"].get(f"{o}-{d}") or f["routes"].get(f"{d}-{o}")
    mu = route["mu"] if route else f["fit"]["intercept"] + f["fit"]["slope"] * math.log(max(dist, 100))
    sigma = route["sigma"] if route and route["sigma"] > 0 else f["fit"]["fare_sigma"]
    dep_d = date.fromisoformat(dep)
    rng = _rng("flight", o, d, dep, ret, adults)
    if not route:                                     # an unseen route gets its own offset so it is not a clone of the fit
        mu += rng.gauss(0, f["fit"]["resid_sigma"])
    base = mu + math.log(_season(dep_d)) + (math.log(ONE_WAY_FACTOR) if not ret else 0)
    prices = sorted(round(math.exp(rng.gauss(base, sigma)) * adults) for _ in range(N_FARES))
    stop_p = [0.55, 0.40, 0.05] if dist < 1500 else [0.25, 0.60, 0.15] if dist < 6000 else [0.05, 0.65, 0.30]
    its = []
    for k, price in enumerate(prices):
        # cheaper fares tend to have more stops
        stops = rng.choices([0, 1, 2], weights=[w * (0.6 + 0.8 * k / N_FARES) for w in stop_p[:1]] +
                            [w * (1.4 - 0.8 * k / N_FARES) for w in stop_p[1:]])[0]
        if dist > 11000:
            stops = max(stops, 1)
        out = _leg(rng, o, d, dep_d, dist, stops)
        it = {"ignav_id": "synthetic-" + hashlib.sha256(f"{o}{d}{dep}{ret}{adults}{k}".encode()).hexdigest()[:24],
              "price": {"amount": float(price), "currency": "USD", "status": "synthetic"}, "cabin_class": "economy", "outbound": out}
        if ret:
            it["inbound"] = _leg(rng, d, o, date.fromisoformat(ret), dist, stops)
        its.append(it)
    return {"origin": o, "destination": d, "departure_date": dep, "return_date": ret, "observed_at": GENERATED_AT,
            "itineraries": its, "synthetic": True}


def hotels(city_key: str, check_in: str, check_out: str, adults: int, currency: str, fx) -> Optional[dict]:
    """A synthetic SerpApi-shaped response for a city we have parameters for, else None. `city_key` is already normalized."""
    H = params()["hotels"]
    c = H["cities"].get(city_key)
    if not c:
        return None
    nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    rng = _rng("hotel", city_key, check_in, check_out, adults, currency)
    rate = 1.0 if currency == "USD" else fx("USD", currency)
    season = _season(date.fromisoformat(check_in))
    types, weights = zip(*c["types"].items())
    props = []
    for i in range(18):
        night = math.ceil(math.exp(rng.gauss(c["night_mu"], c["night_sigma"])) * season * rate)
        t = rng.choices(types, weights=weights)[0]
        props.append({"name": f"Synthetic Hotel {rng.randint(0, 9999):04d}", "type": t,
                      "property_token": "synthetic-" + hashlib.sha256(f"{city_key}{check_in}{check_out}{i}".encode()).hexdigest()[:20],
                      "gps_coordinates": {"latitude": round(c["lat"] + rng.gauss(0, 0.02), 5), "longitude": round(c["lon"] + rng.gauss(0, 0.02), 5)},
                      "overall_rating": round(min(5.0, max(3.0, rng.gauss(c["rating_mean"], 0.4))), 1),
                      "reviews": max(5, round(rng.lognormvariate(math.log(c["reviews_median"]), 0.9))),
                      "rate_per_night": {"extracted_lowest": night}, "total_rate": {"extracted_lowest": night * nights}})
    return {"properties": props, "synthetic": True}
