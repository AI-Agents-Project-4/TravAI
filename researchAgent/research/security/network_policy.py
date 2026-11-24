"""Sandbox by default: the agent may not reach out unless data gathering is switched on.

Demos and live runs use sandbox data only (the on-disk cache under tests/fixtures/). The
network is allowed only when the environment variable TRAVAI_ALLOW_NETWORK is exactly "1",
which only the data-gathering scripts set (`--gather`). The server, the backend and the
demo never set it.

The check sits at every place that can leave the machine: `core._fetch` (all HTTP),
`core.claude_json` (the `claude -p` subprocess, which can run web search) and the socket
code in `fetch_guard`. `run()` also turns on offline replay when the network is not allowed.
"""

from __future__ import annotations

import os

ENV_VAR = "TRAVAI_ALLOW_NETWORK"


class NetworkDisabled(RuntimeError):
    """A call tried to reach out while the agent is in sandbox mode."""


def network_allowed() -> bool:
    return os.environ.get(ENV_VAR) == "1"


def require_network(what: str) -> None:
    """Raise NetworkDisabled unless data gathering has been switched on."""
    if not network_allowed():
        raise NetworkDisabled(
            f"sandbox mode: {what} is not allowed. Demos and live runs use cached sandbox data only. "
            f"To gather new data, run a script with --gather (sets {ENV_VAR}=1)."
        )
