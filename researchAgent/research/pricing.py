"""Activity price lookup, layers 1 and 2 (free sources only).

Layer 1: OSM `fee=no` on the place -> price 0.
Layer 2: Wikivoyage see/do/eat listings -> parsed `price=` text.
Returns None when neither layer has a usable price; the caller falls through to
web search (layer 3) or a category estimate (layer 4). Never guesses.
"""
from __future__ import annotations

import difflib
import html
import json
import math
import os
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .core import ApiError, raw_get

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(ROOT, "tests", "fixtures", "wikivoyage")
UA = "travai-research-test/0.1"

CURRENCY_SYMBOLS = {"¥": "JPY", "円": "JPY", "yen": "JPY", "JPY": "JPY", "$": "USD", "USD": "USD", "US$": "USD",
                    "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP", "MXN": "MXN", "CHF": "CHF",
                    "ISK": "ISK", "kr": "ISK", "CAD": "CAD", "AUD": "AUD"}
FREE_WORDS = re.compile(r"^\W*(free|no charge|free of charge|free admission|gratis)\W*$", re.I)


# ---------- price text parsing ----------

@dataclass
class ParsedPrice:
    amount: float
    currency: Optional[str]
    ambiguous: bool = False   # several different amounts in the text (adult/child, tiers, add-ons)
    raw: str = ""


def clean_wikitext(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)      # [[a|b]] -> b
    s = re.sub(r"\{\{[^{}]*\}\}", " ", s)                          # drop templates
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_price_text(text: str) -> Optional[ParsedPrice]:
    """Return the first amount found, flagging ambiguity. None if no amount and not free."""
    t = clean_wikitext(text or "")
    if not t:
        return None
    if FREE_WORDS.match(t):
        return ParsedPrice(0.0, None, False, t)
    pat = re.compile(r"(US\$|[¥€£$]|\b[A-Z]{3}\b|\bkr\b)?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(円|yen|JPY|USD|EUR|GBP|\bkr\b)?", re.I)
    found = []
    for m in pat.finditer(t):
        prefix, num, suffix = m.group(1), m.group(2), m.group(3)
        cur = None
        for tok in (prefix, suffix):
            if tok and (tok in CURRENCY_SYMBOLS or tok.upper() in CURRENCY_SYMBOLS or tok.lower() in CURRENCY_SYMBOLS):
                cur = CURRENCY_SYMBOLS.get(tok) or CURRENCY_SYMBOLS.get(tok.upper()) or CURRENCY_SYMBOLS.get(tok.lower())
        found.append((float(num.replace(",", "")), cur))
    # ignore bare numbers that look like years, ages or times when a currency amount exists
    with_cur = [f for f in found if f[1]]
    use = with_cur or found
    if not use:
        return ParsedPrice(0.0, None, False, t) if re.search(r"\bfree\b", t, re.I) and not re.search(r"\d", t) else None
    amounts = {a for a, _ in use}
    # several amounts (range, adult/child, add-ons): take the highest so we never underestimate
    amount, cur = max(use, key=lambda x: x[0])
    paid_and_free = bool(re.search(r"\bfree\b", t, re.I)) and amount > 0
    return ParsedPrice(amount, cur, ambiguous=len(amounts) > 1 or paid_and_free or not cur, raw=t)


# ---------- name matching ----------

STOP = {"the", "of", "de", "a", "temple", "shrine", "museum", "park", "garden", "gardens", "tokyo", "national"}


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9぀-ヿ一-鿿 ]+", " ", s)
    words = s.split()
    kept = [w for w in words if w not in STOP]
    return " ".join(kept or words)   # a name made only of generic words keeps them


def name_score(a: str, b: str) -> float:
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


def place_names(props: dict) -> list[str]:
    raw = (props.get("datasource") or {}).get("raw") or {}
    intl = props.get("name_international") or {}
    names = [intl.get("en"), raw.get("name:en"), raw.get("int_name"), props.get("name")]
    return [n for n in dict.fromkeys(names) if n]


# ---------- Wikivoyage ----------

@dataclass
class Listing:
    kind: str
    name: str
    alt: str
    lat: Optional[float]
    lon: Optional[float]
    price_text: str
    page: str
    names: list = field(default_factory=list)
    url: str = ""
    content: str = ""


