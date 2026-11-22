import json, os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jsonschema import Draft202012Validator
from research.pricing import (WikivoyageIndex, name_score, osm_fee_price, parse_listings, parse_price_text, place_names,
                              price_for)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), "..", "schema", "research_output.schema.json")))
PRICE_VALIDATOR = Draft202012Validator({**SCHEMA["$defs"]["price"], "$defs": SCHEMA["$defs"]})
FX = lambda a, b: {"JPY": 0.0065}[a]


@pytest.mark.parametrize("text,amount,cur,ambiguous", [
    ("free", 0, None, False), ("Free", 0, None, False), ("&yen;600", 600, "JPY", False),
    ("1,500 yen", 1500, "JPY", False), ("Adults 2000円", 2000, "JPY", False), ("$12", 12, "USD", False),
    ("¥1,000 adult, ¥500 child", 1000, "JPY", True),      # highest amount wins
    ("&yen;4000–&yen;20,000", 20000, "JPY", True),
    ("Free; observatory ¥600", 600, "JPY", True),
    ("600", 600, None, True),                              # no currency: flagged
])
def test_parse_price_text(text, amount, cur, ambiguous):
    p = parse_price_text(text)
    assert (p.amount, p.currency, p.ambiguous) == (amount, cur, ambiguous)


@pytest.mark.parametrize("text", ["", "   ", "varies", "see website"])
def test_parse_price_text_none(text):
    assert parse_price_text(text) is None


def test_name_score_handles_macrons_and_generic_words():
    assert name_score("Hōzōmon", "Hozomon") == 1.0
    assert name_score("Senso-ji Temple", "Senso-ji") == 1.0
    assert name_score("Kabuki Inari Shrine", "Kabukiza Theater") < 0.75


def test_name_made_only_of_generic_words_still_matches():
    assert name_score("Tokyo National Museum", "Tokyo National Museum") == 1.0
    assert name_score("Tokyo National Museum", "Tokyo National Museum of Modern Art") < 0.9


def load_places():
    seen, out = set(), []
    for fn in ("geoapify_places_tokyo_tourism.json", "geoapify_places_tokyo_tourism_en.json"):
        for f in json.load(open(os.path.join(FIX, fn)))["features"]:
            p = f["properties"]
            if p["place_id"] not in seen:
                seen.add(p["place_id"]); out.append(p)
    return out


def test_osm_fee_no_gives_zero_price_with_osm_source():
    props = next(p for p in load_places() if (p["datasource"]["raw"].get("fee") == "no"))
    r = osm_fee_price(props, retrieved_at="2026-11-22T00:00:00Z")
    assert r["price"]["amount"] == 0 and r["price"]["price_type"] == "published_rate"
    assert r["source"]["url"].startswith("https://www.openstreetmap.org/")
    assert not list(PRICE_VALIDATOR.iter_errors(r["price"]))


def test_osm_fee_yes_has_no_amount_so_returns_none():
    props = next(p for p in load_places() if (p["datasource"]["raw"].get("fee") == "yes"))
    assert osm_fee_price(props) is None


SAMPLE = """
==See==
{{see
| name=Miraikan | alt=未来館 | url=https://x.example | lat=35.619 | long=139.776
| price=&yen;630 | content=Science museum.
}}
{{see | name=Giant Gundam robot | lat=35.62 | long=139.77 | price=free | content=Statue}}
{{do | name=Mystery Spa | price= | content=No price given}}
{{eat | name=Ramen [[Shop]] | alt=ラーメン | price=[[Japanese yen|¥]]900 }}
"""


def test_parse_listings_handles_multiline_links_and_missing_price():
    ls = {l.name: l for l in parse_listings(SAMPLE, "Tokyo/Odaiba")}
    assert set(ls) == {"Miraikan", "Giant Gundam robot", "Mystery Spa", "Ramen Shop"}
    assert ls["Miraikan"].lat == 35.619 and ls["Mystery Spa"].price_text == ""
    assert parse_price_text(ls["Ramen Shop"].price_text).amount == 900


def fake_index(tmp_path):
    return WikivoyageIndex("Tokyo", cache_dir=str(tmp_path), fetch_many=lambda ts: {t: SAMPLE for t in ts})


def test_wikivoyage_price_converts_currency_and_cites_page(tmp_path):
    (tmp_path / "_index_Tokyo.json").write_text(json.dumps(["Tokyo/Odaiba"]))
    idx = fake_index(tmp_path).load()
    props = {"name": "未来館", "lat": 35.6191, "lon": 139.7761,
             "name_international": {"en": "Miraikan"}, "datasource": {"raw": {}}}
    r = price_for(props, idx, fx=FX, retrieved_at="2026-11-22T00:00:00Z")
    assert r["layer"] == "wikivoyage"
    assert r["price"]["amount"] == 630 and r["price"]["currency"] == "JPY"
    assert r["price"]["amount_normalized"] == pytest.approx(4.10, abs=0.01)
    assert r["source"]["url"] == "https://en.wikivoyage.org/wiki/Tokyo/Odaiba"
    assert not list(PRICE_VALIDATOR.iter_errors(r["price"]))


def test_no_match_or_no_price_returns_none_not_a_guess(tmp_path):
    (tmp_path / "_index_Tokyo.json").write_text(json.dumps(["Tokyo/Odaiba"]))
    idx = fake_index(tmp_path).load()
    unknown = {"name": "Somewhere Else", "lat": 35.0, "lon": 139.0, "datasource": {"raw": {}}}
    no_price = {"name": "Mystery Spa", "lat": 35.62, "lon": 139.77, "datasource": {"raw": {}}}
    assert price_for(unknown, idx, fx=FX) is None
    assert price_for(no_price, idx, fx=FX) is None


def test_bare_number_uses_local_currency_and_is_flagged(tmp_path):
    sample = "{{see | name=Tiny Shrine | lat=35.0 | long=139.0 | price=300}}"
    (tmp_path / "_index_Tokyo.json").write_text(json.dumps(["Tokyo/X"]))
    idx = WikivoyageIndex("Tokyo", cache_dir=str(tmp_path), fetch_many=lambda ts: {t: sample for t in ts}).load()
    props = {"name": "Tiny Shrine", "lat": 35.0, "lon": 139.0, "datasource": {"raw": {}}}
    assert price_for(props, idx, fx=FX) is None                       # unknown currency: refuse
    r = price_for(props, idx, fx=FX, local_currency="JPY")
    assert r["ambiguous"] and r["price"]["currency"] == "JPY"


@pytest.mark.skipif(not os.path.exists(os.path.join(FIX, "wikivoyage", "_index_Tokyo.json")), reason="Wikivoyage cache not built")
def test_real_tokyo_fixtures_no_false_positive_for_kabuki_inari():
    idx = WikivoyageIndex("Tokyo").load()
    for p in load_places():
        if "Kabuki Inari" in " ".join(place_names(p)):
            assert price_for(p, idx, fx=FX, local_currency="JPY") is None
