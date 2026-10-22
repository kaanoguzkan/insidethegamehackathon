"""What an operator and a customer need to see about the service while it runs, without a dashboard product.

The Brain keeps a rolling window of its own requests and counts what the agents did: how many stories the model wrote, how many needed a repair, how many fell
back to a verified template, how many claims the verifier let through, how often the shared cache answered. ``GET /api/ops`` serves the summary (the web app's
Operations page reads it) and ``GET /ready`` says whether the service can do its job right now. Nothing here stores anything: a restarted replica starts a new
window, and Application Insights keeps the long history.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, deque

WINDOW_S = 900.0  # the summary covers the last fifteen minutes
MAX_EVENTS = 20_000

GROUPS = (
    ("beats", ("/api/beats",)),
    ("stream", ("/api/stream",)),
    ("live", ("/api/live", "/api/channel", "/api/season")),
    ("ask", ("/api/ask",)),
    ("tools", ("/mcp", "/api/matches")),
    ("health", ("/health", "/ready", "/api/ops")),
)


def group_of(path: str) -> str:
    for name, prefixes in GROUPS:
        if any(path == p or path.startswith(p + "/") or path.startswith(p) for p in prefixes):
            return name
    return "other"


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * q))]


class Ops:
    def __init__(self, clock=time.time) -> None:  # noqa: ANN001
        self._clock = clock
        self.started = clock()
        self._lock = threading.Lock()
        self._requests: deque[tuple[float, str, int, float]] = deque(maxlen=MAX_EVENTS)  # (at, group, status, ms)
        self._beats: deque[tuple[float, Counter]] = deque(maxlen=MAX_EVENTS)
        self.totals: Counter = Counter()

    # ----- recording -------------------------------------------------------------------------------------------

    def record_request(self, path: str, status: int, ms: float) -> None:
        with self._lock:
            self._requests.append((self._clock(), group_of(path), status, ms))
            self.totals["requests"] += 1
            self.totals["errors"] += status >= 500

    def record_beats(self, answer: dict) -> None:
        """Count one answer of the beats service: how each story was made and what the verifier and the cache did."""
        c: Counter = Counter()
        for beat in answer.get("beats", []):
            c["beats"] += 1
            level = int(beat.get("level") or 0)
            c["modelWritten" if level == 0 else "repaired" if level == 1 else "template"] += 1
            for o in beat.get("overlays", []):
                if o.get("kind") in ("lower_third", "ticker"):
                    c["narrativeOverlays"] += 1
                    c["verifiedOverlays"] += bool(o.get("provenance", {}).get("verified"))
        stats = answer.get("stats") or {}
        for k in ("cacheHits", "modelCalls", "hedged", "repaired", "rejected", "missedDeadline", "inputTokens", "outputTokens"):
            c[k] += int(stats.get(k) or 0)
        with self._lock:
            self._beats.append((self._clock(), c))
            self.totals.update(c)

    # ----- the summary -----------------------------------------------------------------------------------------

    def snapshot(self, *, window_s: float = WINDOW_S) -> dict:
        now = self._clock()
        with self._lock:
            reqs = [r for r in self._requests if now - r[0] <= window_s]
            beats = [c for t, c in self._beats if now - t <= window_s]
        by_group: dict[str, dict] = {}
        for g in {r[1] for r in reqs}:
            rows = [r for r in reqs if r[1] == g]
            ms = sorted(r[3] for r in rows)
            by_group[g] = {
                "requests": len(rows), "errors": sum(1 for r in rows if r[2] >= 500),
                "p50Ms": round(_percentile(ms, 0.5) or 0), "p95Ms": round(_percentile(ms, 0.95) or 0),
            }
        ms_all = sorted(r[3] for r in reqs if r[1] not in ("health",))
        served = [r for r in reqs if r[1] != "health"]
        total = Counter()
        for c in beats:
            total.update(c)
        n = total["beats"]
        overlays = total["narrativeOverlays"]
        lookups = total["cacheHits"] + total["modelCalls"]
        return {
            "uptimeS": round(now - self.started),
            "windowS": round(window_s),
            "requests": {
                "total": len(served), "errors": sum(1 for r in served if r[2] >= 500),
                "errorRate": round(sum(1 for r in served if r[2] >= 500) / len(served), 4) if served else 0.0,
                "p50Ms": round(_percentile(ms_all, 0.5) or 0), "p95Ms": round(_percentile(ms_all, 0.95) or 0), "byGroup": by_group,
            },
            "narrative": {
                "stories": n,
                "modelWritten": total["modelWritten"], "repaired": total["repaired"], "template": total["template"],
                "templateShare": round(total["template"] / n, 3) if n else 0.0,
                "claimsVerifiedShare": round(total["verifiedOverlays"] / overlays, 3) if overlays else 1.0,
                "cacheHitRate": round(total["cacheHits"] / lookups, 3) if lookups else 0.0,
                "modelCalls": total["modelCalls"], "hedged": total["hedged"], "missedDeadline": total["missedDeadline"], "rejected": total["rejected"],
                "inputTokens": total["inputTokens"], "outputTokens": total["outputTokens"],
            },
            "totals": dict(self.totals),
        }


ops = Ops()
