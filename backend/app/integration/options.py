"""Turn a research agent output into the contract's `Option` rows.

The research output (researchAgent/schema/research_output.schema.json) is richer
than the contract's `Option`, and its prices have mixed bases: flights are a
total for everyone, hotels are per room per night, activities are per person.
The contract says `price` is the total for the whole party, so this module does
the multiplication (product rule 1: never underestimate):

- per_person x travelers; per_night x nights; hotels x rooms (2 people a room);
- an unknown basis is treated as per person (the higher reading);
- estimates are rounded up to a whole unit, other prices up to the cent.

Everything here is untrusted web data (product rule 6, threat model T1/T3): text
is cleaned and capped, links must have a sane shape, and an item that fails is
dropped and counted, never "fixed" into something it didn't say.
"""

from __future__ import annotations

import contextlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any
from urllib.parse import urlsplit

MAX_TITLE = 200
MAX_DESCRIPTION = 1000
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class MappedOption:
    """One option, before it has a database id. `key` is the research agent's id."""

    key: str
    kind: str
    title: str
    price_amount: Decimal
    price_currency: str
    price_is_estimate: bool
    source_url: str
    fetched_at: datetime
    description: str | None = None
    location_name: str | None = None
    lat: float | None = None
    lng: float | None = None
    duration_minutes: int | None = None
    opening_hours: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MappingResult:
    options: list[MappedOption]
    rejected: list[str]  # "<research id>: <reason>", for logs and the eval


class Rejected(ValueError):
    pass


# Zero-width, bidi and other invisible format characters hide instructions or
# fake text direction (T1). Category "Cf" covers them; "Cc" is control chars.
def clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = "".join(ch for ch in str(value) if unicodedata.category(ch) not in ("Cf", "Cc"))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def check_link(url: Any) -> str:
    """A link we only show, never fetch: http(s), a real host, no credentials, no IP, no odd port.

    Same rules as the research agent's `fetch_guard.check_link_shape(allow_http=True)`.
    Plain http is allowed because some official sites have no https link.
    """
    if not isinstance(url, str) or not url:
        raise Rejected("no source link")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise Rejected(f"source link scheme {parts.scheme!r} is not http(s)")
    if parts.username or parts.password:
        raise Rejected("source link contains credentials")
    host = (parts.hostname or "").lower()
    if "." not in host:
        raise Rejected("source link has no usable host")
    if re.fullmatch(r"[\d.]+", host) or ":" in host:
        raise Rejected("source link host is an IP address")
    try:
        port = parts.port
    except ValueError:
        raise Rejected("source link has an invalid port") from None
    if port not in (None, 80, 443):
        raise Rejected(f"source link uses port {port}")
    return url


def _fetched_at(value: Any, now: datetime) -> datetime:
    if not isinstance(value, str):
        raise Rejected("no retrieval time")
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Rejected(f"bad retrieval time {value!r}") from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return min(when, now)  # a time in the future can't be true


def _amount(price: dict[str, Any], output_currency: str) -> tuple[Decimal, str]:
    raw = price.get("amount_normalized", price.get("amount"))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise Rejected("price is not a number")
    if raw < 0:
        raise Rejected("price is negative")
    currency = output_currency if "amount_normalized" in price else price.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise Rejected("price has no valid currency")
    return Decimal(str(raw)), currency


def round_up(amount: Decimal, estimate: bool) -> Decimal:
    """Product rule 1: estimates up to a whole unit, quotes up to the cent."""
    step = Decimal("1") if estimate else Decimal("0.01")
    return amount.quantize(step, rounding=ROUND_CEILING).quantize(Decimal("0.01"))


def _multiplier(basis: str | None, travelers: int, nights: int, rooms: int) -> int:
    if basis in ("total_all_travelers", "per_group"):
        return 1
    if basis == "per_night":
        return max(nights, 1) * rooms
    return travelers  # "per_person", or unknown: assume the higher reading


def format_hours(hours: Any) -> str | None:
    """{"mon": {"open": "10:00", "close": "17:00"}, ...} -> "Mon 10:00-17:00, Tue ..."."""
    if not isinstance(hours, dict) or not hours:
        return None
    parts = []
    for day in DAYS:
        h = hours.get(day)
        if isinstance(h, dict) and h.get("open") and h.get("close"):
            parts.append(f"{day.title()} {h['open']}-{h['close']}")
    closed = [d.title() for d in DAYS if d not in hours]
    if closed:
        parts.append("closed " + ", ".join(closed))
    return ", ".join(parts) or None


