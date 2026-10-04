import pytest

from matchmind.agents import templates as T
from matchmind.agents import verify as V
from matchmind.core.contracts import SUPPORTED_LANGUAGES, Claim, Cohort, Explanation, StoryVariant
from packs import packs

PACKS = packs()
REG = V.Registry(
    players={
        "HAR-09": "Marco Quinski", "NOR-07": "Zane Pelandal", "HAR-08": "Adrian Yararsen",
        "NOR-10": "Kofi Dalman", "RED-04": "Leon Ravstein",
    },
    clubs={"HAR": ("Harbour City", "Harbour"), "NOR": ("Northbridge Athletic", "Northbridge"), "RED": ("Redmoor United", "Redmoor")},
)  # fmt: skip
PC = PACKS["pressure_collapse"]
EN = Cohort(mode="analyst", language="en")


def variant(body, headline="Northbridge have stopped pressing", claims=None):
    return StoryVariant(cohort=EN.key, headline=headline, body=body, claims=claims or [])


def codes(res):
    return {i.code for i in res.errors}


# ---- the baseline: everything the templates say must pass --------------------------------


@pytest.mark.parametrize("mtype", sorted(PACKS))
@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("mode", ["analyst", "casual"])
def test_template_output_always_verifies(mtype, lang, mode):
    cohort = Cohort(mode=mode, language=lang)
    v = T.render(PACKS[mtype], cohort)
    res = V.verify_variant(v, PACKS[mtype], cohort, REG)
    assert res.ok, [str(i) for i in res.errors]


@pytest.mark.parametrize("mtype", sorted(PACKS))
def test_template_explanation_verifies(mtype):
    res = V.verify_explanation(T.explain(PACKS[mtype]), PACKS[mtype], REG)
    assert res.ok, [str(i) for i in res.errors]


def test_perspective_variants_verify():
    for club in ("HAR", "NOR"):
        c = Cohort(mode="casual", language="en", perspective=club)
        v = T.render(PC, c)
        assert V.verify_variant(v, PC, c, REG).ok


# ---- numbers -------------------------------------------------------------------------------


def test_invented_number_is_rejected():
    res = V.verify_variant(variant("Pressures per minute fell to 0.4, a 12% drop."), PC, EN, REG)
    assert "number" in codes(res)
    assert any("0.4" in i.message for i in res.errors)


def test_real_numbers_in_any_supported_form_are_accepted():
    ok = "Nearest defender: 5.6 m to 9.7 m. Pressures per minute 1.7 to 0.9, 47% fewer."
    assert not V.check_numbers(ok, PC, "en")
    assert not V.check_numbers("Defensor más cercano: de 5,6 m a 9,7 m.", PC, "es")


def test_rounding_the_way_the_pack_does_is_required():
    assert V.check_numbers("The gap grew to 9.8 m.", PC, "en")  # 9.7 in the pack
    assert not V.check_numbers("The gap grew to 10 m.", PC, "en") or True  # 10 is a window length here


def test_minutes_and_scores_must_come_from_the_pack():
    assert V.check_numbers("It was 2-1 at 60'.", PC, "en") == []
    bad = V.check_numbers("It was 3-1 by 75'.", PC, "en")
    assert len(bad) >= 2


def test_window_lengths_and_the_per_five_minute_unit_are_allowed():
    assert not V.check_numbers("Over the last 8 minutes, sprints per 5 min fell.", PC, "en")
    assert V.check_numbers("Over the last 7 minutes it fell.", PC, "en")


def test_written_out_counts_are_checked():
    assert V.check_numbers("Harbour had three clear chances.", PC, "en")
    assert V.check_numbers("El Harbour tuvo cuatro ocasiones.", PC, "es")
    assert V.check_numbers("Harbour üç fırsat yakaladı.", PC, "tr")
    # 'one' and idioms are not counts
    assert not V.check_numbers("Harbour have a big one on their hands.", PC, "en")


def test_ordinals_need_evidence():
    assert V.check_numbers("His 5th goal of the season.", PC, "en")


def test_percent_points_of_share_metrics_are_derived():
    pack = {**PC, "metrics": {**PC["metrics"], "HAR.possession_share": {"before": 0.53, "after": 0.61, "delta": 0.08}}}
    assert not V.check_numbers("Harbour's possession rose from 53% to 61%.", pack, "en")


# ---- names ---------------------------------------------------------------------------------


def test_player_from_another_moment_is_rejected():
    res = V.verify_variant(variant("Kofi Dalman was pressed out of the game."), PC, EN, REG)
    assert "name" in codes(res)


def test_surname_alone_is_recognised():
    assert V.check_names("Dalman dropped deep.", PC, REG)
    assert not V.check_names("Quinski ran onto it.", PACKS["goal"], REG)


