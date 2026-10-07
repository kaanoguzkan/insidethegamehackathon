import asyncio
import logging

import pytest

from matchmind.agents import producer, verify
from matchmind.agents.llm import Faults, OfflineChatClient
from matchmind.agents.store import InMemoryMomentStore
from matchmind.agents.team import AgentSettings, AgentTeam
from matchmind.agents.workflow import Batch, WorkflowDeps, build_workflow, run_batch
from matchmind.core.contracts import Cohort, Explanation, Overlay
from packs import packs
from test_verify import REG

logging.getLogger("agent_framework").setLevel(logging.ERROR)
P = packs()
COHORTS = (
    Cohort(mode="analyst", language="en"),
    Cohort(mode="casual", language="es"),
    Cohort(mode="casual", language="tr", perspective="HAR"),
)


def run(faults=None, moments=("goal", "pressure_collapse"), budget=3, budget_s=10.0, timeout_s=8.0, clock=None, saliences=None):
    client = OfflineChatClient(faults or Faults())
    store = InMemoryMomentStore()
    deps = WorkflowDeps(team=AgentTeam(client, AgentSettings(timeout_s=timeout_s)), registry=REG, store=store)
    if clock:
        deps.clock = clock
    wf = build_workflow(deps)
    moms = tuple({**P[m], "salience": (saliences or {}).get(m, P[m]["salience"])} for m in moments)
    batch = Batch(moments=moms, cohorts=COHORTS, budget=budget, budget_s=budget_s)
    results = asyncio.run(run_batch(wf, batch))
    return {r.momentId: r for r in results}, client, store


def test_full_path_for_selected_beats():
    res, client, store = run()
    for mid in ("t-mo-goal", "t-mo-pressure_collapse"):
        r = res[mid]
        assert r.level == 0
        assert r.agents == ("editor", "explainer", "verifier", "storyteller", "localizer")
        assert len(r.overlays) == len(COHORTS)
        assert all(o.provenance.fallbackLevel == 0 and o.provenance.verified for o in r.overlays)
    assert client.calls.count("edit") == 1 and client.calls.count("explain") == 2


def test_overlays_are_valid_and_every_text_verifies():
    res, _, _ = run(moments=("goal", "pressure_collapse", "chaos_flip", "red_card"))
    seen = set()
    for r in res.values():
        for o in r.overlays:
            Overlay.model_validate(o.model_dump())
            assert o.id not in seen and "/" not in o.id
            seen.add(o.id)
            assert not verify.verify_text(o.content.headline + ". " + o.content.body, P[o.momentId.split("t-mo-")[1] and o.momentId[5:]], o.cohort.language, REG) or o.kind == "ticker"


def test_editor_budget_declines_extra_stories_to_tickers():
    res, client, _ = run(moments=("goal", "chaos_flip", "rhythm_break", "fatigue_drop"), budget=1, saliences={"chaos_flip": 0.5, "rhythm_break": 0.45, "fatigue_drop": 0.4})
    full = [r for r in res.values() if r.level == 0]
    tick = [r for r in res.values() if r.overlays and r.overlays[0].kind == "ticker"]
    assert len(full) == 2  # the goal (must show) plus one
    assert len(tick) == 2
    assert client.calls.count("explain") == 2


def test_a_headline_story_is_told_even_with_no_budget_left():
    res, client, _ = run(moments=("pressure_collapse", "chaos_flip"), budget=0, saliences={"pressure_collapse": 0.7, "chaos_flip": 0.5})
    assert res["t-mo-pressure_collapse"].level == 0
    assert res["t-mo-chaos_flip"].overlays[0].kind == "ticker"


