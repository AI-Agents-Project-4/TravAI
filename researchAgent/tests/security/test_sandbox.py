"""Sandbox mode: demos and live runs use cached data only and can never reach out.

The only way to allow the network is TRAVAI_ALLOW_NETWORK=1, which only the data-gathering
scripts (`--gather`) set. These tests run with it unset, as a demo or the backend would."""

import os
import socket
import subprocess

import pytest

from research import agent, core
from research.security import budget as B
from research.security.fetch_guard import FetchResult, _default_transport
from research.security.network_policy import ENV_VAR, NetworkDisabled, network_allowed, require_network

REQ = {"origin": "DEN", "destinations": ["Tokyo, Japan"], "start_date": "2027-03-10", "duration_days": 5,
       "travelers": 1, "budget": 5000, "currency": "USD", "transport_modes": ["flight"]}


@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_VAR, raising=False)

    def no_socket(*a, **k):
        raise AssertionError("the sandbox opened a network connection")

    def no_proc(*a, **k):
        raise AssertionError("the sandbox started a subprocess")

    monkeypatch.setattr(socket, "create_connection", no_socket)
    monkeypatch.setattr(socket, "getaddrinfo", no_socket)
    monkeypatch.setattr(subprocess, "run", no_proc)
    monkeypatch.setattr(subprocess, "Popen", no_proc)


# ---- the switch ----------------------------------------------------------


def test_network_is_off_by_default():
    assert not network_allowed()
    with pytest.raises(NetworkDisabled, match="--gather"):
        require_network("x")


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "True", " 1", "1 "])
def test_only_exactly_1_turns_the_network_on(monkeypatch, value):
    monkeypatch.setenv(ENV_VAR, value)
    assert not network_allowed()


def test_one_turns_it_on(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    assert network_allowed()


# ---- every exit is closed ---------------------------------------------------


def test_http_cache_miss_does_not_reach_out(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    with pytest.raises(NetworkDisabled):
        core.http("GET", "https://api.geoapify.com/v1/x")  # even with offline=False


def test_raw_get_does_not_reach_out():
    with pytest.raises(NetworkDisabled):
        core.raw_get("https://en.wikivoyage.org/w/api.php")


def test_claude_does_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "LLM_CACHE", str(tmp_path))
    with pytest.raises(NetworkDisabled):
        core.claude_json("p", {"type": "object"}, web=True)


def test_the_raw_transport_refuses_even_if_everything_above_it_is_bypassed():
    with pytest.raises(NetworkDisabled):
        _default_transport("https://api.geoapify.com/x", "93.184.216.34", 5, 100)


def test_cache_hits_still_work_and_cost_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    core.cache_put("GET", "https://api.geoapify.com/v1/y", None, '{"a": 1}')
    b = B.TripBudget()
    with B.use(b):
        assert core.http("GET", "https://api.geoapify.com/v1/y") == {"a": 1}
    assert b.http_calls == 0


def test_secrets_are_not_needed_in_the_sandbox(monkeypatch):
    monkeypatch.setattr(core, "ENV", {})
    assert core.secret("IGNAV_API_KEY", offline=True)


# ---- run() ---------------------------------------------------------------------


def test_run_is_forced_offline_even_when_asked_to_go_live():
    out = agent.run({**REQ, "request_id": "t"}, offline=False)  # what a careless caller would pass
    assert out["status"] == "ok" and out["_schema_errors"] == []
    assert out["_usage"]["network"] == "sandbox"
    assert out["_usage"]["http_calls"] == 0 and out["_usage"]["llm_calls"] == 0
    assert any(n.startswith("Sandbox data:") for n in out["notes"])


def test_a_request_the_sandbox_does_not_cover_returns_an_error_not_a_crash():
    out = agent.run({**REQ, "destinations": ["Reykjavik, Iceland"], "request_id": "t"})
    assert out["status"] == "error" and out["_schema_errors"] == []
    assert any("sandbox" in g["reason"].lower() for g in out["gaps"])
    assert out["flights"] == [] and out["lodging"] == []
    assert out["_usage"]["http_calls"] == 0


def test_run_with_the_switch_on_is_marked_live(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    monkeypatch.setattr(agent, "_run", lambda req, ctx, rid, now, offline: agent._empty(ctx, "ok", rid))
    out = agent.run(REQ)
    assert out["_usage"]["network"] == "live" and not any(n.startswith("Sandbox data:") for n in out["notes"])


def test_a_fake_that_pretends_to_be_the_network_is_never_called(monkeypatch):
    called = []
    monkeypatch.setattr(core, "guarded_fetch", lambda *a, **k: called.append(1) or FetchResult("u", 200, b"{}"))
    with pytest.raises(NetworkDisabled):
        core._fetch("https://api.geoapify.com/x")
    assert not called


# ---- scripts --------------------------------------------------------------------


def test_scripts_only_enable_the_network_with_gather():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for rel in ("scripts/run_agent.py", "tests/run_cases.py"):
        text = open(os.path.join(root, rel), encoding="utf-8").read()
        assert 'if "--gather" in sys.argv:' in text, rel
        assert text.count("TRAVAI_ALLOW_NETWORK") == 1, rel  # set in exactly one place, behind the flag


def test_nothing_in_the_agent_sets_the_switch():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for base in ("research",):
        for dirpath, _d, files in os.walk(os.path.join(root, base)):
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(dirpath, f), encoding="utf-8").read()
                    assert "environ[\"TRAVAI_ALLOW_NETWORK\"]" not in text and "setenv" not in text, f
