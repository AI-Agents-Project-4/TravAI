import pytest

from research.security.budget import BudgetExceeded, Limits, TripBudget


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_tool_call_limit():
    b = TripBudget(Limits(max_tool_calls=2))
    b.charge_tool_call()
    b.charge_tool_call()
    with pytest.raises(BudgetExceeded) as exc:
        b.charge_tool_call()
    assert exc.value.limit == "tool_calls"
    assert b.stopped_by == "tool_calls" and b.tool_calls == 2


def test_page_limit():
    b = TripBudget(Limits(max_pages=1))
    b.charge_page()
    with pytest.raises(BudgetExceeded) as exc:
        b.charge_page()
    assert exc.value.limit == "pages"


def test_token_limit_stops_after_the_call_that_exceeds_it():
    b = TripBudget(Limits(max_tokens=100))
    b.record_model_call(agent="research", model="m", input_tokens=60, output_tokens=30)
    with pytest.raises(BudgetExceeded) as exc:
        b.record_model_call(agent="research", model="m", input_tokens=10, output_tokens=5)
    assert exc.value.limit == "tokens"
    assert len(b.model_calls) == 2  # the overrunning call is still logged


def test_time_limit():
    clock = FakeClock()
    b = TripBudget(Limits(max_seconds=30), clock=clock)
    b.charge_tool_call()
    clock.now = 31
    with pytest.raises(BudgetExceeded) as exc:
        b.charge_tool_call()
    assert exc.value.limit == "time"
    with pytest.raises(BudgetExceeded):
        b.charge_page()


def test_first_limit_hit_is_kept_as_reason():
    b = TripBudget(Limits(max_tool_calls=0, max_pages=0))
    with pytest.raises(BudgetExceeded):
        b.charge_tool_call()
    with pytest.raises(BudgetExceeded):
        b.charge_page()
    assert b.stopped_by == "tool_calls"


def test_usage_summary_for_cost_logging():
    clock = FakeClock()
    b = TripBudget(clock=clock)
    b.charge_tool_call()
    b.charge_page()
    b.record_model_call(
        agent="research", model="m", input_tokens=100, output_tokens=20, cached_tokens=50, tool_calls=1
    )
    clock.now = 4.5
    u = b.usage()
    assert u["tool_calls"] == 1 and u["pages"] == 1 and u["tokens"] == 120
    assert u["seconds"] == 4.5 and u["stopped_by"] is None
    assert u["model_calls"][0]["cached_tokens"] == 50