def test_one_bad_explanation_is_retried_and_succeeds():
    res, client, store = run(Faults(mode="hallucinate", remaining=1, tasks=frozenset({"explain"})), moments=("pressure_collapse",))
    r = res["t-mo-pressure_collapse"]
    assert r.level == 1
    assert client.calls.count("explain") == 2
    trace = store.get("t-mo-pressure_collapse")["trace"]
    assert any(s["agent"] == "verifier" and s["outcome"] == "explanation rejected" for s in trace)
    assert all(o.provenance.fallbackLevel == 1 for o in r.overlays)


def test_a_model_that_keeps_hallucinating_falls_back_to_templates():
    res, client, _ = run(Faults(mode="hallucinate", tasks=frozenset({"explain"})), moments=("pressure_collapse",))
    r = res["t-mo-pressure_collapse"]
    assert r.level == 2 and "template" in r.agents
    assert client.calls.count("explain") == 2  # first try plus one retry, then stop
    assert "story" not in client.calls
    for o in r.overlays:
        assert o.provenance.fallbackLevel == 2 and o.provenance.verified


def test_bad_story_text_is_caught_and_only_failing_cohorts_degrade():
    res, client, _ = run(Faults(mode="hallucinate", remaining=1, tasks=frozenset({"localize"})), moments=("pressure_collapse",))
    r = res["t-mo-pressure_collapse"]
    levels = {o.cohort.key: o.provenance.fallbackLevel for o in r.overlays}
    assert levels["analyst/en/neutral/-"] == 1 and set(levels.values()) <= {1, 2}
    assert client.calls.count("story") == 2  # the Storyteller was asked again with feedback


def test_model_outage_degrades_everything_but_nothing_is_lost():
    res, client, store = run(Faults(mode="error"), moments=("goal", "pressure_collapse", "chaos_flip"))
    assert len(res) == 3
    for r in res.values():
        assert r.level == 2 and len(r.overlays) == len(COHORTS)
    trace = [s["outcome"] for d in store.docs.values() for s in d["trace"] if s["agent"] == "editor"]
    assert any(t.startswith("fallback") for t in trace)


def test_slow_model_hits_the_timeout_and_degrades():
    res, _, _ = run(Faults(mode="slow", delay_s=0.5), moments=("goal",), timeout_s=0.05)
    assert res["t-mo-goal"].level == 2


def test_no_time_left_means_no_model_calls():
    res, client, _ = run(moments=("goal",), budget_s=0.0)
    assert res["t-mo-goal"].level == 2
    assert "explain" not in client.calls and "story" not in client.calls


def test_state_store_records_each_agent_step():
    _, _, store = run(moments=("pressure_collapse",))
    doc = store.get("t-mo-pressure_collapse")
    agents = [s["agent"] for s in doc["trace"]]
    assert agents == ["editor", "explainer", "verifier", "storyteller", "localizer", "verifier", "producer"]
    assert doc["status"] == "published" and doc["explanation"]["tactical_tag"] == "pressing_collapse"


def test_results_are_deterministic():
    a, _, _ = run(moments=("goal", "pressure_collapse"))
    b, _, _ = run(moments=("goal", "pressure_collapse"))
    key = lambda res: {m: [(o.id, o.content.headline, o.content.body) for o in r.overlays] for m, r in res.items()}  # noqa: E731
    assert key(a) == key(b)


# ---- producer ----------------------------------------------------------------------------------


def _ov(i, kind="lower_third", at=0, priority=3, dur=9000, cohort=COHORTS[0]):
    from matchmind.core.contracts import DisplayAt, OverlayContent

    return Overlay(
        id=f"o{i}", matchId="t", kind=kind, displayAt=DisplayAt(matchMs=at), durationMs=dur, priority=priority,
        cohort=cohort, content=OverlayContent(headline=f"h{i}"),
    )


def test_lower_thirds_never_overlap_within_a_cohort():
    out = producer.resolve_collisions([_ov(1, at=0), _ov(2, at=3000), _ov(3, at=4000)])
    spans = sorted((o.displayAt.matchMs, o.displayAt.matchMs + o.durationMs) for o in out)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))
    assert len(out) == 3


