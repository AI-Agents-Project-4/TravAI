"""Security settings for the research agent.

Everything here fails closed: the allowlist starts empty, so nothing can be fetched
or saved until someone adds hosts on purpose. The numbers below are STARTING VALUES
for Kyle to tune, not decisions.
"""

from __future__ import annotations

# Two separate allowlists. A host matches itself and its subdomains
# ("example.com" also allows "www.example.com").
#
# FETCH_ALLOWED_HOSTS: hosts the agent may actually contact at runtime. This is the
# exfiltration boundary (T4), so keep it as small as possible. We only plan to call
# Geoapify live (its API host is believed to be api.geoapify.com; confirm in their docs
# before adding). Ignav and SerpAPI are only used offline to gather snapshot data, so they
# do not belong here.
FETCH_ALLOWED_HOSTS: frozenset[str] = frozenset()

# SOURCE_LINK_HOSTS: hosts an option's source_url may point to. The agent never fetches
# these (snapshot prices link to the original listing), but the user clicks them, so this
# is the phishing boundary (T3).
# TODO(Kyle): fill in from the sites the snapshot data came from.
SOURCE_LINK_HOSTS: frozenset[str] = frozenset()

# Fetch limits.
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 1_000_000
FETCH_TIMEOUT_SECONDS = 10.0

# Plausible price per option, in USD, for the whole party. The maximum is multiplied
# by the number of travelers. These are a net for obviously wrong or injected prices
# (T1, T2), not proof that a price is right.
PRICE_RANGES_USD: dict[str, tuple[float, float]] = {
    "flight": (50.0, 15_000.0),
    "hotel": (20.0, 20_000.0),
    "activity": (0.0, 3_000.0),
    "transport": (0.0, 5_000.0),
    "food": (0.0, 1_500.0),
}

# Exchange rates to USD. Only USD is built in. Where conversion happens is still an
# open question in docs/api-contract.md, so other currencies are rejected until
# someone supplies rates (pass `usd_rates=` to validate_option).
DEFAULT_USD_RATES: dict[str, float] = {"USD": 1.0}

# Text limits for model-visible fields saved from web content.
MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 1_000

# Per-trip limits (T6). One trip = one research run.
MAX_TOOL_CALLS_PER_TRIP = 40
MAX_TOKENS_PER_TRIP = 200_000
MAX_SECONDS_PER_TRIP = 180.0
MAX_PAGES_PER_TRIP = 25
