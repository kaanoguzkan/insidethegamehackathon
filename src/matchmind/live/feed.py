"""The synthetic data provider: a simulated match turned into a feed that arrives over time.

The batch pipeline has always known the order in which a match's documents reach the interpreter (``intel.pipeline.arrival_stream``: events,
then the physical analyzer's events, then the enrichments that trail their pass or shot by 1.4 s). Here that order is stamped onto each
document (``arrivalMs``, in match time) and :func:`play` releases the documents to a :class:`~matchmind.live.store.LiveStore` as wall-clock time
passes, ``speed`` times faster than the match. That is all the interpreter downstream needs to behave live.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from ..intel.pipeline import PHYSICS_LAG_MS, arrival_stream
from ..tracking.analyzer import AnalyzerOutput, analyze_match
from ..tracking.frames import encode_chunk, iter_chunks
from .blobs import Blobs
from .store import FINAL, LiveStore, doc_key, now_ms

CHUNK = 40  # documents written per store call


def _plain(o):  # noqa: ANN001, ANN202
    """numpy numbers and arrays as plain Python, so a document survives ``json.dumps`` (and Cosmos DB)."""
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


def jsonable(doc):  # noqa: ANN001, ANN202
    return json.loads(json.dumps(doc, default=_plain))


INF = 2**53  # "everything": the watermark of a feed or an analyzer that has finished
ORDER = {"feed": 0, "physical": 1, "enrichment": 2, FINAL: 9}  # events, then the analyzer's events, then its enrichments, at equal arrival times


def feed_doc(i: int, ms: int, doc: dict, kind: str = "feed") -> dict:
    return {"id": doc_key(i), "n": i, "kind": kind, "order": ORDER[kind], "seq": doc.get("seq") or 0, "arrivalMs": int(ms), "doc": jsonable(doc)}


def build_feed(result, *, physical: str = "inline") -> list[dict]:  # noqa: ANN001
    """The match's documents in arrival order, each with its sequence number ``n`` and ``arrivalMs``.

    ``physical="inline"`` puts the physical analyzer's documents into the feed too (what the batch pipeline sees) and ends it with a marker; ``"chunks"``
    leaves them out: the feed is the events only, and the physical facts are derived from the tracking chunks by the analyzer Function.
    """
    if physical == "inline":
        stream = arrival_stream(result.events, analyze_match(result))
    else:
        stream = sorted(((e["clock"]["matchMs"], e) for e in result.events), key=lambda x: (x[0], x[1].get("seq", 0)))
    docs = [feed_doc(i, ms, doc) for i, (ms, doc) in enumerate(stream)]
    if physical == "inline":
        last = docs[-1]["arrivalMs"] if docs else 0
        docs.append({"id": doc_key(len(docs)), "n": len(docs), "kind": FINAL, "order": ORDER[FINAL], "seq": 0, "arrivalMs": last + PHYSICS_LAG_MS + 100, "doc": {}})
    return docs


def chunk_name(match_id: str, index: int) -> str:
    return f"{match_id}/{index:05d}.json.gz"


def build_chunks(result) -> list[tuple[int, str, bytes]]:  # noqa: ANN001
    """The tracking feed as the provider delivers it: ``(end of the chunk in match ms, blob name, gzip JSON)``, five seconds each."""
    return [(ch.start_ms + ch.n * 1000 // ch.hz, chunk_name(ch.match_id, ch.index), encode_chunk(ch)) for ch in iter_chunks(result)]


def analyzer_docs(out: AnalyzerOutput) -> list[dict]:
    """The analyzer's output as feed documents (without sequence numbers: they are ordered by arrival time, not by when they were written)."""
    docs = []
    for e in out.events:
        docs.append({"id": f"p-{e['id']}", "kind": "physical", "order": ORDER["physical"], "seq": e.get("seq") or 0, "arrivalMs": int(e["clock"]["matchMs"]), "doc": jsonable(e)})
    for d in out.enrichments:
        docs.append({"id": f"p-{d['id']}", "kind": "enrichment", "order": ORDER["enrichment"], "seq": 0, "arrivalMs": int(d["clock"]["matchMs"]) + PHYSICS_LAG_MS, "doc": jsonable(d)})
    return docs


