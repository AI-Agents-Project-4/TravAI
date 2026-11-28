"""Validate an option before it is saved to the database (threat model T1, T2, T5).

The model extracts fields from a web page. Nothing it returns is trusted until it
passes `validate_option`. Rejections list every reason so they can be logged and
counted in the eval.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from . import config
from .fetch_guard import BlockedURL, check_url_syntax

OPTION_KINDS = ("flight", "hotel", "activity", "transport", "food")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_CLOCK_SKEW = timedelta(minutes=5)


class OptionRejected(Exception):
    """The option failed validation. `reasons` has every problem found."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class ValidatedOption:
    kind: str
    title: str
    price_amount: float
    price_currency: str
    price_is_estimate: bool
    source_url: str
    fetched_at: datetime  # timezone-aware UTC
    description: str | None = None
    extra: Mapping[str, Any] | None = None  # location, hours, details: passed through

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "title": self.title,
            "price": {"amount": self.price_amount, "currency": self.price_currency},
            "price_is_estimate": self.price_is_estimate,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at.isoformat(),
        }
        if self.description is not None:
            out["description"] = self.description
        if self.extra:
            out.update(self.extra)
        return out


def _clean_text(value: Any, name: str, max_chars: int, reasons: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        reasons.append(f"{name} must be a non-empty string")
        return None
    if len(value) > max_chars:
        reasons.append(f"{name} is longer than {max_chars} characters")
        return None
    # Control and invisible characters (zero-width, bidi overrides) are how hidden
    # instructions travel. Real titles don't need them. Newlines are fine in descriptions.
    for ch in value:
        if ch in "\n\t":
            continue
        if unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs"):
            reasons.append(f"{name} contains control or invisible characters")
            return None
    return value.strip()


def _parse_fetched_at(value: Any, now: datetime, reasons: list[str]) -> datetime | None:
    if not isinstance(value, str):
        reasons.append("fetched_at must be an ISO 8601 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        reasons.append("fetched_at is not valid ISO 8601")
        return None
    if parsed.tzinfo is None:
        reasons.append("fetched_at must include a timezone")
        return None
    parsed = parsed.astimezone(timezone.utc)
    if parsed > now + _CLOCK_SKEW:
        reasons.append("fetched_at is in the future")
        return None
    return parsed


def validate_option(
    raw: Mapping[str, Any],
    *,
    source_hosts: Iterable[str] = config.SOURCE_LINK_HOSTS,
    travelers: int = 1,
    usd_rates: Mapping[str, float] = config.DEFAULT_USD_RATES,
    price_ranges_usd: Mapping[str, tuple[float, float]] = config.PRICE_RANGES_USD,
    now: datetime | None = None,
) -> ValidatedOption:
    """Return a normalized option, or raise OptionRejected listing every problem.

    Estimated prices are rounded UP to a whole currency unit (product rule 1).
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    kind = raw.get("kind")
    if kind not in OPTION_KINDS:
        reasons.append(f"kind must be one of {', '.join(OPTION_KINDS)}")
        kind = None

    title = _clean_text(raw.get("title"), "title", config.MAX_TITLE_CHARS, reasons)

    description = None
    if raw.get("description") is not None:
        description = _clean_text(
            raw["description"], "description", config.MAX_DESCRIPTION_CHARS, reasons
        )

    # Price
    amount: float | None = None
    currency: str | None = None
    price = raw.get("price")
    if not isinstance(price, Mapping):
        reasons.append("price must be an object with amount and currency")
    else:
        a = price.get("amount")
        if isinstance(a, bool) or not isinstance(a, (int, float)) or not math.isfinite(a):
            reasons.append("price.amount must be a finite number")
        elif a < 0:
            reasons.append("price.amount must not be negative")
        else:
            amount = float(a)
        c = price.get("currency")
        if not isinstance(c, str) or not _CURRENCY.match(c):
            reasons.append("price.currency must be a 3-letter uppercase ISO 4217 code")
        else:
            currency = c

    estimate = raw.get("price_is_estimate")
    if not isinstance(estimate, bool):
        reasons.append("price_is_estimate must be true or false")
        estimate = None
    elif estimate and amount is not None:
        amount = float(math.ceil(amount))

    # Plausibility (T1, T2): the price must fall in the range for its kind.
    if amount is not None and currency is not None and kind is not None:
        rate = usd_rates.get(currency)
        if rate is None or rate <= 0:
            reasons.append(f"no exchange rate for {currency}, cannot check the price")
        else:
            low, high = price_ranges_usd[kind]
            usd = amount * rate
            high *= max(travelers, 1)
            if usd < low or usd > high:
                reasons.append(
                    f"price is outside the plausible range for {kind} "
                    f"(about ${usd:,.2f}, expected ${low:,.0f} to ${high:,.0f})"
                )

    # Source (T3): required, https, on the allowlist.
    source_url = raw.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        reasons.append("source_url is required")
        source_url = None
    else:
        try:
            check_url_syntax(source_url, source_hosts)
        except BlockedURL as exc:
            reasons.append(f"source_url rejected: {exc}")

    fetched_at = _parse_fetched_at(raw.get("fetched_at"), now, reasons)

    if reasons:
        raise OptionRejected(reasons)

    passthrough = ("location", "duration_minutes", "opening_hours", "details")
    extra = {k: raw[k] for k in passthrough if k in raw} or None
    assert kind and title and amount is not None and currency and source_url and fetched_at
    return ValidatedOption(
        kind=kind,
        title=title,
        price_amount=amount,
        price_currency=currency,
        price_is_estimate=bool(estimate),
        source_url=source_url,
        fetched_at=fetched_at,
        description=description,
        extra=extra,
    )
