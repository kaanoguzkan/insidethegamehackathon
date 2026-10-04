"""The match simulator: state, tick loop, periods, substitutions and output.

``MatchSim`` is a 5 Hz agent-based simulation of 22 players and a ball. Movement lives in
``ShapeMixin`` and on-ball behaviour in ``ActionsMixin``; this class owns the shared state
and turns it into the two things a data provider would deliver: an event stream and
player/ball tracking frames.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np

from ..core import geometry as G
from .actions import ActionsMixin
from .scenarios import Scenario, ScriptItem
from .shape import ShapeMixin
from .teams import GROUP, ROLE_COMPAT, Club, Player, Style, formation_slots

DT = 0.2
HZ = 5
TICKS_PER_CHUNK = 25  # 5 seconds of tracking per chunk


def pick_lineup(club: Club, formation: str) -> tuple[list[Player], list[Player]]:
    """Choose the starting eleven for a formation (slot order) and a seven-player bench."""
    avail = list(club.squad)
    lineup: list[Player] = []
    for role, _, _ in formation_slots(formation):
        compat = ROLE_COMPAT[role]
        best, best_s = None, -1e9
        for p in avail:
            if p.pos in compat:
                s = p.overall - 7.0 * compat.index(p.pos)
                if s > best_s:
                    best, best_s = p, s
        if best is None:
            best = max((p for p in avail if p.pos != "GK"), key=lambda p: p.overall)
        avail.remove(best)
        lineup.append(best)

    bench: list[Player] = []
    gks = sorted((p for p in avail if p.pos == "GK"), key=lambda p: -p.overall)
    if gks:
        bench.append(gks[0])
        avail.remove(gks[0])
    for group in ("DEF", "DEF", "MID", "MID", "ATT", "ATT"):
        pool = sorted((p for p in avail if GROUP[p.pos] == group), key=lambda p: -p.overall)
        if pool:
            bench.append(pool[0])
            avail.remove(pool[0])
    return lineup, bench


@dataclass
class MatchResult:
    meta: dict
    events: list[dict]
    frames: np.ndarray  # (n, 22, 2) float32, absolute metres, NaN while a player is off
    ball: np.ndarray  # (n, 4) float32: x, y, height, in-play flag (0 while the ball is dead)
    chunk_slots: list[list[str]]  # player ids per tracking slot, one list per 5 s chunk
    stats: dict = field(default_factory=dict)


class MatchSim(ShapeMixin, ActionsMixin):
    DT = DT

    def __init__(
        self,
        match_id: str,
        home: Club,
        away: Club,
        *,
        seed: int = 1,
        scenario: Scenario | None = None,
        formations: tuple[str | None, str | None] = (None, None),
    ) -> None:
        self.match_id = match_id
        self.seed = seed
        self.scenario = scenario
        self.rng = random.Random(seed)
        self.nrng = np.random.default_rng(seed)
        self.clubs = [home, away]
        self.club_id = [home.id, away.id]

        self.style: list[Style] = []
        self.slots: list[list[tuple[str, float, float]]] = []
        self.formation_name: list[str] = []
        self.players: list[Player] = []
        self.bench: list[list[Player]] = []
        self.lineups: list[list[str]] = []
        for club, fm in zip(self.clubs, formations, strict=True):
            style = Style.from_dict(club.style.to_dict())
            if fm:
                style.formation = fm
            lineup, bench = pick_lineup(club, style.formation)
            self.style.append(style)
            self.formation_name.append(style.formation)
            self.slots.append(formation_slots(style.formation))
            self.players.extend(lineup)
            self.bench.append(bench)
            self.lineups.append([p.id for p in lineup])

        # Per-player physical state.
        self.pos = np.zeros((22, 2))
        self.vel = np.zeros((22, 2))
        self.wobble = np.zeros((22, 2))
        self.stamina = np.ones(22)
        self.active = np.ones(22, dtype=bool)
        self.vmax = np.zeros(22)
        self.fatigue = np.zeros(22)
        self.dist_run = np.zeros(22)
        for i, p in enumerate(self.players):
            self._set_physique(i, p)

        # Formation geometry (normalised depth u and width fy for the 10 outfield slots).
        self.u = [np.zeros(10), np.zeros(10)]
        self.fy = [np.zeros(10), np.zeros(10)]
        for t in (0, 1):
            self._reindex_shape(t)

        # Match flow.
        self.p1_len = 45 * 60 + self.rng.uniform(60.0, 200.0)
        self.p2_len = 45 * 60 + self.rng.uniform(120.0, 330.0)
        self.t = 0.0
        self.tick_i = 0
        self.period = 1
        self.dir = [1, -1]
        self.finished = False
        self.score = [0, 0]

        # Ball and possession state.
        self.ball = np.array([G.CX, G.CY])
        self.ball_z = 0.0
        self.mode = "dead"
        self.holder: int | None = None
        self.holder_since = 0.0
        self.next_action_t = 0.0
        self.carry: dict | None = None
        self.flight: dict | None = None
        self.restart: dict | None = None
        self.loose_until = 0.0
        self.loose_t0 = 0.0
        self.loose_from = self.ball.copy()
        self.loose_winner = 0
        self.poss_team: int | None = None
        self.announced_team: int | None = None
        self.poss_id = 0
        self.prev_passer: int | None = None
        self.last_passer: int | None = None
        self.last_pass_t = -99.0
        self.transition_until = [-1.0, -1.0]
        self.counterpress_until = [-1.0, -1.0]
        self.over: dict[int, tuple[float, float, float, float]] = {}
        self.first_time: str | None = None
        self.first_time_for: int | None = None
        self.last_lofted = False
        self.set_piece_shot = False
        self.last_pressure: dict[int, float] = {}
        self.yellows: dict[str, int] = {}
        self.dist_by_player: dict[str, float] = {}

        # Output.
        self.seq = 0
        self.events: list[dict] = []
        max_ticks = int((self.p1_len + self.p2_len + 120.0) / DT) + 10
        self.frames = np.full((max_ticks, 22, 2), np.nan, dtype=np.float32)
        self.ball_track = np.zeros((max_ticks, 4), dtype=np.float32)
        self.chunk_slots: list[list[str]] = []
        self.period_marks: list[dict] = []

        # Scheduled changes: scenario script plus ordinary substitutions.
        self.script: list[tuple[float, ScriptItem]] = []
        if scenario is not None:
            for item in scenario.script:
                self.script.append((self._display_to_t(item.at_seconds), item))
            self.script.sort(key=lambda x: x[0])
        self.subs_due: list[list[float]] = [self._plan_subs(0), self._plan_subs(1)]

    # ----- setup helpers --------------------------------------------------------------------

    def _set_physique(self, slot: int, p: Player) -> None:
        self.vmax[slot] = 7.6 + (p.attrs["pace"] - 35.0) / 60.0 * 2.4
        self.fatigue[slot] = 0.0021 * (1.45 - p.attrs["stamina"] / 100.0)
        self.stamina[slot] = 1.0

    def _display_to_t(self, display_seconds: float) -> float:
        if display_seconds < 45 * 60:
            return display_seconds
        return self.p1_len + (display_seconds - 45 * 60)

    def _plan_subs(self, team: int) -> list[float]:
        times = sorted(
            self._display_to_t(self.rng.uniform(lo, hi) * 60.0)
            for lo, hi in ((55, 68), (68, 78), (78, 86))
        )
        return times

    # ----- clock and events ------------------------------------------------------------------

    def clock(self) -> dict:
        sec = self.t if self.period == 1 else 45 * 60 + (self.t - self.p1_len)
        return {
            "period": self.period,
            "minute": int(sec // 60),
            "second": int(sec % 60),
            "matchMs": int(round(self.t * 1000)),
        }

    def emit(
        self,
        type: str,
        team: int | None = None,
        player: int | None = None,
        receiver: int | None = None,
        loc=None,
        end=None,
        outcome: str | None = None,
        **attrs,
    ) -> dict:
        self.seq += 1
        ev: dict = {
            "id": f"{self.match_id}-e{self.seq:05d}",
            "matchId": self.match_id,
            "seq": self.seq,
            "type": type,
            "clock": self.clock(),
            "team": self.club_id[team] if team is not None else None,
            "player": self.players[player].id if player is not None else None,
        }
        if receiver is not None:
            ev["receiver"] = self.players[receiver].id
        if loc is not None:
            ev["location"] = {"x": round(float(loc[0]), 1), "y": round(float(loc[1]), 1)}
        if end is not None:
            ev["end"] = {"x": round(float(end[0]), 1), "y": round(float(end[1]), 1)}
        if outcome is not None:
            ev["outcome"] = outcome
        ev["attributes"] = {k: v for k, v in attrs.items() if v is not None}
        ev["possessionId"] = f"{self.match_id}-p{self.poss_id:04d}" if self.poss_id else None
        self.events.append(ev)
        return ev

    # ----- periods ----------------------------------------------------------------------------

    def _start_period(self, period: int) -> None:
        self.period = period
        self.dir = [1, -1] if period == 1 else [-1, 1]
        self.emit(
            "period_start", outcome=None, period=period,
            attackDirection={self.club_id[0]: self.dir[0], self.club_id[1]: self.dir[1]},
        )  # fmt: skip
        self.period_marks.append(
            {
                "period": period,
                "startMs": int(round(self.t * 1000)),
                "startFrame": self.tick_i,
                "attackDirection": {self.club_id[0]: self.dir[0], self.club_id[1]: self.dir[1]},
            }
        )
        self.mode = "dead"
        self.poss_team = None
        self.holder = None
        self.flight = None
        self.carry = None
        self.over.clear()
        self.first_time = None
        self.transition_until = [-1.0, -1.0]
        self.counterpress_until = [-1.0, -1.0]
        # Line both teams up in their own halves.
        self.ball = np.array([G.CX, G.CY])
        for t in (0, 1):
            self._reindex_shape(t)
        self.restart = {"kind": "kickoff", "team": 0 if period == 1 else 1, "spot": self.ball.copy(), "at": self.t + 3.0, "taker": 0, "setpiece": False}
        tgt = self.pos.copy()
        urg = np.zeros(22)
        for t in (0, 1):
            self._team_targets(t, self.ball, tgt, urg)
        for t in (0, 1):
            for s in range(11):
                i = t * 11 + s
                ax, ay = self.att(t, tgt[i])
                if s > 0:
                    ax = min(ax, 50.0)
                    if abs(ax - 50.0) < 1e-9 and abs(ay - G.CY) < 9.0:
                        ay = G.CY + (9.0 if ay >= G.CY else -9.0)
                    tgt[i] = G.from_att(ax, ay, self.dir[t])
        self.pos[self.active] = tgt[self.active]
        self.vel[:] = 0.0
        self._schedule_restart("kickoff", self.restart["team"], self.ball.copy(), 3.0)

    def _end_period(self) -> None:
        self.emit("period_end", outcome=None, period=self.period)
        for m in self.period_marks:
            if m["period"] == self.period:
                m["endMs"] = int(round(self.t * 1000))
                m["endFrame"] = self.tick_i
        if self.period == 1:
            self._start_period(2)
        else:
            self.finished = True

    # ----- scheduled changes ------------------------------------------------------------------

    def _time_events(self) -> None:
        while self.script and self.script[0][0] <= self.t:
            _, item = self.script.pop(0)
            self._apply_script(item)
        end = self.p1_len if self.period == 1 else self.p1_len + self.p2_len
        if self.t >= end:
            self._end_period()
            return
        if self.tick_i % TICKS_PER_CHUNK == 0 and self.mode == "dead":
            for team in (0, 1):
                due = self.subs_due[team]
                if due and due[0] <= self.t:
                    due.pop(0)
                    self._substitute(team)

    def _team_index(self, club_id: str) -> int:
        try:
            return self.club_id.index(club_id)
        except ValueError:
            raise ValueError(f"scenario names club {club_id!r}, which is not in this match") from None

    def _apply_script(self, item: ScriptItem) -> None:
        team = self._team_index(item.team)
        st = self.style[team]
        for k, dv in item.change.items():
            setattr(st, k, min(1.0, max(0.0, getattr(st, k) + dv)))
        for k, v in item.set.items():
            setattr(st, k, min(1.0, max(0.0, v)))
        if item.event == "substitution":
            self.subs_due[team].insert(0, self.t)
        elif item.event == "red_card":
            slot = None
            if item.player:
                slot = next((i for i in range(team * 11, team * 11 + 11) if self.players[i].id == item.player), None)
            if slot is None:
                slot = next(i for i in range(team * 11 + 1, team * 11 + 11) if self.active[i] and GROUP[self.players[i].pos] == "DEF")
            self._send_off(slot, team)

    def _substitute(self, team: int) -> None:
        base = team * 11
        cands = [(float(self.stamina[base + s]), base + s) for s in range(1, 11) if self.active[base + s]]
        if not cands or not self.bench[team]:
            return
        out_slot = min(cands)[1]
        out_p = self.players[out_slot]
        self.dist_by_player[out_p.id] = float(self.dist_run[out_slot])
        self.dist_run[out_slot] = 0.0
        group = GROUP[out_p.pos]
        pool = [p for p in self.bench[team] if p.pos != "GK"]
        same = [p for p in pool if GROUP[p.pos] == group] or pool
        if not same:
            return
        incoming = max(same, key=lambda p: p.overall)
        self.bench[team].remove(incoming)
        self.players[out_slot] = incoming
        self._set_physique(out_slot, incoming)
        self.emit("substitution", team=team, player=out_slot, loc=self.pos[out_slot], outcome=None, off=out_p.id, position=incoming.pos)

    # ----- the tick -------------------------------------------------------------------------------

    def _update_ball_position(self) -> None:
        if self.mode == "carry" and self.holder is not None:
            h = self.holder
            v = self.vel[h]
            sp = float(np.hypot(v[0], v[1]))
            off = v / sp * 0.5 if sp > 0.5 else np.array([0.3 * self.dir[self.team_of(h)], 0.0])
            self.ball[:] = self.pos[h] + off
            self.ball_z = 0.0
        elif self.mode == "flight" and self.flight is not None:
            f = self.flight
            span = max(f["t1"] - f["t0"], 1e-6)
            s = min(1.0, max(0.0, (self.t - f["t0"]) / span))
            end = np.array(f["end"], dtype=float)
            target = None
            if f["kind"] == "pass":
                if f["outcome"] == "complete":
                    target = f["receiver"]
                elif f["outcome"] == "intercepted":
                    target = f["interceptor"]
            elif f["kind"] == "corner" and f["outcome"] == "complete":
                target = f["receiver"]
            if target is not None:
                w = min(1.0, max(0.0, (s - 0.55) / 0.45))
                end = end + (self.pos[target] - end) * w
            self.ball[:] = f["start"] + s * (end - f["start"])
            self.ball_z = 4.0 * f["z_peak"] * s * (1.0 - s)
        elif self.mode == "loose":
            span = max(self.loose_until - self.loose_t0, 1e-6)
            s = min(1.0, max(0.0, (self.t - self.loose_t0) / span))
            self.ball[:] = self.loose_from + s * (self.pos[self.loose_winner] - self.loose_from)
            self.ball_z = 0.0
        elif self.restart is not None:
            self.ball[:] = self.restart["spot"]
            self.ball_z = 0.0

    def _record(self) -> None:
        i = self.tick_i
        if i % TICKS_PER_CHUNK == 0:
            self.chunk_slots.append([p.id for p in self.players])
        fr = self.pos.astype(np.float32)
        fr[~self.active] = np.nan
        self.frames[i] = fr
        alive = 0.0 if self.mode == "dead" else 1.0
        self.ball_track[i] = (self.ball[0], self.ball[1], self.ball_z, alive)

    def tick(self) -> None:
        self._time_events()
        if self.finished:
            return
        self.advance_ball()
        self.move_players()
        self._update_ball_position()
        self._record()
        self.t += DT
        self.tick_i += 1

    def run(self) -> MatchResult:
        self._start_period(1)
        guard = self.frames.shape[0] - 2
        while not self.finished and self.tick_i < guard:
            self.tick()
        return self._result()

    def _result(self) -> MatchResult:
        n = self.tick_i
        # Pad to whole chunks so every tracking chunk is complete.
        n_chunks = (n + TICKS_PER_CHUNK - 1) // TICKS_PER_CHUNK
        total = n_chunks * TICKS_PER_CHUNK
        frames = self.frames[:total].copy()
        ball = self.ball_track[:total].copy()
        if total > n:
            frames[n:] = frames[n - 1]
            ball[n:] = ball[n - 1]
        meta = {
            "matchId": self.match_id,
            "league": "Lumen League",
            "seed": self.seed,
            "scenario": self.scenario.id if self.scenario else None,
            "hz": HZ,
            "chunkTicks": TICKS_PER_CHUNK,
            "pitch": {"length": G.PITCH_L, "width": G.PITCH_W},
            "home": self._team_meta(0),
            "away": self._team_meta(1),
            "periods": self.period_marks,
            "score": {self.club_id[0]: self.score[0], self.club_id[1]: self.score[1]},
            "frames": total,
        }
        dist = dict(self.dist_by_player)
        for i in range(22):
            dist[self.players[i].id] = dist.get(self.players[i].id, 0.0) + float(self.dist_run[i])
        stats = {
            "distance_km": {pid: d / 1000.0 for pid, d in dist.items()},
            "final_stamina": {self.players[i].id: float(self.stamina[i]) for i in range(22)},
        }
        return MatchResult(meta=meta, events=self.events, frames=frames, ball=ball, chunk_slots=self.chunk_slots, stats=stats)

    def _team_meta(self, t: int) -> dict:
        club = self.clubs[t]
        known = {p.id: p for p in club.squad}
        return {
            "id": club.id,
            "name": club.name,
            "short": club.short,
            "colors": club.colors,
            "formation": self.formation_name[t],
            "lineup": self.lineups[t],
            "players": {
                pid: {"name": p.name, "pos": p.pos, "number": p.number} for pid, p in known.items()
            },
        }


def simulate(
    match_id: str,
    home: Club,
    away: Club,
    *,
    seed: int = 1,
    scenario: Scenario | None = None,
    formations: tuple[str | None, str | None] = (None, None),
) -> MatchResult:
    return MatchSim(match_id, home, away, seed=seed, scenario=scenario, formations=formations).run()
