"""Fetch guard tests. No network: DNS and HTTP are faked."""

import pytest

from research.security.fetch_guard import (
    BlockedURL,
    check_url_syntax,
    guarded_fetch,
    host_allowed,
    redact_url,
    resolve_public_ips,
)

ALLOWED = ["hotels.example", "flights.example"]


def public_resolver(host):
    return ["93.184.216.34"]


def make_transport(responses):
    """responses: {url: (status, headers, body)}. Records the URLs and IPs it was called with."""
    calls = []

    def transport(url, ip, timeout, max_bytes):
        calls.append((url, ip))
        status, headers, body = responses[url]
        truncated = len(body) > max_bytes
        return status, headers, body[:max_bytes], truncated

    transport.calls = calls
    return transport


# ---- syntax checks -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://hotels.example/a",  # not https
        "ftp://hotels.example/a",
        "https://user:pw@hotels.example/a",  # credentials
        "https://evil.example/a",  # not allowlisted
        "https://hotels.example.evil.example/a",  # lookalike suffix
        "https://evilhotels.example/a",  # not a subdomain, just a suffix match
        "https://127.0.0.1/a",  # IP literal
        "https://[::1]/a",
        "https://hotels.example:8443/a",  # odd port
        "https:///nohost",
    ],
)
def test_blocked_urls(url):
    with pytest.raises(BlockedURL):
        check_url_syntax(url, ALLOWED)


def test_allowed_and_subdomain():
    assert check_url_syntax("https://hotels.example/a", ALLOWED) == "hotels.example"
    assert check_url_syntax("https://www.hotels.example/a", ALLOWED) == "www.hotels.example"
    assert host_allowed("HOTELS.example.", ALLOWED)


def test_empty_allowlist_blocks_everything():
    with pytest.raises(BlockedURL):
        check_url_syntax("https://hotels.example/a", [])


# ---- exfiltration (T4) ---------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://hotels.example/search?q=Denver",
        "https://hotels.example/denver",
        "https://hotels.example/s?q=den%76er",  # encoded
        "https://hotels.example/s?q=DENVER",
    ],
)
def test_trip_data_in_url_is_blocked(url):
    with pytest.raises(BlockedURL, match="trip data"):
        check_url_syntax(url, ALLOWED, private_values=["Denver"])


def test_double_encoded_trip_data_is_blocked():
    # "New York" -> "New%2520York" after one decode becomes "New%20York", then "New York"
    with pytest.raises(BlockedURL, match="trip data"):
        check_url_syntax("https://hotels.example/s?q=New%2520York", ALLOWED, ["New York"])


def test_short_private_values_ignored():
    # Two-character values would block almost every URL, so they are skipped.
    check_url_syntax("https://hotels.example/a", ALLOWED, private_values=["a", "5"])


# ---- DNS (private addresses) --------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.9",
        "169.254.169.254",  # cloud metadata
        "0.0.0.0",
        "::1",
        "fd00::1",
        "::ffff:10.0.0.1",  # IPv4-mapped private
    ],
)
def test_private_resolution_is_blocked(ip):
    with pytest.raises(BlockedURL, match="non-public"):
        resolve_public_ips("hotels.example", lambda h: [ip])


def test_one_private_address_among_public_is_blocked():
    with pytest.raises(BlockedURL):
        resolve_public_ips("hotels.example", lambda h: ["93.184.216.34", "10.0.0.1"])


def test_resolution_failure_is_blocked():
    def boom(host):
        raise OSError("no such host")

    with pytest.raises(BlockedURL):
        resolve_public_ips("hotels.example", boom)


# ---- guarded_fetch -------------------------------------------------------


def test_fetch_ok_connects_to_checked_ip():
    t = make_transport({"https://hotels.example/a": (200, {}, b"hello")})
    r = guarded_fetch(
        "https://hotels.example/a", allowed_hosts=ALLOWED, resolver=public_resolver, transport=t
    )
    assert r.status == 200 and r.body == b"hello" and not r.truncated
    assert t.calls == [("https://hotels.example/a", "93.184.216.34")]


def test_fetch_follows_allowed_redirect():
    t = make_transport(
        {
            "https://hotels.example/a": (302, {"location": "/b"}, b""),
            "https://hotels.example/b": (200, {}, b"ok"),
        }
    )
    r = guarded_fetch(
        "https://hotels.example/a", allowed_hosts=ALLOWED, resolver=public_resolver, transport=t
    )
    assert r.url == "https://hotels.example/b"
    assert r.redirects == ["https://hotels.example/b"]


