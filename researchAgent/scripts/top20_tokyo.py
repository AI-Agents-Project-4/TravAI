"""Layers 1-2 pricing test on 20 well-known Tokyo attractions.
Geocodes each name with Geoapify (20 requests), caches to tests/fixtures/top20_geocode.json, then runs price_for."""
import json, os, sys, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from research.pricing import WikivoyageIndex, frankfurter_fx, place_names, price_for, haversine_m

NAMES = ["Senso-ji", "Meiji Jingu", "Tokyo Skytree", "Tokyo Tower", "Shinjuku Gyoen", "Tokyo National Museum",
         "teamLab Planets", "Imperial Palace East Gardens", "Tsukiji Outer Market", "Ghibli Museum",
         "Tokyo Metropolitan Government Building", "Miraikan", "Yasukuni Shrine", "Nezu Museum", "Kabukiza",
         "Ueno Zoo", "Mori Art Museum", "Shibuya Sky", "Hamarikyu Gardens", "Zojoji"]
CACHE = os.path.join(ROOT, "tests", "fixtures", "top20_geocode.json")

def key():
    for line in open(os.path.join(ROOT, ".env")):
        if line.startswith("GEOAPIFY_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")

if os.path.exists(CACHE):
    geo = json.load(open(CACHE))
else:
    k, geo = key(), {}
    for n in NAMES:
        q = urllib.parse.urlencode({"text": n + ", Tokyo", "filter": "countrycode:jp", "bias": "proximity:139.76,35.68", "limit": 1, "lang": "en", "apiKey": k})
        with urllib.request.urlopen("https://api.geoapify.com/v1/geocode/search?" + q, timeout=30) as r:
            body = r.read().decode()
        geo[n] = json.loads(body.replace(k, "<redacted>"))["features"]
    json.dump(geo, open(CACHE, "w"), ensure_ascii=False)

idx = WikivoyageIndex("Tokyo").load()
fx = frankfurter_fx()
print(f"{'attraction':40} {'resolved as':32} {'km':>4}  result")
n_hit = 0
for n in NAMES:
    fs = geo[n]
    if not fs:
        print(f"{n:40} {'(not geocoded)':32}"); continue
    p = fs[0]["properties"]
    p.setdefault("lat", fs[0]["geometry"]["coordinates"][1]); p.setdefault("lon", fs[0]["geometry"]["coordinates"][0])
    km = haversine_m(35.68, 139.76, p["lat"], p["lon"]) / 1000
    r = price_for(p, idx, fx=fx, local_currency="JPY")
    resolved = (place_names(p) or [p.get("formatted", "?")])[0][:31]
    if r:
        n_hit += 1
        pr = r["price"]
        res = f"{pr['amount']:g} {pr['currency']}" + (f" (= ${pr['amount_normalized']})" if "amount_normalized" in pr else "") + f"  [{r['layer']}{', ambiguous' if r.get('ambiguous') else ''}]"
    else:
        res = "-- no price"
    print(f"{n:40} {resolved:32} {km:4.0f}  {res}")
print(f"\npriced {n_hit}/{len(NAMES)}")
