"""Sandbox mode: demos and live runs use cached data only, except Geoapify, which may be reached live.

Full network access needs TRAVAI_ALLOW_NETWORK=1, which only the data-gathering scripts (`--gather`) set. These tests run with it unset, as a demo or the backend would."""

import json
import os
import socket
import subprocess

import pytest

from urllib.parse import urlsplit

from research import agent, core
from research.security import budget as B
from research.security import config
from research.security.fetch_guard import BlockedURL, FetchResult, _default_transport
from research.security.network_policy import ENV_VAR, NetworkDisabled, host_is_live, network_allowed, require_network

REQ = {"origin": "DEN", "destinations": ["Tokyo, Japan"], "start_date": "2027-03-10", "duration_days": 5,
       "travelers": 1, "budget": 5000, "currency": "USD", "transport_modes": ["flight"]}


@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(core, "ENV", {})  # no keys at all: replaying from the cache must not need any

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


# ---- every exit is closed, except Geoapify ---------------------------------------

LIVE = "https://api.geoapify.com/v1/geocode/search?text=x"
OTHERS = ["https://ignav.com/api/fares/one-way", "https://serpapi.com/search.json?q=x",
          "https://en.wikivoyage.org/w/api.php", "https://travel.state.gov/_res/rss/TAsTWs.xml",
          "https://api.frankfurter.dev/v1/latest", "https://open.er-api.com/v6/latest/USD",
          "https://evil.example/x"]


def fake_geoapify(monkeypatch, record):
    def fake(url, **kw):
        record.append({"url": url, **kw})
        return FetchResult(url, 200, b'{"features": []}')

    monkeypatch.setattr(core, "guarded_fetch", fake)


def test_geoapify_is_the_only_live_host():
    assert set(config.SANDBOX_LIVE_HOSTS) == {"api.geoapify.com"}
    assert host_is_live("api.geoapify.com") and host_is_live("sub.api.geoapify.com")
    for url in OTHERS + ["https://api.geoapify.com.evil.example/x", "https://notapi.geoapify.com.example/x"]:
        assert not host_is_live(urlsplit(url).hostname), url


def test_geoapify_cache_miss_goes_live_through_the_guard_and_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    calls = []
    fake_geoapify(monkeypatch, calls)
    b = B.TripBudget()
    with B.use(b):
        assert core.http("GET", LIVE) == {"features": []}
        assert core.http("GET", LIVE) == {"features": []}  # second time: cache
    assert len(calls) == 1 and b.http_calls == 1
    assert set(calls[0]["allowed_hosts"]) == {"api.geoapify.com"}  # the guard's own list is narrowed too


@pytest.mark.parametrize("url", OTHERS)
def test_every_other_host_is_cache_only(url, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    calls = []
    fake_geoapify(monkeypatch, calls)
    with pytest.raises(core.CacheMiss):
        core.http("GET", url)                       # even when the caller says offline=False
    with pytest.raises(core.CacheMiss):
        core.http("POST", url, {"a": 1})
    assert not calls


@pytest.mark.parametrize("url", OTHERS)
def test_uncached_gets_and_the_raw_transport_refuse_other_hosts(url):
    with pytest.raises(NetworkDisabled):
        core.raw_get(url)
    with pytest.raises(NetworkDisabled):
        core._fetch(url)
    with pytest.raises(NetworkDisabled):
        _default_transport(url, "93.184.216.34", 5, 100)


def test_the_real_transport_lets_geoapify_through_to_the_socket():
    with pytest.raises(AssertionError, match="opened a network connection"):  # the trap above fired: policy allowed it
        _default_transport(LIVE, "93.184.216.34", 5, 100)


def test_a_redirect_from_geoapify_to_another_host_is_refused(tmp_path, monkeypatch):
    # the real guard with a fake transport: Geoapify answers with a redirect to Ignav
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    from research.security import fetch_guard as fg

    def transport(url, ip, timeout, max_bytes, **kw):
        return 302, {"location": "https://ignav.com/steal"}, b"", False

    real = fg.guarded_fetch
    monkeypatch.setattr(core, "guarded_fetch", lambda url, **kw: real(url, resolver=lambda h: ["93.184.216.34"], transport=transport, **kw))
    with pytest.raises(BlockedURL, match="allowlist"):
        core.http("GET", LIVE)


def test_claude_with_web_search_never_runs_in_the_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "LLM_CACHE", str(tmp_path))
    with pytest.raises(core.CacheMiss):
        core.claude_json("p", {"type": "object"}, web=True, offline=False)  # the subprocess trap would fire otherwise


