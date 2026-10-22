"""Stream sessions: a match played to one viewer at a time, interpreted as it goes, all in this process.

A demo match is simulated once and kept in memory (the *source*: its feed documents and its tracking chunks). A session plays that source to a viewer
at 1x to 10x real time through the same incremental stages the Azure pipeline uses, but with the stages called directly instead of through Cosmos DB
change feeds, Event Grid and Functions:

    play() releases the feed and the tracking chunks on the clock
      -> AnalyzerWorker.drain()   tracking chunks to physical events, in order, behind a watermark
      -> InterpretWorker.run()    feed + physical events to moments, facts and graphics, up to the lower watermark
      -> dispatch                 the narrative overlays for new moments (the fast path of the Brain)

Each session has a store of its own, so viewers never share a clock and nothing from a viewer's future is ever in their store. The measured cost of a
whole match through the analyzer and the interpreter is a few seconds of CPU, so a Brain serves many viewers; the model text for a moment is shared
through the Brain's beat cache, because the moment ids of a demo are the same for every viewer.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field

from ..agents.service import check_cohorts
from ..agents.verify import Registry
from ..analytics.report import MatchAnalytics
from ..core.contracts import Cohort
from ..core.paths import league_dir
from ..demos import Demo, get_demo
from ..intel.recap import build_pack, build_preview_pack
from ..sim.engine import simulate
from ..sim.league import load_league
from .analysis import AnalyzerWorker
from .blobs import MemoryBlobs
from .feed import build_chunks, build_feed, chunk_name, live_clock_ms, play, start_match
from .pipeline import Intel, InterpretWorker
from .store import FINAL, MemoryLiveStore, now_ms

SPEEDS = (1.0, 2.0, 5.0, 10.0)
MAX_SESSIONS = 12  # matches being played at once: each holds a store, and a few seconds of CPU per match
KEEP_FINISHED_S = 15 * 60  # a finished session stays readable this long, then its memory is released
MAX_AGE_S = 4 * 3600  # a session that is still running after this long is stopped
IDLE_STOP_S = 5 * 60  # a viewer who has not polled for this long has gone: stop the match


class StreamBusy(Exception):
    """Too many sessions at once."""


class _Stopped(Exception):
    """Raised inside the player to end a session early."""


@dataclass
class Source:
    """A demo match, ready to be played: simulated once, shared by every session."""

    demo: Demo
    meta: dict
    docs: list[dict]
    chunks: list[tuple[int, str, bytes]]  # (end of the chunk in match ms, blob name, gzip JSON); the names are the source's own


def build_source(demo: Demo) -> Source:
    clubs = load_league(league_dir() / "league.json")
    result = simulate(demo.id, clubs[demo.home], clubs[demo.away], seed=demo.seed)
    return Source(demo, result.meta, build_feed(result, physical="chunks"), build_chunks(result))


Dispatch = Callable[[MemoryLiveStore, str, list[str], list[Cohort]], "Future | None"]
RecapDispatch = Callable[[MemoryLiveStore, str, str, dict, list[Cohort]], "Future | None"]  # (store, session id, kind, evidence pack, cohorts)
ANALYTICS_EVERY_S = 4.0  # the whole analytics summary of a match in progress costs 0.03-0.05 s; the viewer gets a new one at most this often
MAX_COHORTS = 4  # the viewers one session writes text for (the person watching, and a second profile in split view)


@dataclass
class Session:
    id: str
    demo_id: str
    speed: float
    from_ms: int
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    error: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    queued: set[str] = field(default_factory=set)  # moments whose overlays have been asked for
    cohorts: list[Cohort] = field(default_factory=list)  # who the narrative overlays are written for
    analytics_at: float = 0.0
    recap_packs: dict[str, dict] = field(default_factory=dict)  # kind -> the evidence pack, for every recap asked for so far
    inflight: Future | bool | None = None
    analyzer: AnalyzerWorker | None = None
    interpreter: InterpretWorker | None = None
    thread: threading.Thread | None = None
    view: tuple[int, object] | None = None  # (bucket, interpreter): the match as the viewer has seen it, for questions
    view_lock: threading.Lock = field(default_factory=threading.Lock)


class StreamHub:
    def __init__(
        self, *, dispatch: Dispatch | None = None, recap: RecapDispatch | None = None, intel: Intel | None = None, max_sessions: int = MAX_SESSIONS, tick_s: float = 0.5,
        keep_finished_s: float = KEEP_FINISHED_S, idle_stop_s: float = IDLE_STOP_S,
    ) -> None:
        self.store = MemoryLiveStore()
        self.frames = MemoryBlobs()
        self.dispatch = dispatch
        self.recap = recap
        self.intel = intel
        self.max_sessions, self.tick_s = max_sessions, tick_s
        self.speeds = SPEEDS
        self.keep_finished_s, self.idle_stop_s = keep_finished_s, idle_stop_s
        self.sessions: dict[str, Session] = {}
        self._sources: dict[str, Source] = {}
        self._source_locks: dict[str, threading.Lock] = {}
        self._lock = threading.RLock()
        self.started = 0  # matches started since this replica began
        self.on_release: list[Callable[[str], None]] = []  # told when a session's data is dropped (whoever lent its interpreter out forgets it)

    # ----- sources ---------------------------------------------------------------------------------

    def source(self, demo_id: str) -> Source:
        """The demo, simulated on first use (about 5 s) and kept. ``get_demo`` raises KeyError for a name that is not committed."""
        demo = get_demo(demo_id)
        with self._lock:
            have = self._sources.get(demo.id)
            lock = self._source_locks.setdefault(demo.id, threading.Lock())
        if have is not None:
            return have
        with lock:  # one simulation per demo, however many viewers ask at once
            have = self._sources.get(demo.id)
            if have is None:
                have = self._sources[demo.id] = build_source(demo)
        return have

    def preload(self, demo_ids: list[str]) -> None:
        for d in demo_ids:
            self.source(d)

    # ----- sessions --------------------------------------------------------------------------------

    def start(self, demo_id: str, speed: float = 5.0, from_minute: float = 0.0, cohorts: list[Cohort] | None = None) -> Session:
        if speed not in self.speeds:
            raise ValueError(f"speed must be one of {self.speeds}")
        src = self.source(demo_id)
        cohorts = list(dict.fromkeys(cohorts or [Cohort()]))[:MAX_COHORTS]
        check_cohorts(cohorts, Registry.from_meta(src.meta))  # InvalidCohort: a club or a player the match does not have
        self.sweep()
        with self._lock:
            running = sum(1 for x in self.sessions.values() if x.finished_at is None)
            if running >= self.max_sessions:
                raise StreamBusy(f"{running} matches are already being played")
            finished = sorted((x for x in self.sessions.values() if x.finished_at is not None), key=lambda x: x.finished_at or 0.0)
            evict = finished[: max(0, len(finished) - 2 * self.max_sessions)]  # finished sessions stay readable for a while, but not without limit
            for x in evict:
                self.sessions.pop(x.id, None)
            sid = f"s-{src.demo.id}-{secrets.token_hex(4)}"[:64]
            s = Session(id=sid, demo_id=src.demo.id, speed=speed, from_ms=int(from_minute * 60_000), cohorts=cohorts)
            self.sessions[sid] = s
            self.started += 1
        for x in evict:
            self._release(x)
        chunks = [(end, chunk_name(sid, i), data) for i, (end, _, data) in enumerate(src.chunks)]
        start_match(self.store, sid, src.meta, src.docs, scenario=src.demo.id, speed=speed, from_ms=s.from_ms, chunks=len(chunks))
        s.analyzer = AnalyzerWorker(self.store, self.frames, MemoryBlobs(), key=b"")
        s.interpreter = InterpretWorker(self.store, None, self.intel or self._intel(), key=b"", keep_snapshots=True)
        s.thread = threading.Thread(target=self._run, args=(s, src, chunks), name=f"stream-{sid}", daemon=True)
        s.thread.start()
        return s

    def _intel(self) -> Intel:
        self.intel = Intel.load()
        return self.intel

    def get(self, sid: str) -> Session | None:
        with self._lock:
            s = self.sessions.get(sid)
        if s is not None:
            s.touched = time.monotonic()
        return s

    def add_cohort(self, sid: str, cohort: Cohort) -> bool:
        """Write the narrative overlays of the moments still to come for one more viewer profile too. False when the session is full or unknown."""
        s = self.get(sid)
        if s is None or s.finished_at is not None:
            return False
        meta = (self.store.get_match(sid) or {}).get("meta")
        if meta is None:
            return False
        check_cohorts([cohort], Registry.from_meta(meta))
        if cohort not in s.cohorts:
            if len(s.cohorts) >= MAX_COHORTS:
                s.cohorts.pop(0)  # the profile the viewer has not used for longest goes
            s.cohorts.append(cohort)
            if self.recap is not None:  # the recaps already written for the others: write them for the new profile too
                for kind, pack in s.recap_packs.items():
                    self.recap(self.store, sid, kind, pack, _recap_cohorts([cohort]))
        return True

    def set_speed(self, sid: str, speed: float) -> Session | None:
        """Change how fast a running match is played; the player re-anchors its clock on its next tick. None if there is no such match."""
        if speed not in self.speeds:
            raise ValueError(f"speed must be one of {self.speeds}")
        s = self.get(sid)
        if s is not None and s.finished_at is None:
            s.speed = speed
        return s

    def status(self) -> dict:
        """How busy the hub is: matches being played now, against how many it takes at once, and how many finished ones it still holds."""
        with self._lock:
            running = sum(1 for s in self.sessions.values() if s.finished_at is None)
            return {"active": running, "capacity": self.max_sessions, "retained": len(self.sessions) - running, "started": self.started, "demosLoaded": sorted(self._sources)}

    def stop(self, sid: str) -> bool:
        with self._lock:
            s = self.sessions.get(sid)
        if s is None:
            return False
        s.stop.set()
        return True

    def sweep(self) -> None:
        """Stop sessions nobody watches or that ran too long, and release the memory of the ones that finished a while ago."""
        now = time.monotonic()
        drop: list[Session] = []
        with self._lock:
            for s in self.sessions.values():
                if s.finished_at is None:
                    if now - s.created > MAX_AGE_S or now - s.touched > self.idle_stop_s:
                        s.stop.set()
                elif now - s.finished_at > self.keep_finished_s:
                    drop.append(s)
            for s in drop:
                self.sessions.pop(s.id, None)
        for s in drop:
            self._release(s)

    def view_at(self, sid: str, at_ms: int):  # noqa: ANN201
        """The match as it stands at ``at_ms`` of match time (never later than the match clock): an interpreter fed only the documents that had arrived by then.

        This is what a question is answered from, so it cannot give away anything the viewer has not seen. It is built from the session's documents (a few
        seconds of CPU for a long match) and kept for the next question asked within ten seconds of match time. None if there is no such session.
        """
        s = self.get(sid)
        info = self.store.get_match(sid)
        if s is None or not info or not info.get("meta"):
            return None
        at = max(0, min(int(at_ms), live_clock_ms(info)))
        bucket = at // 10_000
        with s.view_lock:
            if s.view is not None and s.view[0] == bucket:
                return s.view[1]
            intel = self.intel or self._intel()
            from ..analytics.season import context_for
            from ..intel.interpreter import Interpreter

            meta = info["meta"]
            ip = Interpreter(meta, baselines=intel.baselines, xt=intel.xt, models=intel.models, season=context_for(intel.season, meta["home"]["id"], meta["away"]["id"]))
            for d in self.store.docs(sid):
                if d["kind"] != FINAL and d["arrivalMs"] <= at:
                    ip.ingest(d["doc"], arrival_ms=d["arrivalMs"])
            s.view = (bucket, ip)
            return ip

    def _release(self, s: Session) -> None:
        for fn in self.on_release:
            try:
                fn(s.id)
            except Exception:  # noqa: BLE001, S110 - forgetting is best effort
                pass
        self.store.purge(s.id)
        self.frames.purge(f"{s.id}/")
        if s.analyzer is not None:
            s.analyzer._pool.shutdown(wait=False)  # noqa: SLF001 - the worker has no close(); its pool would otherwise outlive the session

    # ----- the player ------------------------------------------------------------------------------

    def _run(self, s: Session, src: Source, chunks: list[tuple[int, str, bytes]]) -> None:
        def sleep(seconds: float) -> None:
            if s.stop.wait(seconds):
                raise _Stopped

        failures = 0

        def tick() -> None:
            nonlocal failures
            try:
                self._tick(s)
                failures = 0
            except Exception as e:  # noqa: BLE001 - one bad tick must not end the match; five in a row do
                failures += 1
                print(f"WARN stream {s.id}: tick failed: {type(e).__name__}: {e}", flush=True)
                if failures >= 5:
                    raise

        try:
            play(self.store, s.id, src.docs, speed=s.speed, from_ms=s.from_ms, chunks=chunks, blobs=self.frames, sleep=sleep, tick_s=self.tick_s, on_tick=tick, speed_of=lambda: s.speed)
            for _ in range(40):  # the last chunk was just published: let the analyzer and the interpreter reach the end
                tick()
                if (self.store.get_state(s.id, "analyzer") or {}).get("final") and self._finished(s):
                    break
                sleep(0.1)
        except _Stopped:
            info = self.store.get_match(s.id)
            if info is not None:
                self.store.put_match(s.id, {**info, "status": "stopped"})
        except Exception as e:  # noqa: BLE001
            s.error = f"{type(e).__name__}: {e}"[:300]
            info = self.store.get_match(s.id)
            if info is not None:
                self.store.put_match(s.id, {**info, "status": "failed", "error": s.error})
            print(f"WARN stream {s.id} failed: {s.error}", flush=True)
        finally:
            s.finished_at = time.monotonic()

    def _tick(self, s: Session) -> None:
        assert s.analyzer is not None and s.interpreter is not None
        s.analyzer.drain(s.id)
        s.interpreter.run(s.id)
        self._dispatch(s)
        self._analytics(s)
        self._recaps(s)

    def _analytics(self, s: Session, force: bool = False) -> None:
        """The analytics summary of the match so far (win probability, shots, shape, space ...), refreshed every few seconds and once at the end."""
        now = time.monotonic()
        run = s.interpreter._cache.get(s.id) if s.interpreter is not None else None  # noqa: SLF001
        if run is None or (not force and now - s.analytics_at < ANALYTICS_EVERY_S) or not run.ip.events:
            return
        s.analytics_at = now
        try:
            data = MatchAnalytics(run.ip).summary()
        except Exception as e:  # noqa: BLE001 - the first minutes may not have enough for every view
            print(f"WARN stream {s.id}: analytics skipped: {type(e).__name__}: {e}", flush=True)
            return
        prev = self.store.get_state(s.id, "analytics") or {"version": 0}
        self.store.put_state(s.id, "analytics", {"version": prev["version"] + 1, "data": data})

    def _recaps(self, s: Session) -> None:
        """The preview at kick-off, the half-time recap when the interpreter has passed the break, the full-time recap when it has finished."""
        run = s.interpreter._cache.get(s.id) if s.interpreter is not None else None  # noqa: SLF001
        if run is None:
            return
        meta = run.ip.meta
        due = {"preview": True, "half_time": run.limit >= (meta["periods"][0].get("endMs") or 1 << 60), "full_time": run.finished}
        for kind, ready in due.items():
            if not ready or kind in s.recap_packs:
                continue
            try:
                pack = build_preview_pack(meta, run.ip.season) if kind == "preview" else build_pack(run.ip, kind)
            except Exception as e:  # noqa: BLE001
                print(f"WARN stream {s.id}: {kind} recap skipped: {type(e).__name__}: {e}", flush=True)
                continue
            s.recap_packs[kind] = pack
            if self.recap is not None:
                self.recap(self.store, s.id, kind, pack, _recap_cohorts(s.cohorts))
            if kind == "full_time":
                self._analytics(s, force=True)

    def _finished(self, s: Session) -> bool:
        run = s.interpreter._cache.get(s.id) if s.interpreter is not None else None  # noqa: SLF001
        return bool(run and run.finished)

    def _dispatch(self, s: Session) -> None:
        """Ask for the narrative overlays of moments found since the last request, one request at a time (the dispatcher keeps a story budget in order)."""
        if self.dispatch is None:
            return
        fut = s.inflight
        if fut is True or (isinstance(fut, Future) and not fut.done()):
            return
        pending = [m["id"] for m in self.store.moments(s.id) if m["id"] not in s.queued]
        if not pending:
            return
        s.queued.update(pending)
        s.inflight = True
        try:
            s.inflight = self.dispatch(self.store, s.id, pending, list(s.cohorts))
        except Exception as e:  # noqa: BLE001 - the viewer still has the graphics and the facts
            s.inflight = None
            print(f"WARN stream {s.id}: dispatch failed: {type(e).__name__}: {e}", flush=True)


def _recap_cohorts(cohorts: list[Cohort]) -> list[Cohort]:
    """A recap is written per mode, language and club (the match center looks for exactly that), not per followed player."""
    return list(dict.fromkeys(Cohort(mode=c.mode, language=c.language, perspective=c.perspective) for c in cohorts))


def new_session_summary(s: Session) -> dict:
    return {"streamId": s.id, "demo": s.demo_id, "speed": s.speed, "fromMs": s.from_ms, "startedMs": now_ms()}
