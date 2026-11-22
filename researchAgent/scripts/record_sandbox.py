"""Record real Ignav (flights) and SerpApi (hotels) responses into the offline cache.

Run it once to spend API quota on a spread of trips. Everything it saves goes to tests/fixtures/http_cache/, the same
cache the agent replays with --offline, so those trips then work with no network and no keys.

    python3 scripts/record_sandbox.py                 # dry run: print the plan and the call counts, spend nothing
    python3 scripts/record_sandbox.py --live          # make the calls (needs IGNAV_API_KEY and SERP_API_KEY in .env)
    python3 scripts/record_sandbox.py --live --max-ignav 60 --max-serp 60 --only flights

Calls already in the cache are skipped, so the script can be stopped and re-run. Only calls that hit the network count
against --max-ignav and --max-serp. It stops at once on an auth or quota error (HTTP 401/402/403/429).

The requests mirror what the agent sends (see research/agent.py: _search_flights, build_flight, lodging_step), because
the cache is keyed on the exact request. Airport codes and city names are written out by hand here. If the agent
resolves a different airport or spells a city differently, that one request is a cache miss when replayed offline.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from research import core, sources  # noqa: E402
from research.agent import pick_flights  # noqa: E402

# (origin, destination airports, city for hotels, depart date, nights, travelers)
# A spread of regions, prices and group sizes: cheap and expensive, domestic and long haul, 1 to 4 travelers.
TRIPS = [
    ("DEN", ["CUN"], "Cancun", "2027-02-20", 7, 2),
    ("DEN", ["LAX"], "Los Angeles", "2027-05-07", 3, 1),
    ("DEN", ["JFK", "EWR"], "New York City", "2027-05-14", 4, 2),
    ("DEN", ["LHR"], "London", "2027-06-12", 8, 1),
    ("DEN", ["BKK"], "Bangkok", "2027-07-10", 14, 2),
    ("DEN", ["SYD"], "Sydney", "2027-08-05", 10, 1),
    ("DEN", ["MEX"], "Mexico City", "2027-03-18", 5, 4),
    ("DEN", ["LIS"], "Lisbon", "2027-04-24", 7, 3),
    ("DEN", ["HNL"], "Honolulu", "2027-09-03", 7, 4),
    ("DEN", ["DXB"], "Dubai", "2027-10-08", 6, 1),
    ("DEN", ["GRU"], "Sao Paulo", "2027-11-05", 10, 2),
    ("DEN", ["CPT"], "Cape Town", "2027-01-29", 12, 1),
    ("ORD", ["MIA"], "Miami", "2027-03-26", 4, 2),
    ("SEA", ["NRT", "HND"], "Tokyo", "2027-10-15", 9, 2),
    ("JFK", ["LHR"], "London", "2027-12-01", 5, 2),
    ("DEN", ["ICN"], "Seoul", "2027-04-02", 7, 1),
    ("DEN", ["ATH"], "Athens", "2027-05-21", 9, 2),
    ("DEN", ["ANC"], "Anchorage", "2027-07-23", 5, 3),
    ("DEN", ["YVR"], "Vancouver", "2027-06-18", 4, 2),
    ("DEN", ["BOG"], "Bogota", "2027-02-05", 6, 1),
]

# Hotel-only extras: (city, check-in, nights, adults)
EXTRA_HOTELS = [
    ("Hanoi", "2027-03-05", 7, 2), ("Marrakech", "2027-04-12", 5, 2), ("Prague", "2027-05-03", 4, 2),
    ("Istanbul", "2027-09-14", 6, 1), ("Buenos Aires", "2027-08-20", 8, 2), ("Reykjavik", "2027-06-25", 4, 2),
    ("Nairobi", "2027-07-02", 7, 2), ("Chicago", "2027-08-12", 3, 1), ("San Francisco", "2027-10-01", 4, 2),
    ("Kyoto", "2027-11-10", 5, 2),
]

# ---- Gap fill: what the first set lacks (see the diversity review). Each group is labeled.
# (origin, destination airports, depart date, nights or None for one-way, travelers). Hotels for these trips come from GAP_HOTELS.
GAP_FLIGHTS = [
    # non-US origins
    ("LHR", ["BKK"], "2027-06-08", 14, 2), ("SYD", ["NRT"], "2027-05-03", 7, 1), ("GRU", ["LIS"], "2027-07-15", 9, 2),
    # cheaper long haul from a bigger hub
    ("LAX", ["BKK"], "2027-09-20", 12, 1),
    # remote airports: should return few or no fares
    ("DEN", ["ADQ"], "2027-08-02", 3, 1), ("DEN", ["GAN"], "2027-08-02", 7, 1),
    # trip shape: 1 night, 3 weeks, one-ways (multi-city legs)
    ("DEN", ["PHX"], "2027-05-28", 1, 1), ("DEN", ["SYD"], "2027-09-10", 21, 2),
    ("DEN", ["LIS"], "2027-09-05", None, 2), ("MAD", ["DEN"], "2027-09-16", None, 2),
    # same routes in a different season than the first set
    ("DEN", ["LHR"], "2027-11-09", 8, 1), ("DEN", ["LIS"], "2027-11-09", 7, 1), ("DEN", ["CUN"], "2027-07-10", 7, 2),
]

# (city, check-in, nights, adults, currency)
GAP_HOTELS = [
    # seasonal pairs against the first set
    ("London", "2027-11-09", 8, 1, "USD"), ("Lisbon", "2027-11-09", 7, 1, "USD"), ("Cancun", "2027-07-10", 7, 2, "USD"),
    ("Honolulu", "2027-01-10", 7, 2, "USD"), ("Reykjavik", "2027-01-15", 4, 2, "USD"), ("Paris", "2027-12-20", 5, 2, "USD"),
    ("Rome", "2027-08-14", 4, 2, "USD"), ("Tokyo", "2027-04-03", 5, 2, "USD"), ("Barcelona", "2027-08-01", 5, 2, "USD"),
    # same city and dates as an existing search, in the local currency
    ("Lisbon", "2027-04-24", 7, 2, "EUR"), ("Paris", "2027-04-20", 5, 1, "EUR"), ("London", "2027-06-12", 8, 1, "GBP"),
    ("Tokyo", "2027-10-15", 9, 2, "JPY"), ("Mexico City", "2027-03-18", 5, 2, "MXN"), ("Bangkok", "2027-07-10", 14, 2, "THB"),
    ("Vancouver", "2027-06-18", 4, 2, "CAD"), ("Sydney", "2027-08-05", 10, 1, "AUD"),
    # stay length: 1 night and long stays
    ("Phoenix", "2027-05-28", 1, 1, "USD"), ("Los Angeles", "2027-05-07", 1, 1, "USD"), ("Sydney", "2027-09-10", 21, 2, "USD"),
    ("Bangkok", "2027-07-10", 28, 1, "USD"), ("Lisbon", "2027-04-24", 28, 1, "USD"), ("Chiang Mai", "2027-01-12", 30, 1, "USD"),
    # low-cost destinations
    ("Chiang Mai", "2027-02-10", 7, 2, "USD"), ("Bali", "2027-06-01", 7, 2, "USD"), ("Ho Chi Minh City", "2027-03-12", 7, 2, "USD"),
    ("Cusco", "2027-05-10", 5, 2, "USD"), ("Tbilisi", "2027-06-14", 6, 2, "USD"), ("Oaxaca", "2027-04-05", 5, 2, "USD"),
    ("Medellin", "2027-03-08", 6, 2, "USD"), ("Budapest", "2027-05-17", 4, 2, "USD"), ("Sofia", "2027-09-06", 4, 1, "USD"),
    # remote places: few or no hotels
    ("Kodiak", "2027-08-02", 3, 1, "USD"), ("Longyearbyen", "2027-07-05", 4, 2, "USD"),
]

# Ignav answers HTTP 424 unsupported_search for these (dates outside its window), so don't spend calls retrying.
KNOWN_UNSUPPORTED = {("JFK", "LHR", "2027-12-01")}

PER_SEARCH_PICKS = 3  # the agent passes n=3 to pick_flights, so up to 3 booking-link calls follow each search


def flight_plan(include_gaps: bool = True):
    """Yields (origin, airport, depart, return or None, travelers)."""
    for o, airports, _city, dep, nights, trav in TRIPS:
        ret = (date.fromisoformat(dep) + timedelta(days=nights)).isoformat()
        for a in airports:  # the agent searches the first two airports of the destination
            if (o, a, dep) in KNOWN_UNSUPPORTED:
                continue
            yield o, a, dep, ret, trav
    if include_gaps:
        for o, airports, dep, nights, trav in GAP_FLIGHTS:
            ret = (date.fromisoformat(dep) + timedelta(days=nights)).isoformat() if nights else None
            for a in airports:
                yield o, a, dep, ret, trav


def hotel_plan(include_gaps: bool = True):
    """Yields (city, check-in, nights, adults, currency)."""
    seen = set()
    rows = []
    for _o, _a, city, dep, nights, trav in TRIPS:
        adults = min(trav, 2)  # the agent caps hotel adults at 2
        rows += [(city, dep, nights, adults, "USD"), (city, dep, max(2, nights // 2), adults, "USD")]
        if adults > 1:
            rows.append((city, dep, nights, 1, "USD"))
    rows += [(*r, "USD") for r in EXTRA_HOTELS]
    if include_gaps:
        rows += GAP_HOTELS
    for r in rows:
        if r not in seen:
            seen.add(r)
            yield r


def miss_plans(limit: int):
    """Searches the sandbox could not answer (sandbox_misses.jsonl), most requested first.
    Returns (flight rows, hotel rows) shaped like flight_plan() / hotel_plan()."""
    import collections
    import json
    path = os.path.join(ROOT, "sandbox_misses.jsonl")
    fl, ho = collections.Counter(), collections.Counter()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = json.loads(line)
            if m["kind"] == "flight":
                fl[(m["origin"], m["destination"], m["departure_date"], m.get("return_date"), int(m["adults"]))] += 1
            elif m["kind"] == "hotel":
                ho[(m["city"], m["check_in"], (date.fromisoformat(m["check_out"]) - date.fromisoformat(m["check_in"])).days,
                    int(m["adults"]), m["currency"])] += 1
    flights = [(*k, ) for k, _ in fl.most_common(limit)]
    hotels = [k for k, _ in ho.most_common(limit)]
    for k, n in fl.most_common(limit):
        print(f"  missed {n}x flight {k[0]}->{k[1]} {k[2]}")
    for k, n in ho.most_common(limit):
        print(f"  missed {n}x hotel {k[0]} {k[1]} for {k[2]} nights")
    return flights, hotels


def cached(method: str, url: str, body=None) -> bool:
    return os.path.exists(os.path.join(core.HTTP_CACHE, core._key(method, url, body) + ".json"))


class Budget:
    def __init__(self, ignav: int, serp: int):
        self.cap = {"ignav": ignav, "serp": serp}
        self.used = {"ignav": 0, "serp": 0}
        self.skipped = {"ignav": 0, "serp": 0}

    def can(self, which: str) -> bool:
        return self.used[which] < self.cap[which]


def record_flights(b: Budget, live: bool, only_base: bool = False, plan=None) -> None:
    planned = 0
    for o, d, dep, ret, trav in (plan if plan is not None else flight_plan(not only_base)):
        body = {"origin": o, "destination": d, "departure_date": dep}
        if ret:
            body["return_date"] = ret
        if trav > 1:
            body["adults"] = trav
        url = "https://ignav.com/api/fares/" + ("round-trip" if ret else "one-way")
        search = (lambda off: sources.ignav_roundtrip(o, d, dep, ret, trav, off)) if ret else (lambda off: sources.ignav_oneway(o, d, dep, trav, off))
        label = f"flights {o}->{d} {dep}{'..' + ret if ret else ' one-way'} x{trav}"
        if cached("POST", url, body):
            b.skipped["ignav"] += 1
            data = search(True)
        else:
            planned += 1
            if not live:
                print(f"  would call  {label}  (+ up to {PER_SEARCH_PICKS} booking-link calls)")
                continue
            if not b.can("ignav"):
                print(f"  cap reached, not recorded: {label}")
                continue
            b.used["ignav"] += 1
            try:
                data = search(False)
            except core.ApiError as e:
                if e.status in (401, 402, 403, 429):
                    raise
                print(f"  search failed, skipped: {label}  ({str(e)[:170]})")
                continue
            print(f"  recorded    {label}  ({len(data.get('itineraries', []))} itineraries)")
        for it in pick_flights(data.get("itineraries", []), PER_SEARCH_PICKS):
            bl = {"ignav_id": it["ignav_id"]}
            if cached("POST", "https://ignav.com/api/fares/booking-links", bl):
                b.skipped["ignav"] += 1
            elif live and b.can("ignav"):
                b.used["ignav"] += 1
                try:
                    sources.ignav_booking(it["ignav_id"], offline=False)
                except core.ApiError as e:
                    if e.status in (401, 402, 403, 429):
                        raise
                    # Upstream failure on one fare. The agent treats this as "search link only", so skip it.
                    print(f"  booking link failed (HTTP {e.status}), skipped: {it['ignav_id'][:10]}")
            elif live:
                print("  cap reached, booking link not recorded")


def record_hotels(b: Budget, live: bool, only_base: bool = False, plan=None) -> None:
    for city, cin, nights, adults, cur in (plan if plan is not None else hotel_plan(not only_base)):
        cout = (date.fromisoformat(cin) + timedelta(days=nights)).isoformat()
        label = f"hotels {city} {cin}..{cout} x{adults} {cur}"
        # Same URL the agent builds, so the cache key matches.
        q = urllib.parse.urlencode({"engine": "google_hotels", "q": f"{city} hotels", "check_in_date": cin,
                                    "check_out_date": cout, "adults": adults, "currency": cur, "gl": "us", "hl": "en",
                                    "api_key": core.secret("SERP_API_KEY", offline=True)})
        if cached("GET", "https://serpapi.com/search.json?" + q):
            b.skipped["serp"] += 1
            continue
        if not live:
            print(f"  would call  {label}")
            b.used["serp"] += 1  # dry run: count what a live run would spend
            continue
        if not b.can("serp"):
            print(f"  cap reached, not recorded: {label}")
            continue
        b.used["serp"] += 1
        try:
            data = sources.serp_hotels(f"{city} hotels", cin, cout, adults, cur, offline=False)
        except core.ApiError as e:
            if e.status in (401, 402, 403, 429):
                raise
            print(f"  search failed, skipped: {label}  ({str(e)[:170]})")
            continue
        print(f"  recorded    {label}  ({len(data.get('properties', []))} properties)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="make real API calls (default is a dry run)")
    ap.add_argument("--max-ignav", type=int, default=140, help="most Ignav calls to make this run (default 140)")
    ap.add_argument("--max-serp", type=int, default=140, help="most SerpApi calls to make this run (default 140)")
    ap.add_argument("--only", choices=["flights", "hotels"], help="record just one source")
    ap.add_argument("--from-misses", type=int, metavar="N", help="record only the N most-requested searches the sandbox could not answer")
    ap.add_argument("--base-only", action="store_true", help="plan only the first set, not the gap-fill additions")
    a = ap.parse_args()

    b = Budget(a.max_ignav, a.max_serp)
    print("LIVE: spending API quota" if a.live else "DRY RUN: nothing is called or written")
    fplan = hplan = None
    if a.from_misses:
        fplan, hplan = miss_plans(a.from_misses)
        print(f"  {len(fplan)} flight and {len(hplan)} hotel searches to fill")
    try:
        if a.only != "hotels":
            record_flights(b, a.live, a.base_only, fplan)
        if a.only != "flights":
            record_hotels(b, a.live, a.base_only, hplan)
    except core.ApiError as e:
        print(f"\nStopped on {e}")
        if e.status in (401, 402, 403, 429):
            print("That looks like a key or quota problem. Re-run later; finished calls are cached and will be skipped.")
        return 1
    except RuntimeError as e:  # secret() raises this when a key is missing
        print(f"\n{e}")
        return 1

    print("\nSummary")
    if a.live:
        print(f"  Ignav calls made: {b.used['ignav']} (cap {b.cap['ignav']}), already cached: {b.skipped['ignav']}")
        print(f"  SerpApi calls made: {b.used['serp']} (cap {b.cap['serp']}), already cached: {b.skipped['serp']}")
    else:
        n = len(fplan) if fplan is not None else sum(1 for _ in flight_plan(not a.base_only))
        print(f"  Ignav: {n} flight searches planned, each followed by up to {PER_SEARCH_PICKS} booking-link calls, "
              f"so at most {n * (1 + PER_SEARCH_PICKS)} calls (cap {b.cap['ignav']}). Already cached calls are skipped.")
        print(f"  SerpApi: {b.used['serp']} hotel searches would be made (cap {b.cap['serp']}), {b.skipped['serp']} already cached.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
