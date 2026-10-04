import re

import pytest

from matchmind.agents import templates as T
from matchmind.core.contracts import SUPPORTED_LANGUAGES, Cohort, Explanation
from packs import packs

PACKS = packs()
NAMES = {"HAR-09": "Marco Quinski", "NOR-07": "Zane Pelandal", "HAR-08": "Adrian Yararsen"}


@pytest.mark.parametrize("mtype", sorted(PACKS))
@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("mode", ["analyst", "casual"])
def test_every_moment_type_renders_in_every_language_and_mode(mtype, lang, mode):
    v = T.render(PACKS[mtype], Cohort(mode=mode, language=lang))
    assert v.headline and v.body
    assert "{" not in v.headline + v.body, "unfilled placeholder"
    assert len(v.headline) <= 90 and len(v.body) <= 380
    assert v.claims, "text must come with claims the Verifier can check"
    assert v.cohort == f"{mode}/{lang}/neutral/-"


@pytest.mark.parametrize("mtype", sorted(PACKS))
def test_analyst_text_leads_with_numbers_and_casual_stays_light(mtype):
    a = T.render(PACKS[mtype], Cohort(mode="analyst", language="en"))
    c = T.render(PACKS[mtype], Cohort(mode="casual", language="en"))
    digits = lambda s: len(re.findall(r"\d", s))  # noqa: E731
    assert digits(a.body) >= digits(c.body)


def test_turkish_never_attaches_case_suffixes_to_numbers():
    """'1,3'den' is right for some numbers and wrong for others, so the templates avoid it."""
    for mtype, pack in PACKS.items():
        for mode in ("analyst", "casual"):
            v = T.render(pack, Cohort(mode=mode, language="tr"))
            assert not re.search(r"\d'[a-zçğıöşü]", v.headline + " " + v.body), (mtype, v.body)


def test_decimal_separator_follows_the_language():
    pack = PACKS["pressure_collapse"]
    en = T.render(pack, Cohort(mode="analyst", language="en")).body
    es = T.render(pack, Cohort(mode="analyst", language="es")).body
    tr = T.render(pack, Cohort(mode="analyst", language="tr")).body
    assert "5.6" in en and "9.7" in en
    assert "5,6" in es and "9,7" in es
    assert "5,6" in tr and "9,7" in tr


def test_club_perspective_changes_tone_not_facts():
    pack = PACKS["pressure_collapse"]
    neutral = T.render(pack, Cohort(mode="casual", language="en"))
    fan = T.render(pack, Cohort(mode="casual", language="en", perspective="HAR"))
    foe = T.render(pack, Cohort(mode="casual", language="en", perspective="NOR"))
    assert fan.body.startswith("Good news for Harbour.")
    assert foe.body.startswith("Worrying for Northbridge.")
    assert neutral.body in fan.body and neutral.body in foe.body
    # proper nouns keep their capital letter
    assert "Northbridge can't keep" in fan.body or "Northbridge" in fan.body
    assert not re.search(r"\bnorthbridge\b|\bharbour\b", fan.body + foe.body)


def test_perspective_is_ignored_for_analysts():
    pack = PACKS["goal"]
    a = T.render(pack, Cohort(mode="analyst", language="en", perspective="HAR"))
    b = T.render(pack, Cohort(mode="analyst", language="en"))
    assert a.body == b.body


@pytest.mark.parametrize("mtype", sorted(PACKS))
def test_club_tone_is_defined_for_both_clubs(mtype):
    tones = {T.club_tone(PACKS[mtype], c) for c in ("HAR", "NOR")}
    assert tones <= {"good", "bad", None}


def test_goal_tone_is_opposite_for_the_two_clubs():
    assert T.club_tone(PACKS["goal"], "HAR") == "good"
    assert T.club_tone(PACKS["goal"], "NOR") == "bad"
    assert T.club_tone(PACKS["red_card"], "NOR") == "bad"


@pytest.mark.parametrize("mtype", sorted(PACKS))
def test_template_explanation_is_grounded(mtype):
    e = T.explain(PACKS[mtype])
    assert isinstance(e, Explanation)
    assert e.what and e.why
    assert e.tactical_tag == T.TAGS[mtype]
    known = set(PACKS[mtype]["metrics"]) | set(PACKS[mtype]["eventIds"])
    for c in e.claims:
        assert set(c.refs) <= known


def test_mixed_evidence_is_admitted_in_caveats_and_lowers_confidence():
    e = T.explain(PACKS["pressure_collapse"])
    assert e.caveats and "ppda" in e.caveats[0]
    assert e.confidence in ("medium", "low")
    surge = T.explain(PACKS["goal"])
    assert not surge.caveats


def test_claims_cite_the_metrics_whose_numbers_they_use():
    v = T.render(PACKS["pressure_collapse"], Cohort(mode="analyst", language="en"))
    refs = {r for c in v.claims for r in c.refs}
    assert "NOR.nearest_defender_m" in refs and "NOR.pressures_per_min" in refs


def test_unknown_moment_type_is_a_clear_error():
    with pytest.raises(KeyError):
        T.render({**PACKS["goal"], "type": "mystery"}, Cohort())


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_fact_cards(lang):
    facts = [
        {"type": "shot_card", "player": "HAR-09", "values": {"xg": 0.31, "shotSpeedKmh": 88.2, "distanceM": 14.3, "outcome": "saved"}},
        {"type": "pass_card", "player": "HAR-08", "values": {"difficulty": 7.4, "distanceM": 31.0, "ballSpeedKmh": 71.0, "passType": "through", "receiver": "HAR-09"}},
        {"type": "speed_badge", "player": "NOR-07", "values": {"peakKmh": 33.4}},
        {"type": "distance_badge", "player": "HAR-08", "values": {"km": 8.0}},
        {"type": "card_event", "player": "NOR-07", "values": {"card": "yellow"}},
        {"type": "substitution", "player": "HAR-09", "values": {"on": "HAR-09", "off": "NOR-07"}},
    ]
    kinds = []
    for f in facts:
        card = T.fact_card(f, lang, NAMES)
        assert card is not None
        headline, body, chips, kind = card
        assert headline
        kinds.append(kind)
    assert set(kinds) <= {"shot_card", "pass_card", "speed_badge", "player_tag", "card_badge", "stat_card"}
    assert T.fact_card({"type": "mystery", "values": {}}, lang, NAMES) is None


def test_number_formatting():
    assert T.num(51.0) == "51" and T.num(9.7) == "9.7" and T.num(0.09, digits=2) == "0.09"
    assert T.num(9.7, "es") == "9,7" and T.num(None) == "?"
    assert T.num(0.3, digits=2) == "0.30"
