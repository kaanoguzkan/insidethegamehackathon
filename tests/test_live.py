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
from matchmind.live.store import FINAL, MemoryLiveStore, sort_key


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


# ---------------------------------------------------------------------------------------------
# The chunked path: tracking chunks in blob storage, the analyzer worker, the incremental interpreter
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chunked(match):
    return feed.build_feed(match, physical="chunks"), feed.build_chunks(match)


def _batch_over_delivered_chunks(match):
    """The analyzer run sequentially over the chunks as a provider delivers them (positions rounded to 0.1 m): the reference for the live worker.
    The recorded replays were analysed from the raw floats, whose derived numbers differ slightly; the live path never sees them."""
    from matchmind.tracking.analyzer import AnalyzerOutput, PhysicalAnalyzer
    from matchmind.tracking.frames import decode_chunk, encode_chunk, iter_chunks

    an = PhysicalAnalyzer(match.meta)
    an.add_events(match.events)
    out = AnalyzerOutput()
    for ch in iter_chunks(match):
        out.extend(an.process_chunk(decode_chunk(encode_chunk(ch))))
    out.extend(an.flush())
    return out


def _run_chunked(match, chunked, intel, *, speed=120.0, from_ms=0, key=b"k", fresh_workers_every=None):
    """Play the match through the real loop on a fake clock; after every tick the workers run, as the triggers would."""
    from matchmind.live.analysis import AnalyzerWorker
    from matchmind.live.blobs import MemoryBlobs
    from matchmind.live.pipeline import InterpretWorker

    docs, chunks = chunked
    mid = match.meta["matchId"]
    store, frames, ckpts = MemoryLiveStore(), MemoryBlobs(), MemoryBlobs()
    feed.start_match(store, mid, match.meta, docs, scenario=None, speed=speed, from_ms=from_ms, chunks=len(chunks))
    box = {"an": AnalyzerWorker(store, frames, ckpts, key=key), "ip": InterpretWorker(store, ckpts, intel, key=key, checkpoint_every_s=0.0), "n": 0}
    wall = [1_000_000]

    def sleep(s: float) -> None:
        wall[0] += int(s * 1000)
        box["n"] += 1
        if fresh_workers_every and box["n"] % fresh_workers_every == 0:  # a cold instance: nothing in memory, only the checkpoints
            box["an"], box["ip"] = AnalyzerWorker(store, frames, ckpts, key=key), InterpretWorker(store, ckpts, intel, key=key, checkpoint_every_s=0.0)
        box["an"].drain(mid)
        box["ip"].run(mid)

    feed.play(store, mid, docs, speed=speed, from_ms=from_ms, chunks=chunks, blobs=frames, now=lambda: wall[0], sleep=sleep, tick_s=1.0)
    box["an"].drain(mid)
    out = box["ip"].run(mid)
    return store, frames, ckpts, out


def test_the_chunked_feed_is_events_only_and_the_chunks_are_five_seconds_each(match, chunked):
    docs, chunks = chunked
    assert {d["kind"] for d in docs} == {"feed"} and all(d["doc"]["type"] != "sprint" for d in docs)
    assert len(chunks) == len(match.chunk_slots) and [c[0] for c in chunks[:3]] == [5000, 10000, 15000]
    assert [c[1] for c in chunks[:2]] == [f"{match.meta['matchId']}/00000.json.gz", f"{match.meta['matchId']}/00001.json.gz"]


def test_the_analyzer_worker_produces_exactly_what_the_batch_analyzer_does(match, chunked, intel):
    store, _, _, _ = _run_chunked(match, chunked, intel)
    mid = match.meta["matchId"]
    live = {d["id"]: (d["kind"], d["arrivalMs"], d["doc"]) for d in store.docs(mid) if d["kind"] in ("physical", "enrichment")}
    batch = {d["id"]: (d["kind"], d["arrivalMs"], d["doc"]) for d in feed.analyzer_docs(_batch_over_delivered_chunks(match))}
    assert live.keys() == batch.keys() and len(live) > 1000
    assert all(json.dumps(live[k], sort_keys=True) == json.dumps(batch[k], sort_keys=True) for k in batch)
    state = store.get_state(mid, "analyzer")
    assert state["final"] and state["next"] == len(chunked[1])


