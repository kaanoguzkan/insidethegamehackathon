"""The rule-based agents around the fast path: Repairer, Cache and Router."""

from __future__ import annotations

import json

import pytest

from matchmind.agents import repair, router, templates, verify
from matchmind.agents.cache import BeatCache, Cached
from matchmind.core.contracts import BeatChoice, Claim, Cohort, StoryVariant
from matchmind.core.paths import replays_dir

CASUAL = Cohort(mode="casual", language="en")


@pytest.fixture(scope="module")
def goal_pack() -> dict:
    moments = json.loads((replays_dir() / "red-card-drama" / "moments.json").read_text())
    moments = moments if isinstance(moments, list) else moments["moments"]
    return next(m for m in moments if m["type"] == "goal")


def good(pack: dict) -> StoryVariant:
    return templates.render(pack, CASUAL).model_copy(update={"cohort": CASUAL.key, "claims": []})


def test_the_repairer_cuts_out_a_sentence_with_a_banned_word_and_keeps_the_rest(goal_pack):
    v = good(goal_pack)
    bad = v.model_copy(update={"body": f"{v.body} The odds of a comeback are slim."})
    assert not verify.verify_variant(bad, goal_pack, CASUAL).ok
    fixed = repair.repair(bad, goal_pack, CASUAL)
    assert fixed is not None and "odds" not in fixed.variant.body.lower() and v.body in fixed.variant.body
    assert verify.verify_variant(fixed.variant, goal_pack, CASUAL).ok and fixed.actions


def test_the_repairer_cuts_out_an_invented_figure(goal_pack):
    v = good(goal_pack)
    bad = v.model_copy(update={"body": f"{v.body} He has scored 87 goals this season."})
    fixed = repair.repair(bad, goal_pack, CASUAL)
    assert fixed is not None and "87" not in fixed.variant.body


def test_the_repairer_replaces_a_bad_headline_and_drops_a_bad_claim(goal_pack):
    v = good(goal_pack)
    bad = v.model_copy(update={"headline": "Betting odds swing", "claims": [Claim(text="Nonsense.", refs=["not.a.key"])]})
    fixed = repair.repair(bad, goal_pack, CASUAL)
    assert fixed is not None and "odds" not in fixed.variant.headline.lower() and fixed.variant.claims == []


def test_the_repairer_gives_up_when_nothing_is_left_or_nothing_needed_mending(goal_pack):
    v = good(goal_pack)
    assert repair.repair(v.model_copy(update={"body": "Rafael Brandmont scored 99 goals."}), goal_pack, CASUAL) is None
    assert repair.repair(v, goal_pack, CASUAL) is None, "a variant that already passes has nothing to repair"


def test_the_cache_returns_model_text_only_and_forgets_it_after_the_ttl():
    now = [0.0]
    cache = BeatCache(max_items=2, ttl_s=10, clock=lambda: now[0])
    v = StoryVariant(cohort="c", headline="h", body="b")
    k1, k2, k3 = (BeatCache.key("m", f"mo-{i}", "c", "model", "v1") for i in (1, 2, 3))
    cache.put(k1, Cached(v, 0, ("composer",)))
    cache.put(k2, Cached(v, 2, ("template",)))
    assert cache.get(k1) is not None and cache.get(k2) is None, "templates are never cached"
    cache.put(k3, Cached(v, 1, ("composer", "repairer")))
    cache.put(BeatCache.key("m", "mo-4", "c", "model", "v1"), Cached(v, 0, ()))
    assert cache.get(k1) is None and len(cache) == 2, "the least recently used entry is evicted"
    now[0] = 11
    assert cache.get(k3) is None


def test_the_cache_key_changes_with_the_model_and_the_prompt_version():
    assert BeatCache.key("m", "a", "c", "gpt-4.1-mini", "v1") != BeatCache.key("m", "a", "c", "gpt-5-mini", "v1")
    assert BeatCache.key("m", "a", "c", "gpt-4.1-mini", "v1") != BeatCache.key("m", "a", "c", "gpt-4.1-mini", "v2")


def test_the_router_sends_beats_to_the_model_and_everything_else_to_templates():
    moments = [{"id": f"mo-{i}", "salience": s} for i, s in enumerate((0.9, 0.8, 0.1))]
    choices = {
        "mo-0": BeatChoice(momentId="mo-0", keep=True, priority=1),
        "mo-1": BeatChoice(momentId="mo-1", keep=True, priority=2),
        "mo-2": BeatChoice(momentId="mo-2", keep=False, priority=5),
    }
    cohorts = [Cohort(mode="casual", language="en"), Cohort(mode="any", language="en")]
    routes = router.plan(moments, choices, cohorts)
    assert routes["mo-0", cohorts[0].key].model and routes["mo-1", cohorts[0].key].model
    assert not routes["mo-0", cohorts[1].key].model, "a stat graphic has no narrative"
    assert not routes["mo-2", cohorts[0].key].model, "a ticker is not worth a call"


def test_the_router_spends_a_limited_number_of_calls_on_the_most_important_moments_first():
    moments = [{"id": "low", "salience": 0.3}, {"id": "high", "salience": 0.9}]
    choices = {m["id"]: BeatChoice(momentId=m["id"], keep=True, priority=3) for m in moments}
    cohorts = [Cohort(mode="casual", language=lang) for lang in ("en", "es")]
    routes = router.plan(moments, choices, cohorts, max_calls=2)
    assert all(routes["high", c.key].model for c in cohorts)
    assert not any(routes["low", c.key].model for c in cohorts)


def _run_fast(pack: dict, faults, **kw):
    import asyncio

    from matchmind.agents.fast import run_fast
    from matchmind.agents.llm import make_chat_client
    from matchmind.agents.team import AgentTeam
    from matchmind.agents.workflow import Batch

    team = AgentTeam(make_chat_client("offline", faults=faults))
    stats: dict = {}
    batch = Batch(moments=(pack,), cohorts=(CASUAL,), budget=3)
    results = asyncio.run(run_fast(team, batch, stats=stats, model_id="offline", **kw))
    return results[0], stats


def test_a_slow_first_call_is_beaten_by_a_hedged_second_call(goal_pack):
    import time

    from matchmind.agents.llm import Faults

    t0 = time.monotonic()
    beat, stats = _run_fast(goal_pack, Faults(mode="slow", delay_s=3.0, remaining=1), deadline_s=2.5, hedge_after_s=0.2)
    assert time.monotonic() - t0 < 1.5, "the hedge answered while the first call was still asleep"
    assert stats["hedged"] == 1 and beat.level == 0


def test_without_a_hedge_the_same_slow_call_misses_the_deadline_and_the_template_is_served(goal_pack):
    from matchmind.agents.llm import Faults

    beat, stats = _run_fast(goal_pack, Faults(mode="slow", delay_s=3.0, remaining=1), deadline_s=0.8, hedge_after_s=0)
    assert stats["hedged"] == 0 and stats["missedDeadline"] == 1 and beat.level == 2


def test_a_fast_call_is_not_hedged(goal_pack):
    from matchmind.agents.llm import Faults

    _, stats = _run_fast(goal_pack, Faults(), deadline_s=2.0, hedge_after_s=0.5)
    assert stats["hedged"] == 0 and stats["modelCalls"] == 1