def test_claude_with_tools_off_may_run_in_the_sandbox_and_is_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "LLM_CACHE", str(tmp_path))
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        out = {"structured_output": {"x": 1}, "total_cost_usd": 0.01, "usage": {"input_tokens": 5, "output_tokens": 2}}
        return type("P", (), {"stdout": json.dumps(out), "stderr": "", "returncode": 0})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = B.TripBudget()
    with B.use(b):
        assert core.claude_json("p", {"type": "object"}, web=False) == {"x": 1}
    cmd = seen[0]
    assert cmd[cmd.index("--tools") + 1] == "" and "--allowedTools" not in cmd  # no tools at all, so no web access
    assert b.llm_calls == 1 and b.cost_usd == pytest.approx(0.01)


def test_explicit_offline_still_blocks_every_claude_call(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "LLM_CACHE", str(tmp_path))
    with pytest.raises(core.CacheMiss):
        core.claude_json("p", {"type": "object"}, web=False, offline=True)


def test_web_price_search_is_skipped_in_the_sandbox_not_an_error():
    from research import activities
    assert activities.web_prices([{"id": "a", "name": "Some Museum"}], "Tokyo", "Japan", offline=False) == {}


def test_web_price_search_still_fails_loudly_on_an_explicit_offline_replay():
    from research import activities
    with pytest.raises(core.CacheMiss):
        activities.web_prices([{"id": "a", "name": "Some Museum"}], "Tokyo", "Japan", offline=True)


def test_data_mode_is_sandbox_unless_gathering(monkeypatch):
    monkeypatch.setenv("TRAVAI_DATA_MODE", "live")
    core.set_data_mode("live")
    try:
        assert core.data_mode() == "sandbox"          # asking for live data does nothing without the switch
        monkeypatch.setenv(ENV_VAR, "1")
        assert core.data_mode() == "live"              # gather mode honors it
        core.set_data_mode("sandbox")
        assert core.data_mode() == "sandbox"           # and --sandbox still works inside it
    finally:
        core.set_data_mode(None)


def test_synthetic_data_is_never_a_silent_fallback(tmp_path, monkeypatch):
    from research import sandbox
    monkeypatch.setattr(sandbox, "DATA_DIR", str(tmp_path))        # no recordings here
    monkeypatch.delenv("TRAVAI_SANDBOX_DATA", raising=False)
    monkeypatch.setattr(sandbox, "_default", None)
    store = sandbox.default_store()
    assert not store.synthetic and store.flights == [] and store.hotels == []
    assert sandbox.find_flights("DEN", "HND", "2027-03-10", "2027-03-15", 1, store) is None  # a gap, not made-up fares
    monkeypatch.setattr(sandbox, "_default", None)
    monkeypatch.setenv("TRAVAI_SANDBOX_DATA", "synthetic")
    assert sandbox.default_store().synthetic                       # only when asked for
    monkeypatch.setattr(sandbox, "_default", None)
    monkeypatch.setenv("TRAVAI_SANDBOX_DATA", "bogus")
    with pytest.raises(ValueError):
        sandbox.default_store()
    monkeypatch.setattr(sandbox, "_default", None)


def test_cache_hits_still_work_and_cost_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    core.cache_put("GET", "https://ignav.com/v1/y", None, '{"a": 1}')
    b = B.TripBudget()
    with B.use(b):
        assert core.http("GET", "https://ignav.com/v1/y") == {"a": 1}
    assert b.http_calls == 0


def test_replay_needs_no_keys_but_a_live_call_without_one_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    calls = []
    fake_geoapify(monkeypatch, calls)
    assert core.secret("IGNAV_API_KEY") == core.secret("GEOAPIFY_API_KEY") == core.NO_KEY
    with pytest.raises(RuntimeError, match="needs its API key"):
        core.http("GET", LIVE + "&apiKey=" + core.secret("GEOAPIFY_API_KEY"))  # the placeholder is never sent
    assert not calls
    monkeypatch.setattr(core, "ENV", {"GEOAPIFY_API_KEY": "real-key-abc"})
    core.http("GET", LIVE + "&apiKey=" + core.secret("GEOAPIFY_API_KEY"))
    assert len(calls) == 1 and "real-key-abc" in calls[0]["url"]


def test_currency_missing_from_frankfurter_falls_back_to_the_second_source_in_the_sandbox(tmp_path, monkeypatch):
    # Frankfurter has no UAH. When replaying, that shows up as a cache miss on a cache-only host.
    from research import sources
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    core.cache_put("GET", "https://open.er-api.com/v6/latest/UAH", None, '{"result": "success", "rates": {"USD": 0.025}}')
    assert sources.fx_rate("UAH", "USD", offline=False) == 0.025


def test_gather_mode_still_requires_every_key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    with pytest.raises(RuntimeError, match="IGNAV_API_KEY missing"):
        core.secret("IGNAV_API_KEY")


