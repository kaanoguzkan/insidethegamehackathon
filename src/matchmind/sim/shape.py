"""Off-ball movement for the match simulator.

Every tick each player gets a target position and an *urgency* (0 = amble, 1 = flat-out).
Targets come from the team's formation stretched between a back line and a front line that
follow the ball, plus pressing, transition and set-piece behaviour. Style dials (press
intensity and height, line height, width, counter bias) feed straight into this, which is
what makes teams look and measure differently.
"""

from __future__ import annotations

import numpy as np

from ..core import geometry as G
from . import tactics

ACC = 6.0  # max acceleration, m/s^2
BASE_URGENCY = 0.068  # urgency of ordinary positional jogging
PHASE_RATE = 0.75  # how fast a team glides between its phases of play (1/s)
PHASE_HOLD_S = 2.5  # a phase must hold this long before it is announced


class ShapeMixin:
    # ----- shape bookkeeping -------------------------------------------------------------

    def _reindex_shape(self, t: int) -> None:
        """Recompute the team's layouts (base, attack, block, build, press, low) for its ten outfield players.

        Depth is normalised against the *base* layout of the players still on the pitch, so a red
        card squeezes the team, while the other layouts keep their own depth relative to it
        (wing-backs really do drop to the back line, a pressing front line really does step up).
        """
        name = self.formation_name[t]
        idx = self.slot_idx[t]
        raw = {ph: np.array(tactics.layout(name, ph))[idx] for ph in tactics.LAYOUT_PHASES}
        tags = self.style[t].tags
        raw["attack"] = np.array(tactics.apply_attack_tags(name, tactics.layout(name, "attack"), tags))[idx]
        raw["build"] = np.array(tactics.apply_attack_tags(name, tactics.layout(name, "build"), tags, build=True))[idx]
        base = raw["base"]
        act = self.active[t * 11 + 1 : t * 11 + 11]
        lo, hi = (base[act, 0].min(), base[act, 0].max()) if act.any() else (0.0, 1.0)
        span = max(hi - lo, 1e-6)
        self.u[t] = (base[:, 0] - lo) / span
        self.fy[t] = base[:, 1]
        self.lay_u[t] = {ph: (raw[ph][:, 0] - lo) / span for ph in tactics.LAYOUT_PHASES}
        self.lay_fy[t] = {ph: raw[ph][:, 1] for ph in tactics.LAYOUT_PHASES}
        self.slot_role[t] = [tactics.roles(name)[k] for k in idx]

    # ----- phases of play ----------------------------------------------------------------

    def _engage_max(self, t: int) -> float:
        """How far from its own goal (in metres, attack frame) the team will press the ball."""
        return max(50.0, 45.0 + 55.0 * self.style[t].press_height)

    def _target_phase(self, t: int, in_poss: bool, bx: float) -> str:
        """Which of the five working phases the team should be in: build, attack, press, block or low."""
        st = self.style[t]
        if in_poss:
            self.phase_cause[t] = "own_third" if bx < tactics.BUILD_ZONE else "settled"
            return "build" if bx < tactics.BUILD_ZONE else "attack"
        if self.t < self.counterpress_until[t]:
            self.phase_cause[t] = "counterpress"
            return "press"
        if self.t < self.regroup_until[t]:
            self.phase_cause[t] = "regroup"
            return "block"
        minute = self.t / 60.0
        lead = self.score[t] - self.score[1 - t]
        protecting = (lead >= 1 and minute > 85.0) or (lead >= 2 and minute > 75.0)
        if protecting or (st.press_height < 0.30 and bx < tactics.BUILD_ZONE):
            self.phase_cause[t] = "protecting_lead" if protecting else "deep_line"
            return "low"
        if st.press_height >= 0.55 and bx <= self._engage_max(t):
            self.phase_cause[t] = "wide_carrier" if self.press_trigger[t] else "press_zone"
            return "press"
        self.phase_cause[t] = "ball_beyond_press_line"
        return "block"

    def _blend_phase(self, t: int, phase: str) -> tuple[np.ndarray, np.ndarray]:
        """The team's current target layout: a glide between its working shapes."""
        goal = np.zeros(len(tactics.PHASES))
        goal[tactics.PHASES.index(phase)] = 1.0
        w = self.phase_w[t]
        w += (goal - w) * (1.0 - np.exp(-PHASE_RATE * self.DT))
        u = sum(w[i] * self.lay_u[t][ph] for i, ph in enumerate(tactics.PHASES))
        fy = sum(w[i] * self.lay_fy[t][ph] for i, ph in enumerate(tactics.PHASES))
        # Announce the phase the team is mainly in once it has held it for a moment.
        main = tactics.PHASES[int(np.argmax(w))]
        if main != self.phase_name[t]:
            cand, since = self.phase_cand[t]
            if cand != main:
                self.phase_cand[t] = (main, self.t)
            elif self.t - since >= PHASE_HOLD_S and w.max() > 0.6:
                prev = self.phase_name[t]
                self.phase_name[t] = main
                if prev:
                    self.emit("phase_change", team=t, phase=main, previous=prev, cause=self.phase_cause[t], outcome=None)
        else:
            self.phase_cand[t] = ("", 0.0)
        return u, fy

    def team_in_possession(self, t: int) -> bool:
        if self.mode == "dead" and self.restart is not None:
            return self.restart["team"] == t
        return self.poss_team == t

    def opp_offside_line(self, t: int) -> float:
        """x (in team t's attack frame) of the second-last opponent: the offside line."""
        o = 1 - t
        sl = slice(o * 11 + 1, o * 11 + 11)
        pts = self.pos[sl][self.active[sl]]
        if len(pts) == 0:
            return G.PITCH_L
        d = self.dir[t]
        ax = pts[:, 0] if d == 1 else G.PITCH_L - pts[:, 0]
        return float(ax.max())

    def focus_point(self) -> np.ndarray:
        """Where the play is going: the ball, or where an in-flight ball will land."""
        if self.mode == "flight" and self.flight is not None:
            return np.array(self.flight["end"], dtype=float)
        return self.ball[:2]

    # ----- targets ------------------------------------------------------------------------

    def compute_targets(self) -> tuple[np.ndarray, np.ndarray]:
        tgt = self.pos.copy()
        urg = np.full(22, BASE_URGENCY)
        focus = self.focus_point()
        for t in (0, 1):
            self._team_targets(t, focus, tgt, urg)
        self._apply_overrides(tgt, urg)
        return tgt, urg

    def _team_targets(self, t: int, focus: np.ndarray, tgt: np.ndarray, urg: np.ndarray) -> None:
        d = self.dir[t]
        st = self.style[t]
        base = t * 11
        in_poss = self.team_in_possession(t)
        bx, by = G.to_att(focus[0], focus[1], d)

        phase = self._target_phase(t, in_poss, bx)
        u_eff, fy = self._blend_phase(t, phase)
        u = self.u[t]  # base depth: who counts as a runner or a free marker
        S = self.stamina[base : base + 11]

        if in_poss:
            back = min(62.0, max(12.0, bx - (28.0 + 10.0 * (1.0 - st.line_height))))
            front = min(95.0, max(back + 22.0, bx + 10.0 + 14.0 * st.directness))
            front = min(front, back + 46.0)
            shift = (by - G.CY) * 0.22
            wscale = 0.85 + 0.30 * st.width
        else:
            line = 14.0 + 24.0 * st.line_height
            back = line + min(16.0, max(-26.0, (bx - 45.0) * 0.45))
            front = min(99.0, back + 28.0 + 10.0 * st.press_height)
            if phase == "low":  # a low block is short as well as deep
                back -= 3.0
                front = min(front, back + 24.0)
            shift = (by - G.CY) * 0.35
            wscale = 0.72 + 0.14 * st.width
            if st.press_scheme == "wide_trap" and phase == "press":
                wscale -= 0.05  # a narrow press shuts the middle and leaves the touchline open as the trap

        x_att = back + u_eff * (front - back)
        y_att = G.CY + (fy - 0.5) * G.PITCH_W * wscale + shift

        if in_poss:
            # Stay onside unless running onto a pass (overrides take care of that).
            x_att = np.minimum(x_att, self.opp_offside_line(t) - 0.6)

        # Transition: a team that just won the ball breaks forward; the loser counter-presses.
        trans = self.t < self.transition_until[t]
        # A club that keeps its shape on winning the ball (``on_win == "keep"``) still moves it quickly, but its
        # forwards do not sprint away from the build-up.
        go = 1.0 if st.on_win == "counter" else 0.3
        if in_poss and trans:
            runners = u >= 0.55
            x_att = np.where(runners, np.minimum(99.0, x_att + go * (8.0 + 12.0 * st.counter_bias)), x_att)
            run_urg = 0.42 + go * 0.40 * st.counter_bias

        px, py = G.from_att(x_att, y_att, d)

        # Goalkeeper.
        gk_x_att = 3.0 + 7.0 * st.line_height * min(1.0, bx / G.PITCH_L)
        gk_y_att = G.CY + (by - G.CY) * 0.15
        gkx, gky = G.from_att(gk_x_att, gk_y_att, d)
        tgt[base] = (gkx, gky)
        urg[base] = 0.12

        sl = slice(base + 1, base + 11)
        tgt[sl, 0], tgt[sl, 1] = px, py
        tgt[sl] += self.wobble[sl]
        urg[sl] = BASE_URGENCY + 0.06 * st.tempo
        if in_poss and trans:
            urg[sl] = np.where(u >= 0.55, run_urg * (0.5 + 0.5 * S[1:]), urg[sl])

        # Recovery runs: anyone far behind their target hurries back. A team that regroups on losing the
        # ball (rather than counter-pressing) runs home at once and from nearer.
        regroup = self.t < self.regroup_until[t]
        far = np.hypot(tgt[sl, 0] - self.pos[sl, 0], tgt[sl, 1] - self.pos[sl, 1]) > (5.0 if regroup else 9.0)
        urg[sl] = np.where(far & (not in_poss), np.maximum(urg[sl], 0.40 if regroup else 0.26), urg[sl])

        if not in_poss:
            pressers = self._assign_pressers(t, focus, bx, tgt, urg)
            self._assign_markers(t, bx, pressers, tgt, urg)

        if self.mode == "dead" and self.restart:
            self._restart_targets(t, tgt, urg)  # the restart's choreography overrides the open-play shape

    def _assign_pressers(
        self, t: int, focus: np.ndarray, bx: float, tgt: np.ndarray, urg: np.ndarray
    ) -> set[int]:
        st = self.style[t]
        base = t * 11
        d = self.dir[t]
        S = self.stamina[base : base + 11]
        engaged = bx <= self._engage_max(t)
        counterpress = self.t < self.counterpress_until[t]
        k = 1
        if engaged:
            k += 1 if st.press_intensity > 0.45 else 0
            k += 1 if (st.press_intensity > 0.75 and bx > 35.0) else 0
        if counterpress:
            k = max(k, 3)
        if st.press_scheme == "man" and engaged:
            k += 1  # a man-oriented press commits one more to the ball as well as picking up the runners
        # The trap: a carrier who is pushed wide near the touchline is the cue to jump, with one more man.
        trap = st.press_scheme == "wide_trap" and engaged and abs(focus[1] - G.CY) > 21.0 and 12.0 < bx < 78.0
        if trap:
            k += 1
            if self.press_trigger[t] is None:
                self.press_trigger[t] = "wide_carrier"
        elif not engaged:
            self.press_trigger[t] = None
        sl = slice(base + 1, base + 11)
        act = self.active[sl]
        dd = np.hypot(self.pos[sl, 0] - focus[0], self.pos[sl, 1] - focus[1])
        dd = np.where(act, dd, 1e9)
        order = np.argsort(dd)
        own_goal = np.array(G.from_att(0.0, G.CY, d))
        away = own_goal - focus
        norm = float(np.hypot(*away)) or 1.0
        away = away / norm
        used: set[int] = set()
        for r in range(min(k, 10)):
            j = int(order[r])
            slot = base + 1 + j
            if slot in self.over:
                continue
            used.add(slot)
            # Stand-off distance: a team that presses closes the carrier down to ~3 m; a passive
            # block (or tired legs) holds off at 6-10 m and only contains.
            eff = st.press_intensity * (0.55 + 0.45 * S[1 + j])
            standoff = 2.2 + 6.0 * (1.0 - eff) + (0.0 if (engaged or counterpress) else 3.5) + 1.8 * r
            if counterpress:
                standoff = min(standoff, 2.6 + 1.8 * r)
            direction = away
            if st.press_scheme == "wide_trap" and engaged and r == 0:
                # Close from the inside so the carrier can only go toward the touchline.
                inward = np.array([0.0, 1.0 if focus[1] < G.CY else -1.0])
                direction = away * 0.8 + inward * 0.6
                direction = direction / (float(np.hypot(*direction)) or 1.0)
            tgt[slot] = focus + direction * standoff
            if engaged or counterpress:
                u_p = 0.18 + 0.55 * st.press_intensity
                if trap:
                    u_p = max(u_p, 0.85)
                if counterpress:
                    u_p = max(u_p, 0.75 + 0.2 * st.press_intensity)
                urg[slot] = min(1.0, u_p * (0.45 + 0.55 * S[1 + j]))
            else:
                urg[slot] = 0.28
        return used

    def _assign_markers(
        self, t: int, bx: float, pressers: set[int], tgt: np.ndarray, urg: np.ndarray
    ) -> None:
        """Goal-side marking of attackers who are close to our goal (a man-oriented press picks up everyone)."""
        man = self.style[t].press_scheme == "man" and bx <= self._engage_max(t)
        if bx > 62.0 and not man:
            return
        o = 1 - t
        d = self.dir[t]
        osl = slice(o * 11 + 1, o * 11 + 11)
        oact = self.active[osl]
        oax, oay = G.to_att(self.pos[osl][:, 0], self.pos[osl][:, 1], d)
        threats = np.where(oact & (oax <= (60.0 if man else 46.0)))[0]
        if len(threats) == 0:
            return
        threats = threats[np.argsort(oax[threats])]  # most dangerous (closest to goal) first
        base = t * 11
        u = self.u[t]
        free = [
            base + 1 + j for j in range(10)
            if self.active[base + 1 + j] and base + 1 + j not in pressers
            and base + 1 + j not in self.over and (u[j] <= 0.78 or man)
        ]  # fmt: skip
        tight = 1.6 + 1.6 * (1.0 - self.style[t].press_intensity)
        for k in threats[:7]:
            if not free:
                break
            apos = self.pos[o * 11 + 1 + k]
            best = min(free, key=lambda s: float(np.hypot(*(self.pos[s] - apos))))
            if float(np.hypot(*(self.pos[best] - apos))) > (34.0 if man else 28.0):
                continue
            free.remove(best)
            own_goal = np.array(G.from_att(0.0, G.CY, d))
            toward = own_goal - apos
            toward = toward / (float(np.hypot(*toward)) or 1.0)
            tgt[best] = apos + toward * tight
            urg[best] = max(urg[best], 0.26)

    def _apply_overrides(self, tgt: np.ndarray, urg: np.ndarray) -> None:
        for slot, (x, y, u, until) in list(self.over.items()):
            if self.t >= until:
                del self.over[slot]
                continue
            tgt[slot] = (x, y)
            urg[slot] = u

    # ----- integration --------------------------------------------------------------------

    def move_players(self) -> None:
        # Slow Ornstein-Uhlenbeck wobble so positions don't look robotic.
        dt = self.DT
        self.wobble += -0.3 * self.wobble * dt + 0.5 * np.sqrt(dt) * self.nrng.standard_normal((22, 2))

        tgt, urg = self.compute_targets()
        delta = tgt - self.pos
        dist = np.hypot(delta[:, 0], delta[:, 1])
        dist_safe = np.maximum(dist, 1e-6)
        vmax_eff = self.vmax * (0.85 + 0.15 * self.stamina)
        v_cap = vmax_eff * (0.25 + 0.75 * np.power(np.clip(urg, 0.0, 1.0), 1.3))
        v_des = np.minimum(v_cap, 1.1 * dist)
        vel_des = delta / dist_safe[:, None] * v_des[:, None]
        dv = vel_des - self.vel
        dv_norm = np.hypot(dv[:, 0], dv[:, 1])
        scale = np.minimum(1.0, ACC * dt / np.maximum(dv_norm, 1e-6))
        self.vel += dv * scale[:, None]
        self.vel[~self.active] = 0.0
        self.pos += self.vel * dt
        # Keep everyone on (or just off) the pitch.
        np.clip(self.pos[:, 0], -1.0, G.PITCH_L + 1.0, out=self.pos[:, 0])
        np.clip(self.pos[:, 1], -1.0, G.PITCH_W + 1.0, out=self.pos[:, 1])

        speed = np.hypot(self.vel[:, 0], self.vel[:, 1])
        frac = speed / self.vmax
        drain = self.fatigue * np.power(frac, 2.2) * dt
        recover = np.where(speed < 2.2, 0.00004 * (1.0 - self.stamina) * 25.0 * dt, 0.0)
        self.stamina = np.clip(self.stamina - drain + recover, 0.25, 1.0)
        self.dist_run += speed * dt
