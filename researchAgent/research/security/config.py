"""Security settings for the research agent.

Everything here fails closed: the allowlist starts empty, so nothing can be fetched
or saved until someone adds hosts on purpose. The numbers below are STARTING VALUES
for Kyle to tune, not decisions.
"""

from __future__ import annotations

# Two separate allowlists. A host matches itself and its subdomains
# ("example.com" also allows "www.example.com").
#
# FETCH_ALLOWED_HOSTS: hosts the agent may actually contact. This is the exfiltration
# boundary (T4), so keep it as small as possible. These are the hosts `research/sources.py`
# and `research/pricing.py` call today.
# TODO(Kyle): Ignav and SerpApi are only needed while gathering test data. Remove them
# once the data is collected, so a demo or production run can never reach them.
FETCH_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "ignav.com",  # flights (data gathering)
        "serpapi.com",  # hotels (data gathering)
        "api.geoapify.com",  # geocoding, places, routing
        "travel.state.gov",  # advisories RSS
        "api.frankfurter.dev",  # FX
        "open.er-api.com",  # FX fallback
        "en.wikivoyage.org",  # curated listings and prices
    }
)

# SANDBOX_LIVE_HOSTS / SANDBOX_LIVE_KEYS: the ONLY exception to the sandbox rule. Demos and live
# runs use cached sandbox data for everything (flights, hotels, advisories, FX, Wikivoyage, every
# `claude -p` call), except that these hosts may be reached live. Everything else is blocked at
# `core._fetch`, in `fetch_guard`'s socket code and by the allowlist `_fetch` passes to the guard.
SANDBOX_LIVE_HOSTS: frozenset[str] = frozenset({"api.geoapify.com"})
SANDBOX_LIVE_KEYS: frozenset[str] = frozenset({"GEOAPIFY_API_KEY"})  # the only key a demo needs

# SOURCE_LINK_HOSTS: hosts an option's source_url may point to. Links come from many
# booking and ticketing sites, so a fixed list does not fit this agent yet. `validate_option`
# uses it; the agent itself only applies `check_link_shape` to links the model returns.
# TODO(Kyle): decide whether to allowlist, flag, or only show the domain in the UI (T3).
SOURCE_LINK_HOSTS: frozenset[str] = frozenset()

# Fetch limits.
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 1_000_000
API_MAX_RESPONSE_BYTES = 10_000_000  # trusted API responses (Ignav, Geoapify, Wikivoyage) can be large
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

# Per-trip limits (T6) for one run of the pipeline. A cache hit costs nothing; only real
# network requests and `claude -p` calls count. STARTING VALUES: a live three-city trip
# makes roughly 100 to 200 requests and 20 to 40 model calls, so check them against a real run.
MAX_HTTP_CALLS_PER_TRIP = 400
MAX_LLM_CALLS_PER_TRIP = 100
MAX_COST_USD_PER_TRIP = 25.0

# Generic limits (agent-loop style), used by charge_tool_call / charge_page.
MAX_TOOL_CALLS_PER_TRIP = 40
MAX_TOKENS_PER_TRIP = 200_000
MAX_SECONDS_PER_TRIP = 900.0  # a live run takes 1 to 5 minutes (README)
MAX_PAGES_PER_TRIP = 25
