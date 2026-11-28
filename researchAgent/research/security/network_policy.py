"""Sandbox by default: the agent may not reach out unless data gathering is switched on.

Demos and live runs use sandbox data (recorded flights and hotels, plus the on-disk cache under
tests/fixtures/) for everything except two things that may run live: Geoapify
(`config.SANDBOX_LIVE_HOSTS`) and `claude -p` calls with tools off (model reasoning only, no web
access). Every other host, and every `claude -p` call that has web search, is cache-only.

Full network access needs the environment variable TRAVAI_ALLOW_NETWORK to be exactly "1",
which only the data-gathering scripts set (`--gather`). The server, the backend and the demo
never set it.

Checked at every place that can leave the machine: `core._fetch` (all HTTP), `core.claude_json`
(the `claude -p` subprocess, web calls only) and the socket code in `fetch_guard`.
"""

from __future__ import annotations

import os
from typing import Iterable

from . import config

ENV_VAR = "TRAVAI_ALLOW_NETWORK"


class NetworkDisabled(RuntimeError):
    """A call tried to reach out while the agent is in sandbox mode."""


def network_allowed() -> bool:
    """True only in data-gathering mode (full network access)."""
    return os.environ.get(ENV_VAR) == "1"


def _matches(host: str, hosts: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == h.lower() or host.endswith("." + h.lower()) for h in hosts)


def host_is_live(host: str) -> bool:
    """May this host be reached right now? Everything in gather mode, only the sandbox-live hosts otherwise."""
    return network_allowed() or _matches(host, config.SANDBOX_LIVE_HOSTS)


def claude_allowed(web: bool) -> bool:
    """May a `claude -p` call run for real? Model-only calls (tools off) may in the sandbox: they fetch no outside data.
    Calls with web search never may, except in gather mode."""
    return network_allowed() or not web


def require_live_host(host: str, what: str = "a request") -> None:
    if not host_is_live(host):
        raise NetworkDisabled(
            f"sandbox mode: {what} to {host!r} is not allowed. Demos and live runs use cached sandbox data, "
            f"except for {sorted(config.SANDBOX_LIVE_HOSTS)}. To gather new data, run a script with --gather "
            f"(sets {ENV_VAR}=1)."
        )


def require_network(what: str) -> None:
    """Raise NetworkDisabled unless data gathering has been switched on (full access)."""
    if not network_allowed():
        raise NetworkDisabled(
            f"sandbox mode: {what} is not allowed. Demos and live runs use cached sandbox data only. "
            f"To gather new data, run a script with --gather (sets {ENV_VAR}=1)."
        )