def test_late_overlays_are_dropped_but_must_show_become_tickers():
    items = [_ov(1, at=0, dur=60000), _ov(2, at=1000, priority=3), _ov(3, at=2000, priority=1)]
    out = {o.id: o for o in producer.resolve_collisions(items)}
    assert "o2" not in out
    assert out["o3"].kind == "ticker"


def test_different_cohorts_do_not_block_each_other():
    out = producer.resolve_collisions([_ov(1, at=0, cohort=COHORTS[0]), _ov(2, at=0, cohort=COHORTS[1])])
    assert [o.displayAt.matchMs for o in out] == [0, 0]


@pytest.mark.parametrize("mtype", ["goal", "pressure_collapse"])
def test_lower_third_timing_follows_the_match_clock(mtype):
    from matchmind.agents import templates as T

    v = T.render(P[mtype], COHORTS[0])
    o = producer.lower_third(P[mtype], v, COHORTS[0], priority=2, level=0, agents=["x"], verified=True)
    assert o.displayAt.matchMs == P[mtype]["detectedAt"]["matchMs"] + producer.LEAD_MS.get(mtype, producer.DEFAULT_LEAD_MS)


def test_verified_flag_is_earned_not_assumed():
    """If text reaching the Producer fails verification, it must not be badged as verified."""
    from matchmind.agents import workflow as W

    res, _, _ = run(moments=("goal",))
    assert all(o.provenance.verified for o in res["t-mo-goal"].overlays)
    # The Producer's check is the Verifier itself: a hallucinated body is rejected by it.
    from matchmind.agents import templates as T
    from matchmind.core.contracts import StoryVariant

    good = T.render(P["goal"], COHORTS[0])
    bad = StoryVariant(cohort=good.cohort, headline=good.headline, body="Rafael Brandmont made 99 shots.", claims=good.claims)
    assert verify.verify_variant(good, P["goal"], COHORTS[0], REG).ok
    assert not verify.verify_variant(bad, P["goal"], COHORTS[0], REG).ok
    assert W.verify is verify


def test_a_reasoning_model_gets_no_temperature_more_tokens_and_more_time(monkeypatch):
    for k in ("MATCHMIND_AGENT_TIMEOUT_S", "MATCHMIND_MAX_TOKENS", "MATCHMIND_BEAT_BUDGET_S", "MATCHMIND_REASONING_EFFORT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MATCHMIND_LLM", "foundry")
    monkeypatch.setenv("MATCHMIND_LLM_MODEL", "gpt-5-mini")
    s = AgentSettings.from_env()
    assert (s.send_temperature, s.reasoning_effort) == (False, "low") and s.max_tokens >= 4000 and s.timeout_s >= 30
    team = AgentTeam(OfflineChatClient(), s)
    opts = team._options(Explanation, 0.2)
    assert "temperature" not in opts and opts["reasoning"] == {"effort": "low"}

    monkeypatch.setenv("MATCHMIND_LLM_MODEL", "gpt-4.1-mini")  # an ordinary model keeps the temperature and the short limits
    s = AgentSettings.from_env()
    assert s.send_temperature and s.timeout_s == 8.0 and s.max_tokens == 700
    assert AgentTeam(OfflineChatClient(), s)._options(Explanation, 0.2)["temperature"] == 0.2

    monkeypatch.setenv("MATCHMIND_LLM", "offline")  # the offline client is never treated as a reasoning model
    monkeypatch.setenv("MATCHMIND_LLM_MODEL", "gpt-5-mini")
    assert AgentSettings.from_env().send_temperature

    monkeypatch.setenv("MATCHMIND_LLM", "foundry")
    monkeypatch.setenv("MATCHMIND_MAX_TOKENS", "2500")
    monkeypatch.setenv("MATCHMIND_REASONING_EFFORT", "none")
    s = AgentSettings.from_env()
    assert s.max_tokens == 2500 and s.reasoning_effort is None
