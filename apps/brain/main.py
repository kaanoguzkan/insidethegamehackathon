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
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Literal

from agent_framework import Content, Message
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from matchmind import __version__
from matchmind.agents.ask import MAX_QUESTION_CHARS
from matchmind.agents.ask import ask as ask_the_match
from matchmind.agents.cache import BeatCache, SharedBeatCache
from matchmind.agents.llm import Faults, make_chat_client
from matchmind.agents.recap import write_recap
from matchmind.agents.service import (  # noqa: F401
    MAX_COHORTS,
    MAX_MOMENTS,
    BeatRequest,
    InvalidCohort,
    UnknownMoments,
    load_recorded,
    read_recorded,
    serve_beats,
)
from matchmind.agents.team import AgentSettings, AgentTeam
from matchmind.agents.verify import Registry
from matchmind.analytics.report import MatchAnalytics
from matchmind.analytics.season import load_season
from matchmind.core.paths import replays_dir
from matchmind.demos import load_demos
from matchmind.guards import ADMIN_HEADER, PUBLIC_MAX_DEADLINE_MS, RateLimitMiddleware, is_admin
from matchmind.live.api import ContainerAppsJobStarter
from matchmind.live.api import make_router as make_live_router
from matchmind.live.blobs import Blobs
from matchmind.live.channel import Channel
from matchmind.live.dispatch import write_beats
from matchmind.live.season import SeasonStore
from matchmind.live.season_api import make_season_router
from matchmind.live.season_job import create_season, make_season_store, run_worker
from matchmind.live.session import StreamHub
from matchmind.live.simulator import make_blobs as make_live_blobs
from matchmind.live.simulator import make_store as make_live_store
from matchmind.live.simulator import run as run_simulator
from matchmind.live.store import LiveStore
from matchmind.live.stream_api import make_stream_router
from matchmind.mcp_server.registry import MatchRegistry, UnknownMatch, preload
from matchmind.mcp_server.server import build_server
from matchmind.ops import ops
from matchmind.runner import build_analytics
from matchmind.telemetry import setup_tracing


class AskRequest(BaseModel):
    match_id: str
    question: str = Field(min_length=2, max_length=MAX_QUESTION_CHARS + 120)  # shaped and cut to MAX_QUESTION_CHARS before it reaches a prompt
    language: Literal["en", "es", "tr"] = "en"
    mode: Literal["analyst", "casual"] = "casual"
    minute: float | None = Field(None, ge=0, le=130, description="where the viewer is in the match; the planner is told, answers may still use the whole match")


class LiveAskRequest(BaseModel):
    streamId: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    question: str = Field(min_length=2, max_length=MAX_QUESTION_CHARS + 120)
    language: Literal["en", "es", "tr"] = "en"
    mode: Literal["analyst", "casual"] = "casual"
    atMs: int = Field(ge=0, le=8_000_000, description="where the viewer is in the match, in match milliseconds: nothing after it is used")


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


def make_beat_cache() -> BeatCache | SharedBeatCache:
    """The in-memory cache, with Cosmos DB behind it (shared by replicas, kept across restarts) when asked for."""
    local = BeatCache()
    if os.environ.get("MATCHMIND_SHARED_CACHE") != "1" or not os.environ.get("COSMOS_ENDPOINT"):
        return local

    async def open_container():  # noqa: ANN202
        from azure.cosmos.aio import CosmosClient
        from azure.identity.aio import DefaultAzureCredential

        client = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=DefaultAzureCredential())
        return client.get_database_client("matchmind").get_container_client("beats")

    return SharedBeatCache(local, open_container)


