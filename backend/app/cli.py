"""Run one trip end to end without the UI, the server or the database (for the eval).

    uv run python -m app.cli ../evals/cases/01-tokyo-5d-5000.json --origin DEN --start-date 2027-03-10
    uv run python -m app.cli case.json --mode single --out result.json

Takes a file with a trip request (the contract's POST /trips body, or an eval case
with it under "input"), runs research and the planner, and prints JSON: the plans
or the infeasible verdict, and every model call with its tokens and cost. That's
what the eval needs to grade a run and to report cost per task.

It makes real model calls unless the research is fully cached and RESEARCH_OFFLINE
is set; the planner always calls its model. Mind the cost.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.agents.planner.planner import Planner, total_cost
from app.agents.planner.types import Item, ModelCallLog, PlanningFailed, TripFacts
from app.config import get_settings
from app.integration import research_agent
from app.integration.options import map_research
from app.pipeline import get_llm, research_calls, research_facts


def _load_request(path: Path, origin: str | None, start: str | None) -> tuple[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    body = dict(data.get("input", data))
    if origin:
        body["origin"] = origin
    if start:
        body["start_date"] = start
    return str(data.get("id", path.stem)), body


def _trip(body: dict[str, Any]) -> research_agent.TripRequest:
    start = body.get("start_date")
    return research_agent.TripRequest(
        origin=body.get("origin"),
        destination=body["destination"],
        end_destination=body.get("end_destination"),
        start_date=date.fromisoformat(start) if start else None,
        duration_days=int(body["duration_days"]),
        travelers=int(body["travelers"]),
        budget=float(body["budget"]["amount"]),
        currency=str(body["budget"]["currency"]),
        transport_mode=str(body["transport_mode"]),
    )


def _call(c: ModelCallLog) -> dict[str, Any]:
    return {**c.__dict__, "cost_usd": float(c.cost_usd)}


def run_case(body: dict[str, Any], mode: str) -> dict[str, Any]:
    started = time.monotonic()
    trip = _trip(body)
    if not trip.destination:
        raise ValueError("The request has no destination.")
    request = research_agent.build_request(
        trip, f"eval-{int(time.time())}", datetime.now(UTC).date()
    )
    raw = research_agent.run_research(request)
    output, usage = research_agent.split_private(raw)
    calls = research_calls(usage)
    research_seconds = round(time.monotonic() - started, 1)

    mapped = map_research(output, travelers=trip.travelers)
    items = [
        Item(
            id=o.key,
            kind=o.kind,
            title=o.title,
            price=o.price_amount,
            currency=o.price_currency,
            is_estimate=o.price_is_estimate,
            source_url=o.source_url,
            fetched_at=o.fetched_at,
            duration_minutes=o.duration_minutes,
            details=o.details,
            lat=o.lat,
            lng=o.lng,
        )
        for o in mapped.options
    ]
    facts = TripFacts(
        destination=trip.destination,
        duration_days=trip.duration_days,
        travelers=trip.travelers,
        budget=Decimal(str(trip.budget)),
        currency=trip.currency,
        transport_mode=trip.transport_mode,
        start_date=request.priced_start_date,
        start_date_assumed=trip.start_date is None,
    )
    result: dict[str, Any] = {
        "mode": mode,
        "request": body,
        "research": {
            "status": output.get("status"),
            "verdict": (output.get("feasibility") or {}).get("verdict"),
            "gaps": output.get("gaps"),
            "options": len(mapped.options),
            "rejected_options": mapped.rejected,
            "seconds": research_seconds,
            "network": usage.get("network"),
        },
    }
    by_id = {i.id: i for i in items}
    try:
        planner = Planner(
            get_llm(), mode=mode, research_output=output if mode == "single" else None
        )
        planned = planner.draft(items, facts, research_facts(output))
    except PlanningFailed as exc:
        result["outcome"] = {"status": "failed", "reason": str(exc)}
    else:
        calls += planned.calls
        if planned.feasible:
            result["outcome"] = {
                "status": "feasible",
                "used_fallback": planned.used_fallback,
                "fallback_reason": planned.fallback_reason,
                "plans": [
                    {
                        "title": p.title,
                        "summary": p.summary,
                        "flight": by_id[p.flight_id].title if p.flight_id else None,
                        "hotel": by_id[p.hotel_id].title if p.hotel_id else None,
                        "total": float(p.total),
                        "cost_breakdown": {c: float(a) for c, a in p.cost_breakdown},
                        "days": [
                            [
                                {
                                    "title": by_id[s.option_id].title,
                                    "price": float(by_id[s.option_id].price),
                                    "estimate": by_id[s.option_id].is_estimate,
                                    "source_url": by_id[s.option_id].source_url,
                                    "start": s.start_time,
                                }
                                for s in d.items
                            ]
                            for d in p.days
                        ],
                        "warnings": p.warnings,
                    }
                    for p in planned.plans
                ],
            }
        else:
            result["outcome"] = {
                "status": "infeasible",
                "reason": planned.infeasible_reason,
                "min_estimated_cost": float(planned.min_estimated_cost or 0),
            }
    result["cost"] = {
        "total_usd": float(total_cost(calls)),
        "research_usd": float(total_cost(c for c in calls if c.agent == "research")),
        "planner_usd": float(total_cost(c for c in calls if c.agent != "research")),
        "calls": [_call(c) for c in calls],
    }
    result["seconds"] = round(time.monotonic() - started, 1)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "case",
        type=Path,
        help="JSON file: a POST /trips body, or an eval case with it under 'input'",
    )
    parser.add_argument(
        "--mode", choices=["two_agent", "single"], default=get_settings().agent_mode
    )
    parser.add_argument("--origin", help="fill in or override the origin")
    parser.add_argument("--start-date", help="fill in or override the start date (YYYY-MM-DD)")
    parser.add_argument("--out", type=Path, help="write the JSON here instead of stdout")
    args = parser.parse_args(argv)

    case_id, body = _load_request(args.case, args.origin, args.start_date)
    try:
        result = {"case": case_id, **run_case(body, args.mode)}
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
