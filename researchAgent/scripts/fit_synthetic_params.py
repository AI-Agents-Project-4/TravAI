"""Fit the synthetic test-data generator's parameters from the recorded sandbox data.

    python3 scripts/fit_synthetic_params.py

Reads sandbox_data/ (the recorded Ignav and SerpApi responses; kept local, not committed) and writes
synthetic_data/params.json: AGGREGATE numbers only (per-route and per-city price spreads, a distance-to-price fit, city
centres rounded to 2 decimals). No hotel names, ids, links, flight numbers or individual fares are written. The generator
(research/synthetic.py) needs only params.json, so anyone can generate test data without the recordings.

Re-run it after recording more data to refresh the parameters.
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from research.sandbox import norm_city  # noqa: E402

DATA = os.path.join(ROOT, "sandbox_data")
OUT = os.path.join(ROOT, "synthetic_data", "params.json")

# Approximate airport coordinates (lat, lon), public geographic facts. Used for distances and local-time offsets only.
AIRPORTS = {
    "DEN": (39.86, -104.67), "LAX": (33.94, -118.41), "JFK": (40.64, -73.78), "EWR": (40.69, -74.17), "LHR": (51.47, -0.45),
    "LGW": (51.15, -0.19), "BKK": (13.69, 100.75), "DMK": (13.91, 100.61), "SYD": (-33.94, 151.18), "MEX": (19.44, -99.07),
    "LIS": (38.78, -9.14), "HNL": (21.32, -157.92), "DXB": (25.25, 55.36), "GRU": (-23.43, -46.47), "CPT": (-33.97, 18.60),
    "MIA": (25.79, -80.29), "NRT": (35.77, 140.39), "HND": (35.55, 139.78), "ICN": (37.46, 126.44), "ATH": (37.94, 23.94),
    "ANC": (61.17, -150.00), "YVR": (49.19, -123.18), "BOG": (4.70, -74.14), "ORD": (41.98, -87.90), "SEA": (47.45, -122.31),
    "CUN": (21.04, -86.87), "CDG": (49.01, 2.55), "ORY": (48.72, 2.38), "KRK": (50.08, 19.78), "RZE": (50.11, 22.02),
    "KEF": (63.99, -22.62), "RKV": (64.13, -21.94), "NLU": (19.75, -99.02), "FCO": (41.80, 12.25), "CIA": (41.80, 12.59),
    "BCN": (41.30, 2.08), "MAD": (40.47, -3.56), "PHX": (33.43, -112.01), "SFO": (37.62, -122.38), "ATL": (33.64, -84.43),
    "DFW": (32.90, -97.04), "FRA": (50.03, 8.57), "AMS": (52.31, 4.76), "IST": (41.26, 28.74), "DOH": (25.27, 51.61),
    "SIN": (1.36, 103.99), "HKG": (22.31, 113.92), "MNL": (14.51, 121.02), "ADQ": (57.75, -152.49), "GAN": (-0.69, 73.16),
    "LAS": (36.08, -115.15), "MCO": (28.43, -81.31), "BOS": (42.37, -71.01), "YYZ": (43.68, -79.63), "SCL": (-33.39, -70.79),
    "LIM": (-12.02, -77.11), "NBO": (-1.32, 36.93), "CMN": (33.37, -7.59), "PRG": (50.10, 14.26), "BUD": (47.44, 19.26),
    "MUC": (48.35, 11.79), "ZRH": (47.46, 8.55), "DUB": (53.42, -6.27), "KIX": (34.43, 135.24), "PEK": (40.08, 116.59),
    "DEL": (28.56, 77.10), "AKL": (-37.01, 174.79), "MEL": (-37.67, 144.84), "HAN": (21.22, 105.81), "SGN": (10.82, 106.65),
    "CNX": (18.77, 98.96), "DPS": (-8.75, 115.17), "TBS": (41.67, 44.95), "SOF": (42.70, 23.41), "CUZ": (-13.54, -71.94),
    "OAX": (16.99, -96.73), "MDE": (6.16, -75.42), "LWO": (49.81, 23.96),
}


def haversine_km(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def rows(name: str) -> list:
    p = os.path.join(DATA, name + ".jsonl")
    if not os.path.exists(p):
        sys.exit(f"{p} not found. Run scripts/build_sandbox_index.py first (it needs the recorded cache).")
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def fit_line(xs: list, ys: list) -> tuple:
    mx, my = st.mean(xs), st.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    return a, b, st.pstdev(resid)


def main() -> int:
    # ---- flights: per-person round-trip fares by route
    routes: dict = {}
    for r in rows("flights"):
        if not r.get("return_date") or not r["itineraries"]:
            continue
        o, d = r["origin"], r["destination"]
        if o not in AIRPORTS or d not in AIRPORTS:
            continue
        pp = [i["price"]["amount"] / r["adults"] for i in r["itineraries"] if i["price"]["amount"] > 0]
        durs = [i["outbound"]["duration_minutes"] for i in r["itineraries"]]
        routes.setdefault((o, d), {"logs": [], "durs": []})
        routes[(o, d)]["logs"] += [math.log(p) for p in pp]
        routes[(o, d)]["durs"] += durs
    route_params, xs, ys = {}, [], []
    for (o, d), v in sorted(routes.items()):
        dist = haversine_km(AIRPORTS[o], AIRPORTS[d])
        mu, sigma = st.mean(v["logs"]), st.pstdev(v["logs"])
        route_params[f"{o}-{d}"] = {"mu": round(mu, 3), "sigma": round(sigma, 3), "dist_km": round(dist)}
        xs.append(math.log(max(dist, 100))); ys.append(mu)
    a, b, resid = fit_line(xs, ys)
    sigmas = [p["sigma"] for p in route_params.values() if p["sigma"] > 0]

    # ---- hotels: per-city nightly rate spread and city centre
    cities: dict = {}
    for r in rows("hotels"):
        key = norm_city(r["city"])
        c = cities.setdefault(key, {"logs": [], "lat": [], "lon": [], "ratings": [], "reviews": [], "types": {}, "name": r["city"]})
        for p in r["properties"]:
            if r["currency"] == "USD":   # other currencies would mix scales
                c["logs"].append(math.log(max(p["rate_per_night"]["extracted_lowest"], 1)))
            c["lat"].append(p["gps_coordinates"]["latitude"]); c["lon"].append(p["gps_coordinates"]["longitude"])
            if p.get("overall_rating"):
                c["ratings"].append(p["overall_rating"])
            if p.get("reviews"):
                c["reviews"].append(p["reviews"])
            c["types"][p.get("type", "hotel")] = c["types"].get(p.get("type", "hotel"), 0) + 1
    city_params = {}
    for key, c in sorted(cities.items()):
        logs = c["logs"]
        if len(logs) < 10:
            continue
        tot = sum(c["types"].values())
        city_params[key] = {"display": c["name"], "lat": round(st.median(c["lat"]), 2), "lon": round(st.median(c["lon"]), 2),
                            "night_mu": round(st.mean(logs), 3), "night_sigma": round(st.pstdev(logs), 3),
                            "rating_mean": round(st.mean(c["ratings"]), 2) if c["ratings"] else 4.0,
                            "reviews_median": round(st.median(c["reviews"])) if c["reviews"] else 300,
                            "types": {t: round(n / tot, 3) for t, n in sorted(c["types"].items())}}
    out = {
        "about": "Aggregate statistics fitted from recorded flight and hotel searches. Contains no individual fares, hotel names, ids or links.",
        "flights": {"fit": {"intercept": round(a, 3), "slope": round(b, 3), "resid_sigma": round(resid, 3),
                            "fare_sigma": round(st.median(sigmas), 3), "n_routes": len(route_params)},
                    "routes": route_params},
        "hotels": {"cities": city_params,
                   "global": {"night_mu": round(st.mean(c["night_mu"] for c in city_params.values()), 3),
                              "night_sigma": round(st.median(c["night_sigma"] for c in city_params.values()), 3)}},
        "airports": {k: list(v) for k, v in sorted(AIRPORTS.items())},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=False)
    print(f"flights: {len(route_params)} routes, price ~ exp({a:.2f}) * dist^{b:.2f} (residual sigma {resid:.2f}); "
          f"hotels: {len(city_params)} cities. Wrote {OUT} ({os.path.getsize(OUT) / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
