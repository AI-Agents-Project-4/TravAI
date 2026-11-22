"""Synthetic test data: deterministic, clearly labeled, schema-valid, and free of recorded data. No network, no keys."""
import json
import os
import re
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research import agent, core, sandbox, sources, synthetic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def synth_mode(monkeypatch):
    monkeypatch.setattr(sandbox, "_default", sandbox.Store.generated())
    monkeypatch.setattr(sandbox, "MISSES", os.devnull)
    core.set_data_mode("sandbox")
    def no_network(*a, **k):
        raise AssertionError("synthetic mode must not call the network")
    monkeypatch.setattr(core, "http", no_network)
    monkeypatch.setattr(sources, "http", no_network)
    yield
    core.set_data_mode(None)


def ctx():
    return agent.Ctx({"origin": "DEN", "travelers": 2, "currency": "USD", "budget": 5000}, False, datetime.now(timezone.utc))


def pp(route, dep="2027-06-10", ret="2027-06-17", adults=1):
    r = synthetic.flights(*route, dep, ret, adults)
    return sorted(i["price"]["amount"] for i in r["itineraries"])[len(r["itineraries"]) // 2]


def test_same_request_gives_the_same_response_and_different_requests_differ():
    a = synthetic.flights("DEN", "FCO", "2027-06-10", "2027-06-15", 2)
    assert a == synthetic.flights("DEN", "FCO", "2027-06-10", "2027-06-15", 2)
    assert a != synthetic.flights("DEN", "FCO", "2027-06-11", "2027-06-15", 2)
    h = synthetic.hotels("lisbon", "2027-06-10", "2027-06-15", 2, "USD", lambda a, b: 1.0)
    assert h == synthetic.hotels("lisbon", "2027-06-10", "2027-06-15", 2, "USD", lambda a, b: 1.0)


def test_every_date_and_party_size_is_covered_unlike_recordings():
    for dep, ret, n in [("2027-01-15", "2027-01-22", 1), ("2027-09-30", "2027-10-12", 4), ("2027-11-01", "2027-11-03", 3)]:
        assert synthetic.flights("DEN", "LIS", dep, ret, n)["itineraries"]
    assert synthetic.flights("DEN", "LIS", "2027-06-10", None, 2)["itineraries"]   # one-way


def test_unknown_airport_or_city_has_no_answer():
    assert synthetic.flights("DEN", "ZZZ", "2027-06-10", "2027-06-15", 1) is None
    assert synthetic.flights("DEN", "DEN", "2027-06-10", "2027-06-15", 1) is None
    assert synthetic.hotels("atlantis", "2027-06-10", "2027-06-15", 2, "USD", lambda a, b: 1.0) is None


def test_prices_grow_with_distance_and_one_way_is_cheaper():
    assert pp(("DEN", "LAX")) < pp(("DEN", "LIS")) < pp(("DEN", "BKK"))
    rt = synthetic.flights("DEN", "NBO", "2027-06-10", "2027-06-17", 1)    # a route never recorded: uses the distance fit
    ow = synthetic.flights("DEN", "NBO", "2027-06-10", None, 1)
    assert min(i["price"]["amount"] for i in ow["itineraries"]) < min(i["price"]["amount"] for i in rt["itineraries"])


def test_party_prices_are_totals():
    one = [i["price"]["amount"] for i in synthetic.flights("DEN", "LIS", "2027-06-10", "2027-06-17", 1)["itineraries"]]
    four = [i["price"]["amount"] for i in synthetic.flights("DEN", "LIS", "2027-06-10", "2027-06-17", 4)["itineraries"]]
    assert 3 * sum(one) / len(one) < sum(four) / len(four) < 5 * sum(one) / len(one)


def test_everything_generated_is_visibly_synthetic():
    f = synthetic.flights("DEN", "FCO", "2027-06-10", "2027-06-15", 2)
    for it in f["itineraries"]:
        assert it["ignav_id"].startswith("synthetic-") and it["price"]["status"] == "synthetic"
        for leg in (it["outbound"], it["inbound"]):
            assert leg["carrier"].startswith("Synthetic Air")
    h = synthetic.hotels("rome", "2027-06-10", "2027-06-15", 2, "USD", lambda a, b: 1.0)
    for p in h["properties"]:
        assert re.fullmatch(r"Synthetic Hotel \d{4}", p["name"]) and p["property_token"].startswith("synthetic-")
        assert "link" not in p


def test_currency_conversion_rounds_up_for_hotels():
    usd = synthetic.hotels("rome", "2027-06-10", "2027-06-15", 2, "USD", lambda a, b: 1.0)["properties"][0]["rate_per_night"]["extracted_lowest"]
    eur = synthetic.hotels("rome", "2027-06-10", "2027-06-15", 2, "EUR", lambda a, b: 0.5)["properties"][0]["rate_per_night"]["extracted_lowest"]
    assert eur < usd and isinstance(eur, int)


def test_sandbox_returns_synthetic_as_estimates_with_no_real_looking_links(synth_mode):
    c = ctx()
    flights = agent._search_flights(c, "DEN", "FCO", "2027-06-10", "2027-06-15", "round_trip", 3)
    assert flights
    for f in flights:
        assert f["price"]["price_type"] == "estimate" and "Synthetic test data" in f["price"]["estimate_method"]
        assert f["confidence"]["level"] == "low" and f["confidence"]["verified"] is False
        assert f["source"]["provider"] == "synthetic" and f["source"]["url"].startswith("https://synthetic.invalid/")
    from datetime import date as d
    hotels = agent.lodging_step(c, [{"city": "Rome"}], d(2027, 6, 10), [5])
    assert hotels
    for h in hotels:
        assert h["price"]["price_type"] == "estimate" and h["source"]["provider"] == "synthetic"
        assert h["source"]["url"].startswith("https://synthetic.invalid/") and h["confidence"]["level"] == "low"


def test_synthetic_output_is_schema_valid(synth_mode):
    from datetime import date as d
    c = ctx()
    out = agent._empty(c, "ok", "synthetic-test")
    out["flights"] = agent._search_flights(c, "DEN", "FCO", "2027-06-10", "2027-06-15", "round_trip", 3)
    out["lodging"] = agent.lodging_step(c, [{"city": "Rome"}], d(2027, 6, 10), [5])
    errs = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:100]}" for e in agent.VALIDATOR.iter_errors(out)]
    assert errs == []


