"""The Brain: REST API, the Match Data MCP server and the agent workflow in one service.

Runs as an Azure Container App (scales to zero on queue depth); locally it serves the same
endpoints with the offline model, so everything here works with no keys and no network:

    uv run uvicorn apps.brain.main:app --port 8000

    GET  /health                       liveness plus which model client is configured
    GET  /api/matches                  matches that can be queried
    GET  /api/matches/{id}/moments     interpreter moments for a match
    GET  /api/matches/{id}/analytics   Opta-style analytics (win probability, possession value, networks ...)
    GET  /api/matches/{id}/win-probability
    POST /api/beats                    overlays for chosen moments and cohorts: mode "fast" (default, one model call per
                                       cohort inside deadlineMs, templates for what misses it) or "full" (five-agent workflow)
    GET  /api/director/faults          current model-fault switch (only when MATCHMIND_DIRECTOR=1)
    POST /api/director/faults          set it (none | error | slow | hallucinate), for the resilience demo;
                                       needs the X-Director-Key header if MATCHMIND_DIRECTOR_KEY is set
    *    /mcp                          Match Data MCP server (streamable HTTP)
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
import time
from typing import Literal

from agent_framework import Content, Message
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from matchmind import __version__
from matchmind.agents.cache import BeatCache
from matchmind.agents.fast import run_fast
from matchmind.agents.llm import Faults, make_chat_client
from matchmind.agents.store import InMemoryMomentStore
from matchmind.agents.team import AgentSettings, AgentTeam
from matchmind.agents.verify import Registry
from matchmind.agents.workflow import Batch, WorkflowDeps, build_workflow, run_batch
from matchmind.analytics.report import MatchAnalytics
from matchmind.analytics.season import load_season
from matchmind.core.contracts import Cohort
from matchmind.core.paths import replays_dir
from matchmind.mcp_server.registry import MatchRegistry, UnknownMatch
from matchmind.mcp_server.server import build_server
from matchmind.runner import build_analytics

MAX_COHORTS = 12  # cost guard: text is generated once per cohort, so bound the number per request
MAX_MOMENTS = 6


class BeatRequest(BaseModel):
    match_id: str
    moment_ids: list[str] = Field(min_length=1, max_length=MAX_MOMENTS)
    cohorts: list[Cohort] = Field(min_length=1, max_length=MAX_COHORTS)
    budget: int = Field(3, ge=0, le=MAX_MOMENTS)
    mode: Literal["fast", "full"] = Field(
        "fast", description="fast: one model call per cohort inside deadlineMs, template text for what misses it; full: the five-agent workflow"
    )
    deadlineMs: int = Field(5000, ge=500, le=30000, description="fast mode: wall-clock limit for the whole request")
    useCache: bool = Field(True, description="fast mode: serve and store verified model text in the Brain's cache")


class FaultRequest(BaseModel):
    mode: Literal["none", "error", "slow", "hallucinate"] = "none"
    delay_s: float = Field(5.0, ge=0, le=30)
    remaining: int | None = Field(None, ge=0, le=1000)
    every: int = Field(1, ge=1, le=20)


LOCAL_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"]


def cors_origins() -> list[str]:
    """Browser origins allowed to call the API: the local dev servers, ``MATCHMIND_CORS_ORIGINS`` and the MCP origins."""
    split = lambda v: [x.strip().rstrip("/") for x in v.split(",") if x.strip()]  # noqa: E731
    env = os.environ
    return list(dict.fromkeys([*LOCAL_ORIGINS, *split(env.get("MATCHMIND_CORS_ORIGINS", "")), *split(env.get("MATCHMIND_ALLOWED_ORIGINS", ""))]))


def create_app(
    registry: MatchRegistry | None = None, llm: str | None = None, director: bool | None = None
) -> FastAPI:
    reg = registry or MatchRegistry()
    faults = Faults()
    kind = (llm or os.environ.get("MATCHMIND_LLM", "offline")).lower()
    client = make_chat_client(kind, faults=faults)
    beat_cache = BeatCache()  # verified model text, shared by every request this replica serves
    mcp = build_server(reg, path="/")

    warm_up: list[asyncio.Task] = []

    def start_warm_up() -> None:
        """Once per replica: fetch the managed-identity token and open the model connection, which cost the first real
        request about 3 s. Started at boot and by the first health check (the web page pings it on load)."""
        if warm_up or kind == "offline":
            return

        async def go() -> None:
            try:
                await asyncio.wait_for(client.get_response([Message("user", [Content.from_text("ping")])], options={"max_tokens": 16}), 30)
            except Exception:  # noqa: BLE001 - a failed warm-up only means the first request pays for it
                pass

        warm_up.append(asyncio.ensure_future(go()))

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        start_warm_up()
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="MatchMind Brain", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "x-director-key"], allow_credentials=False, max_age=600,
    )  # the web app on Azure Static Web Apps and GitHub Pages calls this API from the browser
    app.mount("/mcp", mcp.streamable_http_app())

    @app.get("/health")
    async def health() -> dict:
        start_warm_up()
        return {"status": "ok", "llm": kind, "version": __version__, "matches": len(reg.ids())}

    @app.get("/api/matches")
    def matches() -> list[str]:
        return reg.ids()

    def _ip(match_id: str):
        try:
            return reg.get(match_id)
        except UnknownMatch as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/matches/{match_id}/moments")
    def moments(match_id: str, min_salience: float = 0.0) -> list[dict]:
        ip = _ip(match_id)
        return [
            {"id": m["id"], "type": m["type"], "label": m["detectedAt"]["label"], "salience": m["salience"], "team": m["subjectTeam"]}
            for m in ip.all_moments if m["salience"] >= min_salience
        ]  # fmt: skip

    @app.get("/api/matches/{match_id}/analytics")
    def analytics(match_id: str) -> dict:
        """The match's Opta-style analytics (what the replay package stores as analytics.json)."""
        ip = _ip(match_id)
        return build_analytics(ip, load_season(), ip.season, ip.meta)

    @app.get("/api/matches/{match_id}/report.pdf")
    def report(match_id: str) -> FileResponse:
        """The printable match report of a committed replay package (built with ``matchmind build-pdf``)."""
        if match_id not in reg.ids():
            raise HTTPException(404, f"unknown match {match_id!r}")
        pdf = replays_dir() / match_id / "report.pdf"
        if not pdf.exists():
            raise HTTPException(404, "no report built for this match; run: matchmind build-pdf " + match_id)
        return FileResponse(pdf, media_type="application/pdf", filename=f"{match_id}-report.pdf")

    @app.get("/api/matches/{match_id}/win-probability")
    def win_probability(match_id: str) -> dict:
        return MatchAnalytics(_ip(match_id)).win_probability()

    @app.post("/api/beats")
    async def beats(req: BeatRequest) -> dict:
        ip = _ip(req.match_id)
        by_id = {m["id"]: m for m in ip.all_moments}
        missing = [m for m in req.moment_ids if m not in by_id]
        if missing:
            raise HTTPException(404, f"unknown moments: {missing}")
        store = InMemoryMomentStore()
        settings = AgentSettings.from_env()
        deps = WorkflowDeps(team=AgentTeam(client, settings), registry=Registry.from_meta(ip.meta), store=store)
        batch = Batch(moments=tuple(by_id[m] for m in req.moment_ids), cohorts=tuple(req.cohorts), budget=req.budget, budget_s=min(settings.beat_budget_s or 15.0, 90.0))
        t0 = time.monotonic()
        run_stats: dict = {}
        if req.mode == "fast":
            results = await run_fast(
                deps.team, batch, deadline_s=req.deadlineMs / 1000.0, registry=deps.registry, store=store,
                cache=beat_cache if req.useCache else None, stats=run_stats,
            )
        else:
            results = await run_batch(build_workflow(deps), batch)
        return {
            "mode": req.mode,
            "stats": {**run_stats, "cacheSize": len(beat_cache)} if req.mode == "fast" else None,
            "elapsedMs": round((time.monotonic() - t0) * 1000),
            "beats": [
                {
                    "momentId": r.momentId, "level": r.level, "agents": list(r.agents),
                    "overlays": [o.model_dump(mode="json") for o in r.overlays],
                    "trace": [{k: v for k, v in s.items() if k in ("agent", "outcome", "ms")} for s in store.get(r.momentId).get("trace", [])],
                }
                for r in sorted(results, key=lambda r: r.momentId)
            ],
        }

    # The fault switch degrades the model for every caller, so it is off unless explicitly enabled
    # (MATCHMIND_DIRECTOR=1 or director=True) and, when MATCHMIND_DIRECTOR_KEY is set, key-protected.
    if director if director is not None else os.environ.get("MATCHMIND_DIRECTOR") == "1":

        def require_director(x_director_key: str | None = Header(None)) -> None:
            key = os.environ.get("MATCHMIND_DIRECTOR_KEY")
            if key and not hmac.compare_digest(x_director_key or "", key):
                raise HTTPException(403, "director key required")

        @app.get("/api/director/faults", dependencies=[Depends(require_director)])
        def get_faults() -> dict:
            return {"mode": faults.mode, "delay_s": faults.delay_s, "remaining": faults.remaining, "every": faults.every}

        @app.post("/api/director/faults", dependencies=[Depends(require_director)])
        def set_faults(req: FaultRequest) -> dict:
            faults.mode, faults.delay_s, faults.remaining, faults.every, faults._seen = req.mode, req.delay_s, req.remaining, req.every, 0
            return get_faults()

    return app


app = create_app()