def _common(item: dict[str, Any], price: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or {}
    confidence = item.get("confidence") or {}
    details: dict[str, Any] = {
        "research_id": item.get("id"),
        "price_type": price.get("price_type"),
        "price_basis": price.get("basis"),
        "price_layer": price.get("price_layer"),
        "provider": source.get("provider"),
        "confidence": confidence.get("level"),
        "verified": bool(confidence.get("verified")),
        "synthetic": source.get("provider") == "synthetic",
    }
    if price.get("estimate_method"):
        details["estimate_method"] = clean_text(price["estimate_method"], 300)
    if confidence.get("notes"):
        details["confidence_notes"] = clean_text(confidence["notes"], 300)
    return details


def _flight(f: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]]:
    segs = f.get("segments") or []
    split = f.get("return_segment_start_index") or len(segs)
    out = segs[:split]
    route = "–".join([out[0]["from"], out[-1]["to"]]) if out else "?"
    carriers = sorted({s.get("carrier") for s in segs if s.get("carrier")})
    label = {
        "round_trip": "Round trip",
        "outbound": "Outbound flight",
        "return": "Return flight",
        "intercity": "Flight",
    }.get(f.get("direction", ""), "Flight")
    title = f"{label} {route}" + (f", {' / '.join(carriers)}" if carriers else "")
    stops = f.get("stops")
    minutes = f.get("duration_minutes")
    bits = []
    if isinstance(stops, int):
        bits.append("nonstop" if stops == 0 else f"{stops} stop{'s' if stops > 1 else ''}")
    if isinstance(minutes, int):
        bits.append(f"{minutes // 60}h{minutes % 60:02d} in the air and on layovers")
    details = {
        "role": f.get("direction"),
        "segments": segs,
        "return_segment_start_index": f.get("return_segment_start_index"),
        "stops": stops,
        "cabin": f.get("cabin"),
        "arrive_airport": out[-1]["to"] if out else None,
        "depart_airport": out[0]["from"] if out else None,
    }
    if f.get("direction") == "round_trip" and split < len(segs):
        details["return_depart_airport"] = segs[split]["from"]
    return title, ", ".join(bits) or None, details


def _transport_role(g: dict[str, Any]) -> str:
    gid = str(g.get("id", ""))
    if gid.startswith("gt-apt-"):
        return "airport_transfer"
    if gid == "gt-origin-drive":
        return "drive"
    if gid == "gt-car-rental":
        return "car_rental"
    if g.get("from") and g.get("to") and g.get("from") != g.get("to"):
        return "intercity"
    return "local"


