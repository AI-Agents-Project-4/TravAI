"""A fake planner model: answers from the ids in the prompt, records what it was asked."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from app.agents.planner.llm import LLMError
from app.agents.planner.types import ModelCallLog


class FakeLLM:
    model = "fake-model"

    def __init__(self, *, fail: bool = False, bogus_ids: bool = False, add_on_redraft: int = 1):
        self.fail = fail
        self.bogus_ids = bogus_ids
        self.add_on_redraft = add_on_redraft
        self.prompts: list[str] = []

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, Any], *, agent: str
    ) -> tuple[dict[str, Any], ModelCallLog]:
        self.prompts.append(prompt)
        log = ModelCallLog(
            agent=agent,
            model=self.model,
            input_tokens=1000,
            output_tokens=200,
            cost_usd=Decimal("0.01"),
        )
        if self.fail:
            raise LLMError("fake model is down")
        data = json.loads(prompt.split("\n\n", 1)[1])
        if "plans" in schema["properties"]:
            return self._plans(data), log
        return self._redraft(data), log

    def _plans(self, data: dict[str, Any]) -> dict[str, Any]:
        if "research" in data:  # single-agent prompt: research ids
            research = data["research"]
            flights = [f["id"] for f in research.get("flights", [])]
            hotels = [h["id"] for h in research.get("lodging", [])]
            acts = [
                a["id"] for a in research.get("activities", []) if a.get("category") != "day_trip"
            ]
        else:
            flights = [f["id"] for f in data["flights"]]
            hotels = [h["id"] for h in data["hotels"]]
            acts = [a["id"] for a in data["activities"] if not a.get("day_trip")]
        days = [d["day"] for d in data["days"]]
        plans = []
        for n in range(3):
            picks = acts[n * 2 * len(days) : (n + 1) * 2 * len(days)]
            plan_days = [{"day": d, "items": picks[i * 2 : i * 2 + 2]} for i, d in enumerate(days)]
            if self.bogus_ids:
                plan_days[0]["items"].append("a99999")  # not in the catalog
            plans.append(
                {
                    "title": f"Theme {n + 1}",
                    "summary": f"Summary {n + 1}",
                    "flight": flights[0] if flights else "",
                    "hotels": hotels[:1],
                    "days": plan_days,
                }
            )
        return {"plans": plans}

    def _redraft(self, data: dict[str, Any]) -> dict[str, Any]:
        used = {i["id"] for d in data["plan"]["days"] for i in d["items"]}
        removed = set(data["removed"])
        spare = [
            a["id"]
            for a in data["activities"]
            if a["id"] not in used and a["id"] not in removed and not a.get("day_trip")
        ]
        days = []
        for d in data["plan"]["days"]:
            items = [i["id"] for i in d["items"]]
            if spare and self.add_on_redraft:
                items += spare[: self.add_on_redraft]
                spare = spare[self.add_on_redraft :]
            days.append({"day": d["day"], "items": items})
        return {"summary": "Redrafted around your changes.", "days": days}
