"""On-ball behaviour for the match simulator: decisions, passes, shots, duels and restarts.

The ball is always in exactly one mode:

* ``carry``  - a player holds it and acts when ``next_action_t`` arrives
* ``flight`` - a pass, shot or clearance is travelling; its outcome was decided at launch
* ``loose``  - nobody has it yet; a winner has been chosen and is running to it
* ``dead``   - play is stopped for a restart (throw-in, corner, free kick, kick-off ...)

Decisions are probabilistic but driven by football quantities (xG, pass completion, zone
threat, pressure, the team's style dials), so aggregate statistics come out realistic and
can be tuned through ``TUNE`` without touching the logic.
"""

from __future__ import annotations

import math

import numpy as np

from ..core import geometry as G
from ..core.models import threat, xg, xpass

# Calibration knobs. ``matchmind report-realism`` shows where league averages land.
TUNE: dict[str, float] = {
    "think_base": 1.45,
    "think_slow": 3.90,
    "think_noise": 0.60,
    "pass_w": 1.00,
    "carry_w": 0.45,
    "dribble_w": 0.10,
    "shot_w": 0.09,
    "shot_k": 3.9,
    "first_time_boost": 3.0,
    "clear_w": 6.0,
    "duel_rate": 0.18,
    "pressure_base": 0.20,
    "pressure_gain": 0.90,
    "foul_share": 0.56,
    "tackle_win": 0.40,
    "yellow_p": 0.14,
    "red_p": 0.003,
    "offside_p": 0.22,
    "dead_goal": 28.0,
    "dead_pen": 22.0,
}
DEAD_RANGE = {
    "throw_in": (5.0, 9.0),
    "goal_kick": (7.0, 13.0),
    "corner": (11.0, 18.0),
    "free_kick": (7.0, 14.0),
}

PRESSURE_RANGE = 3.2
DUEL_RANGE = 1.9


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(v[0], v[1]))
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


