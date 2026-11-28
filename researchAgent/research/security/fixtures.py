"""Load snapshot ("sandbox") data as options.

We have no live flight or hotel prices for the demo. The data was collected earlier
from real APIs and trimmed. It goes through the SAME `validate_option` as live research
would, so a bad fixture fails loudly and the demo exercises the real path.

File format (JSON):
{
  "collected_at": "2026-11-20T15:30:00Z",   # when the data was really fetched
  "options": [ { ...option fields..., "fetched_at": "..." (optional) }, ... ]
}

- An option without `fetched_at` gets `collected_at`. Never use the demo date: the UI
  shows the age of each price, and it must be the true age (product rule 2).
- Each option is tagged `details.data_origin = "snapshot"` so the UI can say "sample
  data" and the eval can tell snapshot options from live ones.
- Files must not contain API keys. This repo is public.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import config
from .fetch_guard import _SECRET_PARAM
from .option_validation import OptionRejected, ValidatedOption, validate_option

DATA_ORIGIN_SNAPSHOT = "snapshot"


class FixtureError(Exception):
    """A fixture file is invalid. The message names the file and the option index."""


def find_secrets(value: Any, path: str = "$") -> list[str]:
    """Return JSON paths of strings that look like a leaked key (e.g. '?apiKey=abc')."""
    found: list[str] = []
    if isinstance(value, str):
        for m in _SECRET_PARAM.finditer(value):
            if not m.group(0).endswith("=REDACTED"):
                found.append(path)
    elif isinstance(value, Mapping):
        for k, v in value.items():
            found += find_secrets(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += find_secrets(v, f"{path}[{i}]")
    return found


def load_fixture_options(
    path: str | Path,
    *,
    source_hosts: Iterable[str] = config.SOURCE_LINK_HOSTS,
    travelers: int = 1,
    usd_rates: Mapping[str, float] = config.DEFAULT_USD_RATES,
    now: datetime | None = None,
) -> list[ValidatedOption]:
    """Read one fixture file and return validated options. Raises FixtureError."""
    path = Path(path)
    name = path.name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FixtureError(f"{name}: cannot read JSON ({exc})") from None

    if not isinstance(data, dict) or not isinstance(data.get("options"), list):
        raise FixtureError(f"{name}: expected an object with an 'options' list")

    secrets = find_secrets(data)
    if secrets:
        raise FixtureError(f"{name}: possible API key in {', '.join(secrets)}")

    collected_at = data.get("collected_at")
    if not isinstance(collected_at, str):
        raise FixtureError(f"{name}: 'collected_at' is required (ISO 8601 with timezone)")

    now = now or datetime.now(timezone.utc)
    out: list[ValidatedOption] = []
    for i, raw in enumerate(data["options"]):
        if not isinstance(raw, dict):
            raise FixtureError(f"{name}: option {i} is not an object")
        details = raw.get("details", {})
        if not isinstance(details, dict):
            raise FixtureError(f"{name}: option {i}: details must be an object")
        option = {
            **raw,
            "fetched_at": raw.get("fetched_at", collected_at),
            "details": {**details, "data_origin": DATA_ORIGIN_SNAPSHOT},
        }
        try:
            out.append(
                validate_option(
                    option,
                    source_hosts=source_hosts,
                    travelers=travelers,
                    usd_rates=usd_rates,
                    now=now,
                )
            )
        except OptionRejected as exc:
            raise FixtureError(f"{name}: option {i}: {exc}") from None
    return out


def load_fixture_dir(directory: str | Path, **kwargs: Any) -> list[ValidatedOption]:
    """Load every *.json file in a directory, in name order."""
    options: list[ValidatedOption] = []
    for file in sorted(Path(directory).glob("*.json")):
        options += load_fixture_options(file, **kwargs)
    return options