def create_app(
    registry: MatchRegistry | None = None, llm: str | None = None, director: bool | None = None, live_store: LiveStore | None = None,
    live_frames: Blobs | None = None, season_store: SeasonStore | None = None, live_packs: Blobs | None = None, stream_hub_override: StreamHub | None = None,
) -> FastAPI:
    reg = registry or MatchRegistry()
    faults = Faults()
    kind = (llm or os.environ.get("MATCHMIND_LLM", "offline")).lower()
    client = make_chat_client(kind, faults=faults)
    beat_cache = make_beat_cache()  # verified model text: in memory, and in Cosmos DB when MATCHMIND_SHARED_CACHE=1
    mcp = build_server(reg, path="/")

    # MATCHMIND_AGENTS=foundry: the agents are the ones registered in the Foundry project (`matchmind foundry-register`),
    # called by name, instead of local ones built from the same prompts. They are built once and shared.
    want_foundry_agents = kind == "foundry" and os.environ.get("MATCHMIND_AGENTS", "").lower() == "foundry"
    team_cache: list[AgentTeam] = []
    agents_mode = ["foundry" if want_foundry_agents else "local"]  # what /health reports

    def get_team() -> AgentTeam:
        """Built once and shared. With Foundry agents wanted but stale or missing, the local agents answer and /health says so."""
        if not team_cache:
            team = None
            if want_foundry_agents:
                from matchmind.foundry_agents import foundry_team

                team, problems = foundry_team(client)
                if team is None:
                    agents_mode[0] = "local (Foundry agents stale or missing: run `matchmind foundry-register`)"
                    print(f"WARN Foundry agents not used: {'; '.join(problems)}", flush=True)
            team_cache.append(team or AgentTeam(client, AgentSettings.from_env()))
        return team_cache[0]

    preloading: list[asyncio.Future] = []

    def start_preload(delay_s: float = 0.0) -> None:
        """Load the matches the tools use, in the background, once. Started at boot and, with no delay, by the first health check."""
        if preloading or os.environ.get("MATCHMIND_PRELOAD") != "1":
            return
        preloading.append(asyncio.ensure_future(preload(reg, delay_s=delay_s)))

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
            if isinstance(beat_cache, SharedBeatCache):
                await beat_cache.warm()  # the first Cosmos call is slow (token, account discovery): do it before a request needs it

        warm_up.append(asyncio.ensure_future(go()))

    async def watch_loop() -> None:
        """Logs when something blocks the event loop (a synchronous call inside async code): every request then waits."""
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.25)
            now = time.monotonic()
            if now - last > 1.0:
                print(f"WARN event loop was blocked for {now - last:.1f}s", flush=True)
            last = now

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        start_warm_up()
        start_preload(float(os.environ.get("MATCHMIND_PRELOAD_DELAY_S", "10")))
        if os.environ.get("MATCHMIND_PRELOAD") == "1":  # simulate the demo matches a viewer can kick off, so the first Kick off does not wait for it
            async def preload_streams() -> None:
                await asyncio.sleep(float(os.environ.get("MATCHMIND_PRELOAD_DELAY_S", "10")) + 5.0)
                await asyncio.to_thread(app.state.stream_hub.preload, list(load_demos()))

            asyncio.ensure_future(preload_streams())
        for mid in reg.ids():  # read the packs now, in a thread, so the first request does not wait for them
            asyncio.ensure_future(asyncio.to_thread(beat_inputs, mid))
        watcher = asyncio.ensure_future(watch_loop())
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            watcher.cancel()

    for noisy in ("azure", "httpx", "httpcore"):  # the Azure SDK logs every request and its headers at INFO: ingestion cost, no value
        logging.getLogger(noisy).setLevel(logging.WARNING)
    setup_tracing()  # before the app object exists, so its requests are instrumented
    app = FastAPI(title="MatchMind Brain", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-director-key", ADMIN_HEADER], allow_credentials=False, max_age=600,
    )  # the web app on Azure Static Web Apps and GitHub Pages calls this API from the browser
    app.add_middleware(
        RateLimitMiddleware,
        rules=[
            ("/api/beats", "POST", int(os.environ.get("MATCHMIND_BEATS_PER_MIN", "20")), 60.0),
            ("/api/live/start", "POST", int(os.environ.get("MATCHMIND_LIVE_START_PER_MIN", "3")), 60.0),
            ("/api/season/simulate", "POST", 2, 60.0),
            ("/api/channel/tune", "POST", 20, 60.0),
            ("/api/live", "GET", int(os.environ.get("MATCHMIND_LIVE_POLL_PER_MIN", "240")), 60.0),  # a viewer polls the feed about once a second
            ("/api/stream/", "POST", int(os.environ.get("MATCHMIND_STREAM_CHANGE_PER_MIN", "60")), 60.0),  # speed and profile changes of a running match
            ("/api/stream", "POST", int(os.environ.get("MATCHMIND_STREAM_START_PER_MIN", "6")), 60.0),
            ("/api/stream", "GET", int(os.environ.get("MATCHMIND_STREAM_POLL_PER_MIN", "900")), 60.0),  # the feed once a second, and the tracking chunks of up to 10x speed
            ("/api/ask", "POST", int(os.environ.get("MATCHMIND_ASK_PER_MIN", "10")), 60.0),
            ("/mcp", None, int(os.environ.get("MATCHMIND_MCP_PER_MIN", "60")), 60.0),
        ],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN202
        t0 = time.monotonic()
        resp = await call_next(request)
        ops.record_request(request.url.path, resp.status_code, (time.monotonic() - t0) * 1000)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    app.mount("/mcp", mcp.streamable_http_app())

    @app.get("/health")
    async def health(match: str | None = None) -> dict:
        """Liveness and configuration. ``?match=<id>`` says the match center is open on that match: its data is loaded first, and ``loaded``
        tells the page when a tool call on it will be instant."""
        start_warm_up()
        if match:
            reg.want(match)
        start_preload(0.0)  # a replica that was just woken by this very call starts loading now, not after the boot delay
        return {"loaded": reg.loaded(), "status": "ok", "llm": kind, "agents": agents_mode[0], "sharedCache": beat_cache.status() if isinstance(beat_cache, SharedBeatCache) else {"enabled": False}, "version": __version__, "matches": len(reg.ids())}

    @app.get("/api/ops")
    async def operations() -> dict:
        """What the service did in the last fifteen minutes and how it stands now: request latency and errors, how stories were made (model, repaired, template),
        how much the verifier let through, the cache, and how busy the live matches are. Public and read-only: nothing in it identifies a viewer."""
        hub = app.state.stream_hub
        return {
            **ops.snapshot(),
            "streams": hub.status(),
            "model": {"client": kind, "agents": agents_mode[0], "name": os.environ.get("MATCHMIND_LLM_MODEL", "")},
            "cache": beat_cache.status() if isinstance(beat_cache, SharedBeatCache) else {"enabled": False},
            "version": __version__, "region": os.environ.get("AZURE_LOCATION", ""),
        }

    @app.get("/ready")
    async def ready() -> Response:
        """Whether this replica can do its job now: the matches are known, a model client is configured, the shared cache (when there is one) is reachable.
        Answers 503 with the reason when not, so a load balancer or an availability test can act on it."""
        checks = {"matches": len(reg.ids()) > 0, "model": kind != "offline" or os.environ.get("MATCHMIND_ALLOW_OFFLINE") == "1"}
        if isinstance(beat_cache, SharedBeatCache):
            st = beat_cache.status()
            checks["sharedCache"] = bool(st.get("connected")) or not st.get("enabled")
        ok = all(checks.values())
        return Response(json.dumps({"ready": ok, "checks": checks}), status_code=200 if ok else 503, media_type="application/json")

    # The live pipeline: a simulator job writes a match's feed to Cosmos DB, Functions interpret it and ask this Brain for the narrative overlays,
    # viewers poll the feed below. See docs/live-pipeline.md.
    live_holder: list[LiveStore] = [live_store] if live_store is not None else []

    def get_live_store() -> LiveStore:
        if not live_holder:
            live_holder.append(make_live_store())
        return live_holder[0]

    frames_holder: list[Blobs] = [live_frames] if live_frames is not None else []

    def get_live_frames() -> Blobs:
        if not frames_holder:
            frames_holder.append(make_live_blobs("frames"))
        return frames_holder[0]

    season_holder: list[SeasonStore] = [season_store] if season_store is not None else []
    packs_holder: list[Blobs] = [live_packs] if live_packs is not None else []
    channel_holder: list[Channel] = []

    def get_seasons() -> SeasonStore:
        if not season_holder:
            season_holder.append(make_season_store())
        return season_holder[0]

    def get_packs() -> Blobs:
        if not packs_holder:
            packs_holder.append(make_live_blobs("packs"))
        return packs_holder[0]

    def get_channel() -> Channel:
        if not channel_holder:
            channel_holder.append(Channel(get_live_store(), get_seasons(), get_packs(), get_live_frames(), speed=float(os.environ.get("LIVE_SPEED", "5"))))
        return channel_holder[0]

    def run_season_job(season_id: str) -> None:
        """Simulate a season: the season Container Apps Job (several replicas claim fixtures), or threads of this process on a laptop and in tests."""
        job = os.environ.get("SEASON_JOB_ID")
        if job:
            ContainerAppsJobStarter(job, 0.0).run({"SEASON_ID": season_id})
            return
        import threading

        for i in range(3):
            threading.Thread(target=run_worker, args=(season_id, get_seasons(), get_packs(), f"local-{i}"), daemon=True).start()

    def ensure_default_season() -> None:
        """A site with no season yet (a fresh deployment) plans the default one and has it simulated, so the first visitor is not met by nothing."""
        seasons = get_seasons()
        if seasons.current() is None:
            create_season(seasons, "season-1", 1, featured=True)
            seasons.set_current("season-1")
            run_season_job("season-1")

    def live_starter() -> ContainerAppsJobStarter | None:
        job = os.environ.get("LIVE_JOB_ID")
        return ContainerAppsJobStarter(job, float(os.environ.get("LIVE_SPEED", "5"))) if job else None

    def live_in_process(match_id: str, scenario: str, from_minute: float) -> None:
        import threading

        threading.Thread(
            target=run_simulator, daemon=True,
            kwargs={"scenario_name": scenario, "speed": float(os.environ.get("LIVE_SPEED", "5")), "from_minute": from_minute, "match_id": match_id, "store": get_live_store()},
        ).start()

    in_process_ok = live_store is not None or os.environ.get("MATCHMIND_LIVE_LOCAL") == "1"  # tests and a laptop: no job, play it in this process
    app.include_router(make_live_router(get_live_store, get_team, beat_cache, live_starter, live_in_process if in_process_ok else None, get_live_frames))
    # Stream sessions: a match of your own, played and interpreted in this process (docs/live-pipeline.md, "Streams").
    stream_loop: list[asyncio.AbstractEventLoop] = []

    def stream_dispatch(store, sid, moment_ids, cohorts):  # noqa: ANN001, ANN202
        if not stream_loop:
            return None

        async def beats() -> dict:
            team = await asyncio.to_thread(get_team)
            return await write_beats(store, sid, moment_ids, team=team, cache=beat_cache, cohorts=cohorts)

        return asyncio.run_coroutine_threadsafe(beats(), stream_loop[0])

    def stream_recap(store, sid, kind, pack, cohorts):  # noqa: ANN001, ANN202
        if not stream_loop:
            return None

        async def write() -> None:
            team = await asyncio.to_thread(get_team)
            registry = Registry.from_meta(store.get_match(sid)["meta"])
            moments = {m["id"]: m for m in store.moments(sid)}
            for c in cohorts:
                r = await write_recap(team, pack, c, moments, registry)
                store.put_state(sid, "recaps", [*store.get_state(sid, "recaps", []), r.model_dump(mode="json")])  # no await between the read and the write

        return asyncio.run_coroutine_threadsafe(write(), stream_loop[0])

    stream_hub = stream_hub_override or StreamHub(dispatch=stream_dispatch, recap=stream_recap, max_sessions=int(os.environ.get("STREAM_MAX_SESSIONS", "12")))
    app.include_router(make_stream_router(stream_hub, lambda loop: stream_loop.append(loop) if not stream_loop else None))
    app.state.stream_hub = stream_hub
    stream_hub.on_release.append(reg.forget)
    season_ok = bool(os.environ.get("SEASON_JOB_ID")) or in_process_ok or season_store is not None
    app.include_router(make_season_router(get_channel, get_seasons, get_live_store, run_season_job if season_ok else None, ensure_default_season if season_ok else None))

    @app.get("/api/matches")
    def matches() -> list[str]:
        return reg.ids()

    def _ip(match_id: str):
        try:
            return reg.get(match_id)
        except UnknownMatch as e:
            raise HTTPException(404, str(e)) from e

    beat_data: dict[str, tuple[dict[str, dict], Registry]] = {}
    recorded_files: dict[tuple[str, str], Any] = {}

    def beat_inputs(match_id: str) -> tuple[dict[str, dict], Registry]:
        """The moment packs and the name registry /api/beats needs, without loading the match's interpreter.

        ``reg.get`` re-simulates the match from its seed: about 6 s on a laptop and about 20 s on the 1-vCPU container,
        and doing that inside the request froze the whole server (the 5 s deadline included). The replay package already
        holds the finished packs and metadata, so read those; a match with no package on disk (one registered in
        memory) falls back to the interpreter. Called from a worker thread.
        """
        if match_id in beat_data:
            return beat_data[match_id]
        if match_id not in reg.ids():
            raise HTTPException(404, f"unknown match {match_id!r}")
        out = load_recorded(reg.root, match_id)
        if out is None:
            ip = _ip(match_id)
            out = ({m["id"]: m for m in ip.all_moments}, Registry.from_meta(ip.meta))
        beat_data[match_id] = out
        return out

    def recorded(match_id: str, name: str) -> Any | None:
        """A file of the match's replay package, parsed once. None when the match has no package (then the interpreter
        answers). The package is identical to what the interpreter computes (checked), and reading it takes
        milliseconds where the interpreter takes seconds to load."""
        if match_id not in reg.ids():
            raise HTTPException(404, f"unknown match {match_id!r}")
        key = (match_id, name)
        if key not in recorded_files:
            recorded_files[key] = read_recorded(reg.root, match_id, name)
        return recorded_files[key]

    @app.get("/api/matches/{match_id}/moments")
    def moments(match_id: str, min_salience: float = 0.0) -> list[dict]:
        packs = recorded(match_id, "moments.json")
        if packs is None:
            packs = _ip(match_id).all_moments
        return [
            {"id": m["id"], "type": m["type"], "label": m["detectedAt"]["label"], "salience": m["salience"], "team": m["subjectTeam"]}
            for m in packs if m["salience"] >= min_salience
        ]  # fmt: skip

    @app.get("/api/matches/{match_id}/analytics")
    def analytics(match_id: str) -> dict:
        """The match's Opta-style analytics (what the replay package stores as analytics.json)."""
        rec = recorded(match_id, "analytics.json")
        if rec is not None:
            return rec
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
        rec = recorded(match_id, "analytics.json")
        if rec is not None and "winProbability" in rec:
            return rec["winProbability"]
        return MatchAnalytics(_ip(match_id)).win_probability()

    max_inflight = int(os.environ.get("MATCHMIND_MAX_INFLIGHT", "8"))
    inflight = [0]

    @app.post("/api/beats")
    async def beats(req: BeatRequest, x_admin_key: str | None = Header(None, alias=ADMIN_HEADER)) -> dict:
        # The workflow, bypassing the cache and long deadlines cost operators' money or hold a worker: key-protected.
        if (req.mode == "full" or not req.useCache or req.deadlineMs > PUBLIC_MAX_DEADLINE_MS) and not is_admin(x_admin_key):
            raise HTTPException(403, f"mode 'full', useCache false and deadlineMs over {PUBLIC_MAX_DEADLINE_MS} need the {ADMIN_HEADER} header")
        if inflight[0] >= max_inflight:  # turn a burst away at once rather than queue it behind slow model calls
            raise HTTPException(503, "busy, retry shortly", headers={"Retry-After": "2"})
        inflight[0] += 1
        try:
            packs, names = await asyncio.to_thread(beat_inputs, req.match_id)
            team = await asyncio.to_thread(get_team)
            return await serve_beats(req, packs=packs, registry=names, team=team, cache=beat_cache, settings=AgentSettings.from_env())
        except UnknownMoments as e:
            raise HTTPException(404, str(e)) from e
        except InvalidCohort as e:
            raise HTTPException(422, str(e)) from e
        finally:
            inflight[0] -= 1

    ask_inflight = [0]
    max_ask = int(os.environ.get("MATCHMIND_MAX_ASK_INFLIGHT", "4"))
    ask_cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()  # verified answers, so a repeated question (the suggestion chips) costs nothing
    ask_ttl_s, ask_max = 3600.0, 256

    @app.post("/api/ask")
    async def ask_endpoint(req: AskRequest) -> dict:
        """Ask the match a question. The answer is written from what the match-data tools return, and checked by the Verifier (docs/brain-api.md)."""
        if ask_inflight[0] >= max_ask:
            raise HTTPException(503, "busy, retry shortly", headers={"Retry-After": "3"})
        ask_inflight[0] += 1
        try:
            _, names = await asyncio.to_thread(beat_inputs, req.match_id)
            key = (req.match_id, " ".join(req.question.lower().split()), req.language, req.mode)
            hit = ask_cache.get(key)
            if hit and time.monotonic() - hit[0] < ask_ttl_s:
                ask_cache.move_to_end(key)
                return {**hit[1], "cached": True, "elapsedMs": 0, "usage": {"inputTokens": 0, "outputTokens": 0, "costUsd": 0.0}}
            team = await asyncio.to_thread(get_team)
            res = await ask_the_match(team, mcp, names, match_id=req.match_id, question=req.question, language=req.language, mode=req.mode, minute=req.minute)
            out = res.public()
            if res.level <= 1 and not res.refused:  # only answers the model wrote and the Verifier passed
                ask_cache[key] = (time.monotonic(), out)
                while len(ask_cache) > ask_max:
                    ask_cache.popitem(last=False)
            return {**out, "cached": False}
        finally:
            ask_inflight[0] -= 1

    @app.post("/api/ask/live")
    async def ask_live(req: LiveAskRequest) -> dict:
        """Ask a match that is being played. The answer is written from the match as the viewer has seen it so far (what had happened by ``atMs``), never from
        what is still to come; otherwise it is the same agents, tools and Verifier as /api/ask."""
        if ask_inflight[0] >= max_ask:
            raise HTTPException(503, "busy, retry shortly", headers={"Retry-After": "3"})
        ask_inflight[0] += 1
        try:
            hub = app.state.stream_hub
            ip = await asyncio.to_thread(hub.view_at, req.streamId, req.atMs)
            if ip is None:
                raise HTTPException(404, f"unknown stream {req.streamId}")
            reg.register(req.streamId, ip)  # the tools find the match by id: this id now means the match as seen so far
            names = Registry.from_meta(ip.meta)
            team = await asyncio.to_thread(get_team)
            res = await ask_the_match(team, mcp, names, match_id=req.streamId, question=req.question, language=req.language, mode=req.mode, minute=round(req.atMs / 60_000, 1))
            return {**res.public(), "cached": False}
        finally:
            ask_inflight[0] -= 1

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
