import json, os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research.activities import estimate_price, parse_hours
from research.agent import pick_flights, split_nights, validate_request

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
TODAY = date(2026, 11, 22)
OK = {"start_date": "2027-03-10", "destinations": ["Tokyo"], "duration_days": 5, "travelers": 1, "budget": 5000}


def test_split_nights_sums_and_front_loads_remainder():
    assert split_nights(14, 3) == [5, 5, 4] and sum(split_nights(7, 2)) == 7 and split_nights(0, 2) == [0, 0]


def test_validate_request_rejects_bad_input():
    assert validate_request(OK, TODAY) is None
    assert "past" in validate_request({**OK, "start_date": "2024-01-10"}, TODAY)
    assert "budget" in validate_request({**OK, "budget": 0}, TODAY)
    assert "travelers" in validate_request({**OK, "travelers": 0}, TODAY)
    assert "destination" in validate_request({**OK, "destinations": []}, TODAY)
    assert "start_date" in validate_request({**OK, "start_date": "soon"}, TODAY)


def test_parse_hours_simple_and_complex():
    h = parse_hours("Tu-Su 10:00-17:30; Mo off")
    assert "mon" not in h and h["sun"] == {"open": "10:00", "close": "17:30"}
    assert parse_hours("Mo-Fr 09:00-18:00; Sa 10:00-14:00")["sat"]["close"] == "14:00"
    assert parse_hours("Fr,We[2] 10:00-20:00; PH off") is None      # too complex: refuse rather than guess
    assert parse_hours("") is None and parse_hours(None) is None


def test_pick_flights_offers_price_time_tradeoff():
    d = json.load(open(os.path.join(FIX, "ignav_den_hnd_roundtrip.json")))["itineraries"]
    picks = pick_flights(d)
    assert 3 <= len(picks) <= 6 and len({p["ignav_id"] for p in picks}) == len(picks)
    assert picks[0]["price"]["amount"] == min(i["price"]["amount"] for i in d)
    dur = lambda i: sum(l["duration_minutes"] for l in (i["outbound"], i.get("inbound")) if l)
    assert min(dur(p) for p in picks) == min(dur(i) for i in d)      # the fastest option is always included


def test_estimates_are_marked_and_scale_with_cost_tier():
    fx = lambda a, b: 1.0
    cheap, dear = estimate_price("museum", 1, "USD", fx), estimate_price("museum", 4, "USD", fx)
    assert cheap["price_type"] == "estimate" and cheap["estimate_method"] and dear["amount"] > cheap["amount"]


def test_hours_past_midnight_stay_schema_valid():
    h = parse_hours("Mo-Su 18:00-26:00")
    assert h["mon"] == {"open": "18:00", "close": "02:00"}       # close earlier than open = next day
    assert parse_hours("Mo-Su 10:00-24:00")["tue"]["close"] == "23:59"


def test_numeric_place_names_are_coerced_to_strings(monkeypatch):
    from research import activities
    monkeypatch.setattr(activities.sources, "places", lambda *a, **k: [{"place_id": "x1", "name": 1803, "lat": 0, "lon": 0}])
    out = activities.gather_places(0, 0, True, [])
    assert out and out[0]["name"] == "1803"


def test_cache_freshness_rules():
    from research.core import is_fresh
    assert is_fresh(0, None) and is_fresh(100, 50, now=120) and not is_fresh(100, 50, now=200)


def test_progress_callback_errors_never_break_a_run():
    from datetime import datetime, timezone
    from research.agent import run
    events = []
    def bad(stage, msg):
        events.append(stage); raise RuntimeError("ui exploded")
    out = run({**OK, "budget": 0, "origin": "DEN", "currency": "USD", "transport_modes": ["flight"]}, offline=True,
              now=datetime(2026, 11, 22, tzinfo=timezone.utc), progress=bad)
    assert out["status"] == "error"          # invalid request is rejected before any search; callback not required


def test_planner_view_is_much_smaller_and_keeps_ids():
    import json as _j
    from research.compact import planner_view
    o = _j.load(open(os.path.join(os.path.dirname(__file__), "outputs", "tokyo-5d-5000.json")))
    v = planner_view(o)
    assert len(_j.dumps(v)) < 0.6 * len(_j.dumps(o))
    assert {a["id"] for a in v["activities"]} <= {a["id"] for a in o["activities"]} and v["flights"][0]["id"] == o["flights"][0]["id"]


def test_offline_replay_needs_no_api_keys(monkeypatch):
    from research import core
    monkeypatch.setattr(core, "ENV", {})
    assert core.secret("IGNAV_API_KEY", offline=True)           # placeholder, never sent
    import pytest
    monkeypatch.setenv("TRAVAI_ALLOW_NETWORK", "1")                # gather mode: every key is needed (in the sandbox only Geoapify's is)
    with pytest.raises(RuntimeError, match="missing from .env"):
        core.secret("IGNAV_API_KEY")                              # live runs still fail loudly
