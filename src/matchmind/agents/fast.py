"""The fast path: overlays for a batch of moments inside a hard deadline (a few seconds).

The full workflow (``workflow.py``) chains five model calls, and each takes seconds, so a beat needs tens of
seconds. This path trades the chain for one call per cohort:

    rule-based Editor ─▶ Composer (one call per moment and cohort, all in parallel) ─▶ Verify ─▶ Producer
                              │ late, failing or rejected
                              └──▶ template text, computed up front

* Template text is rendered first for every cohort, so there is always a verified answer to return.
* The model calls run concurrently and share one deadline. Whatever has not finished when it passes is cancelled.
* A model variant replaces its template only if the verifier accepts it (fallback level 0); there is no retry,
  because there is no time for one.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from ..core.contracts import Cohort, Overlay, StoryVariant
from . import producer, templates, verify
from .llm import offline_edit
from .store import InMemoryMomentStore, MomentStore
from .team import AgentFailure, AgentTeam
from .workflow import Batch, BeatResult

MIN_CALL_S = 0.3  # a model call with less time than this left cannot finish


async def run_fast(
    team: AgentTeam,
    batch: Batch,
    *,
    deadline_s: float,
    registry: verify.Registry | None = None,
    store: MomentStore | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[BeatResult]:
    store = store if store is not None else InMemoryMomentStore()
    t0 = clock()
    deadline = t0 + deadline_s
    moments = list(batch.moments)
    slim = [{"id": m["id"], "type": m["type"], "salience": m["salience"], "subjectTeam": m["subjectTeam"]} for m in moments]
    choices = {c.momentId: c for c in offline_edit({"moments": slim, "budget": batch.budget}).beats}
    cohorts = {c.key: c for c in batch.cohorts}

    final: dict[tuple[str, str], StoryVariant] = {}  # (moment, cohort) -> variant, templates first
    level: dict[tuple[str, str], int] = {}
    kept = [m for m in moments if (c := choices.get(m["id"])) and c.keep]
    for m in moments:
        store.trace(m["id"], "editor", "rule-based" if m in kept else "not selected", 0.0)
        for key, c in cohorts.items():
            final[m["id"], key] = templates.render(m, c)
            level[m["id"], key] = 2

    async def compose(m: dict, c: Cohort) -> None:
        start = clock()
        left = deadline - start
        if left < MIN_CALL_S:
            store.trace(m["id"], "composer", f"skipped: {c.key}", 0.0)
            return
        try:
            v = (await team.compose(m, c, timeout_s=left)).model_copy(update={"cohort": c.key})
        except AgentFailure as e:
            store.trace(m["id"], "composer", f"failed: {c.key}: {e.reason}"[:200], (clock() - start) * 1000.0)
            return
        res = verify.verify_variant(v, m, c, registry)
        if not res.ok:
            store.trace(m["id"], "verifier", f"rejected: {c.key}: {'; '.join(str(i) for i in res.errors[:3])}"[:240], 0.0)
            return
        final[m["id"], c.key], level[m["id"], c.key] = v, 0
        store.trace(m["id"], "composer", f"ok: {c.key}", (clock() - start) * 1000.0)

    tasks = [asyncio.ensure_future(compose(m, c)) for m in kept for c in cohorts.values()]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=max(deadline - clock(), 0.0))
        for t in pending:  # the deadline passed: these cohorts keep their template text
            t.cancel()
        for m in kept:
            store.trace(m["id"], "producer", f"{len(pending)} model calls missed the deadline" if pending else "all model calls in time", 0.0)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    results: list[BeatResult] = []
    for m in moments:
        c = choices.get(m["id"])
        is_beat = bool(c and c.keep)
        priority = c.priority if c else 5
        overlays: list[Overlay] = []
        worst = 0
        for key, cohort in cohorts.items():
            v, lv = final[m["id"], key], level[m["id"], key]
            if not is_beat:
                overlays.append(producer.ticker(m, v, cohort, priority=priority))
                worst = 2
                continue
            ok = verify.verify_variant(v, m, cohort, registry).ok  # "verified" is earned here, not assumed
            agents = ["editor", "composer", "verifier"] if lv < 2 else ["editor", "template"]
            overlays.append(
                producer.lower_third(
                    m, v, cohort, priority=priority, level=lv, agents=agents, verified=ok,
                    model="agent-team" if lv < 2 else "template",
                )
            )
            worst = max(worst, lv)
        results.append(
            BeatResult(momentId=m["id"], overlays=tuple(overlays), level=worst, agents=("editor", "composer", "verifier", "producer"))
        )
    return results
