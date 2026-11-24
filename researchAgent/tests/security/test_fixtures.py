"""Fixture loader tests. Sample data here is made up for testing only."""

import json
from datetime import datetime, timezone

import pytest

from research.security.fixtures import (
    FixtureError,
    find_secrets,
    load_fixture_dir,
    load_fixture_options,
)

HOSTS = ["hotels.example"]
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def option(**overrides):
    o = {
        "kind": "hotel",
        "title": "Sample Hotel, 5 nights",
        "price": {"amount": 600, "currency": "USD"},
        "price_is_estimate": False,
        "source_url": "https://hotels.example/sample",
    }
    o.update(overrides)
    return o


def write(tmp_path, options, collected_at="2026-11-20T15:30:00Z", name="f.json", **extra):
    data = {"collected_at": collected_at, "options": options, **extra}
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def load(path, **kw):
    return load_fixture_options(path, source_hosts=HOSTS, now=NOW, **kw)


def test_loads_and_tags_snapshot(tmp_path):
    [opt] = load(write(tmp_path, [option()]))
    assert opt.extra["details"]["data_origin"] == "snapshot"


def test_fetched_at_defaults_to_collection_time_not_now(tmp_path):
    [opt] = load(write(tmp_path, [option()]))
    assert opt.fetched_at == datetime(2026, 11, 20, 15, 30, tzinfo=timezone.utc)


def test_explicit_fetched_at_wins(tmp_path):
    [opt] = load(write(tmp_path, [option(fetched_at="2026-11-19T00:00:00Z")]))
    assert opt.fetched_at.day == 19


def test_existing_details_kept(tmp_path):
    [opt] = load(write(tmp_path, [option(details={"airline": "X"})]))
    assert opt.extra["details"] == {"airline": "X", "data_origin": "snapshot"}


def test_fixture_cannot_claim_to_be_live(tmp_path):
    [opt] = load(write(tmp_path, [option(details={"data_origin": "live"})]))
    assert opt.extra["details"]["data_origin"] == "snapshot"


def test_bad_option_names_file_and_index(tmp_path):
    p = write(tmp_path, [option(), option(price={"amount": 1, "currency": "USD"})])
    with pytest.raises(FixtureError, match=r"f\.json: option 1: .*plausible range"):
        load(p)


def test_source_host_must_be_allowed(tmp_path):
    with pytest.raises(FixtureError, match="allowlist"):
        load(write(tmp_path, [option(source_url="https://other.example/x")]))


def test_empty_config_fails_closed(tmp_path):
    with pytest.raises(FixtureError):
        load_fixture_options(write(tmp_path, [option()]), now=NOW)


@pytest.mark.parametrize("bad", ["[]", "{}", '{"options": "x", "collected_at": "x"}', "not json"])
def test_bad_structure(tmp_path, bad):
    p = tmp_path / "f.json"
    p.write_text(bad)
    with pytest.raises(FixtureError):
        load(p)


def test_missing_collected_at(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"options": [option()]}))
    with pytest.raises(FixtureError, match="collected_at"):
        load(p)


def test_api_key_in_fixture_is_rejected(tmp_path):
    p = write(tmp_path, [option(description="from https://api.example/x?apiKey=abc123")])
    with pytest.raises(FixtureError, match=r"possible API key in \$\.options\[0\]\.description"):
        load(p)


def test_redacted_key_is_fine(tmp_path):
    load(write(tmp_path, [option(description="https://api.example/x?apiKey=REDACTED")]))


def test_find_secrets_walks_nested_data():
    data = {"a": [{"u": "https://x/?token=zzz"}], "b": "ok?keyword=1"}
    assert find_secrets(data) == ["$.a[0].u"]


def test_load_dir_in_name_order(tmp_path):
    write(tmp_path, [option(title="B")], name="b.json")
    write(tmp_path, [option(title="A")], name="a.json")
    assert [o.title for o in load_fixture_dir(tmp_path, source_hosts=HOSTS, now=NOW)] == ["A", "B"]
