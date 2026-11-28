"""Tests that the guards are actually wired into the agent. No network, no `claude`: the
guarded fetch and subprocess are replaced with fakes."""

import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from research import activities, agent, core, pricing
from research.security import budget as B
from research.security.config import FETCH_ALLOWED_HOSTS
from research.security.fetch_guard import BlockedURL, FetchResult, check_link_shape, guarded_fetch

RESEARCH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "research")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVAI_ALLOW_NETWORK", "1")  # these tests simulate gather mode; sandbox tests are in test_sandbox.py
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path / "http"))
    monkeypatch.setattr(core, "LLM_CACHE", str(tmp_path / "llm"))
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    monkeypatch.setattr(core, "_TTL", None)
    return tmp_path


def fake_fetch(monkeypatch, responses):
    """responses: list of (status, body) returned in order. Records every call."""
    calls = []

    def fake(url, **kw):
        calls.append({"url": url, **kw})
        status, body = responses[min(len(calls), len(responses)) - 1]
        return FetchResult(url, status, body.encode() if isinstance(body, str) else body)

    monkeypatch.setattr(core, "guarded_fetch", fake)
    return calls


# ---- link shape (model-found links) -------------------------------------


@pytest.mark.parametrize("url", ["https://www.example.com/tickets", "https://example.com:443/x"])
def test_link_shape_ok(url):
    assert check_link_shape(url)


@pytest.mark.parametrize(
    "url",
    ["http://example.com/x", "ftp://example.com/x", "javascript:alert(1)", "https://u:p@example.com/x",
     "https://10.0.0.1/x", "https://localhost/x", "https://example.com:8443/x", "", "https:///x"],
)
def test_link_shape_rejects(url):
    with pytest.raises(BlockedURL):
        check_link_shape(url)


def test_link_shape_http_only_when_allowed():
    assert check_link_shape("http://www.visitcos.com/directory/acacia-park/", allow_http=True)
    with pytest.raises(BlockedURL):
        check_link_shape("ftp://example.com/x", allow_http=True)
    with pytest.raises(BlockedURL):
        check_link_shape("http://10.0.0.1/x", allow_http=True)


@pytest.mark.parametrize("url,ok", [
    ("https://tickets.example.com/p", True), ("http://www.visitcos.com/x", True), (None, False), ("", False),
    ("javascript:alert(1)", False), ("https://1.2.3.4/x", False), ("https://u:p@example.com/", False),
])
def test_web_price_links_are_checked(url, ok):
    assert activities._safe_link(url) is ok


# ---- fetch guard: POST support -------------------------------------------


def test_post_passes_method_headers_body_to_transport():
    seen = {}

    def transport(url, ip, timeout, max_bytes, **kw):
        seen.update(kw)
        return 200, {"content-type": "application/json"}, b"{}", False

    r = guarded_fetch("https://ignav.com/api/x", allowed_hosts=["ignav.com"], resolver=lambda h: ["93.184.216.34"],
                      transport=transport, method="POST", headers={"X-Api-Key": "k"}, body=b"{}")
    assert seen == {"method": "POST", "headers": {"X-Api-Key": "k"}, "body": b"{}"}
    assert r.headers["content-type"] == "application/json"


def test_redirect_on_post_is_refused():
    def transport(url, ip, timeout, max_bytes, **kw):
        return 307, {"location": "https://ignav.com/other"}, b"", False

    with pytest.raises(BlockedURL, match="POST"):
        guarded_fetch("https://ignav.com/a", allowed_hosts=["ignav.com"], resolver=lambda h: ["93.184.216.34"],
                      transport=transport, method="POST", body=b"{}")


# ---- budget ---------------------------------------------------------------


def test_http_and_llm_limits_are_separate():
    b = B.TripBudget(B.Limits(max_http_calls=1, max_llm_calls=1))
    b.charge_http()
    b.charge_llm()
    with pytest.raises(B.BudgetExceeded) as e:
        b.charge_http()
    assert e.value.limit == "http_calls"
    with pytest.raises(B.BudgetExceeded):
        b.charge_llm()


def test_cost_limit_is_recorded_then_blocks_next_charge():
    b = B.TripBudget(B.Limits(max_cost_usd=1.0))
    b.charge_llm()
    with pytest.raises(B.BudgetExceeded) as e:
        b.record_model_call(agent="a", model="m", input_tokens=1, output_tokens=1, cost_usd=1.5)
    assert e.value.limit == "cost" and b.cost_usd == 1.5
    with pytest.raises(B.BudgetExceeded):
        b.charge_http()  # any later charge stops, even a different kind


