"""The stream endpoints: start a match of your own, then poll it. Same shapes as ``/api/live`` (the viewer code is shared), one session per viewer.

    GET    /api/stream/demos                 the matches that can be played
    POST   /api/stream                       start one: ``{demo, speed, fromMinute}`` answers ``{streamId, ...}`` at once (the first start of a demo
                                             waits for its simulation, about 5 s, unless the Brain preloaded it)
    GET    /api/stream/{id}                  where the clock stands
    GET    /api/stream/{id}/meta|chunks/{n}|feed    exactly as the live endpoints
    DELETE /api/stream/{id}                  stop it
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from ..agents.service import InvalidCohort
from ..core.contracts import Cohort
from ..core.paths import league_dir
from ..demos import load_demos
from ..sim.league import load_league
from .api import feed_page, summary
from .feed import chunk_name
from .session import SPEEDS, StreamBusy, StreamHub, new_session_summary


class StreamRequest(BaseModel):
    demo: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    speed: float = 5.0
    fromMinute: float = Field(0.0, ge=0, le=80)
    cohorts: list[Cohort] = Field(default_factory=list, max_length=2, description="who the narrative overlays are written for; none: a casual English viewer")


def public_meta(meta: dict) -> dict:
    """The match sheet a viewer may see while the match is on: what is only known at the end (the score, how each side played over the whole match, the
    formation it finished in) is left out."""
    out = {k: v for k, v in meta.items() if k != "score"}
    for side in ("home", "away"):
        team = {k: v for k, v in meta[side].items() if k != "phases"}
        team["formation"] = team.get("startFormation", team["formation"])
        out[side] = team
    return out


def make_stream_router(hub: StreamHub, on_loop: Callable[[asyncio.AbstractEventLoop], None] | None = None) -> APIRouter:
    router = APIRouter()

    def _info(sid: str) -> dict:
        s = hub.get(sid)
        info = hub.store.get_match(sid) if s is not None else None
        if info is None:
            raise HTTPException(404, f"unknown stream {sid!r}")
        return info

    @router.get("/api/stream/demos")
    async def demos() -> dict:
        clubs = await asyncio.to_thread(lambda: load_league(league_dir() / "league.json"))
        side = lambda cid: {"id": cid, "name": clubs[cid].name, "short": clubs[cid].short}  # noqa: E731
        return {"speeds": list(hub.speeds), "demos": [{"id": d.id, "home": side(d.home), "away": side(d.away)} for d in load_demos().values()]}

    @router.post("/api/stream")
    async def start(req: StreamRequest) -> dict:
        if on_loop is not None:
            on_loop(asyncio.get_running_loop())  # the dispatcher runs its model calls on this loop
        try:
            s = await asyncio.to_thread(hub.start, req.demo, req.speed, req.fromMinute, req.cohorts or None)
        except KeyError as e:
            raise HTTPException(404, str(e.args[0])) from e
        except (ValueError, InvalidCohort) as e:
            raise HTTPException(422, str(e)) from e
        except StreamBusy as e:
            raise HTTPException(503, str(e), headers={"Retry-After": "30"}) from e
        info = hub.store.get_match(s.id) or {}
        return {**new_session_summary(s), **summary(info)}

    @router.get("/api/stream/{sid}")
    async def one(sid: str) -> dict:
        return summary(_info(sid))

    @router.get("/api/stream/{sid}/meta")
    async def meta(sid: str) -> dict:
        m = _info(sid).get("meta")
        if not m:
            raise HTTPException(404, "the match has not started yet")
        return {**public_meta(m), "package": {"llm": "live", "cohorts": [], "levels": {}, "moments": 0, "overlays": 0}}

    @router.get("/api/stream/{sid}/chunks/{index}")
    async def chunk(sid: str, index: int) -> Response:
        if index < 0 or index > 5000:
            raise HTTPException(404, "no such chunk")
        _info(sid)
        data = await asyncio.to_thread(hub.frames.get, chunk_name(sid, index))
        if data is None:
            raise HTTPException(404, "that chunk has not been published yet")
        return Response(data, media_type="application/json", headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=3600, immutable"})

    @router.get("/api/stream/{sid}/feed")
    async def feed(sid: str, event: int = -1, since: int = 0, full: bool = False, msince: int = 0, snap: int = 0, av: int = 0, rv: int = 0) -> dict[str, Any]:
        """As the live feed; ``full=1`` adds what the match center needs: every event whole, the moments created at or after ``msince`` with their evidence, the snapshots after ``snap``."""
        info = _info(sid)
        page = await asyncio.to_thread(lambda: feed_page(hub.store, sid, event, since, full=full, moment_since=msince, snapshot_after=snap, analytics_version=av, recap_after=rv))
        return {**summary(info), **page}

    @router.post("/api/stream/{sid}/cohorts")
    async def add_cohort(sid: str, cohort: Cohort) -> dict:
        """The viewer changed profile: write the narrative overlays of the moments still to come for the new one as well."""
        _info(sid)
        try:
            ok = await asyncio.to_thread(hub.add_cohort, sid, cohort)
        except InvalidCohort as e:
            raise HTTPException(422, str(e)) from e
        if not ok:
            raise HTTPException(409, "the match is over")
        return {"streamId": sid, "cohort": cohort.key}

    @router.delete("/api/stream/{sid}")
    async def stop(sid: str) -> dict:
        _info(sid)
        hub.stop(sid)
        return {"streamId": sid, "stopping": True}

    return router


__all__ = ["SPEEDS", "StreamRequest", "make_stream_router"]
