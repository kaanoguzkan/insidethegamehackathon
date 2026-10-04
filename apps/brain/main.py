"""The Brain: REST API, the Match Data MCP server and the agent workflow in one service.

Runs as an Azure Container App (scales to zero on queue depth); locally it serves the same
endpoints with the offline model, so everything here works with no keys and no network:

    uv run uvicorn apps.brain.main:app --port 8000

    GET  /health                       liveness plus which model client is configured
    GET  /api/matches                  matches that can be queried
    GET  /api/matches/{id}/moments     interpreter moments for a match
    POST /api/beats                    run the agent workflow for chosen moments and cohorts
    GET  /api/director/faults          current model-fault switch
    POST /api/director/faults          set it (none | error | slow | hallucinate), for the resilience demo
    *    /mcp                          Match Data MCP server (streamable HTTP)
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from matchmind import __version__
from matchmind.agents.llm import Faults, make_chat_client
from matchmind.agents.store import InMemoryMomentStore
from matchmind.agents.team import AgentSettings, AgentTeam
from matchmind.agents.verify import Registry
from matchmind.agents.workflow import Batch, WorkflowDeps, build_workflow, run_batch
from matchmind.core.contracts import Cohort
from matchmind.mcp_server.registry import MatchRegistry, UnknownMatch
from matchmind.mcp_server.server import build_server

MAX_COHORTS = 12  # cost guard: text is generated once per cohort, so bound the number per request
MAX_MOMENTS = 6


class BeatRequest(BaseModel):
    match_id: str
    moment_ids: list[str] = Field(min_length=1, max_length=MAX_MOMENTS)
    cohorts: list[Cohort] = Field(min_length=1, max_length=MAX_COHORTS)
    budget: int = Field(3, ge=0, le=MAX_MOMENTS)


class FaultRequest(BaseModel):
    mode: Literal["none", "error", "slow", "hallucinate"] = "none"
    delay_s: float = Field(5.0, ge=0, le=30)
    remaining: int | None = Field(None, ge=0, le=1000)
    every: int = Field(1, ge=1, le=20)


def create_app(registry: MatchRegistry | None = None, llm: str | None = None) -> FastAPI:
    reg = registry or MatchRegistry()
    faults = Faults()
    kind = (llm or os.environ.get("MATCHMIND_LLM", "offline")).lower()
    client = make_chat_client(kind, faults=faults)
    mcp = build_server(reg, path="/")

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="MatchMind Brain", version=__version__, lifespan=lifespan)
    app.mount("/mcp", mcp.streamable_http_app())

    @app.get("/health")
    def health() -> dict:
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

    @app.post("/api/beats")
    async def beats(req: BeatRequest) -> dict:
        ip = _ip(req.match_id)
        by_id = {m["id"]: m for m in ip.all_moments}
        missing = [m for m in req.moment_ids if m not in by_id]
        if missing:
            raise HTTPException(404, f"unknown moments: {missing}")
        store = InMemoryMomentStore()
        deps = WorkflowDeps(team=AgentTeam(client, AgentSettings(timeout_s=8.0)), registry=Registry.from_meta(ip.meta), store=store)
        batch = Batch(moments=tuple(by_id[m] for m in req.moment_ids), cohorts=tuple(req.cohorts), budget=req.budget, budget_s=15.0)
        t0 = time.monotonic()
        results = await run_batch(build_workflow(deps), batch)
        return {
            "elapsedMs": round((time.monotonic() - t0) * 1000),
            "beats": [
                {
                    "momentId": r.momentId, "level": r.level, "agents": list(r.agents),
                    "overlays": [o.model_dump(mode="json") for o in r.overlays],
                    "trace": [{k: v for k, v in s.items() if k in ("agent", "outcome")} for s in store.get(r.momentId).get("trace", [])],
                }
                for r in sorted(results, key=lambda r: r.momentId)
            ],
        }

    @app.get("/api/director/faults")
    def get_faults() -> dict:
        return {"mode": faults.mode, "delay_s": faults.delay_s, "remaining": faults.remaining, "every": faults.every}

    @app.post("/api/director/faults")
    def set_faults(req: FaultRequest) -> dict:
        faults.mode, faults.delay_s, faults.remaining, faults.every, faults._seen = req.mode, req.delay_s, req.remaining, req.every, 0
        return get_faults()

    return app


app = create_app()