def test_usage_has_cost_and_counts():
    b = B.TripBudget()
    b.charge_http()
    b.charge_llm()
    b.record_model_call(agent="a", model="m", input_tokens=3, output_tokens=4, cost_usd=0.25)
    u = b.usage()
    assert u["http_calls"] == 1 and u["llm_calls"] == 1 and u["tokens"] == 7 and u["cost_usd"] == 0.25


def test_active_budget_reaches_worker_threads_only_through_the_helpers():
    b = B.TripBudget()
    with B.use(b):
        assert B.current() is b
        with ThreadPoolExecutor(3) as ex:
            seen = B.map_in_context(ex, lambda i: B.current() is b, range(6))
            fut = B.submit_in_context(ex, lambda: B.current() is b)
            bare = ex.submit(B.current).result()
        assert all(seen) and fut.result() is True
        assert bare is None  # why the helpers are needed
    assert B.current() is None


def test_budget_is_shared_and_counted_across_threads():
    b = B.TripBudget(B.Limits(max_http_calls=10))
    with B.use(b), ThreadPoolExecutor(4) as ex:
        def work(_):
            try:
                B.current().charge_http()
                return 1
            except B.BudgetExceeded:
                return 0
        done = sum(B.map_in_context(ex, work, range(25)))
    assert done == 10 and b.http_calls == 10 and b.stopped_by == "http_calls"


def test_separate_runs_do_not_share_a_budget():
    a, c = B.TripBudget(), B.TripBudget()
    out = {}

    def run(name, bud):
        with B.use(bud):
            B.current().charge_http()
            out[name] = B.current()

    ts = [threading.Thread(target=run, args=("a", a)), threading.Thread(target=run, args=("c", c))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out["a"] is a and out["c"] is c and a.http_calls == 1 and c.http_calls == 1


# ---- core.http goes through the guard ---------------------------------------


def test_http_uses_guard_with_the_allowlist_and_caches(cache, monkeypatch):
    calls = fake_fetch(monkeypatch, [(200, '{"ok": 1}')])
    b = B.TripBudget()
    with B.use(b):
        assert core.http("GET", "https://api.geoapify.com/v1/x?apiKey=SECRET123456") == {"ok": 1}
        assert core.http("GET", "https://api.geoapify.com/v1/x?apiKey=SECRET123456") == {"ok": 1}  # cache hit
    assert len(calls) == 1 and b.http_calls == 1  # the cache hit cost nothing
    assert set(calls[0]["allowed_hosts"]) == set(FETCH_ALLOWED_HOSTS)
    assert not any("SECRET123456" in open(os.path.join(root, f)).read()
                   for root, _d, fs in os.walk(cache) for f in fs)


def test_http_post_sends_json_body_and_headers(cache, monkeypatch):
    calls = fake_fetch(monkeypatch, [(200, "{}")])
    core.http("POST", "https://ignav.com/api/fares/one-way", {"a": 1}, {"X-Api-Key": "k"})
    assert calls[0]["method"] == "POST" and json.loads(calls[0]["body"]) == {"a": 1}
    assert calls[0]["headers"]["X-Api-Key"] == "k" and calls[0]["headers"]["Content-Type"] == "application/json"


@pytest.mark.parametrize("url", [
    "https://evil.example/x", "http://api.geoapify.com/x", "https://127.0.0.1/x",
    "https://api.geoapify.com.evil.example/x", "https://user:pw@api.geoapify.com/x",
])
def test_http_blocks_everything_off_the_allowlist(cache, url):
    with pytest.raises(BlockedURL):
        core.http("GET", url)  # the real guard runs; it refuses before any network access
    assert not os.path.exists(core.HTTP_CACHE) or not os.listdir(core.HTTP_CACHE)


def test_http_retries_server_errors_but_not_client_errors(cache, monkeypatch):
    calls = fake_fetch(monkeypatch, [(503, "busy"), (200, '{"ok": 2}')])
    assert core.http("GET", "https://api.geoapify.com/a") == {"ok": 2} and len(calls) == 2
    calls = fake_fetch(monkeypatch, [(404, "nope"), (200, "{}")])
    with pytest.raises(core.ApiError) as e:
        core.http("GET", "https://api.geoapify.com/b")
    assert e.value.status == 404 and len(calls) == 1


def test_failed_requests_are_not_cached(cache, monkeypatch):
    fake_fetch(monkeypatch, [(404, "nope")])
    with pytest.raises(core.ApiError):
        core.http("GET", "https://api.geoapify.com/c")
    assert not os.path.exists(core.HTTP_CACHE) or not os.listdir(core.HTTP_CACHE)


def test_network_errors_become_api_errors(cache, monkeypatch):
    def boom(url, **kw):
        raise OSError("connection reset")

    monkeypatch.setattr(core, "guarded_fetch", boom)
    with pytest.raises(core.ApiError) as e:
        core.http("GET", "https://api.geoapify.com/d")
    assert e.value.status == 0


def test_truncated_response_is_an_error_not_bad_data(cache, monkeypatch):
    monkeypatch.setattr(core, "guarded_fetch", lambda url, **kw: FetchResult(url, 200, b'{"a":', truncated=True))
    with pytest.raises(core.ApiError, match="size limit"):
        core.http("GET", "https://api.geoapify.com/e")


def test_http_stops_when_the_trip_budget_is_spent(cache, monkeypatch):
    calls = fake_fetch(monkeypatch, [(200, "{}")])
    with B.use(B.TripBudget(B.Limits(max_http_calls=1))):
        core.http("GET", "https://api.geoapify.com/one")
        with pytest.raises(B.BudgetExceeded):
            core.http("GET", "https://api.geoapify.com/two")
    assert len(calls) == 1  # the second request never left


def test_offline_never_reaches_the_guard_or_budget(cache, monkeypatch):
    calls = fake_fetch(monkeypatch, [(200, "{}")])
    b = B.TripBudget()
    with B.use(b), pytest.raises(core.CacheMiss):
        core.http("GET", "https://api.geoapify.com/zzz", offline=True)
    assert not calls and b.http_calls == 0


# ---- claude_json ---------------------------------------------------------------


def fake_claude(monkeypatch, payload, record):
    def run(cmd, **kw):
        record.append({"cmd": cmd, **kw})
        return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    monkeypatch.setattr(core.subprocess, "run", run)


GOOD = {"structured_output": {"x": 1}, "total_cost_usd": 0.12,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50}}