def test_interpreting_the_chunked_run_finds_the_batch_pipelines_moments(match, chunked, intel):
    from matchmind.core.clock import clock_from_ms  # noqa: F401
    from matchmind.intel.interpreter import Interpreter, InterpretOutput

    store, _, _, out = _run_chunked(match, chunked, intel)
    mid = match.meta["matchId"]
    ip = Interpreter(
        match.meta, baselines=intel.baselines, xt=intel.xt, models=intel.models,
        season=context_for(intel.season, match.meta["home"]["id"], match.meta["away"]["id"]),
    )
    ref = InterpretOutput()
    for d in sorted(feed.analyzer_docs(_batch_over_delivered_chunks(match)) + chunked[0], key=sort_key):
        ref.extend(ip.ingest(d["doc"], arrival_ms=d["arrivalMs"]))
    ref.extend(ip.finish())
    assert out["finished"] and out["feedMs"] == feed.INF and out["physicalMs"] == feed.INF
    assert [m["id"] for m in store.moments(mid)] == [m["id"] for m in sorted(ref.moments, key=lambda m: m["detectedAt"]["matchMs"])]


def test_a_cold_worker_restores_its_checkpoint_and_the_result_is_the_same(match, chunked, intel):
    """Every 7 ticks both workers are replaced by fresh ones that only have the checkpoints: nothing is lost, duplicated or renumbered."""
    mid = match.meta["matchId"]
    warm, _, _, _ = _run_chunked(match, chunked, intel)
    cold, frames, ckpts, out = _run_chunked(match, chunked, intel, fresh_workers_every=7)
    assert ckpts.exists(f"analyzer/{mid}.bin") and ckpts.exists(f"interpreter/{mid}.bin")
    assert out["finished"]
    assert [m["id"] for m in cold.moments(mid)] == [m["id"] for m in warm.moments(mid)]
    assert {d["id"] for d in cold.docs(mid)} == {d["id"] for d in warm.docs(mid)}


def test_a_checkpoint_that_is_not_signed_by_this_service_is_ignored(match, chunked, intel):
    from matchmind.live.analysis import AnalyzerWorker
    from matchmind.live.blobs import MemoryBlobs, sign, unsign

    assert unsign(sign(b"data", b"k"), b"k") == b"data" and unsign(sign(b"data", b"k"), b"other") is None and unsign(b"short", b"k") is None
    docs, chunks = chunked
    mid = match.meta["matchId"]
    store, frames, ckpts = MemoryLiveStore(), MemoryBlobs(), MemoryBlobs()
    feed.start_match(store, mid, match.meta, docs, scenario=None, speed=1.0, chunks=len(chunks))
    store.add_docs(mid, docs)
    for _, name, data in chunks[:40]:
        frames.put(name, data)
    ckpts.put(f"analyzer/{mid}.bin", b"\x00" * 32 + b"this would be a pickle that runs code")  # planted, unsigned
    store.put_state(mid, "analyzer", {"next": 40, "wmMs": 0, "final": False})
    worker = AnalyzerWorker(store, frames, ckpts, key=b"k")
    out = worker.drain(mid)  # restores from scratch (replaying 40 chunks) instead of loading the planted blob
    assert out["next"] == 40 and out["processed"] == 0


def test_the_interpreter_waits_for_the_slower_watermark(match, chunked, intel):
    """Feed and chunks are all there but the analyzer has not run: nothing may be interpreted past what the physical facts cover."""
    from matchmind.live.blobs import MemoryBlobs
    from matchmind.live.pipeline import InterpretWorker

    docs, chunks = chunked
    mid = match.meta["matchId"]
    store, frames = MemoryLiveStore(), MemoryBlobs()
    feed.start_match(store, mid, match.meta, docs, scenario=None, speed=1.0, chunks=len(chunks))
    store.add_docs(mid, docs)
    store.put_state(mid, "feedWm", feed.INF)
    worker = InterpretWorker(store, None, intel)
    out = worker.run(mid)
    assert out["read"] == 0 and out["limitMs"] == -1 and not out["finished"] and store.moments(mid) == []
    store.put_state(mid, "analyzer", {"next": 100, "wmMs": 300_000, "final": False})
    again = worker.run(mid)
    assert again["limitMs"] == 300_000 and again["read"] > 0 and not again["finished"]
    del frames


def test_two_analyzer_invocations_do_not_run_at_once(match, chunked):
    from matchmind.live.analysis import LOCK, AnalyzerWorker
    from matchmind.live.blobs import MemoryBlobs

    docs, chunks = chunked
    mid = match.meta["matchId"]
    store, frames, ckpts = MemoryLiveStore(), MemoryBlobs(), MemoryBlobs()
    feed.start_match(store, mid, match.meta, docs, scenario=None, speed=1.0, chunks=len(chunks))
    for _, name, data in chunks[:5]:
        frames.put(name, data)
    worker = AnalyzerWorker(store, frames, ckpts, key=b"k")
    assert store.acquire(mid, LOCK, 60_000)  # another invocation is in the middle of it
    assert worker.drain(mid) == {"matchId": mid, "processed": 0, "busy": True}
    store.release(mid, LOCK)
    assert worker.drain(mid)["processed"] == 5
    assert worker.drain(mid)["processed"] == 0  # nothing new: a duplicate event does nothing
