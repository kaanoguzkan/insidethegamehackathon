"""The fast path: overlays for a batch of moments inside a hard deadline (a few seconds).

The full workflow (``workflow.py``) chains five model calls, and each takes seconds, so a beat needs tens of
seconds. This path trades the chain for one call per cohort, and puts rule-based agents around it:

    Editor (rules) ─▶ Router (rules) ─▶ Cache ─hit──────────────────────────────────────────┐
                                           │ miss                                            │
                                           └▶ Composer (model, one call per moment+cohort) ─▶ Verifier ─pass─▶ Cache ─┤
                                                  │ late / failed          │ reject                                  │
                                                  │                        └▶ Repairer (rules) ─▶ Verifier ─pass─────┤
                                                  └────────────────────────────────────────────▶ Template ◀─ fail ───┤
                                                                                                         Producer ◀──┘

* Template text is rendered first for every cohort, so there is always a verified answer to return.
* Model calls run concurrently and share one deadline. Whatever has not finished when it passes is cancelled.
* Text the Verifier rejects is mended by the Repairer rather than discarded; it counts as fallback level 1.
* There is no retry, because there is no time for one.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from collections.abc import Awaitable, Callable

from ..core.contracts import Cohort, Overlay, StoryVariant
from . import producer, repair, router, templates, verify
from .cache import BeatCache, Cached
from .llm import offline_edit
from .prompts import PROMPT_VERSION
from .store import InMemoryMomentStore, MomentStore
from .team import AgentFailure, AgentTeam
from .workflow import Batch, BeatResult

MIN_CALL_S = 0.3  # a model call with less time than this left cannot finish
_WINDING_DOWN: set[asyncio.Future] = set()  # cancelled calls still stopping; held so they are not garbage collected


def _wound_down(t: asyncio.Future) -> None:
    _WINDING_DOWN.discard(t)
    if not t.cancelled():
        t.exception()  # retrieved, so a late failure is not reported as never retrieved


# Measured on the live Brain: a call takes about 2.0 s (median) and 3.7 s (95th percentile). Hedging at 2.2 s duplicated about half of
# all calls (about 50% more tokens); at 3.2 s only the slow tail is hedged and a second call still has time to finish.
HEDGE_AFTER_S = float(os.environ.get("MATCHMIND_HEDGE_S", "3.2"))  # 0 turns hedging off


async def _cache_get(cache, key):  # noqa: ANN001, ANN202
    """A hit from either kind of cache: the in-memory one answers directly, the shared one is awaited."""
    if cache is None:
        return None
    r = cache.get(key)
    return await r if inspect.isawaitable(r) else r


async def _cache_put(cache, key, value) -> None:  # noqa: ANN001
    r = cache.put(key, value)
    if inspect.isawaitable(r):
        await r


async def _hedged(call: Callable[[float], Awaitable[StoryVariant]], first_budget: float, hedge_after_s: float, deadline: float, clock: Callable[[], float], stats: dict) -> StoryVariant:
    """The model's answer, asking twice if the first call is slow: the service's latency varies by a second or more
    from call to call, so a second request started part-way through often beats a slow first one. The loser is cancelled."""
    first = asyncio.ensure_future(call(first_budget))
    tasks = {first}
    try:
        if 0 < hedge_after_s < first_budget:
            await asyncio.wait(tasks, timeout=hedge_after_s)
            if not first.done() and deadline - clock() > MIN_CALL_S:
                stats["hedged"] = stats.get("hedged", 0) + 1
                tasks.add(asyncio.ensure_future(call(deadline - clock())))
        failure: AgentFailure | None = None
        while tasks:
            done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                try:
                    return d.result()
                except AgentFailure as e:
                    failure = e
        raise failure or AgentFailure("composer", "no answer")
    finally:
        for t in (first, *tasks):
            if not t.done():
                t.cancel()


async def _run_fast(
    team: AgentTeam,
    batch: Batch,
    *,
    deadline_s: float,
    registry: verify.Registry | None = None,
    store: MomentStore | None = None,
    cache: BeatCache | None = None,
    stats: dict | None = None,
    model_id: str | None = None,
    max_calls: int = router.DEFAULT_MAX_CALLS,
    hedge_after_s: float = HEDGE_AFTER_S,
    clock: Callable[[], float] = time.monotonic,
) -> list[BeatResult]:
    store = store if store is not None else InMemoryMomentStore()
    stats = stats if stats is not None else {}
    stats.update(cacheHits=0, modelCalls=0, hedged=0, repaired=0, rejected=0, missedDeadline=0)
    model_id = model_id or os.environ.get("MATCHMIND_LLM_MODEL", "offline")
    t0 = clock()
    deadline = t0 + deadline_s
    moments = list(batch.moments)
    match_id = moments[0]["matchId"] if moments else ""
    slim = [{"id": m["id"], "type": m["type"], "salience": m["salience"], "subjectTeam": m["subjectTeam"]} for m in moments]
    choices = {c.momentId: c for c in offline_edit({"moments": slim, "budget": batch.budget}).beats}
    cohorts = {c.key: c for c in batch.cohorts}
    kept = [m for m in moments if (c := choices.get(m["id"])) and c.keep]
    routes = router.plan(moments, choices, list(cohorts.values()), max_calls)

    final: dict[tuple[str, str], StoryVariant] = {}  # (moment, cohort) -> variant, templates first
    level: dict[tuple[str, str], int] = {}
    made_by: dict[tuple[str, str], list[str]] = {}
    for m in moments:
        store.trace(m["id"], "editor", "rule-based" if m in kept else "not selected", 0.0)
        for key, c in cohorts.items():
            final[m["id"], key] = templates.render(m, c)
            level[m["id"], key] = 2
            made_by[m["id"], key] = ["template"]
        n = sum(1 for k in cohorts if routes[m["id"], k].model)
        store.trace(m["id"], "router", f"{n} of {len(cohorts)} cohorts to the model", 0.0)

    async def compose(m: dict, c: Cohort) -> None:
        mk = (m["id"], c.key)
        start = clock()
        ck = BeatCache.key(match_id, m["id"], c.key, model_id, PROMPT_VERSION)
        hit = await _cache_get(cache, ck)
        if hit is not None:
            final[mk], level[mk], made_by[mk] = hit.variant, hit.level, ["cache", *hit.agents]
            stats["cacheHits"] += 1
            store.trace(m["id"], "cache", f"hit: {c.key}", (clock() - start) * 1000.0)
            return
        left = deadline - start
        if left < MIN_CALL_S:
            store.trace(m["id"], "composer", f"skipped: {c.key}", 0.0)
            return
        stats["modelCalls"] += 1
        try:
            v = (await _hedged(lambda budget: team.compose(m, c, timeout_s=budget), left, hedge_after_s, deadline, clock, stats)).model_copy(update={"cohort": c.key})
        except AgentFailure as e:
            store.trace(m["id"], "composer", f"failed: {c.key}: {e.reason}"[:200], (clock() - start) * 1000.0)
            return
        store.trace(m["id"], "composer", f"ok: {c.key}", (clock() - start) * 1000.0)
        agents = ["composer", "verifier"]
        lv = 0
        res = verify.verify_variant(v, m, c, registry)
        if not res.ok:
            fixed = repair.repair(v, m, c, registry)
            if fixed is None:
                stats["rejected"] += 1
                store.trace(m["id"], "verifier", f"rejected: {c.key}: {'; '.join(str(i) for i in res.errors[:3])}"[:240], 0.0)
                return
            v, lv, agents = fixed.variant, 1, ["composer", "verifier", "repairer"]
            stats["repaired"] += 1
            store.trace(m["id"], "repairer", f"mended: {c.key}: {', '.join(fixed.actions)}"[:240], 0.0)
        final[mk], level[mk], made_by[mk] = v, lv, agents
        if cache is not None:
            await _cache_put(cache, ck, Cached(v, lv, tuple(agents)))

    tasks = [asyncio.ensure_future(compose(m, c)) for m in kept for c in cohorts.values() if routes[m["id"], c.key].model]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=max(deadline - clock(), 0.0))
        stats["missedDeadline"] = len(pending)
        if pending:
            print(f"WARN {len(pending)} model call(s) passed the {deadline_s:g}s deadline; template text is served", flush=True)
        for t in pending:  # the deadline passed: these cohorts keep their template text
            t.cancel()
            _WINDING_DOWN.add(t)  # a stalled model call can be slow to stop: never hold the response for it
            t.add_done_callback(_wound_down)
        for m in kept:
            store.trace(m["id"], "producer", f"{len(pending)} model calls missed the deadline" if pending else "all model calls in time", 0.0)

    results: list[BeatResult] = []
    for m in moments:
        c = choices.get(m["id"])
        is_beat = bool(c and c.keep)
        priority = c.priority if c else 5
        overlays: list[Overlay] = []
        worst = 0
        seen: list[str] = []
        for key, cohort in cohorts.items():
            v, lv = final[m["id"], key], level[m["id"], key]
            if not is_beat:
                overlays.append(producer.ticker(m, v, cohort, priority=priority))
                worst = 2
                continue
            ok = verify.verify_variant(v, m, cohort, registry).ok  # "verified" is earned here, not assumed
            agents = ["editor", "router", *made_by[m["id"], key]]
            seen += agents
            overlays.append(
                producer.lower_third(
                    m, v, cohort, priority=priority, level=lv, agents=agents, verified=ok,
                    model="agent-team" if lv < 2 else "template",
                )
            )
            worst = max(worst, lv)
        results.append(BeatResult(momentId=m["id"], overlays=tuple(overlays), level=worst, agents=tuple(dict.fromkeys([*seen, "producer"]))))
    return results


async def run_fast(team: AgentTeam, batch: Batch, **kw) -> list[BeatResult]:
    """:func:`_run_fast` inside a trace span carrying the batch's numbers (a no-op without a tracing setup)."""
    from opentelemetry import trace

    stats = kw.setdefault("stats", {})
    with trace.get_tracer("matchmind.fast").start_as_current_span("matchmind.beats") as span:
        span.set_attribute("matchmind.moments", len(batch.moments))
        span.set_attribute("matchmind.cohorts", len(batch.cohorts))
        span.set_attribute("matchmind.deadline_s", kw.get("deadline_s", 0.0))
        results = await _run_fast(team, batch, **kw)
        for k, v in stats.items():
            span.set_attribute(f"matchmind.{k}", v)
        levels = [o.provenance.fallbackLevel for r in results for o in r.overlays if o.kind == "lower_third"]
        for lv in (0, 1, 2):
            span.set_attribute(f"matchmind.overlays_level{lv}", levels.count(lv))
        return results