def test_gather_mode_reaches_everything(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    assert all(host_is_live(urlsplit(u).hostname) for u in OTHERS)


# ---- run() ---------------------------------------------------------------------


def test_run_replays_from_the_cache_in_the_sandbox(with_recordings):
    out = agent.run({**REQ, "request_id": "t"}, offline=False)  # what a careless caller would pass
    assert out["status"] == "ok" and out["_schema_errors"] == []
    assert out["_usage"]["network"] == "sandbox"
    assert out["_usage"]["http_calls"] == 0 and out["_usage"]["llm_calls"] == 0  # all cached: nothing went out
    assert any(n.startswith("Sandbox mode:") and "Geoapify" in n for n in out["notes"])


def test_a_new_destination_uses_live_geoapify_and_model_reasoning_but_gets_no_made_up_prices(with_recordings, tmp_path, monkeypatch):
    """Reykjavik is not in any cache or recording. The model resolves it (tools off) and Geoapify geocodes it live;
    there are no recorded fares or rates for it, so those are gaps. Nothing else reaches out and nothing is invented."""
    monkeypatch.setattr(core, "LLM_CACHE", str(tmp_path / "llm"))
    monkeypatch.setattr(core, "ENV", {"GEOAPIFY_API_KEY": "real-key-abc"})
    stop = {"query": "Reykjavik, Iceland", "city": "Reykjavik", "country": "Iceland", "country_code": "is", "airports": ["KEF"],
            "local_currency": "ISK", "advisory_country": "Iceland", "cost_tier": 4, "daily_cost_usd": 120,
            "wikivoyage_title": "Reykjavik"}
    claude_cmds = []

    def fake_claude(cmd, **kw):
        claude_cmds.append(cmd)
        out = {"origin_airport": "DEN", "notes": [], "stops": [stop], "trips": [], "items": [], "results": []}
        return type("P", (), {"stdout": json.dumps({"structured_output": out, "total_cost_usd": 0.02,
                                                    "usage": {"input_tokens": 10, "output_tokens": 5}}), "stderr": "", "returncode": 0})()

    monkeypatch.setattr(subprocess, "run", fake_claude)
    geo = []
    place = b'{"features": [{"properties": {"lat": 64.14, "lon": -21.94, "formatted": "Reykjavik, Iceland"}}]}'
    monkeypatch.setattr(core, "guarded_fetch", lambda url, **kw: geo.append(url) or FetchResult(
        url, 200, b'{"features": []}' if "/v1/routing" in url else place))
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path / "http"))     # nothing cached: forces the live Geoapify path
    out = agent.run({**REQ, "destinations": ["Reykjavik, Iceland"], "request_id": "t"})
    assert out["_schema_errors"] == [] and out["status"] in ("error", "partial")
    assert out["flights"] == [] and out["lodging"] == []              # no recording, so gaps, not invented prices
    assert any("no recorded" in g["reason"].lower() or "sandbox" in g["reason"].lower() for g in out["gaps"])
    assert claude_cmds and all(c[c.index("--tools") + 1] == "" for c in claude_cmds)  # reasoning only: tools off every time
    assert geo and all(urlsplit(u).hostname == "api.geoapify.com" for u in geo)       # the only live host
    assert out["_usage"]["llm_calls"] == len(claude_cmds) and out["_usage"]["http_calls"] == len(geo)


def test_run_with_the_switch_on_is_marked_live(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    monkeypatch.setattr(agent, "_run", lambda req, ctx, rid, now, offline: agent._empty(ctx, "ok", rid))
    out = agent.run(REQ)
    assert out["_usage"]["network"] == "live" and not any(n.startswith("Sandbox data:") for n in out["notes"])


def test_a_live_geoapify_lookup_during_a_run_is_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "HTTP_CACHE", str(tmp_path))
    calls = []
    fake_geoapify(monkeypatch, calls)
    monkeypatch.setattr(core, "ENV", {"GEOAPIFY_API_KEY": "real-key-abc"})

    def fake_run(req, ctx, rid, now, offline):
        from research import sources
        sources.geocode("Somewhere", offline=False)   # a Geoapify cache miss, as a new origin would be
        return agent._empty(ctx, "ok", rid)

    monkeypatch.setattr(agent, "_run", fake_run)
    out = agent.run(REQ)
    assert len(calls) == 1 and out["_usage"]["http_calls"] == 1 and out["_usage"]["network"] == "sandbox"


# ---- scripts --------------------------------------------------------------------


def test_scripts_only_enable_the_network_with_gather():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for rel, flag in (("scripts/run_agent.py", "--gather"), ("tests/run_cases.py", "--gather"), ("scripts/record_sandbox.py", "--live")):
        text = open(os.path.join(root, rel), encoding="utf-8").read()
        assert f'if "{flag}" in sys.argv:' in text, rel
        assert text.count('os.environ["TRAVAI_ALLOW_NETWORK"]') == 1, rel  # set in exactly one place, behind the flag


def test_nothing_in_the_agent_sets_the_switch():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for base in ("research",):
        for dirpath, _d, files in os.walk(os.path.join(root, base)):
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(dirpath, f), encoding="utf-8").read()
                    assert "environ[\"TRAVAI_ALLOW_NETWORK\"]" not in text and "setenv" not in text, f
