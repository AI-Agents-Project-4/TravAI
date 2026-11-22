"""Build the compact sandbox dataset from the recorded HTTP cache.

    python3 scripts/build_sandbox_index.py

Reads tests/fixtures/http_cache/ (written by scripts/record_sandbox.py and normal live runs) and writes
sandbox_data/flights.jsonl, hotels.jsonl and bookings.jsonl. The agent's sandbox mode (research/sandbox.py) looks
trips up in these files by route/city and date, which the request-hash cache cannot do.

Only the fields the agent reads are kept, so the files are far smaller than the cache. Prices, links and
timestamps are copied unchanged. Nothing here invents or edits a number.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tests", "fixtures", "http_cache")
OUT = os.path.join(ROOT, "sandbox_data")

MAX_FARES_PER_SEARCH = 60  # the agent only offers the cheapest few plus fastest / fewest-stop picks
HOTEL_FIELDS = ("name", "type", "property_token", "gps_coordinates", "overall_rating", "reviews", "link")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def trim_fares(its: list, booked_ids: set) -> list:
    """Cheapest fares, plus the fastest ten and any fare we have a booking link for."""
    by_price = sorted(its, key=lambda i: i["price"]["amount"])
    keep = {i["ignav_id"]: i for i in by_price[:MAX_FARES_PER_SEARCH]}
    dur = lambda i: sum(l["duration_minutes"] for l in (i.get("outbound"), i.get("inbound")) if l)
    for i in sorted(its, key=dur)[:10]:
        keep[i["ignav_id"]] = i
    for i in its:
        if i["ignav_id"] in booked_ids:
            keep[i["ignav_id"]] = i
    return sorted(keep.values(), key=lambda i: i["price"]["amount"])


def trim_hotel(p: dict) -> dict | None:
    night = ((p.get("rate_per_night") or {}).get("extracted_lowest"))
    if not (p.get("gps_coordinates") and night):
        return None
    out = {k: p[k] for k in HOTEL_FIELDS if p.get(k) is not None}
    out["rate_per_night"] = {"extracted_lowest": night}
    total = (p.get("total_rate") or {}).get("extracted_lowest")
    if total:
        out["total_rate"] = {"extracted_lowest": total}
    return out


def main() -> int:
    flights, hotels, bookings = [], [], {}
    raw_flights = []
    for path in sorted(glob.glob(os.path.join(CACHE, "*.json"))):
        rec = json.load(open(path, encoding="utf-8"))
        url, text = rec.get("url", ""), rec.get("text", "")
        if text[:1] != "{":
            continue
        data = json.loads(text)
        if "ignav.com/api/fares/booking-links" in url:
            bookings[rec["body"]["ignav_id"]] = {"saved_at": iso(rec["saved_at"]), "response": data}
        elif "ignav.com/api/fares/" in url:
            b = rec["body"]
            raw_flights.append((rec, b, data))
        elif "serpapi.com/search.json" in url and "google_hotels" in url:
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
            props = [h for h in (trim_hotel(p) for p in data.get("properties", [])) if h]
            hotels.append({"city": q["q"].removesuffix(" hotels"), "check_in": q["check_in_date"], "check_out": q["check_out_date"],
                           "adults": int(q.get("adults", 1)), "currency": q.get("currency", "USD"),
                           "saved_at": iso(rec["saved_at"]), "properties": props})
    for rec, b, data in raw_flights:
        its = data.get("itineraries", [])
        flights.append({"origin": b["origin"], "destination": b["destination"], "departure_date": b["departure_date"],
                        "return_date": b.get("return_date"), "adults": int(b.get("adults", 1)),
                        "saved_at": iso(rec["saved_at"]), "observed_at": data.get("observed_at"),
                        "itineraries": trim_fares(its, set(bookings)) if its else []})
    os.makedirs(OUT, exist_ok=True)
    key = lambda r: (r.get("origin", r.get("city")), r.get("destination", ""), r.get("departure_date", r.get("check_in")), r["adults"])
    for name, rows in (("flights", sorted(flights, key=key)), ("hotels", sorted(hotels, key=key))):
        with open(os.path.join(OUT, name + ".jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    with open(os.path.join(OUT, "bookings.jsonl"), "w", encoding="utf-8") as f:
        for i, b in sorted(bookings.items()):
            f.write(json.dumps({"ignav_id": i, **b}, ensure_ascii=False, separators=(",", ":")) + "\n")
    sizes = {n: os.path.getsize(os.path.join(OUT, n + ".jsonl")) for n in ("flights", "hotels", "bookings")}
    print(f"flights: {len(flights)} searches, hotels: {len(hotels)} searches, booking links: {len(bookings)}")
    print("sizes:", ", ".join(f"{n}.jsonl {s / 1e6:.1f} MB" for n, s in sizes.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