def test_unmatched_search_is_a_gap_not_made_up_data(synth_mode):
    c = ctx()
    assert agent._search_flights(c, "DEN", "ZZZ", "2027-06-10", "2027-06-15", "round_trip", 3) == []
    assert any(g["category"] == "flights" for g in c.gaps)


def test_default_store_uses_synthetic_when_no_recordings_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sandbox, "_default", None)
    monkeypatch.delenv("TRAVAI_SANDBOX_DATA", raising=False)
    assert sandbox.default_store().synthetic is True
    monkeypatch.setattr(sandbox, "_default", None)
    monkeypatch.setenv("TRAVAI_SANDBOX_DATA", "recorded")
    assert sandbox.default_store().synthetic is False


def test_params_file_holds_only_aggregates():
    txt = open(synthetic.PARAMS_PATH, encoding="utf-8").read()
    p = json.loads(txt)
    assert set(p) == {"about", "flights", "hotels", "airports"}
    assert all(set(v) == {"mu", "sigma", "dist_km"} for v in p["flights"]["routes"].values())
    assert all("name" not in c and "link" not in c for c in p["hotels"]["cities"].values())
    assert "ignav_id" not in txt and "property_token" not in txt


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "sandbox_data", "hotels.jsonl")), reason="recorded data is not in this checkout")
def test_nothing_recorded_leaks_into_params_or_output():
    rec_hotels = [json.loads(l) for l in open(os.path.join(ROOT, "sandbox_data", "hotels.jsonl"), encoding="utf-8")]
    names = {pr["name"] for r in rec_hotels for pr in r["properties"] if len(pr["name"]) > 6}
    rec_ids = {i["ignav_id"] for l in open(os.path.join(ROOT, "sandbox_data", "flights.jsonl"), encoding="utf-8")
               for i in json.loads(l)["itineraries"]}
    blob = open(synthetic.PARAMS_PATH, encoding="utf-8").read()
    blob += json.dumps([synthetic.hotels(k, "2027-06-10", "2027-06-15", 2, "USD", lambda a, b: 1.0)
                        for k in synthetic.params()["hotels"]["cities"]])
    blob += json.dumps([synthetic.flights("DEN", "LIS", f"2027-0{m}-10", f"2027-0{m}-17", 2) for m in range(1, 9)])
    # whole-value matches (JSON-quoted): a real name like "Hotel 31" is a harmless substring of "Synthetic Hotel 3123"
    assert not [n for n in names if json.dumps(n) in blob]
    assert not [i for i in rec_ids if i in blob]
