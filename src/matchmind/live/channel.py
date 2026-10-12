"""The channel: what is on right now.

Opening the site should show a match, not a form. The channel always knows which fixture of the season is being played: a visitor **tunes in**, and either
joins the match that is already on (every viewer shares one match, like a broadcast) or starts the next fixture, which is a matter of reading its pack from
storage (a second or two) and releasing its feed and tracking chunks at the playing speed. Nothing is simulated while a viewer waits.

The match is played by a thread of the Brain (``feed.play``, the same loop the simulator job uses). That is enough because the thing being played is already a
finished simulation, and because a match that nobody is watching does not need to run: when the last viewer leaves the Brain scales to zero and the match
stops with it. The next visitor finds a heartbeat that has gone stale and starts the next fixture. Which fixture is next is remembered in the store
(``played``), so a season is worked through in order whoever tunes in.

State, in the live store under the match id ``_channel``: ``now`` (the match on air with a heartbeat) and ``played`` (fixtures already shown).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .blobs import Blobs
from .feed import jsonable, play, start_match
from .packs import read_pack
from .season import SeasonStore
from .store import LiveStore, now_ms

CHANNEL = "_channel"
LOCK = "channel"
HEARTBEAT_EVERY_S = 3.0
STALE_MS = 20_000  # a match whose player has not been heard from for this long is not on air any more
SPEEDS = (5.0, 10.0, 20.0)


class Switched(Exception):
    """Raised inside a match's playback loop when the channel has moved on to another match: the old one stops being played."""


class Channel:
    def __init__(
        self, store: LiveStore, seasons: SeasonStore, packs: Blobs, frames: Blobs, *, speed: float = 5.0,
        spawn: Callable[[Callable[[], None]], None] | None = None, play_fn: Callable[..., int] = play,
    ) -> None:
        self.store, self.seasons, self.packs, self.frames, self.speed = store, seasons, packs, frames, speed
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._play = play_fn

    # ----- what is on -----------------------------------------------------------------------------------

    def on_air(self) -> dict | None:
        """The match being played, if its player is alive; None if nothing is on."""
        now = self.store.get_state(CHANNEL, "now")
        if not now or now_ms() - now.get("heartbeatMs", 0) > STALE_MS:
            return None
        info = self.store.get_match(now["matchId"])
        return now if info and info.get("status") in ("scheduled", "live") else None

    def next_fixture(self, season_id: str) -> dict | None:
        """The first simulated fixture that has not been shown; when all have been, the season starts over."""
        played = set(self.store.get_state(CHANNEL, "played", []))
        done = [f for f in self.seasons.fixtures(season_id) if f["status"] == "done"]
        fresh = [f for f in done if f["id"] not in played]
        if fresh:
            return fresh[0]
        if done:
            self.store.put_state(CHANNEL, "played", [])
            return done[0]
        return None

    def mark_aired(self, season_id: str, fixture_id: str) -> None:
        key = f"{season_id}/{fixture_id}"
        aired = list(self.store.get_state(CHANNEL, "aired", []))
        if key not in aired:
            self.store.put_state(CHANNEL, "aired", [*aired, key])

    def aired(self, season_id: str) -> list[str]:
        """The fixtures of the season that have been played on air to the end."""
        return [k.split("/", 1)[1] for k in self.store.get_state(CHANNEL, "aired", []) if k.startswith(f"{season_id}/")]

    # ----- tuning in ------------------------------------------------------------------------------------

    def tune(self, fixture_id: str | None = None, speed: float | None = None, *, from_minute: float = 0.0, skip: bool = False) -> dict | None:
        """Join the match that is on, or start one. ``fixture_id`` asks for a particular fixture and ``skip`` for the next one: both take the match on air off;
        returns the channel state, or None when there is no simulated fixture to show yet."""
        speed = speed if speed in SPEEDS else self.speed
        cur = self.on_air()
        if cur is not None and not skip and (fixture_id is None or fixture_id == cur.get("fixtureId")):
            return cur
        if not self.store.acquire(CHANNEL, LOCK, 30_000):  # another replica is starting one: wait for it, then join
            for _ in range(40):
                time.sleep(0.25)
                if (cur := self.on_air()) is not None:
                    return cur
            return None
        try:
            if (cur := self.on_air()) is not None and fixture_id is None and not skip:
                return cur
            season_id = self.seasons.current()
            if season_id is None:
                return None
            fx = next((f for f in self.seasons.fixtures(season_id) if f["id"] == fixture_id and f["status"] == "done"), None) if fixture_id else self.next_fixture(season_id)
            if fx is None:
                return None
            return self._start(season_id, fx, speed, from_minute)
        finally:
            self.store.release(CHANNEL, LOCK)

    def _start(self, season_id: str, fx: dict, speed: float, from_minute: float) -> dict | None:
        pack = read_pack(self.packs, fx["pack"] or f"{season_id}/{fx['id']}")
        if pack is None:
            return None
        match_id = f"live-{season_id}-{fx['id']}-{time.strftime('%H%M%S')}"
        meta = jsonable({**pack.meta, "matchId": match_id})
        docs, chunks = pack.feed(match_id), pack.chunks(match_id)
        from_ms = int(from_minute * 60_000)
        info = start_match(self.store, match_id, meta, docs, scenario=fx.get("scenario"), speed=speed, from_ms=from_ms, chunks=len(chunks))
        self.store.put_match(match_id, {**info, "seasonId": season_id, "fixtureId": fx["id"], "round": fx["round"]})
        now = {"matchId": match_id, "seasonId": season_id, "fixtureId": fx["id"], "round": fx["round"], "speed": speed, "heartbeatMs": now_ms()}
        self.store.put_state(CHANNEL, "now", now)
        played = list(self.store.get_state(CHANNEL, "played", []))
        self.store.put_state(CHANNEL, "played", [*played, fx["id"]])

        def run() -> None:
            beat = [0.0]

            def on_tick() -> None:
                if time.monotonic() - beat[0] >= HEARTBEAT_EVERY_S:
                    beat[0] = time.monotonic()
                    cur = self.store.get_state(CHANNEL, "now") or {}
                    if cur.get("matchId") != match_id:  # someone tuned to another fixture: this one comes off air
                        raise Switched
                    self.store.put_state(CHANNEL, "now", {**now, "heartbeatMs": now_ms()})

            try:
                self._play(self.store, match_id, docs, speed=speed, from_ms=from_ms, chunks=chunks, blobs=self.frames, on_tick=on_tick)
            except Switched:
                self.store.put_match(match_id, {**(self.store.get_match(match_id) or {}), "status": "finished", "abandoned": True})
            except Exception as e:  # noqa: BLE001 - a match that cannot be played is taken off air; the next visitor starts the next fixture
                print(f"WARN channel: {match_id} stopped: {e}", flush=True)
                self.store.put_state(CHANNEL, "now", {**now, "heartbeatMs": 0})
            else:  # it was played to the end: the fixture now counts in the table "as broadcast"
                self.mark_aired(season_id, fx["id"])

        self._spawn(run)
        return now
