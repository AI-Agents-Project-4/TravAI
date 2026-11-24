"""Thin clients for each data source. Every call goes through the disk cache in core.http."""
from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional

from . import sandbox
from .core import ApiError, CacheMiss, data_mode, http, secret
from .security.network_policy import host_is_live

DAY = 86400


# ---------- Ignav (flights) ----------

def _ignav_headers(offline: bool = False) -> dict:
    return {"X-Api-Key": secret("IGNAV_API_KEY", offline), "Content-Type": "application/json"}


def _no_recording(kind: str, key: dict, what: str) -> ApiError:
    sandbox.log_miss(kind, key)
    return ApiError(404, f"sandbox: no recorded {what} close enough to this request")


def ignav_roundtrip(origin: str, dest: str, depart: str, ret: str, adults: int, offline: bool) -> dict:
    if data_mode() == "sandbox":
        r = sandbox.find_flights(origin, dest, depart, ret, adults)
        if r is None:
            raise _no_recording("flight", {"origin": origin, "destination": dest, "departure_date": depart, "return_date": ret, "adults": adults}, "fares")
        return r
    body = {"origin": origin, "destination": dest, "departure_date": depart, "return_date": ret}
    if adults > 1:
        body["adults"] = adults
    return http("POST", "https://ignav.com/api/fares/round-trip", body, _ignav_headers(offline), offline=offline)


def ignav_oneway(origin: str, dest: str, depart: str, adults: int, offline: bool) -> dict:
    if data_mode() == "sandbox":
        r = sandbox.find_flights(origin, dest, depart, None, adults)
        if r is None:
            raise _no_recording("flight", {"origin": origin, "destination": dest, "departure_date": depart, "return_date": None, "adults": adults}, "fares")
        return r
    body = {"origin": origin, "destination": dest, "departure_date": depart}
    if adults > 1:
        body["adults"] = adults
    return http("POST", "https://ignav.com/api/fares/one-way", body, _ignav_headers(offline), offline=offline)


def ignav_booking(ignav_id: str, offline: bool) -> dict:
    if data_mode() == "sandbox":
        b = sandbox.find_booking(ignav_id)
        if b is None:
            raise ApiError(404, "sandbox: no recorded booking link for this fare")
        return b
    return http("POST", "https://ignav.com/api/fares/booking-links", {"ignav_id": ignav_id}, _ignav_headers(offline), offline=offline)


# ---------- SerpApi (hotels) ----------

def serp_hotels(query: str, check_in: str, check_out: str, adults: int, currency: str, offline: bool) -> dict:
    if data_mode() == "sandbox":
        r = sandbox.find_hotels(query, check_in, check_out, adults, currency, lambda a, b: fx_rate(a, b, offline))
        if r is None:
            raise _no_recording("hotel", {"city": query.removesuffix(" hotels"), "check_in": check_in, "check_out": check_out,
                                          "adults": adults, "currency": currency}, "hotel rates")
        return r
    q = urllib.parse.urlencode({"engine": "google_hotels", "q": query, "check_in_date": check_in, "check_out_date": check_out,
                                "adults": adults, "currency": currency, "gl": "us", "hl": "en", "api_key": secret("SERP_API_KEY", offline)})
    return http("GET", "https://serpapi.com/search.json?" + q, offline=offline)


# ---------- Geoapify (places, geocoding, routing) ----------

def _geo(path: str, params: dict, offline: bool) -> dict:
    q = urllib.parse.urlencode({**params, "apiKey": secret("GEOAPIFY_API_KEY", offline)})
    return http("GET", f"https://api.geoapify.com{path}?{q}", offline=offline)


def geocode(text: str, offline: bool, country_code: Optional[str] = None) -> Optional[dict]:
    """Return {lat, lon, name, props} or None."""
    p = {"text": text, "limit": 1, "lang": "en"}
    if country_code:
        p["filter"] = f"countrycode:{country_code.lower()}"
    fs = _geo("/v1/geocode/search", p, offline).get("features", [])
    if not fs:
        return None
    pr = fs[0]["properties"]
    return {"lat": pr["lat"], "lon": pr["lon"], "name": pr.get("formatted") or text, "props": pr}


def places(categories: str, lat: float, lon: float, radius_m: int, limit: int, offline: bool) -> list[dict]:
    p = {"categories": categories, "filter": f"circle:{lon},{lat},{radius_m}", "bias": f"proximity:{lon},{lat}",
         "limit": limit, "lang": "en"}
    return [f["properties"] for f in _geo("/v2/places", p, offline).get("features", [])]


def route(a: tuple, b: tuple, mode: str, offline: bool) -> Optional[dict]:
    """a, b are (lat, lon). Returns {distance_km, duration_minutes} or None when no route exists."""
    try:
        d = _geo("/v1/routing", {"waypoints": f"{a[0]},{a[1]}|{b[0]},{b[1]}", "mode": mode}, offline)
    except ApiError as e:
        if e.status in (400, 404):
            return None
        raise
    f = (d.get("features") or [None])[0]
    if not f:
        return None
    pr = f["properties"]
    return {"distance_km": round(pr["distance"] / 1000, 1), "duration_minutes": round(pr["time"] / 60)}


# ---------- State Dept advisories ----------

LEVELS = {1: "normal", 2: "caution", 3: "reconsider", 4: "do_not_travel"}


def advisories(offline: bool) -> list[dict]:
    xml = http("GET", "https://travel.state.gov/_res/rss/TAsTWs.xml", offline=offline, ttl=DAY, parse=False)
    out = []
    for item in ET.fromstring(xml).iter("item"):
        title = item.findtext("title") or ""
        m = re.match(r"(.+?) - Level (\d)", title)
        if not m:
            continue
        desc = re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or ""))
        out.append({"country": m.group(1).strip(), "level": LEVELS[int(m.group(2))], "level_num": int(m.group(2)),
                    "summary": re.sub(r"\s+", " ", desc).strip()[:500], "link": item.findtext("link") or "",
                    "title": title})
    return out


# ---------- FX ----------

def fx_rate(base: str, quote: str, offline: bool) -> float:
    """Frankfurter (ECB rates) first; it lacks currencies like UAH, so fall back to open.er-api.com (free, no key)."""
    if base == quote:
        return 1.0
    try:
        d = http("GET", f"https://api.frankfurter.dev/v1/latest?base={base}&symbols={quote}", offline=offline, ttl=DAY)
        return float(d["rates"][quote])
    except ApiError as e:
        if e.status not in (404, 422):
            raise
    except CacheMiss:
        # Errors are never cached, so a currency Frankfurter lacks looks like a cache miss when replaying offline.
        if not (offline or not host_is_live("api.frankfurter.dev")):  # sandbox: this host is cache-only, so a miss means "not covered"
            raise
    d = http("GET", f"https://open.er-api.com/v6/latest/{base}", offline=offline, ttl=DAY)
    if d.get("result") != "success" or quote not in d.get("rates", {}):
        raise ApiError(404, f"no FX rate for {base}->{quote}")
    return float(d["rates"][quote])
