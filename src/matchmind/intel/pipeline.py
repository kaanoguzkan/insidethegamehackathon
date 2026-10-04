"""Run a finished match through the physical analyzer and the interpreter (batch mode).

The live system does the same work incrementally: events and tracking chunks arrive over
time, the analyzer and interpreter react to each. ``interpret_match`` reproduces that
arrival order (physics enrichments trail their events by 1.4 s, as they do live) so batch
results match what the streaming pipeline would have produced.
"""

from __future__ import annotations

from ..tracking.analyzer import analyze_match
from .config import InterpreterConfig
from .interpreter import Interpreter, InterpretOutput
from .xt import XTGrid

PHYSICS_LAG_MS = 1400


def arrival_stream(events: list[dict], analysis) -> list[tuple[int, dict]]:
    """All documents of a match in the order they would reach the interpreter."""
    docs: list[tuple[int, int, dict]] = []
    for e in events:
        docs.append((e["clock"]["matchMs"], 0, e))
    for e in analysis.events:
        docs.append((e["clock"]["matchMs"], 1, e))
    for d in analysis.enrichments:
        docs.append((d["clock"]["matchMs"] + PHYSICS_LAG_MS, 2, d))
    docs.sort(key=lambda x: (x[0], x[1], x[2].get("seq", 0)))
    return [(ms, doc) for ms, _, doc in docs]


def interpret_match(
    result,
    *,
    cfg: InterpreterConfig | None = None,
    baselines: dict | None = None,
    xt: XTGrid | None = None,
    season: dict | None = None,
) -> tuple[Interpreter, InterpretOutput]:
    analysis = analyze_match(result)
    ip = Interpreter(result.meta, cfg=cfg, baselines=baselines, xt=xt, season=season)
    total = InterpretOutput()
    for ms, doc in arrival_stream(result.events, analysis):
        total.extend(ip.ingest(doc, arrival_ms=ms))
    total.extend(ip.finish())
    return ip, total