def start_match(
    store: LiveStore, match_id: str, meta: dict, docs: list[dict], *, scenario: str | None, speed: float, from_ms: int = 0, chunks: int = 0,
) -> dict:
    """Register the match as scheduled, with what a viewer needs to run its clock. ``chunks`` > 0 says the physical facts come from that many
    tracking chunks (the analyzer Function); 0 says they are in the feed."""
    info = {
        "meta": jsonable(meta), "scenario": scenario, "status": "scheduled", "speed": speed, "fromMs": from_ms, "wallStartMs": None,
        "durationMs": (chunks * meta["chunkTicks"] * 1000 // meta["hz"]) if chunks else (docs[-1]["arrivalMs"] if docs else 0),
        "documents": len(docs), "chunks": chunks, "physical": "chunks" if chunks else "inline",
    }
    store.put_match(match_id, info)
    return info


def play(
    store: LiveStore, match_id: str, docs: list[dict], *, speed: float, from_ms: int = 0,
    chunks: list[tuple[int, str, bytes]] | None = None, blobs: Blobs | None = None,
    now: Callable[[], int] = now_ms, sleep: Callable[[float], None] = time.sleep, tick_s: float = 0.5, on_tick: Callable[[], None] | None = None,
    speed_of: Callable[[], float] | None = None,
) -> int:
    """Release the feed at ``speed`` times real time, starting ``from_ms`` into the match. Returns the number of documents written.

    Everything that has already "happened" by ``from_ms`` is written at once (a viewer who joins late still gets a match with a past), the rest
    follows the clock. Each tick writes the documents that are due, then **states the feed watermark** (every document up to that match time is
    written: this is what lets the interpreter consume the feed deterministically), then publishes the tracking chunks that are complete, in order. The
    match is marked live when the first document goes out and finished when both are exhausted.

    ``speed_of`` lets the speed change while the match is played: when it answers something new, the clock is re-anchored where it stands (match time
    ``anchorMs`` at wall time ``wallStartMs``), so the match carries on from the same minute at the new speed and never jumps.
    """
    info = store.get_match(match_id) or {}
    wall0 = now()
    store.put_match(match_id, {**info, "status": "live", "speed": speed, "fromMs": from_ms, "wallStartMs": wall0})
    chunks = chunks or []
    sent = published = 0
    base_ms = float(from_ms)  # the match time at wall0
    while sent < len(docs) or published < len(chunks):
        if speed_of is not None and speed_of() != speed:
            base_ms, wall0, speed = base_ms + (now() - wall0) * speed, now(), speed_of()
            info = store.get_match(match_id) or info
            store.put_match(match_id, {**info, "speed": speed, "anchorMs": int(base_ms), "wallStartMs": wall0})
        sim_ms = base_ms + (now() - wall0) * speed
        due = []
        while sent + len(due) < len(docs) and docs[sent + len(due)]["arrivalMs"] <= sim_ms:
            due.append(docs[sent + len(due)])
        for i in range(0, len(due), CHUNK):
            store.add_docs(match_id, due[i : i + CHUNK])
        sent += len(due)
        done = sent >= len(docs)
        store.put_state(match_id, "feedWm", INF if done else int(sim_ms))
        while published < len(chunks) and chunks[published][0] <= sim_ms and blobs is not None:
            blobs.put(chunks[published][1], chunks[published][2])
            published += 1
        if blobs is None:
            published = len(chunks)
        if on_tick is not None:  # whatever stands in for the triggers (a local run runs the workers here)
            on_tick()
        if sent < len(docs) or published < len(chunks):
            sleep(tick_s)
    store.put_match(match_id, {**(store.get_match(match_id) or info), "status": "finished"})
    return sent


def live_clock_ms(info: dict, at_ms: int | None = None) -> int:
    """Where the match clock stands now, in match milliseconds, from a match document (0 until it starts, frozen once it has finished)."""
    if not info.get("wallStartMs"):
        return int(info.get("anchorMs") if info.get("anchorMs") is not None else (info.get("fromMs") or 0))
    t = (at_ms if at_ms is not None else now_ms()) - info["wallStartMs"]
    clock = int(info.get("anchorMs") if info.get("anchorMs") is not None else (info.get("fromMs") or 0)) + t * float(info.get("speed") or 1.0)
    return int(min(clock, info.get("durationMs") or clock)) if info.get("status") == "finished" else int(clock)
