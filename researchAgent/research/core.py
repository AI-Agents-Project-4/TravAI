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
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

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
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = r.read().decode("utf-8", "replace")
            cache_put(method, url, body, text)
            return json.loads(text) if parse and text[:1] in "{[" else text
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            last = ApiError(e.code, _redact(msg), url)
            if e.code not in (429, 500, 502, 503, 504):
                raise last
            time.sleep(2 ** attempt * 2)
        except (urllib.error.URLError, TimeoutError) as e:
            last = ApiError(0, str(e), url)
            time.sleep(2 ** attempt)
    raise last


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
    with tempfile.TemporaryDirectory() as cwd:  # neutral cwd: do not load this project's context
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p gave non-JSON output (exit {proc.returncode}): {proc.stdout[:200]} {proc.stderr[:200]}")
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
