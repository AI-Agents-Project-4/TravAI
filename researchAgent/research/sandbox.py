"""Sandbox data mode: answer flight and hotel searches from recorded real responses, including trips we never recorded.

The recordings live in sandbox_data/ (built by scripts/build_sandbox_index.py). A search is answered from the closest
recording, and every adaptation is marked, never hidden:

* Prices, links, carriers, times and `observed_at` are copied from the recording. Nothing is invented.
* A recording for other dates or another party size is returned as an estimate, rounded UP, with a note saying what it
  was recorded for. The agent turns that into price_type "estimate", low confidence and an estimate_method.
* When nothing is close enough there is no answer (None). The miss is appended to sandbox_misses.jsonl so we can spend
  API credits recording it.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Callable, Optional

from . import synthetic
from .core import ROOT

DATA_DIR = os.path.join(ROOT, "sandbox_data")
MISSES = os.path.join(ROOT, "sandbox_misses.jsonl")

FLIGHT_WINDOW_DAYS = 14   # how far the recorded departure may be from the requested one
FLIGHT_NIGHTS_TOLERANCE = 4  # how much shorter or longer a recorded round trip may be
HOTEL_WINDOW_DAYS = 120   # hotel nightly rates move less than fares, so a wider window is acceptable

CITY_ALIASES = {"nyc": "new york city", "new york": "new york city", "new york ny": "new york city",
                "sao paulo": "sao paulo", "mexico df": "mexico city", "cdmx": "mexico city", "ho chi minh": "ho chi minh city",
                "saigon": "ho chi minh city"}


def norm_city(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+hotels?$", "", s)
    return CITY_ALIASES.get(s, s)


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


class Store:
    """The recorded searches. Built from rows so tests can use tiny hand-made data."""

    def __init__(self, flights: list, hotels: list, bookings: Optional[dict] = None, synthetic_data: bool = False):
        self.flights, self.hotels, self.bookings = flights, hotels, bookings or {}
        self.synthetic = synthetic_data   # True: answer from research/synthetic.py instead of recordings

    @classmethod
    def from_dir(cls, path: str = DATA_DIR) -> "Store":
        def rows(name):
            p = os.path.join(path, name + ".jsonl")
            return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []
        return cls(rows("flights"), rows("hotels"), {b["ignav_id"]: b for b in rows("bookings")})

    @classmethod
    def generated(cls) -> "Store":
        return cls([], [], {}, synthetic_data=True)

    def captured_range(self) -> Optional[tuple]:
        ts = sorted(r["saved_at"][:10] for r in self.flights + self.hotels if r.get("saved_at"))
        return (ts[0], ts[-1]) if ts else None


_default: Optional[Store] = None


def default_store() -> Store:
    """Recorded data from sandbox_data/. Synthetic test data (research/synthetic.py) is used ONLY when asked for with
    TRAVAI_SANDBOX_DATA=synthetic (tests, CI): it is never a silent fallback, so a demo cannot show generated prices
    by accident. With no recordings and no explicit choice the store is empty and searches become gaps."""
    global _default
    if _default is None:
        choice = os.environ.get("TRAVAI_SANDBOX_DATA", "recorded")
        if choice not in ("recorded", "synthetic"):
            raise ValueError(f"TRAVAI_SANDBOX_DATA must be 'recorded' or 'synthetic', got {choice!r}")
        _default = Store.generated() if choice == "synthetic" and synthetic.available() else Store.from_dir(DATA_DIR)
    return _default


def log_miss(kind: str, key: dict) -> None:
    """Remember a search we could not answer, so the next recording run can fill it."""
    try:
        with open(MISSES, "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, **key, "requested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    except OSError:
        pass


# ---------- flights ----------

def find_flights(origin: str, dest: str, dep: str, ret: Optional[str], adults: int, store: Optional[Store] = None) -> Optional[dict]:
    """Closest recorded search for this route. Returns an Ignav-shaped response plus `_sandbox`, or None."""
    store = store or default_store()
    if store.synthetic:
        r = synthetic.flights(origin, dest, dep, ret, adults)
        if r is None:
            return None
        for it in r["itineraries"]:
            it["_sandbox"] = {"price_type": "estimate", "recorded": "synthetic", "saved_at": synthetic.GENERATED_AT, "synthetic": True,
                              "method": "Synthetic test data generated from aggregate fare statistics; not a real fare.",
                              "note": "Synthetic test data, not a real fare."}
        r["_sandbox"] = {"exact": False, "recorded": "synthetic", "saved_at": synthetic.GENERATED_AT, "synthetic": True}
        return r
    want_dep = _d(dep)
    want_nights = (_d(ret) - want_dep).days if ret else None
    best, best_score = None, None
    for r in store.flights:
        if r["origin"] != origin.upper() or r["destination"] != dest.upper() or bool(r.get("return_date")) != bool(ret):
            continue
        ddelta = abs((_d(r["departure_date"]) - want_dep).days)
        ndelta = abs((_d(r["return_date"]) - _d(r["departure_date"])).days - want_nights) if ret else 0
        exact = ddelta == 0 and ndelta == 0
        if not exact and (ddelta > FLIGHT_WINDOW_DAYS or ndelta > FLIGHT_NIGHTS_TOLERANCE or not r["itineraries"]):
            continue
        score = (ddelta + 2 * ndelta, -_ts(r["saved_at"]))  # closest dates and length first, then the newest recording
        if best_score is None or score < best_score:
            best, best_score = r, score
    if best is None:
        return None
    ddelta = abs((_d(best["departure_date"]) - want_dep).days)
    same_dates = ddelta == 0 and (not ret or (_d(best["return_date"]) - _d(best["departure_date"])) == (_d(ret) - want_dep))
    same_party = best["adults"] == adults
    recorded = f"{best['departure_date']}" + (f" to {best['return_date']}" if best.get("return_date") else " (one way)")
    its = []
    for it in best["itineraries"]:
        it = json.loads(json.dumps(it))  # copy: never mutate the loaded recording
        if not same_party:
            per_person = it["price"]["amount"] / best["adults"]
            it["price"]["amount"] = float(math.ceil(per_person * adults))
        if same_dates and same_party:
            it["_sandbox"] = {"price_type": "live_quote", "recorded": recorded, "saved_at": best["saved_at"],
                              "note": f"Recorded fare snapshot from {best['saved_at'][:10]}, not a live quote."}
        else:
            why = []
            if not same_dates:
                why.append(f"recorded for {recorded}, requested {dep}" + (f" to {ret}" if ret else ""))
            if not same_party:
                why.append(f"scaled from {best['adults']} to {adults} traveler(s), rounded up")
            it["_sandbox"] = {"price_type": "estimate", "recorded": recorded, "saved_at": best["saved_at"],
                              "method": "Nearest recorded fare: " + "; ".join(why) + ". Flight times are those of the recorded date.",
                              "note": f"Estimate from a {best['saved_at'][:10]} recording for other dates or party size."}
        its.append(it)
    return {"origin": origin.upper(), "destination": dest.upper(), "departure_date": dep, "return_date": ret,
            "observed_at": best.get("observed_at") or best["saved_at"], "itineraries": its,
            "_sandbox": {"exact": same_dates and same_party, "recorded": recorded, "saved_at": best["saved_at"]}}


def _ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def find_booking(ignav_id: str, store: Optional[Store] = None) -> Optional[dict]:
    b = (store or default_store()).bookings.get(ignav_id)
    return b["response"] if b else None


# ---------- hotels ----------

def find_hotels(city: str, check_in: str, check_out: str, adults: int, currency: str,
                fx: Callable[[str, str], float], store: Optional[Store] = None) -> Optional[dict]:
    """Closest recorded hotel search for this city. Returns a SerpApi-shaped response plus `_sandbox`, or None."""
    store = store or default_store()
    key = norm_city(city)
    if store.synthetic:
        r = synthetic.hotels(key, check_in, check_out, adults, currency, fx)
        if r is None:
            return None
        r["_sandbox"] = {"exact": False, "recorded": "synthetic", "saved_at": synthetic.GENERATED_AT, "synthetic": True,
                         "price_type": "estimate", "method": "Synthetic test data generated from aggregate hotel-rate statistics; not a real rate.",
                         "note": "Synthetic test data, not a real rate."}
        return r
    want_in = _d(check_in)
    want_nights = (_d(check_out) - want_in).days
    best, best_score = None, None
    for r in store.hotels:
        if norm_city(r["city"]) != key or not r["properties"]:
            continue
        ddelta = abs((_d(r["check_in"]) - want_in).days)
        ndelta = abs((_d(r["check_out"]) - _d(r["check_in"])).days - want_nights)
        if ddelta > HOTEL_WINDOW_DAYS:
            continue
        # prefer the same currency, then the nearest dates, then the closest stay length, then the newest recording
        score = (r["currency"] != currency, ddelta, ndelta, -_ts(r["saved_at"]))
        if best_score is None or score < best_score:
            best, best_score = r, score
    if best is None:
        return None
    nights_rec = (_d(best["check_out"]) - _d(best["check_in"])).days
    same_dates = best["check_in"] == check_in and best["check_out"] == check_out
    same_cur = best["currency"] == currency
    same_party = best["adults"] == adults
    exact = same_dates and same_cur and same_party
    rate = 1.0 if same_cur else fx(best["currency"], currency)
    props = []
    for p in best["properties"]:
        p = json.loads(json.dumps(p))
        night = p["rate_per_night"]["extracted_lowest"]
        if exact:
            total = (p.get("total_rate") or {}).get("extracted_lowest") or night * nights_rec
        else:
            night = math.ceil(night * rate)
            total = math.ceil(night * want_nights)
            p["rate_per_night"]["extracted_lowest"] = night
        p["total_rate"] = {"extracted_lowest": total}
        props.append(p)
    recorded = f"{best['check_in']} to {best['check_out']}, {best['adults']} adult(s), {best['currency']}"
    if exact:
        meta = {"price_type": "published_rate", "note": f"Recorded rate snapshot from {best['saved_at'][:10]}, not a live quote."}
    else:
        why = []
        if not same_dates:
            why.append(f"recorded for {best['check_in']} to {best['check_out']}, requested {check_in} to {check_out}")
        if not same_cur:
            why.append(f"converted from {best['currency']} at {rate:.4g}")
        if not same_party:
            why.append(f"recorded for {best['adults']} adult(s), requested {adults}")
        meta = {"price_type": "estimate", "method": "Nearest recorded rate: " + "; ".join(why) + "; rounded up.",
                "note": f"Estimate from a {best['saved_at'][:10]} recording for other dates, currency or party size."}
    return {"properties": props, "_sandbox": {"exact": exact, "recorded": recorded, "saved_at": best["saved_at"], **meta}}
