"""The Router: decides, with rules, which moment and cohort pairs are worth a model call.

Every model call costs seconds and tokens, and the free tier has a token-per-minute cap, so calls go where they
matter and the rest get template text at once:

* a moment the Editor did not make a beat is a ticker: template;
* a stat-graphic cohort (mode "any") has no narrative to write: template;
* the remaining pairs are served most important first (priority, then salience) until the call cap is used up.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.contracts import BeatChoice, Cohort

DEFAULT_MAX_CALLS = 18


@dataclass(frozen=True)
class Route:
    model: bool
    reason: str


def plan(moments: list[dict], choices: dict[str, BeatChoice], cohorts: list[Cohort], max_calls: int = DEFAULT_MAX_CALLS) -> dict[tuple[str, str], Route]:
    routes: dict[tuple[str, str], Route] = {}
    order = sorted(
        (m for m in moments if (c := choices.get(m["id"])) and c.keep),
        key=lambda m: (choices[m["id"]].priority, -m["salience"]),
    )
    calls = 0
    for m in order:
        for c in cohorts:
            if c.mode == "any":
                routes[m["id"], c.key] = Route(False, "stat graphic: no narrative")
            elif calls >= max_calls:
                routes[m["id"], c.key] = Route(False, f"over the {max_calls}-call cap")
            else:
                routes[m["id"], c.key] = Route(True, "beat")
                calls += 1
    for m in moments:
        for c in cohorts:
            routes.setdefault((m["id"], c.key), Route(False, "not a beat"))
    return routes