def _split_params(body: str) -> dict:
    """Split a template body on top-level pipes (ignoring pipes inside [[ ]] and {{ }})."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1; cur += two; i += 2; continue
        if two in ("]]", "}}"):
            depth -= 1; cur += two; i += 2; continue
        if body[i] == "|" and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += body[i]
        i += 1
    parts.append(cur)
    out = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def parse_listings(wikitext: str, page: str) -> list[Listing]:
    out = []
    for m in re.finditer(r"\{\{\s*(see|do|eat|listing)\s*\|", wikitext, re.I):
        start, depth, i = m.start(), 0, m.start()
        while i < len(wikitext):
            two = wikitext[i:i + 2]
            if two == "{{": depth += 1; i += 2; continue
            if two == "}}":
                depth -= 1; i += 2
                if depth == 0: break
                continue
            i += 1
        body = wikitext[start + 2:i - 2]
        p = _split_params(body)
        name = clean_wikitext(p.get("name", ""))
        if not name:
            continue
        def f(k):
            try: return float(p.get(k, ""))
            except ValueError: return None
        alts = [clean_wikitext(p.get(k, "")) for k in ("alt", "name-local", "name-latin")]
        out.append(Listing(m.group(1).lower(), name, alts[0], f("lat"), f("long"), p.get("price", ""), page,
                           [n for n in [name, *alts] if n], clean_wikitext(p.get("url", "")), clean_wikitext(p.get("content", ""))))
    return out


class WikivoyageIndex:
    def __init__(self, city: str, cache_dir: str = DEFAULT_CACHE, fetch_many: Optional[Callable[[list], dict]] = None):
        self.city, self.cache_dir = city, cache_dir
        self._fetch_many = fetch_many or self._http_fetch_many
        self.listings: list[Listing] = []

    def _api(self, params: dict) -> dict:
        url = "https://en.wikivoyage.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
        for attempt in range(6):
            status, headers, body = raw_get(url, headers={"User-Agent": UA}, timeout=30)
            if status == 429 and attempt < 5:
                time.sleep(float(headers.get("retry-after") or 2 ** attempt * 2))
                continue
            if status >= 400:
                raise ApiError(status, body.decode("utf-8", "replace"), url)
            return json.loads(body)
        raise RuntimeError("unreachable")

    def _http_fetch_many(self, titles: list[str]) -> dict[str, str]:
        d = self._api({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": "|".join(titles)})
        return {pg["title"]: pg["revisions"][0]["slots"]["main"]["content"]
                for pg in d["query"]["pages"] if pg.get("revisions")}

    def _page_titles(self) -> list[str]:
        path = os.path.join(self.cache_dir, f"_index_{self.city}.json")
        if os.path.exists(path):
            return json.load(open(path))
        d = self._api({"action": "query", "list": "allpages", "apprefix": self.city + "/", "aplimit": 100})
        titles = [self.city] + [p["title"] for p in d["query"]["allpages"]]
        os.makedirs(self.cache_dir, exist_ok=True)
        json.dump(titles, open(path, "w"))
        return titles

    def _path(self, title: str) -> str:
        return os.path.join(self.cache_dir, title.replace("/", "__") + ".wiki")

    def load(self) -> "WikivoyageIndex":
        os.makedirs(self.cache_dir, exist_ok=True)
        titles = self._page_titles()
        missing = [t for t in titles if not os.path.exists(self._path(t))]
        for i in range(0, len(missing), 15):
            batch = missing[i:i + 15]
            got = self._fetch_many(batch)
            for t in batch:
                # pages that do not exist are cached as empty so we do not refetch
                open(self._path(t), "w", encoding="utf-8").write(got.get(t, ""))
            if i + 15 < len(missing):
                time.sleep(1)
        for t in titles:
            self.listings += parse_listings(open(self._path(t), encoding="utf-8").read(), t)
        return self

    def candidates(self, lat: float, lon: float, radius_m: int = 15000, kinds=("see", "do")) -> list[Listing]:
        """Curated listings with coordinates near a point."""
        return [l for l in self.listings if l.kind in kinds and l.lat is not None and l.lon is not None
                and haversine_m(lat, lon, l.lat, l.lon) <= radius_m]

    def match(self, names: list[str], lat: Optional[float], lon: Optional[float]) -> Optional[Listing]:
        best, best_score = None, 0.0
        for l in self.listings:
            s = max((name_score(a, b) for a in names for b in l.names), default=0.0)
            near = (lat is not None and l.lat is not None and haversine_m(lat, lon, l.lat, l.lon) <= 200)
            if s >= 0.9 or (near and s >= 0.75):
                if s > best_score:
                    best, best_score = l, s
        return best


# ---------- public API ----------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_price(amount: float, currency: str, price_type: str, retrieved_at: str, *, target_currency: str = "USD",
               fx: Optional[Callable[[str, str], float]] = None, **extra) -> dict:
    p = {"amount": amount, "currency": currency, "basis": "per_person", "price_type": price_type,
         "includes_taxes_fees": None, "retrieved_at": retrieved_at, **extra}
    if currency != target_currency and amount > 0:
        if fx is None:
            raise ValueError("fx required for non-target currency")
        rate = fx(currency, target_currency)
        p["fx_rate"] = rate
        p["amount_normalized"] = round(amount * rate, 2)
    return p


def osm_fee_price(props: dict, target_currency: str = "USD", retrieved_at: Optional[str] = None) -> Optional[dict]:
    """Layer 1. Only fee=no is useful (yes carries no amount)."""
    raw = (props.get("datasource") or {}).get("raw") or {}
    if str(raw.get("fee", "")).lower() != "no":
        return None
    t = {"n": "node", "w": "way", "r": "relation"}.get(raw.get("osm_type"))
    if not (t and raw.get("osm_id")):
        return None
    return {"price": make_price(0, target_currency, "published_rate", retrieved_at or now_iso(), target_currency=target_currency),
            "source": {"url": f"https://www.openstreetmap.org/{t}/{raw['osm_id']}", "provider": "osm"},
            "layer": "osm_fee", "notes": "OSM fee=no"}


def wikivoyage_price(props: dict, index: WikivoyageIndex, target_currency: str = "USD",
                     fx: Optional[Callable[[str, str], float]] = None, local_currency: Optional[str] = None,
                     retrieved_at: Optional[str] = None) -> Optional[dict]:
    """Layer 2. local_currency fills in when the listing has a bare number with no symbol."""
    l = index.match(place_names(props), props.get("lat"), props.get("lon"))
    if not l:
        return None
    parsed = parse_price_text(l.price_text)
    if not parsed:
        return None
    cur = parsed.currency or (target_currency if parsed.amount == 0 else local_currency)
    if not cur:
        return None
    page_url = "https://en.wikivoyage.org/wiki/" + urllib.parse.quote(l.page.replace(" ", "_"))
    notes = f"Wikivoyage '{l.name}': \"{parsed.raw}\""
    if parsed.ambiguous:
        notes += " (multiple amounts or unclear currency; highest amount used)"
    return {"price": make_price(parsed.amount, cur, "published_rate", retrieved_at or now_iso(),
                                target_currency=target_currency, fx=fx),
            "source": {"url": page_url, "provider": "wikivoyage"},
            "layer": "wikivoyage", "ambiguous": parsed.ambiguous, "notes": notes}


def price_for(props: dict, index: Optional[WikivoyageIndex], **kw) -> Optional[dict]:
    """Layers 1 then 2. Returns {price, source, layer, notes} or None."""
    retrieved_at = kw.get("retrieved_at")
    hit = osm_fee_price(props, kw.get("target_currency", "USD"), retrieved_at)
    if hit:
        return hit
    return wikivoyage_price(props, index, **kw) if index else None


def frankfurter_fx(cache: dict = {}) -> Callable[[str, str], float]:
    def fx(base: str, quote: str) -> float:
        key = (base, quote)
        if key not in cache:
            url = f"https://api.frankfurter.dev/v1/latest?base={base}&symbols={quote}"
            status, _h, body = raw_get(url, headers={"User-Agent": UA}, timeout=30)
            if status >= 400:
                raise ApiError(status, body.decode("utf-8", "replace"), url)
            cache[key] = json.loads(body)["rates"][quote]
        return cache[key]
    return fx
