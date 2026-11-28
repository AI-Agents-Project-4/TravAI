"""The eval entry point: one trip, no server or database, plans plus a cost log."""

import json
from pathlib import Path

import pytest

from app import cli
from app.config import REPO_ROOT
from tests.fakes import FakeLLM

CASE = REPO_ROOT / "evals" / "cases" / "01-tokyo-5d-5000.json"


@pytest.mark.parametrize("mode", ["two_agent", "single"])
def test_runs_an_eval_case_in_both_modes(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeLLM()
    monkeypatch.setattr(cli, "get_llm", lambda: fake)
    out = tmp_path / "result.json"
    # The case leaves origin and date open; these match the research agent's cached Tokyo case.
    code = cli.main(
        [
            str(CASE),
            "--origin",
            "DEN",
            "--start-date",
            "2027-03-10",
            "--mode",
            mode,
            "--out",
            str(out),
        ]
    )
    assert code == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["case"] == "01-tokyo-5d-5000" and result["mode"] == mode
    assert result["research"]["status"] == "ok"
    outcome = result["outcome"]
    assert outcome["status"] == "feasible" and not outcome["used_fallback"]
    assert len(outcome["plans"]) == 3
    assert all(p["total"] <= 5000 for p in outcome["plans"])
    agent = "single" if mode == "single" else "planner"
    assert [c["agent"] for c in result["cost"]["calls"]] == [agent]
    assert result["cost"]["total_usd"] == pytest.approx(0.01)
    if mode == "single":
        assert '"research"' in fake.prompts[0]  # the single agent saw the raw research


def test_a_case_without_an_origin_fails_clearly(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([str(CASE)]) == 2
    assert "origin" in capsys.readouterr().err