def test_claude_tools_are_off_unless_web_search_is_requested(cache, monkeypatch):
    rec = []
    fake_claude(monkeypatch, GOOD, rec)
    core.claude_json("p1", {"type": "object"})
    core.claude_json("p2", {"type": "object"}, web=True)
    off, web = rec[0]["cmd"], rec[1]["cmd"]
    assert off[off.index("--tools") + 1] == "" and "--allowedTools" not in off
    assert web[web.index("--tools") + 1] == "WebSearch,WebFetch"
    assert web[web.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    for r in rec:  # always: a spend cap, no saved session, and a directory with no project files
        assert "--max-budget-usd" in r["cmd"] and "--no-session-persistence" in r["cmd"]
        assert not os.path.abspath(r["cwd"]).startswith(os.path.abspath(core.ROOT))


def test_claude_usage_is_recorded_and_cache_hits_are_free(cache, monkeypatch):
    rec = []
    fake_claude(monkeypatch, GOOD, rec)
    b = B.TripBudget()
    with B.use(b):
        assert core.claude_json("same", {"type": "object"}) == {"x": 1}
        assert core.claude_json("same", {"type": "object"}) == {"x": 1}
    assert len(rec) == 1 and b.llm_calls == 1
    assert b.tokens == 120 and b.cost_usd == pytest.approx(0.12)
    assert b.model_calls[0].cached_tokens == 50 and b.model_calls[0].agent == "research"


def test_claude_missing_usage_fields_count_as_zero(cache, monkeypatch):
    fake_claude(monkeypatch, {"structured_output": {"x": 1}}, [])
    b = B.TripBudget()
    with B.use(b):
        core.claude_json("p", {"type": "object"})
    assert b.tokens == 0 and b.cost_usd == 0 and len(b.model_calls) == 1


def test_claude_call_limit_and_cost_limit(cache, monkeypatch):
    rec = []
    fake_claude(monkeypatch, {**GOOD, "total_cost_usd": 5.0}, rec)
    with B.use(B.TripBudget(B.Limits(max_cost_usd=1.0))):
        assert core.claude_json("a", {"type": "object"}) == {"x": 1}  # already paid for: returned and cached
        with pytest.raises(B.BudgetExceeded) as e:
            core.claude_json("b", {"type": "object"})
        assert e.value.limit == "cost"
    assert len(rec) == 1
    rec.clear()
    with B.use(B.TripBudget(B.Limits(max_llm_calls=1))):
        core.claude_json("c", {"type": "object"})
        with pytest.raises(B.BudgetExceeded):
            core.claude_json("d", {"type": "object"})
    assert len(rec) == 1


def test_claude_offline_cache_miss_does_not_run_or_charge(cache, monkeypatch):
    rec = []
    fake_claude(monkeypatch, GOOD, rec)
    b = B.TripBudget()
    with B.use(b), pytest.raises(core.CacheMiss):
        core.claude_json("never cached", {"type": "object"}, offline=True)
    assert not rec and b.llm_calls == 0


# ---- Wikivoyage / FX through the guard -------------------------------------------


def test_wikivoyage_retries_429_with_retry_after_then_succeeds(monkeypatch):
    seq = [(429, {"retry-after": "3"}, b""), (200, {}, b'{"query": {}}')]
    sleeps = []
    monkeypatch.setattr(pricing, "raw_get", lambda url, **kw: seq.pop(0))
    monkeypatch.setattr(pricing.time, "sleep", sleeps.append)
    idx = pricing.WikivoyageIndex("Tokyo", cache_dir="unused", fetch_many=lambda t: {})
    assert idx._api({"action": "query"}) == {"query": {}} and sleeps == [3.0]


def test_wikivoyage_client_error_raises_api_error(monkeypatch):
    monkeypatch.setattr(pricing, "raw_get", lambda url, **kw: (400, {}, b"bad"))
    idx = pricing.WikivoyageIndex("Tokyo", cache_dir="unused", fetch_many=lambda t: {})
    with pytest.raises(core.ApiError):
        idx._api({"action": "query"})


def test_frankfurter_fx_uses_the_guarded_get(monkeypatch):
    monkeypatch.setattr(pricing, "raw_get", lambda url, **kw: (200, {}, b'{"rates": {"JPY": 150.0}}'))
    assert pricing.frankfurter_fx({})("USD", "JPY") == 150.0


def test_raw_get_is_guarded(cache):
    with pytest.raises(BlockedURL):
        core.raw_get("https://evil.example/x")


# ---- run(): budget stop, usage, and threads ---------------------------------------

REQ = {"origin": "DEN", "destinations": ["Tokyo, Japan"], "start_date": "2027-03-10", "duration_days": 5,
       "travelers": 1, "budget": 5000, "currency": "USD", "transport_modes": ["flight"]}


def test_run_that_hits_a_limit_stops_with_a_gap_and_partial_status(monkeypatch):
    def fake_run(req, ctx, rid, now, offline):
        for _ in range(5):
            try:
                B.current().charge_http()
            except B.BudgetExceeded:
                pass  # steps swallow errors; the run must still report it
        return agent._empty(ctx, "ok", rid)

    monkeypatch.setattr(agent, "_run", fake_run)
    out = agent.run(REQ, offline=True, limits=B.Limits(max_http_calls=2))
    assert out["status"] == "partial"
    assert any("stopped early" in g["reason"] and "http_calls" in g["reason"] for g in out["gaps"])
    assert out["_usage"]["stopped_by"] == "http_calls" and out["_usage"]["http_calls"] == 2
    assert out["_schema_errors"] == []


def test_run_survives_a_limit_raised_out_of_the_pipeline(monkeypatch):
    def fake_run(req, ctx, rid, now, offline):
        for _ in range(3):
            B.current().charge_http()

    monkeypatch.setattr(agent, "_run", fake_run)
    out = agent.run(REQ, offline=True, limits=B.Limits(max_http_calls=1))
    assert out["status"] == "error" and out["_usage"]["stopped_by"] == "http_calls"
    assert out["_schema_errors"] == []


def test_each_run_gets_its_own_budget(monkeypatch):
    seen = []
    monkeypatch.setattr(agent, "_run", lambda req, ctx, rid, now, offline: (seen.append(B.current()), agent._empty(ctx, "ok", rid))[1])
    agent.run(REQ, offline=True)
    agent.run(REQ, offline=True)
    assert seen[0] is not None and seen[0] is not seen[1] and B.current() is None


def test_offline_replay_uses_no_budget_and_reports_usage(with_recordings):
    out = agent.run({**REQ, "request_id": "t"}, offline=True)
    assert out["status"] == "ok" and out["_schema_errors"] == []
    u = out["_usage"]
    assert u["http_calls"] == 0 and u["llm_calls"] == 0 and u["cost_usd"] == 0 and u["stopped_by"] is None


# ---- source-level rules: nothing bypasses the guard ---------------------------------


def _sources():
    for name in sorted(os.listdir(RESEARCH_DIR)):
        if name.endswith(".py"):
            yield name, open(os.path.join(RESEARCH_DIR, name), encoding="utf-8").read()


def test_only_the_guard_touches_the_network():
    for name, text in _sources():
        assert "urlopen" not in text and "urllib.request" not in text, f"{name} fetches directly"
        assert "import requests" not in text and "import httpx" not in text, f"{name} uses another HTTP client"
        assert not re.search(r"HTTPS?Connection|socket\.create_connection", text), f"{name} opens connections itself"


def test_only_core_runs_subprocesses():
    for name, text in _sources():
        if name != "core.py":
            assert "subprocess" not in text and "os.system" not in text, f"{name} runs a subprocess"


def test_thread_pools_always_carry_the_budget():
    pattern = re.compile(r"\bex\.(submit|map)\(")
    for name, text in _sources():
        assert not pattern.search(text), f"{name} uses ex.submit/ex.map; use submit_in_context/map_in_context"