class ActionsMixin:
    # ----- small helpers ---------------------------------------------------------------------

    @staticmethod
    def team_of(slot: int) -> int:
        return 0 if slot < 11 else 1

    def att(self, t: int, p) -> tuple[float, float]:
        return G.to_att(float(p[0]), float(p[1]), self.dir[t])

    def pressure_at(self, p, o: int) -> float:
        sl = slice(o * 11, o * 11 + 11)
        pts = self.pos[sl][self.active[sl]]
        d = np.hypot(pts[:, 0] - p[0], pts[:, 1] - p[1])
        return float(min(1.0, np.exp(-np.power(d / 2.8, 1.5)).sum()))

    def nearest_opps(self, p, o: int, n: int = 1, outfield: bool = True) -> list[tuple[float, int]]:
        lo = o * 11 + (1 if outfield else 0)
        sl = slice(lo, o * 11 + 11)
        pts = self.pos[sl]
        d = np.hypot(pts[:, 0] - p[0], pts[:, 1] - p[1])
        d = np.where(self.active[sl], d, 1e9)
        idx = np.argsort(d)[:n]
        return [(float(d[i]), lo + int(i)) for i in idx]

    def urgency_for_speed(self, slot: int, v: float) -> float:
        r = v / float(self.vmax[slot])
        if r <= 0.25:
            return 0.1
        return float(min(1.0, ((r - 0.25) / 0.75) ** (1.0 / 1.3)))

    # ----- possession --------------------------------------------------------------------------

    def think_time(self, slot: int, first_time: bool = False) -> float:
        t = self.team_of(slot)
        st = self.style[t]
        pr = self.pressure_at(self.pos[slot], 1 - t)
        base = TUNE["think_base"] + TUNE["think_slow"] * (1.0 - st.tempo)
        base *= 1.0 - 0.55 * pr
        if self.t < self.transition_until[t]:
            base *= 0.6
        if first_time:
            base *= 0.45
        return max(0.3, base + self.rng.random() * TUNE["think_noise"])

    def _turnover_to(self, team: int) -> None:
        """Hand possession to ``team`` silently (new possession id, no event)."""
        if self.poss_team != team:
            self.poss_team = team
            self.poss_id += 1
            self.prev_passer = None

    def _announce_possession(self, team: int, slot: int, cause: str) -> None:
        """Emit a possession_change event the first time ``team`` is seen with the ball."""
        if self.announced_team == team:
            return
        prev = self.announced_team
        self.announced_team = team
        self.emit("possession_change", team=team, player=slot, loc=self.pos[slot], cause=cause)
        ax, _ = self.att(team, self.pos[slot])
        if cause in ("tackle", "interception", "loose_ball", "save") and ax < 78.0:
            self.transition_until[team] = self.t + 7.0
        if prev is not None and cause in ("tackle", "interception", "loose_ball"):
            if self.style[prev].on_loss == "counterpress":
                self.counterpress_until[prev] = self.t + 4.5
            else:  # contain for two seconds, then drop into the block
                self.counterpress_until[prev] = self.t + 2.0
                self.regroup_until[prev] = self.t + 5.0

    def gain_possession(self, slot: int, cause: str) -> None:
        t = self.team_of(slot)
        self._turnover_to(t)
        self._announce_possession(t, slot, cause)
        self.holder = slot
        self.mode = "carry"
        self.holder_since = self.t
        self.carry = None
        ft = self.first_time is not None and self.first_time_for == slot
        self.next_action_t = self.t + self.think_time(slot, first_time=ft)
        self.ball[:2] = self.pos[slot]
        self.ball_z = 0.0

    # ----- per-tick ball logic ----------------------------------------------------------------

    def advance_ball(self) -> None:
        if self.mode == "carry":
            self._advance_carry()
        elif self.mode == "flight":
            if self.t >= self.flight["t1"]:
                self._resolve_flight()
        elif self.mode == "loose":
            if self.t >= self.loose_until:
                self._resolve_loose()
        elif self.mode == "dead":
            if self.t >= self.restart["at"]:
                self._execute_restart()

    def _advance_carry(self) -> None:
        h = self.holder
        t_ = self.team_of(h)
        o = 1 - t_
        if self.t - self.holder_since >= 0.4:
            (d, c), = self.nearest_opps(self.pos[h], o)
            if d <= DUEL_RANGE:
                p = TUNE["duel_rate"] * self.DT * (0.6 + 0.4 * self.style[o].press_intensity)
                if self.rng.random() < p:
                    self._duel(h, c)
                    return
        if self.t >= self.next_action_t:
            self._decide()

    # ----- decisions ------------------------------------------------------------------------------

    def _flush_carry(self) -> None:
        """Emit the carry event for movement with the ball since the last action."""
        if self.carry is None:
            return
        h = self.holder
        start = self.carry["start"]
        end = self.pos[h]
        if math.hypot(end[0] - start[0], end[1] - start[1]) >= 4.0:
            self.emit("carry", team=self.team_of(h), player=h, loc=start, end=end, outcome="complete")
        self.carry = None

    def _emit_pressure(self, h: int, o: int, hp) -> None:
        """A defender closing the carrier down. Frequency is a direct readout of how hard the
        defending team is pressing (intensity, how high it is willing to press) and how tired
        the defender is, which is what pressure events measure in real data."""
        (d, c), = self.nearest_opps(hp, o)
        if d > PRESSURE_RANGE or self.t - self.last_pressure.get(c, -9.0) <= 2.5:
            return
        st = self.style[o]
        bx_def, _ = self.att(o, hp)
        engaged = bx_def <= max(50.0, 45.0 + 55.0 * st.press_height)
        stamina = float(self.stamina[c])
        p = (TUNE["pressure_base"] + TUNE["pressure_gain"] * st.press_intensity * (0.4 + 0.6 * stamina))
        p *= (1.0 if engaged else 0.4) * (1.0 - 0.25 * d / PRESSURE_RANGE)
        if self.rng.random() < p:
            self.last_pressure[c] = self.t
            self.emit(
                "pressure", team=o, player=c, loc=self.pos[c], outcome=None,
                against=self.players[h].id,
            )  # fmt: skip

    def _space_ahead(self, h: int, t_: int, o: int, hp):
        hax, hay = self.att(t_, hp)
        d = self.dir[t_]
        to_goal = np.array([G.PITCH_L - hax, G.CY - hay])
        u_att = _unit(to_goal) if hax > 45 else np.array([1.0, 0.0])
        u = np.array([u_att[0] * d, u_att[1] * d])  # attack frame -> absolute direction
        sl = slice(o * 11, o * 11 + 11)
        pts = self.pos[sl][self.active[sl]]
        r = pts - hp
        along = r @ u
        lateral = np.abs(r[:, 0] * u[1] - r[:, 1] * u[0])
        blocked = (along > 0.5) & (along < 18.0) & (lateral < 3.5 + 0.12 * along)
        space = float(along[blocked].min()) if blocked.any() else 18.0
        return space, u

    def _decide(self, restart: str | None = None) -> None:
        h = self.holder
        t_ = self.team_of(h)
        o = 1 - t_
        st = self.style[t_]
        pl = self.players[h]
        hp = self.pos[h].copy()
        hax, hay = self.att(t_, hp)
        pr = self.pressure_at(hp, o)
        trans = self.t < self.transition_until[t_]
        ft = self.first_time if self.first_time_for == h else None
        is_gk = h % 11 == 0

        self._flush_carry()
        if restart is None:
            self._emit_pressure(h, o, hp)

        weights: dict[str, float] = {}
        shot_ctx = None
        gd = G.goal_dist(hax, hay)
        can_shoot = not is_gk and hax >= 68.0 and gd <= 32.0
        if restart == "free_kick":
            can_shoot = hax >= 72.0 and gd <= 30.0 and abs(hay - G.CY) <= 22.0
        elif restart is not None:
            can_shoot = False
        if can_shoot:
            if restart == "free_kick":
                xgv = xg(hax, hay, direct_free_kick=True)
                w = 0.8
                shot_ctx = (xgv, "foot", "free_kick")
            else:
                body = "head" if (ft == "cross" and self.last_lofted) else "foot"
                assist = ft if ft in ("cross", "through", "cutback") else "open"
                xgv = xg(hax, hay, body=body, assist=assist, pressure=pr)
                w = TUNE["shot_w"] * math.exp(TUNE["shot_k"] * (xgv - 0.07))
                w *= 1.0 + 0.012 * (pl.attrs["finishing"] - 65)
                if ft in ("cross", "through", "cutback"):
                    w *= TUNE["first_time_boost"]
                shot_ctx = (xgv, body, assist)
            weights["shot"] = w

        cands = self._pass_candidates(h, t_, o, hax, hay, pr, restart)
        if cands:
            weights["pass"] = TUNE["pass_w"] * (1.0 + 0.5 * pr)

        carry_info = None
        if not is_gk and restart is None:
            space, u = self._space_ahead(h, t_, o, hp)
            if space >= 5.5:
                w = TUNE["carry_w"] * (0.7 + pl.attrs["dribbling"] / 100.0) * (1.15 - 0.9 * pr)
                w *= (1.3 if trans else 1.0) * min(1.0, (space - 4.0) / 8.0)
                weights["carry"] = max(0.0, w)
                carry_info = (space, u)
            (d1, c1), = self.nearest_opps(hp, o)
            if 1.5 <= d1 <= 5.5 and hax > 35:
                to_c = _unit(self.pos[c1] - hp)
                ahead = to_c @ (carry_info[1] if carry_info else _unit(np.array([self.dir[t_], 0.0])))
                if ahead > 0.6:
                    weights["dribble"] = TUNE["dribble_w"] * (0.5 + pl.attrs["dribbling"] / 90.0)
            if hax < 30.0 and pr > 0.4:
                weights["clear"] = TUNE["clear_w"] * (pr - 0.3) * (1.8 if hax < 16.0 else 1.0)

        if not weights:  # nothing sensible: hoof it
            weights["clear"] = 1.0
        action = self._weighted(weights)

        if action == "shot":
            xgv, body, assist = shot_ctx
            self._launch_shot(h, xgv, body, assist, pr, restart)
        elif action == "pass":
            self._launch_pass(h, self._pick_pass(cands, pl, st), restart)
        elif action == "carry":
            self._start_carry(h, carry_info[0], carry_info[1], hp)
        elif action == "dribble":
            self._take_on(h, c1, pr, hp)
        else:
            self._clearance(h, t_, o, hp)

    def _weighted(self, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        r = self.rng.random() * total
        acc = 0.0
        for k, w in weights.items():
            acc += w
            if r <= acc:
                return k
        return k  # noqa: B023 - last key

    # ----- carries and take-ons ----------------------------------------------------------------

    def _start_carry(self, h: int, space: float, u: np.ndarray, hp) -> None:
        length = min(14.0, max(4.0, space - 3.5 + self.rng.uniform(-2.0, 2.0)))
        speed = 4.2 + 0.03 * (self.players[h].attrs["pace"] - 60)
        dur = length / speed
        target = hp + u * length
        self.over[h] = (float(target[0]), float(target[1]), 0.55, self.t + dur)
        self.carry = {"start": hp.copy()}
        self.next_action_t = self.t + dur
        self.first_time = None

    def _take_on(self, h: int, c: int, pr: float, hp) -> None:
        t_ = self.team_of(h)
        pl, dfn = self.players[h], self.players[c]
        p = min(0.8, max(0.2, 0.55 + 0.012 * (pl.attrs["dribbling"] - dfn.attrs["defending"]) - 0.1 * (pr - 0.5)))
        won = self.rng.random() < p
        self.emit(
            "dribble", team=t_, player=h, loc=hp, outcome="complete" if won else "failed",
            opponent=dfn.id,
        )  # fmt: skip
        if won:
            u = _unit(self.pos[c] - hp)
            target = self.pos[c] + u * 3.5
            self.over[h] = (float(target[0]), float(target[1]), 0.8, self.t + 1.3)
            self.next_action_t = self.t + 1.3
            self.carry = None
        else:
            self._tackle_won(h, c, hp)

    # ----- duels, fouls and cards -------------------------------------------------------------

    def _duel(self, h: int, c: int) -> None:
        t_ = self.team_of(h)
        o = 1 - t_
        hp = self.pos[h].copy()
        self._flush_carry()
        r = self.rng.random()
        pl, dfn = self.players[h], self.players[c]
        skill = (dfn.attrs["defending"] - pl.attrs["dribbling"]) * 0.004
        hax, hay = self.att(t_, hp)
        foul_p = TUNE["foul_share"] + 0.1 * (dfn.attrs["aggression"] - 60) / 100.0
        if G.in_box(hax, hay):
            foul_p *= 0.12  # defenders know better than to foul in their own box
        if r < foul_p:
            self._foul(c, h, hp)
        elif r < foul_p + TUNE["tackle_win"] + skill:
            self._tackle_won(h, c, hp)
        else:
            self.emit(
                "tackle", team=o, player=c, loc=hp, outcome="lost", against=pl.id
            )
            self.next_action_t = min(self.next_action_t, self.t + 0.4)

    def _tackle_won(self, h: int, c: int, hp) -> None:
        o = self.team_of(c)
        self.emit("tackle", team=o, player=c, loc=hp, outcome="won", against=self.players[h].id)
        self.holder = None
        if self.rng.random() < 0.55:
            self.gain_possession(c, "tackle")
        else:
            self._start_loose(hp, bias_team=o, bias=1.6)

    def _foul(self, c: int, h: int, spot) -> None:
        o = self.team_of(c)
        t_ = self.team_of(h)
        self.holder = None
        hax, hay = self.att(t_, spot)
        in_box = G.in_box(hax, hay)
        self.emit(
            "foul", team=o, player=c, loc=spot, outcome=None,
            fouled=self.players[h].id, inBox=in_box,
        )  # fmt: skip
        self._maybe_card(c, o)
        self._turnover_to(t_)
        if in_box:
            self._schedule_restart("penalty", t_, np.array(G.from_att(G.PITCH_L - G.PENALTY_SPOT, G.CY, self.dir[t_])), TUNE["dead_pen"])
        else:
            self._schedule_restart("free_kick", t_, np.array(spot, dtype=float), self.rng.uniform(*DEAD_RANGE["free_kick"]))

    def _maybe_card(self, c: int, team: int) -> None:
        r = self.rng.random()
        pl = self.players[c]
        if c % 11 == 0:
            r = 1.0  # keep goalkeepers on the pitch to keep the formation logic simple
        red_now = r < TUNE["red_p"]
        yellow = (not red_now) and r < TUNE["red_p"] + TUNE["yellow_p"]
        if yellow:
            n = self.yellows.get(pl.id, 0) + 1
            self.yellows[pl.id] = n
            if n >= 2:
                self.emit("card", team=team, player=c, loc=self.pos[c], outcome="yellow", second=True)
                self._send_off(c, team, second_yellow=True)
            else:
                self.emit("card", team=team, player=c, loc=self.pos[c], outcome="yellow")
        elif red_now:
            self._send_off(c, team)

    def _send_off(self, c: int, team: int, second_yellow: bool = False) -> None:
        self.emit("card", team=team, player=c, loc=self.pos[c], outcome="red", secondYellow=second_yellow)
        self.active[c] = False
        self.vel[c] = 0.0
        self._reindex_shape(team)

    # ----- passes --------------------------------------------------------------------------------

    def _lane_block(self, start, end, opp_pts: np.ndarray) -> float:
        ab = end - start
        l2 = float(ab @ ab)
        if l2 < 1e-6:
            return 0.0
        tt = np.clip(((opp_pts - start) @ ab) / l2, 0.0, 1.0)
        closest = start + tt[:, None] * ab
        dd = np.hypot(opp_pts[:, 0] - closest[:, 0], opp_pts[:, 1] - closest[:, 1])
        mask = (tt > 0.12) & (tt < 0.95)
        if not mask.any():
            return 0.0
        return float(max(0.0, 1.0 - dd[mask].min() / 2.6))

    def _pass_candidates(self, h, t_, o, hax, hay, pr, restart) -> list[dict]:
        st = self.style[t_]
        d = self.dir[t_]
        hp = self.pos[h]
        osl = slice(o * 11, o * 11 + 11)
        opp_pts = self.pos[osl][self.active[osl]]
        line = self.opp_offside_line(t_)
        skill = self.players[h].attrs["passing"]
        fwd_vec = np.array([float(d), 0.0])
        out: list[dict] = []
        for slot in range(11):
            j = t_ * 11 + slot
            if j == h or not self.active[j]:
                continue
            if slot == 0 and not (hax < 40.0 and (pr > 0.35 or restart is not None)):
                continue
            if restart == "goal_kick" and slot == 0:
                continue
            jp = self.pos[j]
            dist0 = float(np.hypot(*(jp - hp)))
            if dist0 < 4.0 or dist0 > 58.0:
                continue
            if restart == "throw_in" and dist0 > 30.0:
                continue
            if restart == "kickoff":
                if dist0 > 28.0 or self.att(t_, jp)[0] > hax + 3.0:
                    continue
            eta = dist0 / 18.0
            run = self.vel[j] * eta
            rl = float(np.hypot(*run))
            if rl > 7.0:
                run = run / rl * 7.0
            end = jp + run
            jax, jay = self.att(t_, end)
            fwd = jax - hax
            # A forward player level with the defensive line may be played in behind.
            through = (
                fwd >= 12.0 and jax >= line - 3.0 and dist0 <= 34.0
                and self.players[j].pos in ("ST", "LW", "RW", "AM", "CM", "LM", "RM")
                and restart is None
            )  # fmt: skip
            if through:
                end = end + fwd_vec * (3.0 + 4.0 * self.rng.random())
                end[0] = min(max(end[0], 1.0), G.PITCH_L - 6.0) if d == 1 else max(min(end[0], G.PITCH_L - 1.0), 6.0)
                jax, jay = self.att(t_, end)
                fwd = jax - hax
            end = np.array(G.clamp_pitch(end[0], end[1], 0.5))
            dist = float(np.hypot(*(end - hp)))
            lateral = abs(jay - hay)

            if restart == "throw_in":
                kind = "throw_in"
            elif restart == "goal_kick":
                kind = "goal_kick" if dist > 25.0 else "short"
            elif restart == "kickoff":
                kind = "short" if dist < 16.0 else "medium"
            elif (hax >= 74.0 and abs(hay - G.CY) >= 18.0 and jax >= G.PITCH_L - 17.0
                  and abs(jay - G.CY) <= 18.0 and dist >= 10.0):  # fmt: skip
                kind = "cross"
            elif through:
                kind = "through"
            elif lateral >= 30.0 and dist >= 28.0:
                kind = "switch"
            elif fwd <= -6.0:
                kind = "back"
            elif dist >= 30.0:
                kind = "long"
            elif dist >= 16.0:
                kind = "medium"
            else:
                kind = "short"
            if restart == "free_kick" and dist > 25.0 and kind not in ("cross", "through"):
                kind = "free_kick"

            prx = self.pressure_at(end, o)
            lane = self._lane_block(hp, end, opp_pts)
            p = xpass(
                dist, kind=kind, pressure_receiver=prx, pressure_passer=pr, lane_block=lane,
                skill=skill, forward=fwd,
            )  # fmt: skip

            prog = fwd
            s = (0.030 + 0.030 * st.directness) * prog
            s += 14.0 * (threat(jax, jay) - threat(hax, hay))
            s += 1.8 * math.log(max(p, 0.03))
            s -= 0.020 * max(0.0, dist - 25.0) * (1.25 - st.directness)
            if dist < 18.0:
                s += 0.25 * (1.0 - st.directness)
            if kind == "back" and pr < 0.5:
                s -= 0.8
            if kind == "through":
                s -= 0.9
            if slot == 0:
                s -= 0.6
            if j == self.prev_passer:
                s -= 0.35
            s += 0.3 * st.width * abs(jay - G.CY) / G.CY
            if self.t < self.transition_until[t_]:
                s += 0.04 * prog * st.counter_bias
            if restart == "goal_kick" and self.routine:  # build short from the back, or go long to the target
                s += (1.4 if dist < 30.0 else -1.6) if self.routine.get("mode") == "short" else (-1.5 if dist < 28.0 else 1.2)
            out.append({
                "j": j, "end": end, "kind": kind, "dist": dist, "p": p, "score": s, "fwd": fwd,
                "lane": lane, "prx": prx, "through": through, "jax": jax, "line": line,
            })  # fmt: skip
        return out

    def _pick_pass(self, cands: list[dict], pl, st) -> dict:
        tau = min(0.7, max(0.28, 0.55 - 0.25 * (pl.attrs["vision"] - 50) / 50.0))
        m = max(c["score"] for c in cands)
        ws = [math.exp((c["score"] - m) / tau) for c in cands]
        r = self.rng.random() * sum(ws)
        acc = 0.0
        for c, w in zip(cands, ws, strict=True):
            acc += w
            if r <= acc:
                return c
        return cands[-1]

    def _find_interceptor(self, start, end, o: int):
        best = None
        ab = end - start
        l2 = float(ab @ ab)
        if l2 < 1e-6:
            return None
        for k in range(o * 11 + 1, o * 11 + 11):
            if not self.active[k]:
                continue
            tt = float(np.clip(((self.pos[k] - start) @ ab) / l2, 0.0, 1.0))
            if not 0.2 < tt < 0.97:
                continue
            dd = float(np.hypot(*(self.pos[k] - (start + tt * ab))))
            if dd < 6.0 and (best is None or dd < best[0]):
                best = (dd, k, tt)
        return best

    def _nearest_exit(self, p) -> np.ndarray:
        """Where an overhit ball leaves the pitch: a boundary near the target, favouring touchlines."""
        x, y = float(p[0]), float(p[1])
        gaps = {"left": x, "right": G.PITCH_L - x, "bottom": y, "top": G.PITCH_W - y}
        weights = {k: math.exp(-g / 7.0) * (0.06 if k in ("left", "right") else 1.0) for k, g in gaps.items()}
        r = self.rng.random() * sum(weights.values())
        acc = 0.0
        side = "top"
        for k, w in weights.items():
            acc += w
            if r <= acc:
                side = k
                break
        if side == "left":
            return np.array([0.0, min(G.PITCH_W - 0.5, max(0.5, y))])
        if side == "right":
            return np.array([G.PITCH_L, min(G.PITCH_W - 0.5, max(0.5, y))])
        if side == "bottom":
            return np.array([min(G.PITCH_L - 0.5, max(0.5, x)), 0.0])
        return np.array([min(G.PITCH_L - 0.5, max(0.5, x)), G.PITCH_W])

    def _exit_point(self, start, end):
        """Where the line start->end (extended) leaves the pitch, and the fraction along it."""
        ab = end - start
        s_best = None
        for axis, lo, hi in ((0, 0.0, G.PITCH_L), (1, 0.0, G.PITCH_W)):
            if abs(ab[axis]) < 1e-9:
                continue
            for bound in (lo, hi):
                s = (bound - start[axis]) / ab[axis]
                if s > 0 and (s_best is None or s < s_best):
                    s_best = s
        if s_best is None:
            return None, None
        return start + ab * s_best, s_best

    def _launch_pass(self, h: int, c: dict, restart: str | None) -> None:
        t_ = self.team_of(h)
        o = 1 - t_
        hp = self.pos[h].copy()
        end = c["end"].copy()
        j = c["j"]
        kind = c["kind"]
        lofted = kind in ("long", "cross", "switch", "free_kick", "goal_kick") or (kind == "through" and c["dist"] > 28.0)
        dist = c["dist"]
        speed = (min(30.0, 16.0 + 0.25 * dist) if lofted else min(25.0, 11.0 + 0.35 * dist))
        speed *= 1.0 + self.rng.uniform(-0.06, 0.06)

        outcome = "complete"
        interceptor = None
        if self.rng.random() >= c["p"]:
            hit = self._find_interceptor(hp, end, o)
            r = self.rng.random()
            if hit is not None and r < 0.20:
                _, k, tt = hit
                end = hp + (end - hp) * tt
                outcome, interceptor = "intercepted", k
            else:
                edge = min(end[0], G.PITCH_L - end[0], end[1], G.PITCH_W - end[1])
                p_out = 0.27 + 0.55 * math.exp(-edge / 8.0) + (0.08 if lofted else 0.0)
                if self.rng.random() < p_out:
                    end = self._nearest_exit(end)
                    outcome = "out"
                else:
                    outcome = "loose"
        elif (c["through"] and c["jax"] > c["line"] + 0.3 and restart is None
              and self.rng.random() < TUNE["offside_p"]):  # fmt: skip
            outcome = "offside"

        dur = max(0.25, float(np.hypot(*(end - hp))) / speed)
        ev_outcome = "complete" if outcome == "complete" else "incomplete"
        if outcome == "offside":
            ev_outcome = "offside"
        body = self.rng.choice(("right_foot", "right_foot", "left_foot"))
        attrs = {
            "passType": kind,
            "height": "lofted" if lofted else "ground",
            "bodyPart": body,
            "underPressure": self.pressure_at(hp, o) > 0.35,
        }
        if restart:
            attrs["restart"] = restart
        self._flush_carry()
        self.emit("pass", team=t_, player=h, receiver=j, loc=hp, end=end, outcome=ev_outcome, **attrs)

        self.flight = {
            "kind": "pass", "t0": self.t, "t1": self.t + dur, "start": hp, "end": end,
            "passer": h, "receiver": j, "outcome": outcome, "interceptor": interceptor,
            "pass_kind": kind, "lofted": lofted, "z_peak": min(8.0, c["dist"] * 0.12) if lofted else 0.0,
        }  # fmt: skip
        self.mode = "flight"
        self.last_passer, self.last_pass_t = h, self.t
        self.prev_passer = h
        # The intended receiver (or interceptor) runs onto the ball.
        runner = interceptor if outcome == "intercepted" else j
        tgt = end
        v_need = float(np.hypot(*(tgt - self.pos[runner]))) / max(dur, 0.2)
        self.over[runner] = (float(tgt[0]), float(tgt[1]), self.urgency_for_speed(runner, 1.05 * v_need + 0.3), self.t + dur + 0.4)
        self.holder = None
        self.first_time = None
        if outcome == "complete":
            if kind == "cross":
                self.first_time, self.first_time_for = "cross", j
            elif kind == "through":
                self.first_time, self.first_time_for = "through", j
            elif c["fwd"] < -4.0 and G.in_box(*self.att(t_, end)):
                self.first_time, self.first_time_for = "cutback", j
        self.last_lofted = lofted

    # ----- clearances -----------------------------------------------------------------------------

    def _clearance(self, h: int, t_: int, o: int, hp) -> None:
        self._flush_carry()
        hax, hay = self.att(t_, hp)
        length = self.rng.uniform(32.0, 55.0)
        ang = self.rng.uniform(-0.55, 0.55)
        dvec = np.array([math.cos(ang), math.sin(ang)]) * self.dir[t_]
        end = hp + dvec * length
        out = self.rng.random() < 0.28
        if not out:
            end = np.array(G.clamp_pitch(end[0], end[1], 1.0))
        else:
            pt, _ = self._exit_point(hp, end)
            if pt is not None:
                end = pt
        dur = float(np.hypot(*(end - hp))) / 24.0
        self.emit("clearance", team=t_, player=h, loc=hp, end=end, outcome="out" if out else "clear")
        self.flight = {
            "kind": "clearance", "t0": self.t, "t1": self.t + dur, "start": hp.copy(), "end": end,
            "passer": h, "outcome": "out" if out else "loose", "lofted": True, "z_peak": 7.0,
        }  # fmt: skip
        self.mode = "flight"
        self.holder = None
        self.first_time = None
        self.last_lofted = True

    # ----- shots ----------------------------------------------------------------------------------

    def _launch_shot(self, h: int, xgv: float, body: str, assist: str, pr: float, restart: str | None) -> None:
        t_ = self.team_of(h)
        o = 1 - t_
        d = self.dir[t_]
        hp = self.pos[h].copy()
        hax, hay = self.att(t_, hp)
        pl = self.players[h]
        penalty = restart == "penalty"
        gd = G.goal_dist(hax, hay)
        goal_x = G.PITCH_L if d == 1 else 0.0
        fin = pl.attrs["finishing"]

        p_goal = min(0.95, xgv * (0.96 + 0.40 * (fin - 40.0) / 55.0))
        gk = o * 11
        p_goal *= 1.0 - 0.25 * (self.players[gk].attrs["keeping"] - 70.0) / 30.0
        p_goal = min(0.95, max(0.005, p_goal))

        blocker = None
        p_block = 0.0
        if not penalty and body != "head" and restart != "free_kick":
            tgt = np.array([goal_x, G.CY])
            best = None
            ab = tgt - hp
            l2 = float(ab @ ab)
            for k in range(o * 11 + 1, o * 11 + 11):
                if not self.active[k]:
                    continue
                tt = float(np.clip(((self.pos[k] - hp) @ ab) / l2, 0.0, 1.0))
                if not 0.08 < tt < 0.85:
                    continue
                dd = float(np.hypot(*(self.pos[k] - (hp + tt * ab))))
                if best is None or dd < best[0]:
                    best = (dd, k, tt)
            if best is not None:
                p_block = min(0.55, 0.20 + 0.30 * max(0.0, 1.0 - best[0] / 2.2))
                blocker = best
        p_on = min(0.75, max(0.25, 0.50 - 0.010 * (gd - 15.0) - 0.25 * pr + 0.20 * (fin - 65.0) / 35.0))
        if penalty:
            p_on = 0.92
        p_goal_cond = min(p_goal / max(1e-6, 1.0 - p_block), p_on * 0.92)
        r = self.rng.random()
        post_p = 0.025
        if r < p_block:
            outcome = "blocked"
        else:
            r2 = self.rng.random()
            if r2 < p_goal_cond:
                outcome = "goal"
            elif r2 < p_on:
                outcome = "saved"
            elif r2 < p_on + post_p:
                outcome = "post"
            else:
                outcome = "off_target"

        mouth_z: float | None = None
        if outcome == "blocked":
            end = hp + (blocker[2]) * (np.array([goal_x, G.CY]) - hp)
        else:
            side = -1 if self.rng.random() < 0.5 else 1
            if outcome in ("goal", "saved"):
                # Placement matters: finishers beat the keeper toward the corners, while the shots a
                # keeper saves are more often central and at a comfortable height. Post-shot xG learns this.
                f, mouth_z = (
                    (self.rng.betavariate(2.4, 1.1), self.rng.betavariate(1.4, 1.5) * 2.3) if outcome == "goal"
                    else (self.rng.betavariate(1.2, 2.2), self.rng.betavariate(1.3, 2.6) * 2.3)
                )
                ty = G.CY + side * f * (G.GOAL_W / 2 - 0.35)
            elif outcome == "post":
                ty = G.POST_LO if side < 0 else G.POST_HI
                mouth_z = self.rng.uniform(0.2, 2.3)
            else:
                ty = G.CY + side * (G.GOAL_W / 2 + self.rng.uniform(0.4, 5.0))
                mouth_z = self.rng.uniform(0.2, 4.5)
            end = np.array([goal_x, ty])
        v = min(36.0, max(15.0, self.rng.gauss(24.0 + 0.15 * min(gd, 25.0), 3.5)))
        if penalty:
            v = self.rng.uniform(22.0, 30.0)
        dur = max(0.2, float(np.hypot(*(end - hp))) / v + 0.1)

        situation = restart or ("open_play" if assist != "corner" else "corner")
        if self.set_piece_shot:
            situation = "corner"
        self._flush_carry()
        self.emit(
            "shot", team=t_, player=h, loc=hp, end=end, outcome=outcome,
            bodyPart="head" if body == "head" else self.rng.choice(("right_foot", "right_foot", "left_foot")),
            situation=situation, assist=assist, underPressure=pr > 0.35, penalty=penalty,
            goalMouthY=None if outcome == "blocked" else round(float(end[1] - G.CY), 2),
            goalMouthZ=None if mouth_z is None else round(mouth_z, 2),
        )  # fmt: skip
        self.flight = {
            "kind": "shot", "t0": self.t, "t1": self.t + dur, "start": hp, "end": end,
            "shooter": h, "outcome": outcome, "blocker": blocker[1] if blocker else None,
            "z_peak": 0.0, "xg": xgv, "penalty": penalty,
        }  # fmt: skip
        self.mode = "flight"
        self.holder = None
        self.first_time = None
        self.set_piece_shot = False
        # The goalkeeper dives toward the shot.
        if outcome != "blocked":
            dive_x = goal_x - d * 1.0
            dive_y = float(np.clip(end[1], G.POST_LO - 2.0, G.POST_HI + 2.0))
            self.over[gk] = (dive_x, dive_y, 0.8, self.t + dur)

    # ----- flight resolution ---------------------------------------------------------------------

    def _resolve_flight(self) -> None:
        f = self.flight
        self.flight = None
        self.ball_z = 0.0
        kind = f["kind"]
        if kind == "pass":
            self._resolve_pass(f)
        elif kind == "clearance":
            self._resolve_clearance(f)
        elif kind == "corner":
            self._resolve_corner(f)
        else:
            self._resolve_shot(f)

    def _resolve_pass(self, f: dict) -> None:
        h, j = f["passer"], f["receiver"]
        t_ = self.team_of(h)
        o = 1 - t_
        end = f["end"]
        out = f["outcome"]
        if out == "complete":
            self.ball[:2] = self.pos[j]
            self.gain_possession(j, "pass")
        elif out == "intercepted":
            k = f["interceptor"]
            self.ball[:2] = self.pos[k]
            self.emit("interception", team=o, player=k, loc=self.pos[k], outcome=None, against=self.players[h].id)
            if f["pass_kind"] == "cross" and self.rng.random() < 0.62:
                self._corner_for(t_, end)  # cleared behind for a corner
            else:
                self.gain_possession(k, "interception")
        elif out == "offside":
            self.ball[:2] = end
            spot = np.array(self.pos[j], dtype=float)
            self.emit("offside", team=t_, player=j, loc=spot, outcome=None)
            self._turnover_to(o)
            self._schedule_restart("free_kick", o, spot, self.rng.uniform(*DEAD_RANGE["free_kick"]))
        elif out == "out":
            self._ball_out(t_, end)
        else:
            self.ball[:2] = end
            self._start_loose(end, bias_team=o, bias=1.35)

    def _resolve_corner(self, f: dict) -> None:
        team = self.team_of(f["passer"])
        o = 1 - team
        end = f["end"]
        out = f["outcome"]
        self.ball[:2] = end
        if out == "complete":
            j = f["receiver"]
            self.set_piece_shot = True
            self.first_time, self.first_time_for = ("cutback" if f.get("delivery") == "edge" else "cross"), j
            self.last_lofted = bool(f.get("lofted", True))
            self.gain_possession(j, "pass")
        elif out == "claimed":
            gk = o * 11
            self.emit("claim", team=o, player=gk, loc=self.pos[gk], outcome=None)
            self._turnover_to(o)
            self.gain_possession(gk, "save")
        elif out == "intercepted":
            k = min(range(o * 11 + 1, o * 11 + 11), key=lambda q: float(np.hypot(*(self.pos[q] - end))) if self.active[q] else 1e9)
            self.emit("clearance", team=o, player=k, loc=self.pos[k], end=end, outcome="clear")
            self._start_loose(end + np.array([-self.dir[team] * 8.0, self.rng.uniform(-8.0, 8.0)]), bias_team=o, bias=1.5)
        else:
            self._start_loose(end, bias_team=None)

    def _resolve_clearance(self, f: dict) -> None:
        t_ = self.team_of(f["passer"])
        end = f["end"]
        if f["outcome"] == "out":
            self._ball_out(t_, end)
        else:
            self.ball[:2] = end
            self._start_loose(end, bias_team=1 - t_, bias=1.1)

    def _resolve_shot(self, f: dict) -> None:
        h = f["shooter"]
        t_ = self.team_of(h)
        o = 1 - t_
        gk = o * 11
        end = f["end"]
        out = f["outcome"]
        self.ball[:2] = end
        if out == "goal":
            self.score[t_] += 1
            assist = None
            if self.last_passer is not None and self.team_of(self.last_passer) == t_ and self.t - self.last_pass_t < 9.0 and self.last_passer != h:
                assist = self.players[self.last_passer].id
            self.emit(
                "goal", team=t_, player=h, loc=end, outcome=None, assist=assist,
                score={self.club_id[0]: self.score[0], self.club_id[1]: self.score[1]},
            )  # fmt: skip
            self.poss_team = None
            self._schedule_restart("kickoff", o, np.array([G.CX, G.CY]), TUNE["dead_goal"])
        elif out == "saved":
            held = self.rng.random() < 0.45
            self.emit("save", team=o, player=gk, loc=end, outcome="held" if held else "parried", against=self.players[h].id)
            if held:
                self.gain_possession(gk, "save")
            elif self.rng.random() < 0.68:
                self._corner_for(t_, end)
            else:
                self._start_loose(end - np.array([self.dir[t_] * 4.0, 0.0]), bias_team=t_, bias=1.3)
        elif out == "blocked":
            k = f["blocker"]
            self.emit("block", team=o, player=k, loc=self.pos[k], outcome=None, against=self.players[h].id)
            r = self.rng.random()
            if r < 0.38:
                self._corner_for(t_, end)
            else:
                self._start_loose(end, bias_team=o if r < 0.70 else t_, bias=1.4)
        elif out == "post":
            self._start_loose(end - np.array([self.dir[t_] * 3.0, 0.0]), bias_team=t_, bias=1.2)
        else:  # off target
            if self.rng.random() < 0.16:
                self._corner_for(t_, end)
            else:
                self._goal_kick_for(o)

    # ----- loose balls and out of play -------------------------------------------------------------

    def _start_loose(self, point, bias_team: int | None = None, bias: float = 1.0) -> None:
        raw = np.array(point, dtype=float)
        if min(raw[1], G.PITCH_W - raw[1]) < 2.5 and self.rng.random() < 0.35:
            # Run out for a throw-in, to the side that did not last touch it.
            last_touch = (1 - bias_team) if bias_team is not None else self.rng.randrange(2)
            self._ball_out(last_touch, np.array([raw[0], 0.0 if raw[1] < G.CY else G.PITCH_W]))
            return
        point = np.array(G.clamp_pitch(point[0], point[1], 0.5), dtype=float)
        self.ball[:2] = point
        cands, ws = [], []
        for t_ in (0, 1):
            for slot in range(1, 11):
                j = t_ * 11 + slot
                if not self.active[j]:
                    continue
                dd = float(np.hypot(*(self.pos[j] - point)))
                if dd > 16.0:
                    continue
                w = math.exp(-dd / 4.5) * (1.0 + 0.004 * (self.players[j].attrs["aggression"] - 60))
                if bias_team is not None and t_ == bias_team:
                    w *= bias
                cands.append((j, dd))
                ws.append(w)
        if not cands:
            nearest = min(range(22), key=lambda j: float(np.hypot(*(self.pos[j] - point))) if self.active[j] else 1e9)
            cands, ws = [(nearest, float(np.hypot(*(self.pos[nearest] - point))))], [1.0]
        r = self.rng.random() * sum(ws)
        acc = 0.0
        win = cands[-1]
        for c, w in zip(cands, ws, strict=True):
            acc += w
            if r <= acc:
                win = c
                break
        j, dd = win
        self.loose_winner = j
        self.loose_t0 = self.t
        self.loose_from = point.copy()
        self.loose_until = self.t + max(0.6, dd / (0.8 * float(self.vmax[j])))
        self.over[j] = (float(point[0]), float(point[1]), 0.9, self.loose_until + 0.2)
        self.mode = "loose"
        self.holder = None
        self.carry = None
        self.first_time = None

    def _resolve_loose(self) -> None:
        j = self.loose_winner
        self.ball[:2] = self.pos[j]
        self.emit("ball_recovery", team=self.team_of(j), player=j, loc=self.pos[j], outcome=None)
        self.gain_possession(j, "loose_ball")

    def _ball_out(self, last_touch_team: int, point) -> None:
        d = self.dir[last_touch_team]
        o = 1 - last_touch_team
        x, y = float(point[0]), float(point[1])
        self.holder = None
        if y <= 0.01 or y >= G.PITCH_W - 0.01:
            spot = np.array([min(G.PITCH_L - 1.0, max(1.0, x)), 0.0 if y <= 0.01 else G.PITCH_W])
            self._turnover_to(o)
            self._schedule_restart("throw_in", o, spot, self.rng.uniform(*DEAD_RANGE["throw_in"]))
            return
        ax, _ = G.to_att(x, y, d)
        if ax >= G.PITCH_L - 0.01:  # over the opponent's goal line: goal kick for them
            self._goal_kick_for(o)
        else:  # over our own goal line: corner for them
            self._corner_for(o, point)

    def _goal_kick_for(self, team: int) -> None:
        spot = np.array(G.from_att(5.5, G.CY + self.rng.choice((-1, 1)) * 5.0, self.dir[team]))
        self._turnover_to(team)
        self._schedule_restart("goal_kick", team, spot, self.rng.uniform(*DEAD_RANGE["goal_kick"]))

    def _corner_for(self, attacking: int, point) -> None:
        goal_x = G.PITCH_L if self.dir[attacking] == 1 else 0.0
        side_y = 0.0 if float(point[1]) < G.CY else G.PITCH_W
        self._turnover_to(attacking)
        self._schedule_restart(
            "corner", attacking, np.array([goal_x, side_y]), self.rng.uniform(*DEAD_RANGE["corner"]), setpiece=True
        )

    # ----- restarts ------------------------------------------------------------------------------

    def _pick_taker(self, kind: str, team: int, spot, delay: float = 10.0) -> int:
        base = team * 11
        reach = 4.5 * delay
        best, best_s = None, -1e9
        for slot in range(0, 11):
            j = base + slot
            if not self.active[j]:
                continue
            pl = self.players[j]
            dd = float(np.hypot(*(self.pos[j] - spot)))
            if kind == "goal_kick":
                s = 100.0 if slot == 0 else -1e3
            elif slot == 0:
                continue
            elif dd > reach:
                continue
            elif kind == "throw_in":
                s = -dd + (6.0 if pl.pos in ("LB", "RB", "LW", "RW", "LM", "RM", "LWB", "RWB") else 0.0)
            elif kind == "corner":
                s = pl.attrs["passing"] + (6.0 if pl.pos in ("LW", "RW", "AM", "LM", "RM") else 0.0) - 0.15 * dd
            elif kind == "penalty":
                s = pl.attrs["finishing"] + (3.0 if pl.pos == "ST" else 0.0)
            elif kind == "kickoff":
                s = -dd + (8.0 if pl.pos in ("ST", "AM") else 0.0)
            else:  # free kick
                s = pl.attrs["passing"] * 0.6 + pl.attrs["finishing"] * 0.4 - 0.9 * dd
            if s > best_s:
                best, best_s = j, s
        if best is None:  # nobody can get there in time: the nearest outfield player walks over
            near = [base + k for k in range(1, 11) if self.active[base + k]]
            best = min(near, key=lambda j: float(np.hypot(*(self.pos[j] - spot))), default=base + 1)
        return best

    def _pick_thrower(self, team: int, spot, delay: float) -> int:
        """A long-throw specialist: the strong, aggressive player who can reach the spot in time."""
        base = team * 11
        reach = 4.5 * delay
        best, best_s = None, -1e9
        for slot in range(1, 11):
            j = base + slot
            if not self.active[j]:
                continue
            dd = float(np.hypot(*(self.pos[j] - spot)))
            if dd > reach:
                continue
            a = self.players[j].attrs
            s = a["aggression"] + 0.5 * a["stamina"] - 0.8 * dd
            if s > best_s:
                best, best_s = j, s
        return best if best is not None else self._pick_taker("throw_in", team, spot, delay)

    def _schedule_restart(self, kind: str, team: int, spot, delay: float, setpiece: bool = False) -> None:
        spot = np.array(G.clamp_pitch(spot[0], spot[1], 0.0), dtype=float)
        if kind == "free_kick":
            ax, ay = self.att(team, spot)
            setpiece = ax >= 78.0 and abs(ay - G.CY) <= 26.0
        taker = self._pick_taker(kind, team, spot, delay)
        routine = self._plan_routine(kind, team, spot)
        if routine and routine.get("mode") == "long" and kind == "throw_in":
            taker = self._pick_thrower(team, spot, delay)
        # Give the taker time to walk to the spot rather than appear there (a jog is about 5 m/s).
        delay = max(delay, float(np.hypot(*(self.pos[taker] - spot))) / 5.0 + 0.5)
        self.restart = {
            "kind": kind, "team": team, "spot": spot, "at": self.t + delay, "taker": taker,
            "setpiece": setpiece, "routine": routine,
        }  # fmt: skip
        self.mode = "dead"
        self.holder = None
        self.flight = None
        self.carry = None
        self.first_time = None
        self.ball[:2] = spot
        self.over[taker] = (float(spot[0]), float(spot[1]), 0.5, self.t + delay + 10.0)

    def _execute_restart(self) -> None:
        r = self.restart
        taker = r["taker"]
        if self.t < r["at"] + 9.0 and float(np.hypot(*(self.pos[taker] - r["spot"]))) > 2.0:
            return  # still walking to the ball
        self.restart = None
        kind, team, spot = r["kind"], r["team"], r["spot"]
        self.routine = r.get("routine")
        label = self._routine_label(kind, self.routine)
        wall = self._wall_size(self.routine)
        self.pos[taker] = spot + np.array([-0.4 * self.dir[team], 0.0])
        self.vel[taker] = 0.0
        self.ball[:2] = spot
        self._turnover_to(team)
        self._announce_possession(team, taker, kind)
        if kind == "kickoff":
            self.emit("kickoff", team=team, player=taker, loc=spot, outcome=None)
        elif kind in ("throw_in", "goal_kick", "corner"):
            self.emit(kind, team=team, player=taker, loc=spot, outcome=None, routine=label)
        elif kind == "free_kick":
            self.emit("free_kick", team=team, player=taker, loc=spot, outcome=None, routine=label, wall=wall or None)
        self.holder = taker
        self.mode = "carry"
        self.holder_since = self.t
        self.carry = None
        self.first_time = None
        if kind == "penalty":
            xgv = xg(0, 0, penalty=True)
            self._launch_shot(taker, xgv, "foot", "open", 0.0, "penalty")
        elif kind == "corner":
            self._deliver_corner(taker, team, spot)
        elif kind == "throw_in" and self.routine and self.routine.get("mode") == "long":
            self._deliver_corner(taker, team, spot, throw=True)
        else:
            self._decide(restart=kind)

    def _deliver_corner(self, taker: int, team: int, spot, throw: bool = False) -> None:
        d = self.dir[team]
        pl = self.players[taker]
        rt = self.routine or {}
        delivery = rt.get("delivery", "far") if not throw else "far"
        side = rt.get("side", 1)
        helper = rt.get("helper")
        if delivery == "short" and helper is not None and self.active[helper]:
            self._short_corner(taker, team, spot, helper)
            return
        if delivery == "short":
            delivery = "near"
        # Attackers in the box compete with defenders for the delivery.
        att = []
        for slot in range(1, 11):
            j = team * 11 + slot
            if not self.active[j]:
                continue
            ax, ay = self.att(team, self.pos[j])
            if ax >= G.PITCH_L - 20.0 and abs(ay - G.CY) <= 20.0:
                att.append(j)
        U = self.rng.uniform
        if delivery == "near":
            end_att = (G.PITCH_L - U(3.0, 8.0), G.CY + side * U(1.0, 6.0))
        elif delivery == "edge":
            end_att = (G.PITCH_L - U(14.0, 19.0), G.CY + U(-9.0, 9.0))
        else:
            end_att = (G.PITCH_L - U(5.0, 12.0), G.CY - side * U(0.0, 8.0))
        end = np.array(G.from_att(end_att[0], end_att[1], d))
        r = self.rng.random()
        skill_adj = 0.06 * (pl.attrs["passing"] - 65) / 30.0
        # Zonal defences give attackers a run at the ball; man-markers stay with them.
        marking_adj = {"zonal": 0.02, "man": -0.02}.get(rt.get("defence", "zonal"), 0.0)
        p_complete = {"near": 0.34, "far": 0.40, "edge": 0.32}[delivery] + marking_adj + skill_adj
        if throw:
            p_complete -= 0.06
        if att and r < p_complete:
            j = min(att, key=lambda k: float(np.hypot(*(self.pos[k] - end))))
            outcome = "complete"
        elif r < 0.66 + skill_adj:
            outcome, j = "intercepted", None
        elif r < 0.78:
            outcome, j = "claimed", None
        else:
            outcome, j = "loose", None
        dist = float(np.hypot(*(end - spot)))
        dur = max(0.8, dist / (14.0 if throw else 20.0))
        ev_out = "complete" if outcome == "complete" else "incomplete"
        self.emit(
            "pass", team=team, player=taker, receiver=j, loc=spot, end=end, outcome=ev_out,
            passType="throw_in" if throw else "corner", height="lofted" if delivery != "edge" else "ground",
            bodyPart="hands" if throw else "right_foot", underPressure=False,
            restart="throw_in" if throw else "corner", routine=delivery,
        )  # fmt: skip
        self.last_passer, self.last_pass_t = taker, self.t
        self.flight = {
            "kind": "corner", "t0": self.t, "t1": self.t + dur, "start": np.array(spot, dtype=float), "end": end,
            "passer": taker, "receiver": j, "outcome": outcome, "z_peak": 7.0 if delivery != "edge" else 0.0,
            "lofted": delivery != "edge", "delivery": delivery,
        }  # fmt: skip
        self.mode = "flight"
        self.holder = None
        self.last_lofted = delivery != "edge"
        if j is not None:
            self.over[j] = (float(end[0]), float(end[1]), 0.9, self.t + dur + 0.4)
