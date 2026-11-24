"""Shared plumbing: .env loading, a disk cache for every HTTP call, and a `claude -p` wrapper.

All network results are cached under tests/fixtures/ so test runs and reruns spend no API quota.
Secrets are stripped from cache keys and redacted from stored bodies."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
from http.client import HTTPException  # not `import http`: this module defines a function named http
from typing import Any, Optional

from .security import budget as _budget
from .security import config as sec_config
from .security.network_policy import require_network
from .security.fetch_guard import BlockedURL, guarded_fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTTP_CACHE = os.path.join(ROOT, "tests", "fixtures", "http_cache")
LLM_CACHE = os.path.join(ROOT, "tests", "fixtures", "llm_cache")
UA = "travai-research-test/0.1"
SECRET_PARAMS = {"apikey", "api_key"}


_TTL: Optional[float] = None   # seconds; None = cached entries never expire (tests / replay)


def set_cache_ttl(hours: Optional[float]) -> None:
    """Make cached HTTP and LLM results older than `hours` count as missing (live runs only; offline ignores it)."""
    global _TTL
    _TTL = None if hours is None else hours * 3600


def is_fresh(saved_at: float, ttl: Optional[float], now: Optional[float] = None) -> bool:
    return ttl is None or (now if now is not None else time.time()) - saved_at < ttl


class CacheMiss(RuntimeError):
    pass


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, url: str = ""):
        super().__init__(f"HTTP {status} from {_canon_url(url)}: {body[:200]}")
        self.status, self.body = status, body


def load_env(path: Optional[str] = None) -> dict:
    out = {}
    p = path or os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return {**out, **{k: v for k, v in os.environ.items() if k.endswith("_API_KEY")}}


ENV = load_env()


def secret(name: str, offline: bool = False) -> str:
    """API key from .env. When replaying offline the key is never sent (it is stripped from cache keys), so a
    missing key is fine there."""
    v = ENV.get(name)
    if not v:
        if offline:
            return "offline-no-key"
        raise RuntimeError(f"{name} missing from .env (copy .env.example to .env and fill it in)")
    return v


def _canon_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if k.lower() not in SECRET_PARAMS]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), ""))


def _key(method: str, url: str, body: Any) -> str:
    return hashlib.sha1(f"{method} {_canon_url(url)} {json.dumps(body, sort_keys=True)}".encode()).hexdigest()


def _redact(text: str) -> str:
    for k, v in ENV.items():
        if v and len(v) > 6:
            text = text.replace(v, "<redacted>")
    return text


def cache_put(method: str, url: str, body: Any, text: str) -> None:
    os.makedirs(HTTP_CACHE, exist_ok=True)
    open(os.path.join(HTTP_CACHE, _key(method, url, body) + ".json"), "w", encoding="utf-8").write(
        json.dumps({"method": method, "url": _canon_url(url), "body": body, "saved_at": time.time(), "text": _redact(text)}, ensure_ascii=False))


def http(method: str, url: str, body: Any = None, headers: Optional[dict] = None, *, offline: bool = False,
         timeout: int = 90, ttl: Optional[float] = None, parse: bool = True):
    """Cached HTTP. ttl (seconds) lets stale entries be refetched; offline never touches the network."""
    path = os.path.join(HTTP_CACHE, _key(method, url, body) + ".json")
    if os.path.exists(path):
        rec = json.load(open(path, encoding="utf-8"))
        eff = ttl if ttl is not None else _TTL
        if offline or is_fresh(rec["saved_at"], eff):
            return json.loads(rec["text"]) if parse and rec["text"][:1] in "{[" else rec["text"]
    if offline:
        raise CacheMiss(f"offline and not cached: {method} {_canon_url(url)} {json.dumps(body)[:120]}")
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"User-Agent": UA, **(headers or {})}
    if data:
        hdrs.setdefault("Content-Type", "application/json")
    last: Exception = RuntimeError("unreachable")
    for attempt in range(3):
        try:
            status, _h, raw, _t = _fetch(url, method=method, headers=hdrs, body=data, timeout=timeout)
        except BlockedURL:
            raise  # not retried: the guard said no
        except (OSError, HTTPException) as e:  # network trouble, timeouts, TLS errors
            last = ApiError(0, str(e), url)
            time.sleep(2 ** attempt)
            continue
        text = raw.decode("utf-8", "replace")
        if status >= 400:
            last = ApiError(status, _redact(text), url)
            if status not in (429, 500, 502, 503, 504):
                raise last
            time.sleep(2 ** attempt * 2)
            continue
        cache_put(method, url, body, text)
        return json.loads(text) if parse and text[:1] in "{[" else text
    raise last


def _fetch(url: str, *, method: str = "GET", headers: Optional[dict] = None, body: Optional[bytes] = None,
           timeout: float = 30) -> tuple:
    """The only place the agent touches the network. Applies the fetch guard (https, host allowlist,
    public IPs only, size cap) and charges the trip budget. Returns (status, headers, body, truncated)."""
    require_network(f"a request to {urllib.parse.urlsplit(url).netloc}")
    b = _budget.current()
    if b is not None:
        b.charge_http()
    r = guarded_fetch(url, allowed_hosts=sec_config.FETCH_ALLOWED_HOSTS, method=method, headers=headers, body=body,
                      timeout=timeout, max_bytes=sec_config.API_MAX_RESPONSE_BYTES)
    if r.truncated:
        raise ApiError(0, "response larger than the size limit", url)
    return r.status, r.headers, r.body, False


def raw_get(url: str, *, headers: Optional[dict] = None, timeout: float = 30) -> tuple:
    """Uncached guarded GET for callers that keep their own cache (Wikivoyage, FX). Returns (status, headers, body)."""
    status, h, body, _ = _fetch(url, headers={"User-Agent": UA, **(headers or {})}, timeout=timeout)
    return status, h, body


# ---------- claude -p ----------

def claude_json(prompt: str, schema: dict, *, web: bool = False, offline: bool = False, timeout: int = 300,
                max_budget_usd: float = 1.0, model: Optional[str] = None) -> dict:
    """Run `claude -p` and return structured output validated by the CLI against `schema`.
    Cached by prompt+schema so reruns are free and deterministic."""
    key = hashlib.sha1(json.dumps([prompt, schema, web, model], sort_keys=True).encode()).hexdigest()
    path = os.path.join(LLM_CACHE, key + ".json")
    if os.path.exists(path) and (offline or is_fresh(os.path.getmtime(path), _TTL)):
        return json.load(open(path, encoding="utf-8"))
    if offline:
        raise CacheMiss(f"offline and LLM call not cached: {prompt[:100]!r}")
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(schema),
           "--no-session-persistence", "--max-budget-usd", str(max_budget_usd)]
    cmd += ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch"] if web else ["--tools", ""]
    if model:
        cmd += ["--model", model]
    require_network("a `claude -p` call")  # the CLI can run web search, so it counts as reaching out
    b = _budget.current()
    if b is not None:
        b.charge_llm()
    with tempfile.TemporaryDirectory() as cwd:  # neutral cwd: do not load this project's context
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p gave non-JSON output (exit {proc.returncode}): {proc.stdout[:200]} {proc.stderr[:200]}")
    _record_usage(b, d, model, web)
    if d.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(d.get('result'))[:300]}")
    out = d.get("structured_output")
    if out is None:
        try:
            out = json.loads(d.get("result", ""))
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(f"claude -p returned no structured output: {str(d)[:300]}")
    os.makedirs(LLM_CACHE, exist_ok=True)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def _record_usage(b: Optional["_budget.TripBudget"], d: dict, model: Optional[str], web: bool) -> None:
    """Log tokens and cost from the CLI's JSON (missing fields count as 0). The answer is already paid for, so a
    limit hit here is not raised now: `stopped_by` is set and the next charge stops the run."""
    if b is None or not isinstance(d, dict):
        return
    u = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    try:
        b.record_model_call(
            agent="research" + ("-web" if web else ""), model=model or "default",
            input_tokens=int(num(u.get("input_tokens"))), output_tokens=int(num(u.get("output_tokens"))),
            cached_tokens=int(num(u.get("cache_read_input_tokens"))), cost_usd=float(num(d.get("total_cost_usd"))))
    except _budget.BudgetExceeded:
        pass
