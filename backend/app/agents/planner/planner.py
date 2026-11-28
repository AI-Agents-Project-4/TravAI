"""The planner agent: three itineraries, or an honest "not possible"; and redrafts.

Flow for a new trip:
1. Check there's enough real data (flights, hotels, a route). If not: PlanningFailed.
2. Feasibility, in code: cheapest flight + hotels + required transport + food/local
   transport. Over budget -> infeasible with that minimum, rounded up (rule 3).
3. Ask the model for three themed proposals (ids only).
4. Assemble each proposal with the rules (hours, stops, day length, budget, totals).
   If the model fails, a simple rule-based fallback proposes instead, and the
   result says so (`used_fallback`) so the eval never counts it as the model's work.

Redraft: locked items stay, removed items stay out, the model fills the rest, and
anything the user kept that had to go is returned with a reason (rule 5).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any

from app.agents.planner import prompts
from app.agents.planner.llm import LLM, LLMError
from app.agents.planner.rules import Assembler, Catalog, PlanInput, infeasible_reason, round_up_to
from app.agents.planner.types import (
    Dropped,
    Item,
    ModelCallLog,
    PlanDraft,
    PlanningResult,
    RedraftResult,
    ResearchFacts,
    Scheduled,
    TripFacts,
)

log = logging.getLogger(__name__)

THEMES: list[tuple[str, str, set[str]]] = [
    (
        "Culture and history",
        "Museums, historic sites and culture, with time to eat well.",
        {"museum", "history", "culture"},
    ),
    (
        "Food and nightlife",
        "Markets, restaurants and evenings out, with a few sights between meals.",
        {"food", "nightlife", "shopping", "entertainment"},
    ),
    (
        "Outdoors and day trips",
        "Parks, nature and trips out of the city.",
        {"nature", "outdoors", "day_trip", "tour", "other"},
    ),
]


def _lookup(mapping: dict[str, str]) -> Callable[[str], str]:
    return lambda ref: mapping.get(ref, "")


def _clean(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


class Planner:
    def __init__(
        self,
        llm: LLM | None,
        *,
        mode: str = "two_agent",
        research_output: dict[str, Any] | None = None,
    ):
        """`mode="single"` is the eval's single-agent baseline: the model reads the whole
        research output instead of the structured option catalog."""
        self.llm = llm
        self.mode = mode
        self.research_output = research_output or {}
        self.agent = "single" if mode == "single" else "planner"

    # ---- new trip ------------------------------------------------------------

    def draft(
        self, items: Iterable[Item], trip: TripFacts, research: ResearchFacts
    ) -> PlanningResult:
        cat = Catalog(items, trip, research)
        cat.check_enough_data()
        minimum = cat.minimum_total()
        if minimum > trip.budget:
            return PlanningResult(
                feasible=False,
                infeasible_reason=infeasible_reason(cat, minimum),
                min_estimated_cost=round_up_to(minimum, 50),
            )

        calls: list[ModelCallLog] = []
        proposals: list[PlanInput] = []
        fallback_reason = None
        if self.llm is None:
            fallback_reason = "No planner model is configured."
        else:
            try:
                proposals = self._ask_for_plans(cat, calls)
            except (LLMError, KeyError, TypeError, ValueError) as exc:
                fallback_reason = f"The planner model failed: {exc}"
                log.warning("planner fallback: %s", exc)
            if not proposals and fallback_reason is None:
                fallback_reason = "The planner model returned no usable plans."
        used_fallback = len(proposals) < 3
        if used_fallback:
            fallback_reason = (
                fallback_reason or "The planner model returned fewer than three plans."
            )
            proposals += self._fallback_proposals(cat)[len(proposals) :]

        assembler = Assembler(cat)
        plans = [assembler.assemble(p)[0] for p in proposals[:3]]
        return PlanningResult(
            feasible=True,
            plans=plans,
            calls=calls,
            used_fallback=used_fallback,
            fallback_reason=fallback_reason if used_fallback else None,
        )

    def _ask_for_plans(self, cat: Catalog, calls: list[ModelCallLog]) -> list[PlanInput]:
        assert self.llm is not None
        resolve: Callable[[str], str]
        if self.mode == "single":
            by_research_id = {str(i.details.get("research_id")): i.id for i in cat.items}
            data, call = self.llm.complete_json(
                prompts.SINGLE_SYSTEM,
                prompts.single_prompt(cat, self.research_output),
                prompts.PLANS_SCHEMA,
                agent=self.agent,
            )
            resolve = _lookup(by_research_id)
        else:
            aliases = prompts.Aliases()
            data, call = self.llm.complete_json(
                prompts.PLANNER_SYSTEM,
                prompts.plans_prompt(cat, aliases),
                prompts.PLANS_SCHEMA,
                agent=self.agent,
            )
            resolve = aliases.resolve
        calls.append(call)
        out = []
        for raw in data.get("plans") or []:
            days: dict[int, list[Scheduled]] = {}
            for d in raw.get("days") or []:
                ids = [resolve(str(x)) for x in d.get("items") or []]
                days[int(d.get("day", 0))] = [Scheduled(i) for i in ids if i]
            out.append(
                PlanInput(
                    title=_clean(raw.get("title"), 80) or "Itinerary",
                    summary=_clean(raw.get("summary"), 400),
                    flight_id=resolve(str(raw.get("flight") or "")) or None,
                    hotel_ids=[h for h in (resolve(str(x)) for x in raw.get("hotels") or []) if h],
                    days=days,
                )
            )
        return out[:3]

    def _fallback_proposals(self, cat: Catalog) -> list[PlanInput]:
        """Three themed plans from simple rules, used only when the model fails."""
        flight = cat.cheapest_fixed().flight
        hotels_by_stop = {s: cat.hotels_at(s) for s in cat.stops}
        out = []
        for n, (title, summary, cats) in enumerate(THEMES):
            # Vary the hotel a little: cheapest, then the best-rated of the cheaper half.
            hotel_ids = []
            for options in hotels_by_stop.values():
                if not options:
                    continue
                pick = options[0]
                if n == 1:
                    half = options[: max(1, len(options) // 2)]
                    pick = max(half, key=lambda h: float(h.details.get("rating") or 0))
                hotel_ids.append(pick.id)
            themed = [a for a in prompts.pick_activities(cat) if a.details.get("category") in cats]
            others = [a for a in prompts.pick_activities(cat) if a not in themed]
            days: dict[int, list[Scheduled]] = {d: [] for d in range(1, cat.n_days + 1)}
            day = 1
            for a in themed + others[:4]:
                for _ in range(cat.n_days):
                    if len(days[day]) < 3 and (
                        cat.stop_for(a) is None or cat.stop_of(day) in (None, cat.stop_for(a))
                    ):
                        days[day].append(Scheduled(a.id))
                        day = day % cat.n_days + 1
                        break
                    day = day % cat.n_days + 1
            out.append(
                PlanInput(
                    title=title,
                    summary=summary,
                    flight_id=flight.id if flight else None,
                    hotel_ids=hotel_ids,
                    days=days,
                )
            )
        return out

    # ---- redraft -------------------------------------------------------------

    def redraft(
        self,
        items: Iterable[Item],
        trip: TripFacts,
        research: ResearchFacts,
        *,
        current: PlanDraft,
        days: dict[int, list[Scheduled]],
        removed: set[str],
    ) -> RedraftResult:
        """Redraft around the user's edits. `days` is the edited plan the user sent."""
        cat = Catalog(items, trip, research)
        assembler = Assembler(cat)
        locked = {d: [s for s in items_ if s.locked] for d, items_ in days.items()}
        kept = {s.option_id for items_ in days.values() for s in items_ if not s.locked}
        kept_content = {
            i for i in kept if i in cat.by_id and cat.by_id[i].kind in ("activity", "food")
        }

        calls: list[ModelCallLog] = []
        proposal_days: dict[int, list[Scheduled]] | None = None
        summary = current.summary
        used_fallback = False
        if self.llm is not None:
            try:
                proposal_days, summary = self._ask_for_redraft(cat, current, days, removed, calls)
            except (LLMError, KeyError, TypeError, ValueError) as exc:
                log.warning("redraft fallback: %s", exc)
        if proposal_days is None:
            used_fallback = True
            proposal_days = {d: list(items_) for d, items_ in days.items()}
        else:
            # Locked items go back exactly where the user put them, whatever the model said.
            for d in range(1, cat.n_days + 1):
                locked_ids = {s.option_id for s in locked.get(d, [])}
                rest = [s for s in proposal_days.get(d, []) if s.option_id not in locked_ids]
                rest = [
                    s
                    for s in rest
                    if all(s.option_id not in {x.option_id for x in v} for v in locked.values())
                ]
                proposal_days[d] = list(locked.get(d, [])) + rest

        plan_input = PlanInput(
            title=current.title,
            summary=summary,
            flight_id=current.flight_id,
            hotel_ids=[current.hotel_id] if current.hotel_id else [],
            days=proposal_days,
        )
        draft, dropped = assembler.assemble(
            plan_input, removed=removed, user_items=kept_content, allow_swap=False
        )
        final = {s.option_id for day in draft.days for s in day.items}
        reported = {d.option_id for d in dropped}
        for option_id in sorted(kept_content - final - reported - removed):
            dropped.append(
                Dropped(option_id, "The planner swapped it out to make room for your changes.")
            )
        return RedraftResult(plan=draft, dropped=dropped, calls=calls, used_fallback=used_fallback)

    def _ask_for_redraft(
        self,
        cat: Catalog,
        current: PlanDraft,
        days: dict[int, list[Scheduled]],
        removed: set[str],
        calls: list[ModelCallLog],
    ) -> tuple[dict[int, list[Scheduled]], str]:
        assert self.llm is not None
        aliases = prompts.Aliases()
        flight = cat.by_id.get(current.flight_id or "")
        hotel = cat.by_id.get(current.hotel_id or "")
        fixed = cat.fixed_for(
            flight if flight and flight.kind == "flight" else None,
            {cat.stops[0]: hotel} if hotel and hotel.kind == "hotel" else {},
        )
        prompt = prompts.redraft_prompt(
            cat,
            aliases,
            title=current.title,
            summary=current.summary,
            fixed_cost=fixed.cost(),
            days={d: [(s.option_id, s.locked) for s in items_] for d, items_ in days.items()},
            removed=removed,
        )
        data, call = self.llm.complete_json(
            prompts.REDRAFT_SYSTEM, prompt, prompts.REDRAFT_SCHEMA, agent=self.agent
        )
        calls.append(call)
        out: dict[int, list[Scheduled]] = {}
        for d in data.get("days") or []:
            ids = [aliases.resolve(str(x)) for x in d.get("items") or []]
            out[int(d.get("day", 0))] = [Scheduled(i) for i in ids if i and i not in removed]
        return out, _clean(data.get("summary"), 400) or current.summary


def total_cost(calls: Iterable[ModelCallLog]) -> Decimal:
    return sum((c.cost_usd for c in calls), Decimal(0))
