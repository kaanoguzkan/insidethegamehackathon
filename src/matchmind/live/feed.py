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
from ..tracking.analyzer import analyze_match
from .store import FINAL, LiveStore, doc_key, now_ms

CHUNK = 40  # documents written per store call


def _plain(o):  # noqa: ANN001, ANN202
    """numpy numbers and arrays as plain Python, so a document survives ``json.dumps`` (and Cosmos DB)."""
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


def jsonable(doc):  # noqa: ANN001, ANN202
    return json.loads(json.dumps(doc, default=_plain))


def build_feed(result) -> list[dict]:  # noqa: ANN001
    """Every document of the match in arrival order, each with its sequence number ``n`` and ``arrivalMs``; the last one is the end marker."""
    docs = [
        {"id": doc_key(i), "n": i, "kind": "feed", "arrivalMs": int(ms), "doc": jsonable(doc)}
        for i, (ms, doc) in enumerate(arrival_stream(result.events, analyze_match(result)))
    ]
    last = docs[-1]["arrivalMs"] if docs else 0
    docs.append({"id": doc_key(len(docs)), "n": len(docs), "kind": FINAL, "arrivalMs": last + PHYSICS_LAG_MS + 100, "doc": {}})
    return docs


def start_match(store: LiveStore, match_id: str, meta: dict, docs: list[dict], *, scenario: str | None, speed: float, from_ms: int = 0) -> dict:
    """Register the match as scheduled, with what a viewer needs to run its clock."""
    info = {
        "meta": jsonable(meta), "scenario": scenario, "status": "scheduled", "speed": speed, "fromMs": from_ms, "wallStartMs": None,
        "durationMs": docs[-1]["arrivalMs"] if docs else 0, "documents": len(docs),
    }
    store.put_match(match_id, info)
    return info


def play(
    store: LiveStore, match_id: str, docs: list[dict], *, speed: float, from_ms: int = 0,
    now: Callable[[], int] = now_ms, sleep: Callable[[float], None] = time.sleep, tick_s: float = 0.5,
) -> int:
    """Release the feed at ``speed`` times real time, starting ``from_ms`` into the match. Returns the number of documents written.

    Everything that has already "happened" by ``from_ms`` is written at once (a viewer who joins late still gets a match with a past), the rest
    follows the clock. The match is marked live when the first document goes out and finished after the end marker.
    """
    info = store.get_match(match_id) or {}
    wall0 = now()
    store.put_match(match_id, {**info, "status": "live", "speed": speed, "fromMs": from_ms, "wallStartMs": wall0})
    sent = 0
    while sent < len(docs):
        sim_ms = from_ms + (now() - wall0) * speed
        due = []
        while sent + len(due) < len(docs) and docs[sent + len(due)]["arrivalMs"] <= sim_ms:
            due.append(docs[sent + len(due)])
        for i in range(0, len(due), CHUNK):
            store.add_docs(match_id, due[i : i + CHUNK])
        sent += len(due)
        if sent < len(docs):
            sleep(tick_s)
    store.put_match(match_id, {**(store.get_match(match_id) or info), "status": "finished"})
    return sent


def live_clock_ms(info: dict, at_ms: int | None = None) -> int:
    """Where the match clock stands now, in match milliseconds, from a match document (0 until it starts, frozen once it has finished)."""
    if not info.get("wallStartMs"):
        return int(info.get("fromMs") or 0)
    t = (at_ms if at_ms is not None else now_ms()) - info["wallStartMs"]
    clock = int(info.get("fromMs") or 0) + t * float(info.get("speed") or 1.0)
    return int(min(clock, info.get("durationMs") or clock)) if info.get("status") == "finished" else int(clock)