def test_redirect_to_other_host_is_blocked():
    t = make_transport(
        {"https://hotels.example/a": (302, {"location": "https://evil.example/steal"}, b"")}
    )
    with pytest.raises(BlockedURL, match="allowlist"):
        guarded_fetch(
            "https://hotels.example/a", allowed_hosts=ALLOWED, resolver=public_resolver, transport=t
        )
    assert len(t.calls) == 1  # never contacted evil.example


def test_redirect_to_private_ip_host_is_blocked():
    # An allowlisted name that resolves to an internal address on the second hop.
    answers = {"hotels.example": ["93.184.216.34"], "flights.example": ["169.254.169.254"]}
    t = make_transport(
        {"https://hotels.example/a": (301, {"location": "https://flights.example/x"}, b"")}
    )
    with pytest.raises(BlockedURL, match="non-public"):
        guarded_fetch(
            "https://hotels.example/a",
            allowed_hosts=ALLOWED,
            resolver=lambda h: answers[h],
            transport=t,
        )


def test_redirect_carrying_trip_data_is_blocked():
    t = make_transport(
        {"https://hotels.example/a": (302, {"location": "https://flights.example/?o=Denver"}, b"")}
    )
    with pytest.raises(BlockedURL, match="trip data"):
        guarded_fetch(
            "https://hotels.example/a",
            allowed_hosts=ALLOWED,
            private_values=["Denver"],
            resolver=public_resolver,
            transport=t,
        )


def test_redirect_loop_is_stopped():
    t = make_transport({"https://hotels.example/a": (302, {"location": "/a"}, b"")})
    with pytest.raises(BlockedURL, match="redirects"):
        guarded_fetch(
            "https://hotels.example/a",
            allowed_hosts=ALLOWED,
            resolver=public_resolver,
            transport=t,
            max_redirects=3,
        )
    assert len(t.calls) == 4


def test_large_response_is_truncated():
    t = make_transport({"https://hotels.example/a": (200, {}, b"x" * 100)})
    r = guarded_fetch(
        "https://hotels.example/a",
        allowed_hosts=ALLOWED,
        resolver=public_resolver,
        transport=t,
        max_bytes=10,
    )
    assert len(r.body) == 10 and r.truncated


# ---- key redaction -------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://h.example/p?text=cafe&apiKey=abc123", "https://h.example/p?text=cafe&apiKey=REDACTED"),
        ("https://h.example/p?apikey=abc&x=1", "https://h.example/p?apikey=REDACTED&x=1"),
        ("https://h.example/p?API_KEY=abc", "https://h.example/p?API_KEY=REDACTED"),
        ("https://h.example/p?x=1&token=t0k&y=2#frag", "https://h.example/p?x=1&token=REDACTED&y=2#frag"),
        ("https://h.example/p?keyword=tokyo", "https://h.example/p?keyword=tokyo"),  # not a key
        ("https://h.example/p", "https://h.example/p"),
    ],
)
def test_redact_url(url, expected):
    assert redact_url(url) == expected


def test_fetch_result_never_contains_the_key():
    secret = "s3cr3t-key-value"
    t = make_transport(
        {
            "https://hotels.example/a?apiKey=" + secret: (
                302,
                {"location": "/b?apiKey=" + secret},
                b"",
            ),
            "https://hotels.example/b?apiKey=" + secret: (200, {}, b"ok"),
        }
    )
    r = guarded_fetch(
        "https://hotels.example/a?apiKey=" + secret,
        allowed_hosts=ALLOWED,
        resolver=public_resolver,
        transport=t,
    )
    assert r.status == 200  # the real key was still sent
    assert secret not in r.url
    assert all(secret not in x for x in r.redirects)
    assert r.url.endswith("apiKey=REDACTED")


def test_blocked_error_and_logs_do_not_contain_the_key(caplog):
    secret = "s3cr3t-key-value"
    with caplog.at_level("INFO", logger="research.fetch"):
        with pytest.raises(BlockedURL) as exc:
            guarded_fetch(
                "https://evil.example/a?apiKey=" + secret,
                allowed_hosts=ALLOWED,
                resolver=public_resolver,
                transport=make_transport({}),
            )
    assert secret not in str(exc.value)
    assert secret not in caplog.text
