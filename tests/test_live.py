"""The live pipeline: a match arrives as a feed, is interpreted as it arrives and gets its overlays written while it is being played."""

from __future__ import annotations

import asyncio
import json

import pytest

from matchmind.agents.llm import make_chat_client
from matchmind.agents.team import AgentSettings, AgentTeam
from matchmind.analytics.season import context_for
from matchmind.intel.pipeline import interpret_match
from matchmind.live import dispatch, feed, pipeline
from matchmind.live.store import FINAL, MemoryLiveStore


@pytest.fixture(scope="module")
def docs(match):
    return feed.build_feed(match)


@pytest.fixture(scope="module")
def intel():
    return pipeline.Intel.load()


def _loaded(match, docs, upto=None) -> MemoryLiveStore:
    store = MemoryLiveStore()
    feed.start_match(store, match.meta["matchId"], match.meta, docs, scenario=None, speed=5.0)
    store.add_docs(match.meta["matchId"], docs if upto is None else docs[:upto])
    return store


def test_the_feed_is_plain_json_in_arrival_order_and_ends_with_a_marker(docs):
    json.dumps(docs)  # it has to survive Cosmos DB
    assert [d["n"] for d in docs] == list(range(len(docs)))
    assert all(a["arrivalMs"] <= b["arrivalMs"] for a, b in zip(docs, docs[1:], strict=False))
    assert docs[-1]["kind"] == FINAL and all(d["kind"] == "feed" for d in docs[:-1])
    assert len({d["id"] for d in docs}) == len(docs) and all("/" not in d["id"] for d in docs)


def test_interpreting_the_live_feed_gives_the_moments_the_batch_pipeline_finds(match, docs, intel):
    store = _loaded(match, docs)
    out = pipeline.interpret(store, match.meta["matchId"], intel)
    _, batch = interpret_match(
        match, baselines=intel.baselines, xt=intel.xt, models=intel.models,
        season=context_for(intel.season, match.meta["home"]["id"], match.meta["away"]["id"]),
    )
    assert out["finished"] and out["moments"] == len(batch.moments) > 0
    assert [m["id"] for m in store.moments(match.meta["matchId"])] == [m["id"] for m in sorted(batch.moments, key=lambda m: m["detectedAt"]["matchMs"])]


def test_interpretation_is_idempotent_and_can_run_while_the_match_is_still_being_played(match, docs, intel):
    mid = match.meta["matchId"]
    half = len(docs) // 2
    store = _loaded(match, docs, upto=half)
    first = pipeline.interpret(store, mid, intel)
    assert not first["finished"] and first["newMoments"]
    again = pipeline.interpret(store, mid, intel)  # the same batch delivered twice
    assert again["newMoments"] == [] and again["newOverlays"] == 0
    store.add_docs(mid, docs[half:])
    rest = pipeline.interpret(store, mid, intel)
    assert rest["finished"] and set(first["newMoments"]).isdisjoint(rest["newMoments"])
    assert {m["id"] for m in store.moments(mid)} >= set(first["newMoments"])  # nothing found early is lost or renumbered


def test_playing_the_feed_releases_it_with_the_clock_and_marks_the_match(match, docs):
    mid = match.meta["matchId"]
    store = MemoryLiveStore()
    feed.start_match(store, mid, match.meta, docs, scenario="x", speed=60.0, from_ms=20 * 60_000)
    wall = [1_000_000]
    sizes: list[int] = []
    real_add = store.add_docs

    def add(m, d):  # noqa: ANN001, ANN202
        sizes.append(len(d))
        real_add(m, d)

    store.add_docs = add  # type: ignore[method-assign]

    def sleep(s: float) -> None:
        wall[0] += int(s * 1000)

    n = feed.play(store, mid, docs, speed=60.0, from_ms=20 * 60_000, now=lambda: wall[0], sleep=sleep, tick_s=1.0)
    assert n == len(docs) == len(store.docs(mid))
    head = sum(1 for d in docs if d["arrivalMs"] <= 20 * 60_000)
    assert head > feed.CHUNK and sizes[0] == feed.CHUNK  # the part of the match already played goes out at once (in full chunks)
    info = store.get_match(mid)
    assert info["status"] == "finished" and info["wallStartMs"] == 1_000_000
    # one wall second is a match minute at 60x: the 95-minute match, started at minute 20, needs about 75 wall seconds
    assert 70_000 <= wall[0] - 1_000_000 <= 90_000


def test_the_clock_follows_the_wall_clock_at_the_chosen_speed_and_stops_when_the_match_is_over():
    info = {"status": "live", "fromMs": 600_000, "wallStartMs": 1_000, "speed": 5.0, "durationMs": 5_700_000}
    assert feed.live_clock_ms(info, at_ms=1_000) == 600_000
    assert feed.live_clock_ms(info, at_ms=11_000) == 600_000 + 50_000
    assert feed.live_clock_ms({"status": "scheduled", "fromMs": 0}) == 0
    done = {**info, "status": "finished"}
    assert feed.live_clock_ms(done, at_ms=10**9) == 5_700_000


def test_narrative_overlays_are_written_for_new_moments_and_never_twice(match, docs, intel):
    mid = match.meta["matchId"]
    store = _loaded(match, docs)
    new = pipeline.interpret(store, mid, intel)["newMoments"]
    team = AgentTeam(make_chat_client("offline"), AgentSettings())
    out = asyncio.run(dispatch.write_beats(store, mid, new, team=team))
    assert out["moments"] == len(new) and out["overlaysWritten"] > 0 and out["rejected"] == 0
    rows = store.overlays_since(mid, 0)
    stories = [r["overlay"] for r in rows if r["overlay"]["kind"] == "lower_third"]
    assert stories and all(o["provenance"]["verified"] for o in stories)
    assert {o["momentId"] for o in stories} <= set(new)
    again = asyncio.run(dispatch.write_beats(store, mid, new, team=team))
    assert again["overlaysWritten"] == 0, "re-delivering the same moments must not duplicate overlays"


def test_the_story_budget_is_shared_across_dispatches(match, docs, intel):
    """Moments dispatched in separate calls still count against the same ten-minute story budget."""
    mid = match.meta["matchId"]
    store = _loaded(match, docs)
    new = pipeline.interpret(store, mid, intel)["newMoments"]
    team = AgentTeam(make_chat_client("offline"), AgentSettings())
    for m in new:  # one moment per call, the way a trickling change feed delivers them
        asyncio.run(dispatch.write_beats(store, mid, [m], team=team))
    assert isinstance(store.get_state(mid, "kept_at"), list)
    optional = [m for m in store.moments(mid) if m["type"] not in dispatch.MUST_SHOW and m["salience"] < dispatch.HEADLINE_SALIENCE]
    kept = [t for t in store.get_state(mid, "kept_at")]
    for t in kept:  # never more than the budget inside any ten minutes
        assert sum(1 for u in kept if 0 <= t - u < 10 * 60_000) <= 3 + 1
    assert len(kept) <= len(optional)
