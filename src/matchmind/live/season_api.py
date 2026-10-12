"""The Brain's season and channel endpoints.

* ``GET  /api/channel``              what is on now (the match, its clock), and the season it belongs to
* ``POST /api/channel/tune``         join the match that is on, or start the next fixture (``{"fixtureId": "f07", "speed": 5}`` to ask for one)
* ``GET  /api/season``               the current season: fixtures with their results, the table, and how far its simulation has got
* ``POST /api/season/simulate``      plan a new season and start the season job (several replicas simulating at once); the site switches to it at once
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from functools import cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.paths import league_dir
from ..sim.league import load_league
from .api import summary
from .channel import SPEEDS, Channel
from .season import SeasonStore, now_ms, standings
from .season_job import create_season
from .store import LiveStore

SIMULATING_MS = 20 * 60_000  # a season whose job has not finished after this long is not holding the next one back


class TuneRequest(BaseModel):
    fixtureId: str | None = Field(None, pattern=r"^f\d{2}$")
    speed: float | None = None
    next: bool = False  # take the match on air off and start the next fixture


@cache
def _league() -> dict:
    return load_league(league_dir() / "league.json")


def clubs() -> dict[str, dict]:
    return {cid: {"name": c.name, "short": c.short, "primary": c.colors["primary"], "secondary": c.colors["secondary"]} for cid, c in _league().items()}


def make_season_router(
    get_channel: Callable[[], Channel], get_seasons: Callable[[], SeasonStore], get_store: Callable[[], LiveStore],
    run_season_job: Callable[[str], None] | None, ensure_default: Callable[[], None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def season_view(season_id: str) -> dict[str, Any]:
        seasons = get_seasons()
        season = seasons.get(season_id) or {}
        fixtures = seasons.fixtures(season_id)
        names = {cid: c["name"] for cid, c in clubs().items()}
        done = sum(1 for f in fixtures if f["status"] == "done")
        aired = set(get_channel().aired(season_id))
        return {
            "seasonId": season_id, "seed": season.get("seed"), "featured": season.get("featured"), "createdMs": season.get("createdMs"),
            "total": len(fixtures), "done": done, "simulating": sum(1 for f in fixtures if f["status"] == "simulating"),
            "fixtures": [{k: f.get(k) for k in ("id", "round", "home", "away", "scenario", "status", "score")} for f in fixtures],
            "aired": sorted(aired), "standings": standings(fixtures, names),
            "standingsAired": standings([f if f["id"] in aired else {**f, "status": "pending"} for f in fixtures], names), "clubs": clubs(),  # every club, counting only what has been on air
        }

    @router.get("/api/channel")
    async def channel() -> dict:
        def read() -> dict:
            ch, store, seasons = get_channel(), get_store(), get_seasons()
            now = ch.on_air()
            info = store.get_match(now["matchId"]) if now else None
            return {"now": {**now, "match": summary(info)} if now and info else None, "seasonId": seasons.current(), "speeds": list(SPEEDS)}

        return await asyncio.to_thread(read)

    @router.post("/api/channel/tune")
    async def tune(req: TuneRequest) -> dict:
        if req.speed is not None and req.speed not in SPEEDS:
            raise HTTPException(422, f"speed must be one of {list(SPEEDS)}")

        def go() -> dict | None:
            if ensure_default is not None:
                ensure_default()
            return get_channel().tune(req.fixtureId, req.speed, skip=req.next)

        now = await asyncio.to_thread(go)
        if now is None:  # no season, or none of its fixtures simulated yet: the page shows the season simulating and tries again
            raise HTTPException(503, "the season is being simulated; try again in a moment", headers={"Retry-After": "5"})
        return now

    @router.get("/api/season")
    async def season() -> dict:
        def read() -> dict:
            if ensure_default is not None:
                ensure_default()
            sid = get_seasons().current()
            if sid is None:
                return {"seasonId": None}
            return season_view(sid)

        return await asyncio.to_thread(read)

    @router.post("/api/season/simulate")
    async def simulate_season() -> dict:
        if run_season_job is None:
            raise HTTPException(503, "no season job is configured on this Brain")

        def go() -> dict:
            seasons = get_seasons()
            now = now_ms()
            for s in seasons.list()[:3]:
                if now - (s.get("createdMs") or 0) < SIMULATING_MS and any(f["status"] in ("pending", "simulating") for f in seasons.fixtures(s["id"])):
                    raise HTTPException(409, {"detail": "a season is already being simulated", "seasonId": s["id"]})
            sid = f"season-{time.strftime('%d%H%M%S')}"
            create_season(seasons, sid, random.randrange(10, 10_000), featured=False)  # noqa: S311 - a simulation seed, not a secret
            seasons.set_current(sid)
            run_season_job(sid)
            return {"seasonId": sid}

        return await asyncio.to_thread(go)

    return router
