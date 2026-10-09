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


def test_the_deadline_holds_even_when_a_stalled_model_call_ignores_cancellation(goal_pack):
    import asyncio
    import time
    from types import SimpleNamespace

    from matchmind.agents.fast import run_fast
    from matchmind.agents.workflow import Batch

    async def stubborn(pack, cohort, timeout_s=None):
        while True:  # swallows every cancellation and keeps going for 3 s, like a call stuck in a retry
            try:
                await asyncio.sleep(3.0)
                raise RuntimeError("late")
            except asyncio.CancelledError:
                await asyncio.sleep(3.0)
                raise

    async def go():
        stats: dict = {}
        t0 = time.monotonic()
        res = await run_fast(SimpleNamespace(compose=stubborn), Batch(moments=(goal_pack,), cohorts=(CASUAL,), budget=3), deadline_s=0.6, stats=stats, model_id="x", hedge_after_s=0)
        return time.monotonic() - t0, res[0], stats

    took, beat, stats = asyncio.run(go())
    assert took < 1.5, f"the response was held {took:.1f}s past a 0.6s deadline"
    assert beat.level == 2 and stats["missedDeadline"] == 1


@pytest.mark.parametrize("bad", ["../red-card-drama", "..", "/etc", "red-card-drama/../high-line-gamble", "RED", "a" * 65, "", "red card", "x\\y"])
def test_a_match_id_that_is_not_a_plain_slug_never_reaches_the_filesystem(bad):
    from matchmind.agents.service import load_recorded

    assert load_recorded(replays_dir(), bad) is None


def test_a_real_match_id_still_loads():
    from matchmind.agents.service import load_recorded

    packs, names = load_recorded(replays_dir(), "red-card-drama")
    assert packs and names


class FakeCosmos:
    """A stand-in for a Cosmos container client: documents in a dict, with switches for slowness and failure."""

    def __init__(self) -> None:
        self.docs: dict = {}
        self.delay = 0.0
        self.fail = False
        self.reads = 0

    async def read_item(self, item, partition_key):  # noqa: ANN001
        import asyncio

        self.reads += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("cosmos is down")
        if item not in self.docs:
            raise KeyError("not found")
        return self.docs[item]

    async def upsert_item(self, doc):  # noqa: ANN001
        import asyncio

        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("cosmos is down")
        self.docs[doc["id"]] = doc


def _shared(cos, **kw):  # noqa: ANN001, ANN202
    from matchmind.agents.cache import BeatCache, SharedBeatCache

    async def open_container():
        return cos

    return SharedBeatCache(BeatCache(), open_container, **kw)


KEY = ("m", "mo-1", "casual/en/neutral/-", "gpt-4.1-mini", "v1")


def test_the_shared_cache_writes_through_and_a_new_replica_reads_it_back():
    import asyncio

    from matchmind.agents.cache import Cached

    async def go():
        cos = FakeCosmos()
        a = _shared(cos)
        await a.put(KEY, Cached(StoryVariant(cohort="c", headline="h", body="b"), 0, ("composer", "verifier")))
        await asyncio.gather(*a._pending)
        assert len(cos.docs) == 1
        b = _shared(cos)  # another replica, or this one after a restart: empty memory
        hit = await b.get(KEY)
        return hit, len(b.local), cos.reads, await b.get(KEY), cos.reads

    hit, kept, reads, again, reads_after = asyncio.run(go())
    assert hit.variant.headline == "h" and hit.level == 0 and hit.agents == ("composer", "verifier")
    assert kept == 1 and again is not None and reads_after == reads, "the second read is served from memory"


def test_the_shared_cache_never_stores_templates_and_never_serves_another_keys_text():
    import asyncio

    from matchmind.agents.cache import Cached, doc_id

    async def go():
        cos = FakeCosmos()
        c = _shared(cos)
        await c.put(KEY, Cached(StoryVariant(cohort="c", headline="h", body="b"), 2, ("template",)))
        await asyncio.gather(*c._pending)
        cos.docs[doc_id(KEY)] = {"key": ["other"], "level": 0, "agents": [], "variant": {"cohort": "c", "headline": "x", "body": "y"}}
        return len(cos.docs), await _shared(cos).get(KEY)

    n, served = asyncio.run(go())
    assert n == 1 and served is None  # only the planted, mismatching document exists, and it is refused


def test_a_slow_or_failing_cosmos_is_only_a_miss_and_is_left_alone_for_a_while():
    import asyncio
    import time

    async def go():
        cos = FakeCosmos()
        cos.delay = 2.0
        c = _shared(cos, timeout_s=0.1, cooldown_s=30)
        t0 = time.monotonic()
        first = await c.get(KEY)
        took = time.monotonic() - t0
        reads = cos.reads
        t1 = time.monotonic()
        second = await c.get(KEY)  # inside the cooldown: not even tried
        return first, took, second, time.monotonic() - t1, cos.reads - reads

    first, took, second, took2, extra_reads = asyncio.run(go())
    assert first is None and second is None
    assert took < 0.5, "the time box held"
    assert took2 < 0.05 and extra_reads == 0, "after a failure the shared layer is skipped for the cooldown"

    async def failing():
        cos = FakeCosmos()
        cos.fail = True
        return await _shared(cos).get(KEY)

    assert asyncio.run(failing()) is None


def test_a_cache_hit_from_the_shared_layer_makes_the_fast_path_skip_the_model(goal_pack):
    import asyncio


    async def go():
        from matchmind.agents.fast import run_fast
        from matchmind.agents.llm import make_chat_client
        from matchmind.agents.team import AgentTeam
        from matchmind.agents.workflow import Batch

        cos = FakeCosmos()
        cache = _shared(cos)
        team = AgentTeam(make_chat_client("offline"))
        batch = Batch(moments=(goal_pack,), cohorts=(CASUAL,), budget=3)
        s1: dict = {}
        await run_fast(team, batch, deadline_s=2.0, stats=s1, model_id="offline", cache=cache)
        await asyncio.gather(*cache._pending)
        fresh = _shared(cos)  # a restarted replica
        s2: dict = {}
        await run_fast(team, batch, deadline_s=2.0, stats=s2, model_id="offline", cache=fresh)
        return s1, s2

    s1, s2 = asyncio.run(go())
    assert s1["modelCalls"] == 1 and s1["cacheHits"] == 0
    assert s2["modelCalls"] == 0 and s2["cacheHits"] == 1


def test_warming_opens_the_connection_so_the_first_request_is_not_the_slow_one():
    import asyncio

    async def go():
        cos = FakeCosmos()
        cos.delay = 0.3  # a slow first call, longer than the per-request time box below
        c = _shared(cos, timeout_s=0.1)
        await c.warm(timeout_s=5)
        cos.delay = 0.0
        return c.status(), await c.get(KEY)

    status, hit = asyncio.run(go())
    assert status["connected"] and status["lastError"] is None, "a not-found warm-up probe is the normal answer"
    assert hit is None  # a miss, but a quick, healthy one


def test_a_failure_is_recorded_for_health():
    import asyncio

    async def go():
        cos = FakeCosmos()
        cos.fail = True
        c = _shared(cos)
        await c.get(KEY)
        return c.status()

    assert "cosmos is down" in asyncio.run(go())["lastError"]
