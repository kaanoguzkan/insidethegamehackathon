"""The multi-agent workflow, built on Microsoft Agent Framework's ``WorkflowBuilder``.

    Editor ─▶ Explainer ─▶ Verify ─▶ Storyteller ─▶ Localizer ─▶ Verify ─▶ Producer
                 ▲           │ retry      ▲                          │ retry
                 └───────────┘            └──────────────────────────┘
       (any step failing, timing out or out of budget) ─▶ Template ─▶ Producer

Design rules, learned the hard way while prototyping:

* **Messages are immutable.** A branch that mutates a shared message changes what another edge's
  condition sees; the graph then fires two paths. Every executor sends a fresh ``Beat``.
* **Conditions are mutually exclusive** and keyed on ``Beat.stage``, so exactly one edge fires.
* **Degrade, never drop.** Each step has a deadline; a failure, a timeout or a failed check sends
  the beat down the template path, so the overlay still lands on time.
* **Agents coordinate through the moment store**, not by calling each other.

``fallbackLevel`` on every overlay says how it was made: 0 first-time model text, 1 after a
retry, 2 template text, 3 stat-only.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from agent_framework import Workflow, WorkflowBuilder, WorkflowContext, executor

from ..core.contracts import Cohort, Explanation, Overlay, StoryVariant
from . import producer, templates, verify
from .store import InMemoryMomentStore, MomentStore
from .team import AgentFailure, AgentTeam

MAX_RETRIES = 1
MIN_STEP_BUDGET_S = 0.5  # don't start a model call with less time than this left


@dataclass(frozen=True)
class Batch:
    """Candidate moments the Editor sees together."""

    moments: tuple[dict, ...]
    cohorts: tuple[Cohort, ...]
    budget: int = 3
    budget_s: float = 10.0  # wall-clock time each beat has to become overlays


@dataclass(frozen=True)
class Beat:
    pack: dict
    cohorts: tuple[Cohort, ...]
    stage: str  # edited | ticker | explained | verified | retry | told | localized | retry_story | degrade | ready
    priority: int = 3
    deadline: float = 0.0
    attempt: int = 0  # retries used so far across the beat
    feedback: str = ""
    explanation: Explanation | None = None
    base: tuple[StoryVariant, ...] = ()  # English variants from the Storyteller
    variants: tuple[tuple[str, StoryVariant], ...] = ()  # (cohort key, final variant)
    levels: tuple[tuple[str, int], ...] = ()  # per-cohort fallback level
    agents: tuple[str, ...] = ()
    reason: str = ""
    ticker: bool = False  # the Editor declined it: render a one-line ticker, no model call


@dataclass(frozen=True)
class BeatResult:
    momentId: str
    overlays: tuple[Overlay, ...]
    level: int  # worst fallback level among the overlays
    agents: tuple[str, ...]
    reason: str = ""


@dataclass
class WorkflowDeps:
    team: AgentTeam
    registry: verify.Registry | None = None
    store: MomentStore = field(default_factory=InMemoryMomentStore)
    clock: Callable[[], float] = time.monotonic


def build_workflow(deps: WorkflowDeps) -> Workflow:
    team, store, clock, registry = deps.team, deps.store, deps.clock, deps.registry

    def time_left(b: Beat) -> float:
        return b.deadline - clock()

    def done(b: Beat, agent: str, outcome: str, t0: float, **extra) -> None:
        store.trace(b.pack["id"], agent, outcome, (clock() - t0) * 1000.0, **extra)

    # ---- Editor -------------------------------------------------------------------------------

    @executor(id="editor")
    async def editor(batch: Batch, ctx: WorkflowContext[Beat]):
        t0 = clock()
        moments = list(batch.moments)
        deadline = t0 + batch.budget_s
        try:
            out = await team.edit(moments, budget=batch.budget)
            choices = {c.momentId: c for c in out.beats}
            outcome = "ok"
        except AgentFailure as e:  # the Editor failing must not stop the show: keep by salience
            from .llm import offline_edit

            slim = [{"id": m["id"], "type": m["type"], "salience": m["salience"], "subjectTeam": m["subjectTeam"]} for m in moments]
            choices = {c.momentId: c for c in offline_edit({"moments": slim, "budget": batch.budget}).beats}
            outcome = f"fallback: {e.reason}"
        for m in moments:
            c = choices.get(m["id"])
            keep = c.keep if c else False
            store.put(m["id"], status="selected" if keep else "templated", priority=c.priority if c else 5)
            store.trace(m["id"], "editor", outcome if keep else "not selected", (clock() - t0) * 1000.0)
            await ctx.send_message(
                Beat(pack=m, cohorts=batch.cohorts, stage="edited" if keep else "ticker",
                     priority=c.priority if c else 5, deadline=deadline, agents=("editor",), ticker=not keep)
            )  # fmt: skip

    # ---- Explainer -----------------------------------------------------------------------------

    @executor(id="explain")
    async def explain(b: Beat, ctx: WorkflowContext[Beat]):
        t0 = clock()
        if time_left(b) < MIN_STEP_BUDGET_S:
            await ctx.send_message(replace(b, stage="degrade", reason="out of time before the Explainer"))
            return
        try:
            expl = await team.explain(b.pack, feedback=b.feedback)
        except AgentFailure as e:
            done(b, "explainer", f"failed: {e.reason}", t0)
            await ctx.send_message(replace(b, stage="degrade", reason=str(e), agents=b.agents + ("explainer",)))
            return
        done(b, "explainer", "ok", t0, attempt=b.attempt)
        store.put(b.pack["id"], explanation=expl.model_dump())
        await ctx.send_message(replace(b, stage="explained", explanation=expl, feedback="", agents=b.agents + ("explainer",)))

    @executor(id="verify_explanation")
    async def verify_explanation(b: Beat, ctx: WorkflowContext[Beat]):
        t0 = clock()
        res = verify.verify_explanation(b.explanation, b.pack, registry)
        if res.ok:
            done(b, "verifier", "explanation ok", t0)
            await ctx.send_message(replace(b, stage="verified", agents=b.agents + ("verifier",)))
            return
        done(b, "verifier", "explanation rejected", t0, issues=[str(i) for i in res.errors][:5])
        if b.attempt < MAX_RETRIES and time_left(b) > MIN_STEP_BUDGET_S:
            await ctx.send_message(replace(b, stage="retry", attempt=b.attempt + 1, feedback=res.feedback()))
        else:
            await ctx.send_message(replace(b, stage="degrade", reason="explanation failed verification"))

    # ---- Storyteller and Localizer -------------------------------------------------------------------

    @executor(id="story")
    async def story(b: Beat, ctx: WorkflowContext[Beat]):
        t0 = clock()
        if time_left(b) < MIN_STEP_BUDGET_S:
            await ctx.send_message(replace(b, stage="degrade", reason="out of time before the Storyteller"))
            return
        base_cohorts = sorted({Cohort(mode=c.mode, language="en", perspective=c.perspective, focusPlayer=c.focusPlayer) for c in b.cohorts}, key=lambda c: c.key)
        try:
            out = await team.tell(b.pack, b.explanation, base_cohorts, feedback=b.feedback)
        except AgentFailure as e:
            done(b, "storyteller", f"failed: {e.reason}", t0)
            await ctx.send_message(replace(b, stage="degrade", reason=str(e), agents=b.agents + ("storyteller",)))
            return
        done(b, "storyteller", "ok", t0, cohorts=len(base_cohorts))
        await ctx.send_message(replace(b, stage="told", base=tuple(out.variants), feedback="", agents=b.agents + ("storyteller",)))

    @executor(id="localize")
    async def localize(b: Beat, ctx: WorkflowContext[Beat]):
        import asyncio

        t0 = clock()
        by_key = {v.cohort: v for v in b.base}

        async def one(c: Cohort) -> tuple[str, StoryVariant | None, str]:
            base = by_key.get(Cohort(mode=c.mode, language="en", perspective=c.perspective, focusPlayer=c.focusPlayer).key)
            if base is None:
                return c.key, None, "storyteller returned no variant for this cohort"
            if c.language == "en":
                return c.key, base.model_copy(update={"cohort": c.key}), ""
            if time_left(b) < MIN_STEP_BUDGET_S:
                return c.key, None, "out of time"
            try:
                return c.key, await team.localize(b.pack, base, c), ""
            except AgentFailure as e:
                return c.key, None, e.reason

        results = await asyncio.gather(*(one(c) for c in b.cohorts))
        got = tuple((k, v) for k, v, _ in results if v is not None)
        missing = [k for k, v, _ in results if v is None]
        done(b, "localizer", "ok" if not missing else f"missing {len(missing)}", t0, languages=sorted({c.language for c in b.cohorts}))
        await ctx.send_message(replace(b, stage="localized", variants=got, agents=b.agents + ("localizer",)))

    @executor(id="verify_variants")
    async def verify_variants(b: Beat, ctx: WorkflowContext[Beat]):
        t0 = clock()
        cohorts = {c.key: c for c in b.cohorts}
        kept: list[tuple[str, StoryVariant]] = []
        bad: dict[str, str] = {}
        for key, v in b.variants:
            r = verify.verify_variant(v, b.pack, cohorts[key], registry)
            if r.ok:
                kept.append((key, v))
            else:
                bad[key] = r.feedback()
        have = {k for k, _ in kept}
        for key in cohorts:
            if key not in have and key not in bad:
                bad[key] = "no variant produced"
        done(b, "verifier", "variants ok" if not bad else f"{len(bad)} rejected", t0, rejected=sorted(bad)[:4])
        if bad and b.attempt < MAX_RETRIES and time_left(b) > MIN_STEP_BUDGET_S:
            fb = "\n".join(sorted(set(bad.values())))
            await ctx.send_message(replace(b, stage="retry_story", attempt=b.attempt + 1, feedback=fb))
            return
        levels = tuple((k, 1 if b.attempt else 0) for k, _ in kept)
        variants = list(kept)
        for key in bad:  # per-cohort fallback: only the failing cohorts drop to templates
            variants.append((key, templates.render(b.pack, cohorts[key])))
            levels += ((key, 2),)
        await ctx.send_message(replace(b, stage="ready", variants=tuple(variants), levels=levels, agents=b.agents + ("verifier",)))

    # ---- Template tier -----------------------------------------------------------------------------------

    @executor(id="template")
    async def template(b: Beat, ctx: WorkflowContext[Beat]):
        t0 = clock()
        variants = tuple((c.key, templates.render(b.pack, c)) for c in b.cohorts)
        levels = tuple((c.key, 2) for c in b.cohorts)
        done(b, "template", b.reason or "not selected", t0)
        await ctx.send_message(replace(b, stage="ready", variants=variants, levels=levels, agents=b.agents + ("template",)))

    # ---- Overlay Producer ---------------------------------------------------------------------------------

    @executor(id="producer")
    async def producer_exec(b: Beat, ctx: WorkflowContext[Beat, BeatResult]):
        t0 = clock()
        cohorts = {c.key: c for c in b.cohorts}
        levels = dict(b.levels)
        overlays: list[Overlay] = []
        for key, v in b.variants:
            c, level = cohorts[key], levels.get(key, 2)
            if b.ticker:
                overlays.append(producer.ticker(b.pack, v, c, priority=b.priority))
            else:
                overlays.append(
                    producer.lower_third(
                        b.pack, v, c, priority=b.priority, level=level, agents=list(dict.fromkeys(b.agents)),
                        verified=True, model="agent-team" if level < 2 else "template",
                    )
                )
        worst = max((levels.get(k, 2) for k, _ in b.variants), default=3)
        store.put(b.pack["id"], status="published", level=worst)
        done(b, "producer", f"{len(overlays)} overlays", t0)
        await ctx.yield_output(
            BeatResult(momentId=b.pack["id"], overlays=tuple(overlays), level=worst, agents=tuple(dict.fromkeys(b.agents)), reason=b.reason)
        )

    # ---- The graph ------------------------------------------------------------------------------------------

    wf = (
        WorkflowBuilder(start_executor=editor, name="matchmind-beat", max_iterations=80)
        .add_edge(editor, explain, condition=lambda b: b.stage == "edited")
        .add_edge(editor, template, condition=lambda b: b.stage == "ticker")
        .add_edge(explain, verify_explanation, condition=lambda b: b.stage == "explained")
        .add_edge(explain, template, condition=lambda b: b.stage == "degrade")
        .add_edge(verify_explanation, story, condition=lambda b: b.stage == "verified")
        .add_edge(verify_explanation, explain, condition=lambda b: b.stage == "retry")
        .add_edge(verify_explanation, template, condition=lambda b: b.stage == "degrade")
        .add_edge(story, localize, condition=lambda b: b.stage == "told")
        .add_edge(story, template, condition=lambda b: b.stage == "degrade")
        .add_edge(localize, verify_variants, condition=lambda b: b.stage == "localized")
        .add_edge(verify_variants, producer_exec, condition=lambda b: b.stage == "ready")
        .add_edge(verify_variants, story, condition=lambda b: b.stage == "retry_story")
        .add_edge(template, producer_exec)
        .build()
    )
    return wf


async def run_batch(wf: Workflow, batch: Batch) -> list[BeatResult]:
    result = await wf.run(batch)
    return [o for o in result.get_outputs() if isinstance(o, BeatResult)]