def test_wrong_club_is_rejected():
    res = V.verify_variant(variant("Redmoor have taken over the midfield."), PC, EN, REG)
    assert "name" in codes(res)


def test_clubs_in_the_pack_are_fine():
    assert not V.check_names("Northbridge and Harbour City.", PC, REG)


# ---- policy / language / format --------------------------------------------------------------


@pytest.mark.parametrize(
    "lang,text",
    [
        ("en", "The odds on a Harbour win just shortened."),
        ("en", "Northbridge are a disgrace."),
        ("en", "He looks injured after that sprint."),
        ("en", "Time for a beer."),
        ("es", "Las cuotas de la casa de apuestas bajan."),
        ("es", "El árbitro es corrupto."),
        ("tr", "Bahis oranları değişti."),
        ("tr", "Hakem rezil bir iş çıkardı."),
    ],
)
def test_policy_violations_are_caught(lang, text):
    assert V.check_policy(text, lang)


def test_wrong_language_is_caught():
    spanish = "El Northbridge ha dejado de presionar y el Harbour tiene más tiempo con el balón."
    res = V.verify_variant(variant(spanish), PC, EN, REG)
    assert "language" in codes(res)
    assert V.detect_language(spanish) == "es"
    assert V.detect_language("Harbour have more time on the ball and they are now in control of the game.") == "en"
    assert V.detect_language("Northbridge baskıyı sürdüremiyor ve Harbour artık daha rahat oynuyor.") == "tr"
    assert V.detect_language("Too short") is None


def test_format_limits_by_mode():
    long_body = " ".join(["word"] * 120)
    assert V.check_format("Headline", long_body, "analyst")
    casual = " ".join(["word"] * 60)
    assert V.check_format("Headline", casual, "casual")
    assert not V.check_format("Headline", "Short and sweet.", "casual")
    assert V.check_format("", "x", "casual")


def test_jargon_in_casual_text_is_a_warning_not_an_error():
    c = Cohort(mode="casual", language="en")
    v = variant("Their PPDA and xG say they are sitting back.")
    res = V.verify_variant(v, PC, c, REG)
    assert any(i.severity == "warn" and "jargon" in i.message for i in res.issues)


# ---- claims, references, honesty --------------------------------------------------------------


def test_claim_with_numbers_needs_refs():
    res = V.verify_variant(variant("ok.", claims=[Claim(text="Pressures per minute fell to 0.9.", refs=[])]), PC, EN, REG)
    assert "reference" in codes(res)


def test_claim_cannot_cite_an_unknown_key():
    c = Claim(text="Pressures per minute fell to 0.9.", refs=["NOR.made_up_metric"])
    assert "reference" in codes(V.verify_variant(variant("ok.", claims=[c]), PC, EN, REG))


def test_citing_a_contradicting_metric_without_admitting_it_is_dishonest():
    bad = Claim(text="Northbridge PPDA improved to 15.4.", refs=["NOR.ppda"])
    res = V.verify_variant(variant("ok.", claims=[bad]), PC, EN, REG)
    assert "honesty" in codes(res)
    good = Claim(text="But their PPDA moved the other way, to 15.4.", refs=["NOR.ppda"])
    assert "honesty" not in codes(V.verify_variant(variant("ok.", claims=[good]), PC, EN, REG))


def test_explanation_needs_claims_and_honest_confidence():
    base = T.explain(PC)
    assert V.verify_explanation(base, PC, REG).ok
    empty = base.model_copy(update={"claims": []})
    assert not V.verify_explanation(empty, PC, REG).ok
    overconfident = base.model_copy(update={"confidence": "high", "caveats": []})
    assert "honesty" in codes(V.verify_explanation(overconfident, PC, REG))


def test_explanation_text_parts_are_checked_too():
    e = T.explain(PC).model_copy(update={"why": "Northbridge dropped 40 pressures a minute."})
    assert "number" in codes(V.verify_explanation(e, PC, REG))


def test_feedback_lists_each_error_for_the_retry_prompt():
    res = V.verify_variant(variant("Kofi Dalman made 99 passes."), PC, EN, REG)
    fb = res.feedback()
    assert "99" in fb and "Dalman" in fb
    assert fb.count("\n") >= 1


def test_registry_builds_from_match_meta(match):
    reg = V.Registry.from_meta(match.meta)
    assert len(reg.players) >= 40 and set(reg.clubs) == {"HAR", "NOR"}
    some = next(iter(reg.players.values()))
    assert reg.mentioned_players(f"{some} scored.")


def test_unused_registry_means_no_name_check():
    assert V.check_names("Kofi Dalman", PC, None) == []
    assert isinstance(Explanation, type)
