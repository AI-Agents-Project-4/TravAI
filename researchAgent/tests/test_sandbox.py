"""Sandbox mode: nearest-match lookup over recorded data. Hand-made data, no network, no keys."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research import agent, core, sandbox, sources  # noqa: E402


def seg(a, b, day):
    return {"marketing_carrier_code": "AA", "flight_number": "1", "operating_carrier_name": "American", "departure_airport": a,
            "arrival_airport": b, "departure_time_local": f"{day}T08:00:00", "arrival_time_local": f"{day}T12:00:00"}


def itin(i, amount, out_day, back_day=None):
    it = {"ignav_id": i, "price": {"amount": amount, "currency": "USD"}, "cabin_class": "economy",
          "outbound": {"duration_minutes": 240, "segments": [seg("DEN", "LIS", out_day)]}}
    if back_day:
        it["inbound"] = {"duration_minutes": 240, "segments": [seg("LIS", "DEN", back_day)]}
    return it


def flight_row(dep, ret, adults, amount, saved="2026-11-22T10:00:00Z", origin="DEN", dest="LIS"):
    return {"origin": origin, "destination": dest, "departure_date": dep, "return_date": ret, "adults": adults,
            "saved_at": saved, "observed_at": saved, "itineraries": [itin("fare1", amount, dep, ret)]}


def hotel_row(city, cin, cout, adults, cur, night, total=None, saved="2026-11-22T10:00:00Z"):
    p = {"name": "Hotel A", "type": "hotel", "property_token": "tok", "gps_coordinates": {"latitude": 1.0, "longitude": 2.0},
         "rate_per_night": {"extracted_lowest": night}, "total_rate": {"extracted_lowest": total or night * 7}}
    return {"city": city, "check_in": cin, "check_out": cout, "adults": adults, "currency": cur, "saved_at": saved, "properties": [p]}


@pytest.fixture
def store():
    return sandbox.Store(
        flights=[flight_row("2027-04-24", "2027-05-01", 3, 2986.0),
                 flight_row("2027-09-05", None, 2, 600.0)],
        hotels=[hotel_row("Lisbon", "2027-04-24", "2027-05-01", 2, "USD", 100),
                hotel_row("Sao Paulo", "2027-11-05", "2027-11-15", 2, "USD", 60, 600)],
        bookings={"fare1": {"ignav_id": "fare1", "saved_at": "x", "response": {"booking_options": []}}})


def test_exact_flight_is_returned_unchanged(store):
    r = sandbox.find_flights("DEN", "LIS", "2027-04-24", "2027-05-01", 3, store)
    assert r["itineraries"][0]["price"]["amount"] == 2986.0
    sb = r["itineraries"][0]["_sandbox"]
    assert sb["price_type"] == "live_quote" and r["_sandbox"]["exact"]


def test_nearby_date_is_an_estimate_and_keeps_original_flight_times(store):
    r = sandbox.find_flights("DEN", "LIS", "2027-05-02", "2027-05-09", 3, store)
    it = r["itineraries"][0]
    assert it["_sandbox"]["price_type"] == "estimate" and "recorded for 2027-04-24" in it["_sandbox"]["method"]
    assert it["outbound"]["segments"][0]["departure_time_local"].startswith("2027-04-24")  # never shifted to fake a date


def test_party_size_scaling_rounds_up(store):
    r = sandbox.find_flights("DEN", "LIS", "2027-04-24", "2027-05-01", 2, store)
    assert r["itineraries"][0]["price"]["amount"] == math.ceil(2986.0 / 3 * 2)
    assert r["itineraries"][0]["_sandbox"]["price_type"] == "estimate"


def test_too_far_or_unknown_route_has_no_answer(store):
    assert sandbox.find_flights("DEN", "LIS", "2027-07-01", "2027-07-08", 3, store) is None   # 2+ months away
    assert sandbox.find_flights("DEN", "ROM", "2027-04-24", "2027-05-01", 3, store) is None   # route not recorded
    assert sandbox.find_flights("DEN", "LIS", "2027-04-24", None, 3, store) is None            # one-way never served from a round trip


def test_one_way_matches_one_way(store):
    assert sandbox.find_flights("DEN", "LIS", "2027-09-05", None, 2, store)["itineraries"][0]["price"]["amount"] == 600.0


def test_lookup_does_not_mutate_the_recording(store):
    sandbox.find_flights("DEN", "LIS", "2027-04-24", "2027-05-01", 1, store)
    assert store.flights[0]["itineraries"][0]["price"]["amount"] == 2986.0


def test_hotel_exact_keeps_recorded_totals(store):
    r = sandbox.find_hotels("Lisbon hotels", "2027-04-24", "2027-05-01", 2, "USD", lambda a, b: 1.0, store)
    assert r["_sandbox"]["exact"] and r["properties"][0]["total_rate"]["extracted_lowest"] == 700


def test_hotel_other_dates_recomputes_total_and_marks_estimate(store):
    r = sandbox.find_hotels("lisbon", "2027-06-01", "2027-06-04", 2, "USD", lambda a, b: 1.0, store)
    assert r["_sandbox"]["price_type"] == "estimate"
    assert r["properties"][0]["total_rate"]["extracted_lowest"] == 300  # 100/night x 3 nights


def test_hotel_currency_conversion_rounds_up(store):
    r = sandbox.find_hotels("Lisbon", "2027-04-24", "2027-05-01", 2, "EUR", lambda a, b: 0.915, store)
    assert r["properties"][0]["rate_per_night"]["extracted_lowest"] == math.ceil(100 * 0.915)
    assert "converted from USD" in r["_sandbox"]["method"]


def test_city_names_are_normalized(store):
    assert sandbox.norm_city("São Paulo hotels") == "sao paulo"
    assert sandbox.find_hotels("São Paulo", "2027-11-05", "2027-11-15", 2, "USD", lambda a, b: 1.0, store)
    assert sandbox.norm_city("NYC") == "new york city"


def test_hotel_with_no_close_dates_has_no_answer(store):
    assert sandbox.find_hotels("Lisbon", "2028-06-01", "2028-06-05", 2, "USD", lambda a, b: 1.0, store) is None


@pytest.fixture
def sandbox_mode(store, monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "_default", store)
    monkeypatch.setattr(sandbox, "MISSES", str(tmp_path / "misses.jsonl"))
    core.set_data_mode("sandbox")
    def no_network(*a, **k):
        raise AssertionError("sandbox mode must not call the network")
    monkeypatch.setattr(core, "http", no_network)
    monkeypatch.setattr(sources, "http", no_network)
    yield tmp_path / "misses.jsonl"
    core.set_data_mode(None)


def ctx():
    from datetime import datetime, timezone
    return agent.Ctx({"origin": "DEN", "travelers": 3, "currency": "USD"}, False, datetime.now(timezone.utc))


def test_agent_flight_step_labels_estimates_and_keeps_retrieved_at(sandbox_mode):
    c = ctx()
    out = agent._search_flights(c, "DEN", "LIS", "2027-05-02", "2027-05-09", "round_trip", 3)
    f = out[0]
    assert f["price"]["price_type"] == "estimate" and f["price"]["estimate_method"]
    assert f["price"]["retrieved_at"] == "2026-11-22T10:00:00Z"        # the recording time, not "now"
    assert f["confidence"]["level"] == "low" and f["source"]["provider"] == "google_flights_search"


def test_agent_flight_step_exact_uses_recorded_booking_lookup(sandbox_mode):
    out = agent._search_flights(ctx(), "DEN", "LIS", "2027-04-24", "2027-05-01", "round_trip", 3)
    assert out[0]["price"]["price_type"] == "live_quote" and out[0]["confidence"]["verified"] is False


def test_agent_records_a_gap_and_a_miss_when_nothing_is_close(sandbox_mode):
    c = ctx()
    assert agent._search_flights(c, "DEN", "ROM", "2027-04-24", "2027-05-01", "round_trip", 3) == []
    assert any(g["category"] == "flights" for g in c.gaps)
    assert '"destination": "ROM"' in sandbox_mode.read_text()


def test_agent_lodging_step_marks_estimates(sandbox_mode):
    from datetime import date
    c = ctx()
    stops = [{"city": "Lisbon"}]
    out = agent.lodging_step(c, stops, date(2027, 6, 1), [3])
    assert out and out[0]["price"]["price_type"] == "estimate" and out[0]["confidence"]["level"] == "low"
    assert out[0]["price"]["retrieved_at"] == "2026-11-22T10:00:00Z"


def test_set_data_mode_rejects_unknown_values():
    with pytest.raises(ValueError):
        core.set_data_mode("fake")
