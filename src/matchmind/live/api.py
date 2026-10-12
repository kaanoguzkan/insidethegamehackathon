"""The Brain's side of the live pipeline: what a viewer reads, what the dispatcher calls, and how a live match is started.

* ``GET  /api/live``                list of live and recent matches
* ``GET  /api/live/{id}``           one match: teams, status, speed and where its clock stands
* ``GET  /api/live/{id}/feed``      what is new since the caller's cursors: feed events, moments and overlays (poll every second or two)
* ``POST /api/live/{id}/beats``     internal: write the narrative overlays for new moments (the dispatcher Function calls this; key-protected)
* ``POST /api/live/start``          start the simulator job on a scenario (one live match at a time; rate-limited)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..core.paths import scenarios_dir
from .dispatch import write_beats
from .feed import live_clock_ms
from .store import LiveStore, now_ms

LIVE_KEY_HEADER = "x-live-key"
FEED_EVENTS = {"goal", "shot", "card", "substitution", "red_card", "yellow_card", "penalty", "formation_change", "phase_change"}
SHOWN_EVENTS = {"goal", "shot", "card", "substitution", "formation_change"}
SCENARIOS = tuple(sorted(p.stem for p in scenarios_dir().glob("*.yaml"))) if scenarios_dir().exists() else ("red-card-drama",)
FEED_PAGE = 500  # raw feed documents read per poll; a viewer who joins late pages through the past until ``more`` is false
MAX_LIVE_AGE_MS = 3 * 3600 * 1000  # a match that is still "live" after this long was killed, not played: it no longer blocks a new one
MAX_SCHEDULED_AGE_MS = 10 * 60 * 1000  # a job that has not started playing after this long failed to start: same


class StartRequest(BaseModel):
    scenario: Literal[SCENARIOS] = SCENARIOS[0]  # type: ignore[valid-type]
    fromMinute: float = Field(0.0, ge=0, le=80)


class BeatsRequest(BaseModel):
    momentIds: list[str] = Field(min_length=1, max_length=200)


class JobStarter(Protocol):
    def start(self, match_id: str, scenario: str, from_minute: float) -> None: ...


class ContainerAppsJobStarter:
    """Starts the simulator Container Apps Job through Azure Resource Manager, with the identity the Brain runs as.

    The job's own container definition is read first and sent back with the match's settings added, so the job always runs the image it was
    last deployed with.
    """

    API = "2024-03-01"

    def __init__(self, job_id: str, speed: float) -> None:
        self.job_id, self.speed = job_id, speed

    def _call(self, method: str, url: str, body: dict | None = None) -> dict:
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token("https://management.azure.com/.default").token
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - a fixed https ARM address
                raw = r.read()
        except urllib.error.HTTPError as e:  # say what ARM said: a bare "400 Bad Request" hides the reason
            raise RuntimeError(f"ARM {method} answered {e.code}: {e.read().decode(errors='replace')[:300]}") from e
        return json.loads(raw) if raw else {}

    def start(self, match_id: str, scenario: str, from_minute: float) -> None:
        base = f"https://management.azure.com{self.job_id}"
        job = self._call("GET", f"{base}?api-version={self.API}")
        container = dict(job["properties"]["template"]["containers"][0])
        env = [e for e in container.get("env", []) if not e["name"].startswith("LIVE_")]
        env += [{"name": "LIVE_MATCH_ID", "value": match_id}, {"name": "LIVE_SCENARIO", "value": scenario}, {"name": "LIVE_FROM_MINUTE", "value": str(from_minute)}, {"name": "LIVE_SPEED", "value": str(self.speed)}]
        # The start API takes the containers themselves (a StartJobExecutionTemplate), not a job template around them.
        self._call("POST", f"{base}/start?api-version={self.API}", {"containers": [{**container, "env": env}]})


def live_key_ok(supplied: str | None) -> bool:
    """The internal dispatch endpoint spends model tokens, so it fails closed: without ``MATCHMIND_LIVE_KEY`` nobody gets in, unless
    ``MATCHMIND_LIVE_OPEN=1`` says this is a development machine."""
    key = os.environ.get("MATCHMIND_LIVE_KEY")
    if not key:
        return os.environ.get("MATCHMIND_LIVE_OPEN") == "1"
    return hmac.compare_digest(supplied or "", key)


def summary(info: dict) -> dict:
    """A match document as a viewer needs it: who plays, how it is going, where the clock stands, and the names events refer to."""
    meta = info.get("meta") or {}
    side = lambda k: {"id": meta[k]["id"], "name": meta[k]["name"], "short": meta[k]["short"]}  # noqa: E731
    out: dict[str, Any] = {
        "matchId": info["matchId"], "status": info.get("status"), "scenario": info.get("scenario"), "speed": info.get("speed"),
        "fromMs": info.get("fromMs"), "wallStartMs": info.get("wallStartMs"), "durationMs": info.get("durationMs"),
        "clockMs": live_clock_ms(info), "serverNowMs": now_ms(),
    }
    if meta:
        out["home"], out["away"] = side("home"), side("away")
        out["players"] = {pid: p["name"] for k in ("home", "away") for pid, p in meta[k]["players"].items()}
    return out


def make_router(
    get_store: Callable[[], LiveStore], get_team: Callable[[], Any], beat_cache: Any, starter: Callable[[], JobStarter | None],
    in_process: Callable[[str, str, float], None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def store() -> LiveStore:
        return get_store()

    def _match(match_id: str) -> dict:
        info = store().get_match(match_id)
        if info is None:
            raise HTTPException(404, f"unknown live match {match_id!r}")
        return info

    def shown(r: dict, now: int) -> bool:
        """A match worth listing: not a failed start, and not a job that was asked for long ago and never began."""
        if r.get("status") == "failed":
            return False
        return not (r.get("status") == "scheduled" and now - (r.get("scheduledMs") or 0) >= MAX_SCHEDULED_AGE_MS)

    @router.get("/api/live")
    async def list_live() -> list[dict]:
        rows = await asyncio.to_thread(store().list_matches)
        rows = [r for r in rows if shown(r, now_ms())]
        rows.sort(key=lambda r: r.get("wallStartMs") or r.get("scheduledMs") or 0, reverse=True)
        return [{k: v for k, v in summary(r).items() if k != "players"} for r in rows[:20]]

    @router.get("/api/live/{match_id}")
    async def one(match_id: str) -> dict:
        return summary(await asyncio.to_thread(_match, match_id))

    @router.get("/api/live/{match_id}/feed")
    async def feed(match_id: str, event: int = -1, since: int = 0) -> dict:
        """What is new: feed events above sequence ``event``, overlays emitted at or after ``since`` (the client drops repeats by id), and every moment so far."""
        info = await asyncio.to_thread(_match, match_id)

        def read() -> dict:
            s = store()
            docs = s.docs_after(match_id, event, FEED_PAGE)
            events = [
                {"n": d["n"], "arrivalMs": d["arrivalMs"], **{k: d["doc"].get(k) for k in ("id", "type", "clock", "team", "player", "receiver", "outcome", "location")}}
                for d in docs if d["kind"] == "feed" and d["doc"].get("type") in SHOWN_EVENTS
            ]
            rows = s.overlays_since(match_id, max(since - 1, 0))
            moments = [
                {k: m.get(k) for k in ("id", "type", "label", "salience", "detectedAt", "subjectTeam", "facts")} for m in s.moments(match_id)
            ]
            return {
                "events": events, "eventCursor": docs[-1]["n"] if docs else event, "more": len(docs) >= FEED_PAGE,
                "overlays": [r["overlay"] | {"emittedMs": r["emittedMs"]} for r in rows], "overlayCursor": max([r["emittedMs"] for r in rows], default=since),
                "moments": moments,
            }

        return {**summary(info), **await asyncio.to_thread(read)}

    @router.post("/api/live/{match_id}/beats")
    async def beats(match_id: str, req: BeatsRequest, x_live_key: str | None = Header(None, alias=LIVE_KEY_HEADER)) -> dict:
        if not live_key_ok(x_live_key):
            raise HTTPException(403, f"the {LIVE_KEY_HEADER} header is required")
        await asyncio.to_thread(_match, match_id)
        team = await asyncio.to_thread(get_team)
        return await write_beats(store(), match_id, req.momentIds, team=team, cache=beat_cache)

    @router.post("/api/live/start")
    async def start(req: StartRequest) -> dict:
        rows = await asyncio.to_thread(store().list_matches)
        now = now_ms()

        def blocking(r: dict) -> bool:
            if r.get("status") == "scheduled":
                return now - (r.get("scheduledMs") or 0) < MAX_SCHEDULED_AGE_MS
            return r.get("status") == "live" and now - (r.get("wallStartMs") or now) < MAX_LIVE_AGE_MS

        running = sorted((r for r in rows if blocking(r)), key=lambda r: r.get("status") != "live")  # a match that is really being played first
        if running:  # one live match at a time: a visitor who arrives meanwhile simply watches it
            raise HTTPException(409, {"detail": "a live match is already running", "matchId": running[0]["matchId"]})
        match_id = f"live-{req.scenario}-{time.strftime('%d%H%M%S')}"
        job = starter()
        if job is None and in_process is None:
            raise HTTPException(503, "no simulator job is configured on this Brain")
        # Claim the slot now: the job needs a while to start, and a second visitor must see this match rather than start another.
        await asyncio.to_thread(store().put_match, match_id, {"status": "scheduled", "scenario": req.scenario, "scheduledMs": now, "fromMs": int(req.fromMinute * 60_000)})
        try:
            if job is not None:
                await asyncio.to_thread(job.start, match_id, req.scenario, req.fromMinute)
            else:
                in_process(match_id, req.scenario, req.fromMinute)  # type: ignore[misc]
        except Exception as e:  # noqa: BLE001 - release the slot, or the next visitor would wait for a job that never started
            await asyncio.to_thread(store().put_match, match_id, {"status": "failed", "scenario": req.scenario, "scheduledMs": now, "error": str(e)[:300]})
            print(f"WARN live start failed: {e}", flush=True)
            raise HTTPException(502, "the simulator job could not be started") from e
        return {"matchId": match_id, "scenario": req.scenario, "fromMinute": req.fromMinute}

    return router
