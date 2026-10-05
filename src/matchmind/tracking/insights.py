"""Tracking-derived analytics, computed incrementally frame by frame.

Everything a tracking provider adds on top of events, from nothing but player and ball positions:

* ``space_control`` every 30 s: how much of the pitch each team controls, how much of the final third,
  how much space the opponent controls *behind the team's defensive line* while they have the ball, and how
  large the defending block is (convex hull of its ten outfield players)
* ``off_ball_run`` events: runs in behind, overlaps and forwards dropping into midfield, from player
  velocities alone
* ``player_load`` every 5 minutes: distance, high-speed running, sprint distance, accelerations and
  decelerations per player, with a 15-minute block profile for fatigue
* ``shape_profile`` per team every 15 minutes: each player's average position while defending and while
  in possession, from which the *measured* formation is read (``analytics.measured_shape``)

State is per frame and deterministic, so streaming and batch runs agree.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

import numpy as np

from ..core import geometry as G
from .control import CELL_AREA, CELLS, attack_x_grid, home_control

CONTROL_EVERY = 5  # frames between pitch-control samples (1 Hz)
CONTROL_WINDOW = 150  # frames per space_control event (30 s)
LOAD_WINDOW = 1500  # frames per player_load event (5 min)
BLOCK_FRAMES = 4500  # 15 minutes: fatigue blocks and shape profiles
HSR_KMH = 19.8
SPRINT_KMH = 25.0
ACCEL = 3.0  # m/s^2 over one second, the usual 'high-intensity' threshold
RUN_SPEED = 4.4  # m/s (about 16 km/h) sustained
RUN_SPEED_FULLBACK = 1.8  # a fullback's overlap is a long stride up the touchline, not a sprint
RUN_MIN_FRAMES = 7
RUN_GRACE_FRAMES = 3
RUN_MIN_FORWARD_M = 10.0
DROP_SPEED = 3.0
DROP_MIN_M = 8.0
FULLBACKS = ("LB", "RB", "LWB", "RWB")

Make = Callable[..., dict]


def hull_area(points: np.ndarray) -> float:
    """Area in m^2 of the convex hull of a set of (x, y) points (monotone chain and the shoelace formula)."""
    p = sorted(map(tuple, points.tolist()))
    if len(p) < 3:
        return 0.0

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list = []
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    h = lower[:-1] + upper[:-1]
    return abs(sum(h[i][0] * h[(i + 1) % len(h)][1] - h[(i + 1) % len(h)][0] * h[i][1] for i in range(len(h)))) / 2.0


class TrackingInsights:
    def __init__(self, meta: dict, make: Make, hz: int) -> None:
        self.make = make
        self.hz = hz
        self.dt = 1.0 / hz
        self.clubs = [meta["home"]["id"], meta["away"]["id"]]
        self.pos_of: dict[str, str] = {}
        for side in ("home", "away"):
            for pid, p in meta[side]["players"].items():
                self.pos_of[pid] = p["pos"]
        self.hist: list[np.ndarray] = []
        self.speed_hist: list[np.ndarray] = []
        # space control
        self.ctrl = {c: self._blank_ctrl() for c in self.clubs}
        # runs
        self.runs: dict[int, dict] = {}
        # load
        self.load: dict[str, dict] = {}
        self.acc_active: dict[str, int] = {}
        # shape
        self.shape: dict[str, dict[str, dict[str, list]]] = {c: {"def": {}, "ip": {}} for c in self.clubs}
        self._cur_block = 0

    @staticmethod
    def _blank_ctrl() -> dict:
        return {"share": 0.0, "third": 0.0, "n": 0, "behind": 0.0, "behind_n": 0, "block": 0.0, "block_n": 0}

    # ----- the frame step ----------------------------------------------------------------------------------

    def step(
        self, f: int, pos: np.ndarray, ball: np.ndarray, alive: bool, slots: list[str],
        sm_kmh: np.ndarray, step_dist: np.ndarray, dirs: dict[str, int], new_period: bool,
    ) -> list[dict]:
        out: list[dict] = []
        self._cur_block = f // BLOCK_FRAMES
        if new_period:
            self.hist, self.speed_hist = [], []
            self._close_all_runs(f, pos, slots, dirs, out)
        self.hist.append(pos)
        self.hist = self.hist[-3:]
        self.speed_hist.append(sm_kmh / 3.6)
        self.speed_hist = self.speed_hist[-6:]

        nearest, poss_team = self._possession(pos, ball, alive)
        self._shape_acc(pos, slots, dirs, poss_team, ball)
        self._load_acc(slots, sm_kmh, step_dist)
        if f % CONTROL_EVERY == 0 and alive:
            self._control_sample(pos, ball, dirs, poss_team)
        self._runs_step(f, pos, ball, slots, dirs, nearest, poss_team, out)

        if (f + 1) % CONTROL_WINDOW == 0:
            out.extend(self._emit_control(f + 1))
        if (f + 1) % LOAD_WINDOW == 0:
            out.append(self._emit_load(f + 1))
        if (f + 1) % BLOCK_FRAMES == 0:
            out.extend(self._emit_shape(f + 1))
        return out

    def flush(self, f: int) -> list[dict]:
        out: list[dict] = []
        if self.hist:
            pos = self.hist[-1]
            self._close_all_runs(f, pos, None, None, out)
        if any(c["n"] for c in self.ctrl.values()):
            out.extend(self._emit_control(f))
        out.append(self._emit_load(f))
        out.extend(self._emit_shape(f))
        return out

    # ----- helpers -------------------------------------------------------------------------------------------

    def _possession(self, pos: np.ndarray, ball: np.ndarray, alive: bool) -> tuple[int | None, int | None]:
        if not alive:
            return None, None
        d = np.hypot(pos[:, 0] - ball[0], pos[:, 1] - ball[1])
        d = np.where(np.isnan(d), np.inf, d)
        n = int(np.argmin(d))
        return (n, n // 11) if np.isfinite(d[n]) else (None, None)

    @staticmethod
    def _to_att(pts: np.ndarray, d: int) -> np.ndarray:
        return pts if d == 1 else np.stack([G.PITCH_L - pts[..., 0], G.PITCH_W - pts[..., 1]], axis=-1)

    # ----- space control -----------------------------------------------------------------------------------------

    def _control_sample(self, pos: np.ndarray, ball: np.ndarray, dirs: dict[str, int], poss: int | None) -> None:
        p_home = home_control(pos)
        for ti, club in enumerate(self.clubs):
            p = p_home if ti == 0 else 1.0 - p_home
            d = dirs.get(club, 1)
            ax = attack_x_grid(d)
            c = self.ctrl[club]
            c["share"] += float(p.mean())
            c["third"] += float(p[ax >= G.FINAL_THIRD_X].mean())
            c["n"] += 1
        if poss is None:
            return
        att, dfn = self.clubs[poss], self.clubs[1 - poss]
        d_att = dirs.get(att, 1)
        ball_ax = ball[0] if d_att == 1 else G.PITCH_L - ball[0]
        if ball_ax < 40.0:
            return
        opp = pos[(1 - poss) * 11 + 1 : (1 - poss) * 11 + 11]
        opp = opp[~np.isnan(opp[:, 0])]
        if len(opp) < 4:
            return
        opp_x = np.sort(self._to_att(opp, d_att)[:, 0])[::-1]
        line = float(opp_x[:4].mean())  # the deepest four: the defensive line, in the attacker's frame
        p_att = p_home if poss == 0 else 1.0 - p_home
        ax = attack_x_grid(d_att)
        cy = CELLS[:, 1].reshape(p_att.shape)
        region = (ax >= line) & (np.abs(cy - G.CY) <= 22.0)
        space = float(((p_att > 0.5) & region).sum() * CELL_AREA)
        c = self.ctrl[dfn]
        c["behind"] += space
        c["behind_n"] += 1
        if ball_ax <= 75.0:  # the defending block while the ball is in the middle of the pitch
            c["block"] += hull_area(opp)
            c["block_n"] += 1

    def _emit_control(self, f_end: int) -> list[dict]:
        evs = []
        for club in self.clubs:
            c = self.ctrl[club]
            if c["n"] == 0:
                continue
            attrs = {
                "controlShare": round(c["share"] / c["n"], 3),
                "finalThirdControl": round(c["third"] / c["n"], 3),
                "spaceBehindM2": round(c["behind"] / c["behind_n"], 0) if c["behind_n"] else None,
                "behindSamples": c["behind_n"],
                "blockAreaM2": round(c["block"] / c["block_n"], 0) if c["block_n"] else None,
                "samples": c["n"],
            }
            evs.append(self.make("space_control", f_end, club, None, attrs))
        self.ctrl = {c: self._blank_ctrl() for c in self.clubs}
        return evs

    # ----- physical load ---------------------------------------------------------------------------------------------

    def _load_acc(self, slots: list[str], sm_kmh: np.ndarray, step: np.ndarray) -> None:
        for i in range(22):
            if i % 11 == 0:
                continue
            pid = slots[i]
            L = self.load.setdefault(pid, {"m": 0.0, "hsr": 0.0, "sprint": 0.0, "acc": 0, "dec": 0, "frames": 0, "blocks": defaultdict(float)})
            s = float(step[i])
            L["m"] += s
            L["frames"] += 1
            if sm_kmh[i] >= HSR_KMH:
                L["hsr"] += s
            if sm_kmh[i] >= SPRINT_KMH:
                L["sprint"] += s
            if len(self.speed_hist) >= 6:
                a = (float(self.speed_hist[-1][i]) - float(self.speed_hist[0][i])) / (5 * self.dt)
                st = self.acc_active.get(pid, 0)
                if a >= ACCEL and st != 1:
                    L["acc"] += 1
                    self.acc_active[pid] = 1
                elif a <= -ACCEL and st != -1:
                    L["dec"] += 1
                    self.acc_active[pid] = -1
                elif abs(a) < 0.8:
                    self.acc_active[pid] = 0
            if sm_kmh[i] >= HSR_KMH:
                self._block_add(L, s)

    def _block_add(self, L: dict, s: float) -> None:
        L["blocks"][self._cur_block] += s

    def _emit_load(self, f_end: int) -> dict:
        players = {}
        for pid, L in self.load.items():
            blocks = [round(L["blocks"].get(b, 0.0)) for b in range(max(L["blocks"], default=-1) + 1)]
            players[pid] = {
                "km": round(L["m"] / 1000.0, 2), "hsrM": round(L["hsr"]), "sprintM": round(L["sprint"]),
                "acc": L["acc"], "dec": L["dec"], "minutes": round(L["frames"] / self.hz / 60.0, 1), "hsrBlocks": blocks,
            }
        return self.make("player_load", f_end, None, None, {"players": players})

    # ----- measured shape --------------------------------------------------------------------------------------------------

    def _shape_acc(self, pos: np.ndarray, slots: list[str], dirs: dict[str, int], poss: int | None, ball: np.ndarray) -> None:
        for ti, club in enumerate(self.clubs):
            d = dirs.get(club, 1)
            ball_ax = ball[0] if d == 1 else G.PITCH_L - ball[0]
            if poss is None:
                continue
            phase = "ip" if poss == ti else ("def" if 35.0 <= ball_ax <= 75.0 else None)
            if phase is None:
                continue
            for i in range(ti * 11 + 1, ti * 11 + 11):
                p = pos[i]
                if np.isnan(p[0]):
                    continue
                ax, ay = (p[0], p[1]) if d == 1 else (G.PITCH_L - p[0], G.PITCH_W - p[1])
                acc = self.shape[club][phase].setdefault(slots[i], [0.0, 0.0, 0])
                acc[0] += ax
                acc[1] += ay
                acc[2] += 1

    def _emit_shape(self, f_end: int) -> list[dict]:
        evs = []
        block = max(f_end - 1, 0) // BLOCK_FRAMES
        for club in self.clubs:
            attrs = {"block": block}
            empty = True
            for phase in ("def", "ip"):
                players = {pid: [round(a[0] / a[2], 1), round(a[1] / a[2], 1), a[2]] for pid, a in self.shape[club][phase].items() if a[2] >= 25}
                attrs[phase] = players
                empty = empty and not players
            if not empty:
                evs.append(self.make("shape_profile", f_end, club, None, attrs))
            self.shape[club] = {"def": {}, "ip": {}}
        return evs

    # ----- off-ball runs --------------------------------------------------------------------------------------------------------

    def _runs_step(
        self, f: int, pos: np.ndarray, ball: np.ndarray, slots: list[str], dirs: dict[str, int],
        nearest: int | None, poss: int | None, out: list[dict],
    ) -> None:
        if len(self.hist) < 3:
            return
        vel = (self.hist[-1] - self.hist[-3]) / (2 * self.dt)
        for i in range(22):
            if i % 11 == 0:
                continue
            run = self.runs.get(i)
            on_ball_team = poss is not None and i // 11 == poss and i != nearest
            kind = None
            if on_ball_team and not np.isnan(vel[i, 0]):
                d = dirs.get(self.clubs[i // 11], 1)
                vx = float(vel[i, 0]) * d
                sp = float(np.hypot(vel[i, 0], vel[i, 1]))
                floor = RUN_SPEED_FULLBACK if self.pos_of.get(slots[i]) in FULLBACKS else RUN_SPEED
                if sp >= floor and vx >= 0.55 * sp:
                    kind = "f"
                elif sp >= DROP_SPEED and vx <= -0.6 * sp:
                    kind = "d"
            if run is not None and kind != run["kind"]:
                run["miss"] += 1  # a run survives a moment below the threshold (0.6 s of grace)
                if run["miss"] > RUN_GRACE_FRAMES:
                    self._close_run(i, f, pos, ball, slots, dirs, out)
                    run = None
            if kind is not None:
                d = dirs.get(self.clubs[i // 11], 1)
                here = self._to_att(pos[i][None, :], d)[0].copy()
                if run is None:
                    self.runs[i] = run = {
                        "kind": kind, "start": f, "pid": slots[i], "peak": 0.0, "miss": 0, "last": f, "last_pos": here,
                        "from": here,
                        "carrier": slots[nearest] if nearest is not None else None,
                        "carrier_pos": self._to_att(pos[nearest][None, :], d)[0].copy() if nearest is not None else None,
                    }
                if kind == run["kind"]:
                    run["miss"] = 0
                    run["last"], run["last_pos"] = f, here
                    run["peak"] = max(run["peak"], float(np.hypot(vel[i, 0], vel[i, 1])))

    def _close_all_runs(self, f: int, pos: np.ndarray, slots, dirs, out: list[dict]) -> None:
        for i in list(self.runs):
            self.runs.pop(i)  # a period boundary or the final whistle ends the run without a report

    def _close_run(self, i: int, f: int, pos: np.ndarray, ball: np.ndarray, slots: list[str], dirs: dict[str, int], out: list[dict]) -> None:
        run = self.runs.pop(i)
        n = run["last"] - run["start"] + 1
        club = self.clubs[i // 11]
        d = dirs.get(club, 1)
        end = run["last_pos"]
        start = run["from"]
        dist = float(np.hypot(*(end - start)))
        if n < RUN_MIN_FRAMES:
            return
        role = self.pos_of.get(run["pid"], "")
        ball_att = self._to_att(np.array([[ball[0], ball[1]]]), d)[0]
        opp = pos[(1 - i // 11) * 11 + 1 : (1 - i // 11) * 11 + 11]
        opp = opp[~np.isnan(opp[:, 0])]
        kind = None
        if run["kind"] == "f" and dist >= (12.0 if role in FULLBACKS else RUN_MIN_FORWARD_M) and len(opp) >= 4:
            opp_x = np.sort(self._to_att(opp, d)[:, 0])[::-1]
            line = float(opp_x[1])  # second-last outfield opponent (the goalkeeper is last): the offside line
            if start[0] < line - 2.0 <= end[0] and end[0] >= ball_att[0] + 3.0:
                kind = "in_behind"
            elif role in FULLBACKS and run["carrier_pos"] is not None:
                cpos = run["carrier_pos"]
                if start[0] < cpos[0] - 1.0 and end[0] > ball_att[0] + 2.0 and abs(end[1] - G.CY) >= abs(cpos[1] - G.CY) + 3.0:
                    kind = "overlap"
        elif run["kind"] == "d" and dist >= DROP_MIN_M and role in ("ST", "AM", "LW", "RW", "CM"):
            if start[0] - end[0] >= DROP_MIN_M and float(np.hypot(*(end - ball_att))) <= 30.0:
                kind = "drop"
        if kind is None:
            return
        out.append(self.make(
            "off_ball_run", f, club, run["pid"],
            {"kind": kind, "distanceM": round(dist, 1), "peakKmh": round(run["peak"] * 3.6, 1), "durationMs": round(n * 1000 / self.hz),
             "startMs": round(run["start"] * 1000 / self.hz), "from": [round(float(start[0]), 1), round(float(start[1]), 1)],
             "to": [round(float(end[0]), 1), round(float(end[1]), 1)], "carrier": run["carrier"]},
        ))
