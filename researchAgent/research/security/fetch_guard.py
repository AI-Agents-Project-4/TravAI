"""Guarded outbound fetching for the research agent (threat model T3, T4).

Every web request the agent makes should go through `guarded_fetch`. It only allows
https to allowlisted hosts, refuses private or internal addresses, checks every
redirect hop, caps size and time, and refuses URLs that carry the user's trip data.

DNS rebinding: the hostname is resolved once, checked, and then the connection is
made to that same checked IP (TLS still verifies the hostname's certificate).
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import re
import socket
import ssl
from dataclasses import dataclass, field
from typing import Callable, Iterable
from urllib.parse import unquote, urljoin, urlsplit

from . import config

log = logging.getLogger("research.fetch")


class BlockedURL(Exception):
    """The URL is not allowed. The message says why (safe to log)."""


@dataclass
class FetchResult:
    url: str  # final URL after redirects, with key-like query values redacted
    status: int
    body: bytes
    truncated: bool = False
    redirects: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names


# transport(url, ip, timeout, max_bytes, method=..., headers=..., body=...)
#   -> (status, headers, body, truncated).
# It must NOT follow redirects. Injected in tests.
Transport = Callable[..., "tuple[int, dict[str, str], bytes, bool]"]
Resolver = Callable[[str], "list[str]"]


_SECRET_PARAM = re.compile(
    r"(?<=[?&])(api[_-]?key|key|access[_-]?token|token|secret|password|auth|signature|sig)=[^&#]*",
    re.IGNORECASE,
)


def redact_url(url: str) -> str:
    """Replace the value of key-like query parameters (apiKey=..., token=...) with REDACTED.

    Geoapify and similar APIs take the key in the URL. Anything that leaves this module
    (results, logs, errors) must use the redacted form so a key can't end up in saved
    data or the model's context.
    """
    return _SECRET_PARAM.sub(lambda m: f"{m.group(1)}=REDACTED", url)


def host_allowed(host: str, allowed_hosts: Iterable[str]) -> bool:
    """True if host equals an allowed host or is a subdomain of one."""
    host = host.lower().rstrip(".")
    for allowed in allowed_hosts:
        allowed = allowed.lower().rstrip(".")
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def check_link_shape(url: str, allow_http: bool = False) -> str:
    """Shape checks for a URL the model gave us (no allowlist): https (or http if `allow_http`),
    no credentials, no IP-literal host, standard port. This is for links we only SHOW, never
    fetch. Returns the lowercase hostname or raises BlockedURL."""
    parts = urlsplit(url)
    if parts.scheme not in (("https", "http") if allow_http else ("https",)):
        raise BlockedURL(f"scheme must be https, got {parts.scheme!r}")
    if parts.username or parts.password:
        raise BlockedURL("credentials in URL are not allowed")
    host = (parts.hostname or "").lower()
    if not host or "." not in host:
        raise BlockedURL("URL has no usable host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise BlockedURL("IP address hosts are not allowed")
    try:
        port = parts.port
    except ValueError:
        raise BlockedURL("invalid port") from None
    if port not in (None, 443, 80 if allow_http else 443):
        raise BlockedURL(f"port {port} is not allowed")
    return host


def check_url_syntax(
    url: str,
    allowed_hosts: Iterable[str],
    private_values: Iterable[str] = (),
) -> str:
    """Checks that need no network. Returns the lowercase hostname or raises BlockedURL."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise BlockedURL(f"scheme must be https, got {parts.scheme!r}")
    if parts.username or parts.password:
        raise BlockedURL("credentials in URL are not allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise BlockedURL("URL has no host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise BlockedURL("IP address hosts are not allowed")
    try:
        port = parts.port
    except ValueError:
        raise BlockedURL("invalid port") from None
    if port not in (None, 443):
        raise BlockedURL(f"port {port} is not allowed")
    if not host_allowed(host, allowed_hosts):
        raise BlockedURL(f"host {host!r} is not on the allowlist")

    # Exfiltration check (T4): the user's trip data must never appear in a URL.
    # Decode a few times so %2520-style double encoding doesn't hide it.
    visible = url.lower()
    for _ in range(3):
        visible = unquote(visible).replace("+", " ")
    for value in private_values:
        v = str(value).strip().lower()
        if len(v) >= 3 and v in visible:
            raise BlockedURL("URL contains trip data")
    return host


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def resolve_public_ips(host: str, resolver: Resolver = _default_resolver) -> list[str]:
    """Resolve host and require EVERY address to be public. Returns the addresses."""
    try:
        ips = resolver(host)
    except OSError as exc:
        raise BlockedURL(f"could not resolve {host!r}: {exc}") from None
    if not ips:
        raise BlockedURL(f"{host!r} resolved to no addresses")
    for ip in ips:
        addr = ipaddress.ip_address(ip.split("%")[0])
        # Unwrap IPv4-mapped IPv6 (::ffff:10.0.0.1) so it can't smuggle a private IP.
        mapped = getattr(addr, "ipv4_mapped", None)
        if mapped is not None:
            addr = mapped
        if not addr.is_global:
            raise BlockedURL(f"{host!r} resolves to a non-public address")
    return ips


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a specific, already-checked IP, verifying the cert for `host`."""

    def __init__(self, host: str, ip: str, timeout: float):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _default_transport(
    url: str,
    ip: str,
    timeout: float,
    max_bytes: int,
    method: str = "GET",
    headers: "dict[str, str] | None" = None,
    body: "bytes | None" = None,
) -> tuple[int, dict[str, str], bytes, bool]:
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    conn = _PinnedHTTPSConnection(parts.hostname or "", ip, timeout)
    try:
        hdrs = {"User-Agent": "TravAI-research/0.1", "Accept-Encoding": "identity"}
        hdrs.update(headers or {})
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data[:max_bytes], truncated
    finally:
        conn.close()


def guarded_fetch(
    url: str,
    *,
    allowed_hosts: Iterable[str] = config.FETCH_ALLOWED_HOSTS,
    private_values: Iterable[str] = (),
    max_redirects: int = config.MAX_REDIRECTS,
    max_bytes: int = config.MAX_RESPONSE_BYTES,
    timeout: float = config.FETCH_TIMEOUT_SECONDS,
    resolver: Resolver = _default_resolver,
    transport: Transport = _default_transport,
    method: str = "GET",
    headers: "dict[str, str] | None" = None,
    body: "bytes | None" = None,
) -> FetchResult:
    """Request `url` with every check applied to the first request and each redirect.

    Only GET requests follow redirects. A redirect on any other method is refused,
    because replaying a body or key header to another location is not safe.

    Raises BlockedURL if any hop is not allowed. Network errors propagate as OSError.
    `private_values` are the user's trip fields (origin, destination, ...) that must
    never show up in a URL.
    """
    allowed = tuple(allowed_hosts)
    private = tuple(private_values)
    redirects: list[str] = []
    current = url

    for _ in range(max_redirects + 1):
        try:
            host = check_url_syntax(current, allowed, private)
            ips = resolve_public_ips(host, resolver)
        except BlockedURL as exc:
            log.warning("fetch blocked: %s (%s)", _loggable(current), exc)
            raise
        log.info("fetch: %s", _loggable(current))
        kwargs: dict = {}
        if method != "GET" or headers or body is not None:
            kwargs = {"method": method, "headers": headers, "body": body}
        status, resp_headers, data, truncated = transport(
            current, ips[0], timeout, max_bytes, **kwargs
        )
        if status in (301, 302, 303, 307, 308) and "location" in resp_headers:
            if method != "GET":
                log.warning("fetch blocked: redirect on %s %s", method, _loggable(current))
                raise BlockedURL(f"redirect on a {method} request is not followed")
            current = urljoin(current, resp_headers["location"])
            redirects.append(current)
            continue
        return FetchResult(
            redact_url(current),
            status,
            data,
            truncated,
            [redact_url(r) for r in redirects],
            resp_headers,
        )

    log.warning("fetch blocked: too many redirects from %s", _loggable(url))
    raise BlockedURL(f"more than {max_redirects} redirects")


def _loggable(url: str) -> str:
    """Log the host and path but not the query string (it may hold search terms)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"
