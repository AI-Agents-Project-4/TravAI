"""Calls the research agent and the State Dept advisory lookup.

The research agent is Kyle's plain Python package in `researchAgent/` (not a
service). It's imported from there unchanged. Its README section "Integrating
with the backend" is what this module follows:

- it's slow and blocking, so it only ever runs in the background worker;
- the backend never sets TRAVAI_ALLOW_NETWORK, so it always runs in sandbox mode
  (recorded flights/hotels, cache-only for everything but Geoapify and
  tools-off `claude -p`);
- `run()` can raise; callers mark the trip failed;
- keys starting with `_` are private and stripped before storing.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from types import ModuleType
from typing import Any

from app.config import get_settings

_import_lock = threading.Lock()

# State Dept levels that get a safety warning before research starts (product rule 4).
WARN_LEVELS = {3: "Reconsider travel", 4: "Do not travel"}


class ResearchUnavailable(RuntimeError):
    """The research agent's code couldn't be loaded."""


def _module(name: str) -> ModuleType:
    """Import a module from researchAgent/ (e.g. "research.agent")."""
    root = str(get_settings().research_agent_dir)
    with _import_lock:
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            raise ResearchUnavailable(f"Can't import {name} from {root}: {exc}") from exc


def check_network_policy() -> None:
    """Refuse to start if live data gathering is switched on (researchAgent/TODO.md)."""
    if os.environ.get("TRAVAI_ALLOW_NETWORK"):
        raise RuntimeError(
            "TRAVAI_ALLOW_NETWORK is set. The backend must never run the research agent with "
            "full network access (that is for Kyle's data-gathering scripts only). Unset it."
        )


@dataclass(frozen=True)
class TripRequest:
    """What the backend knows about a trip, independent of the database."""

    origin: str | None
    destination: str
    end_destination: str | None
    start_date: date | None
    duration_days: int
    travelers: int
    budget: float
    currency: str
    transport_mode: str


@dataclass(frozen=True)
class ResearchRequest:
    body: dict[str, Any]
    priced_start_date: date
    notes: list[str]

    @property
    def key(self) -> str:
        """Same request -> same key. Used to reuse a recent research run."""
        stable = {k: v for k, v in self.body.items() if k != "request_id"}
        return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def build_request(trip: TripRequest, request_id: str, today: date) -> ResearchRequest:
    """Translate the API's trip request into the research agent's request shape.

    The shapes differ (researchAgent/README.md "Request fields"): a list of
    destinations, a plain-number budget, and transport modes "flight"/"drive".
    """
    if not trip.origin:
        raise ValueError(
            "An origin (home airport or city) is needed to research flights or a drive."
        )
    notes: list[str] = []
    start = trip.start_date
    if start is None:
        start = today + timedelta(days=get_settings().default_start_in_days)
        notes.append(
            f"No start date was given, so prices are for a trip starting {start.isoformat()}. "
            "Prices for other dates will differ."
        )
    destinations = [trip.destination]
    body: dict[str, Any] = {
        "request_id": request_id,
        "origin": trip.origin,
        "destinations": destinations,
        "start_date": start.isoformat(),
        "duration_days": trip.duration_days,
        "travelers": trip.travelers,
        "budget": trip.budget,
        "currency": trip.currency,
        "transport_modes": ["flight"] if trip.transport_mode == "fly" else ["drive"],
    }
    if trip.end_destination:
        destinations.append(trip.end_destination)
        body["start_point"] = trip.destination
        body["end_point"] = trip.end_destination
        if trip.transport_mode == "fly":
            body["transport_modes"] = ["flight", "train"]
    return ResearchRequest(body=body, priced_start_date=start, notes=notes)


ProgressFn = Callable[[str, str], None]


def run_research(request: ResearchRequest, progress: ProgressFn | None = None) -> dict[str, Any]:
    """Run the research agent. Blocking: 1 to 5 minutes live, about a second from cache.

    Returns the raw output, private `_` keys included. Use `split_private` to
    separate the public output (to store) from `_usage` (tokens and cost).
    """
    check_network_policy()
    settings = get_settings()
    agent = _module("research.agent")
    result: dict[str, Any] = agent.run(
        request.body,
        offline=settings.research_offline,
        progress=progress,
        cache_ttl_hours=settings.research_cache_ttl_hours,
        data_mode_override="sandbox",
    )
    return result


def split_private(output: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(public output, usage). Drops every `_` key; returns `_usage` separately."""
    usage = output.get("_usage") or {}
    public = {k: v for k, v in output.items() if not k.startswith("_")}
    return public, usage


def safety_warnings(destination: str) -> list[dict[str, Any]]:
    """State Dept Level 3/4 advisories for countries named in the destination.

    Runs before research so the UI can warn first (product rule 4). Reads the
    research agent's cached State Dept feed; a match needs the country's name in
    the destination text ("Lviv, Ukraine"). Anything the feed can't answer gives
    no warning here; research still records advisories, and plans carry them.
    """
    try:
        sources = _module("research.sources")
        feed: list[dict[str, Any]] = sources.advisories(get_settings().research_offline)
    except Exception:  # the feed is optional at this point; research checks again
        return []
    text = destination.lower()
    warnings = []
    for entry in feed:
        country = str(entry.get("country", "")).strip()
        level = entry.get("level_num")
        if not country or level not in WARN_LEVELS:
            continue
        if re.search(rf"\b{re.escape(country.lower())}\b", text):
            warnings.append(
                {
                    "kind": "safety",
                    "message": (
                        f'US State Dept: {country} is Level {level}, "{WARN_LEVELS[level]}". '
                        "Map and price data there may be out of date or wrong. You can still "
                        "continue."
                    ),
                    "source_url": entry.get("link") or None,
                }
            )
    return warnings