def map_research(
    output: dict[str, Any], *, travelers: int, now: datetime | None = None
) -> MappingResult:
    """Map every flight, hotel, activity and transport leg the research found."""
    now = now or datetime.now(UTC)
    currency = output.get("currency") or "USD"
    rooms = max(1, math.ceil(travelers / 2))
    options: list[MappedOption] = []
    rejected: list[str] = []
    seen: set[str] = set()

    def add(item: dict[str, Any], build: Any) -> None:
        rid = str(item.get("id") or f"item-{len(options) + len(rejected)}")
        try:
            option = build(item)
        except (Rejected, KeyError, TypeError, IndexError) as exc:
            rejected.append(f"{rid}: {exc}")
            return
        key = rid
        n = 2
        while key in seen:  # ids should be unique; never let a duplicate overwrite
            key = f"{rid}#{n}"
            n += 1
        seen.add(key)
        option.key = key
        options.append(option)

    def flight(f: dict[str, Any]) -> MappedOption:
        price = f["price"]
        amount, cur = _amount(price, currency)
        estimate = price.get("price_type") == "estimate"
        title, description, extra = _flight(f)
        return MappedOption(
            key="",
            kind="flight",
            title=clean_text(title, MAX_TITLE) or "Flight",
            description=description,
            price_amount=round_up(
                amount * _multiplier(price.get("basis"), travelers, 1, 1), estimate
            ),
            price_currency=cur,
            price_is_estimate=estimate,
            source_url=check_link((f.get("source") or {}).get("url")),
            fetched_at=_fetched_at(price.get("retrieved_at"), now),
            duration_minutes=f.get("duration_minutes"),
            details=_common(f, price) | extra,
        )

    def hotel(h: dict[str, Any]) -> MappedOption:
        nights = 1
        if h.get("check_in") and h.get("check_out"):
            nights = max(
                1,
                (
                    datetime.fromisoformat(h["check_out"]) - datetime.fromisoformat(h["check_in"])
                ).days,
            )
        stay = h.get("total_stay_price")
        price = stay if isinstance(stay, dict) else h["price"]
        amount, cur = _amount(price, currency)
        estimate = price.get("price_type") == "estimate"
        basis = price.get("basis")
        # A stay total is for one room; more than 2 travelers need more rooms.
        mult = rooms if basis in ("per_group", "total_all_travelers") else 0
        mult = mult or _multiplier(basis, travelers, nights, rooms)
        name = clean_text(h.get("name"), MAX_TITLE) or "Hotel"
        area = clean_text(h.get("area"), 100)
        rating = h.get("rating")
        loc = h.get("location") or {}
        return MappedOption(
            key="",
            kind="hotel",
            title=name,
            description=(
                f"{nights} night{'s' if nights > 1 else ''}"
                + (f", {rooms} rooms" if rooms > 1 else "")
                + (f", rated {rating}" if rating else "")
            ),
            price_amount=round_up(amount * mult, estimate),
            price_currency=cur,
            price_is_estimate=estimate,
            source_url=check_link((h.get("source") or {}).get("url")),
            fetched_at=_fetched_at(price.get("retrieved_at"), now),
            location_name=area,
            lat=loc.get("lat"),
            lng=loc.get("lng"),
            details=_common(h, price)
            | {
                "role": "lodging",
                "stop": area,
                "check_in": h.get("check_in"),
                "check_out": h.get("check_out"),
                "nights": nights,
                "rooms": rooms,
                "rating": rating,
            },
        )

    def activity(a: dict[str, Any]) -> MappedOption:
        price = a["price"]
        amount, cur = _amount(price, currency)
        estimate = price.get("price_type") == "estimate"
        category = a.get("category")
        area = clean_text(a.get("area"), 100)
        loc = a.get("location") or {}
        details = _common(a, price) | {
            "role": "day_trip" if category == "day_trip" else "activity",
            "category": category,
            "area": area,  # a neighborhood, not a trip stop
            "hours": a.get("hours"),
            "name_local": clean_text(a.get("name_local"), MAX_TITLE),
        }
        if a.get("round_trip_from_base_minutes"):
            details["round_trip_from_base_minutes"] = a["round_trip_from_base_minutes"]
        if (a.get("price_source") or {}).get("url"):
            with contextlib.suppress(Rejected):
                details["price_source_url"] = check_link(a["price_source"]["url"])
        return MappedOption(
            key="",
            kind="food" if category == "food" else "activity",
            title=clean_text(a.get("name"), MAX_TITLE) or "Activity",
            description=clean_text(a.get("description"), MAX_DESCRIPTION),
            price_amount=round_up(
                amount * _multiplier(price.get("basis"), travelers, 1, rooms), estimate
            ),
            price_currency=cur,
            price_is_estimate=estimate,
            source_url=check_link((a.get("source") or {}).get("url")),
            fetched_at=_fetched_at(price.get("retrieved_at"), now),
            location_name=area,
            lat=loc.get("lat"),
            lng=loc.get("lng"),
            duration_minutes=a.get("duration_minutes"),
            opening_hours=format_hours(a.get("hours")),
            details=details,
        )

    def transport(g: dict[str, Any]) -> MappedOption:
        price = g.get("price")
        if not isinstance(price, dict):
            raise Rejected("transport leg has no price")
        amount, cur = _amount(price, currency)
        estimate = price.get("price_type") == "estimate"
        role = _transport_role(g)
        src, dst = clean_text(g.get("from"), 100), clean_text(g.get("to"), 100)
        mode = str(g.get("mode") or "transport")
        if role == "car_rental":
            title = f"Car rental in {dst}"
        elif role in ("airport_transfer", "drive"):  # used both ways: there and back
            title = f"{mode.title()} between {src} and {dst}"
        else:
            title = f"{mode.title()}: {src} to {dst}"
        km = g.get("distance_km")
        geo = g.get("to_geo") or {}
        gid = str(g.get("id", ""))
        return MappedOption(
            key="",
            kind="transport",
            title=clean_text(title, MAX_TITLE) or "Transport",
            description=f"About {round(km)} km" if isinstance(km, (int, float)) else None,
            price_amount=round_up(
                amount * _multiplier(price.get("basis"), travelers, 1, rooms), estimate
            ),
            price_currency=cur,
            price_is_estimate=estimate,
            source_url=check_link((g.get("source") or {}).get("url")),
            fetched_at=_fetched_at(price.get("retrieved_at"), now),
            location_name=dst,
            lat=geo.get("lat"),
            lng=geo.get("lng"),
            duration_minutes=g.get("duration_minutes"),
            details=_common(g, price)
            | {
                "role": role,
                "mode": mode,
                "from": src,
                "to": dst,
                "stop": dst,
                "airport": gid.removeprefix("gt-apt-") if role == "airport_transfer" else None,
            },
        )

    for f in output.get("flights") or []:
        add(f, flight)
    for h in output.get("lodging") or []:
        add(h, hotel)
    for a in output.get("activities") or []:
        add(a, activity)
    for g in output.get("ground_transport") or []:
        add(g, transport)
    return MappingResult(options=options, rejected=rejected)
