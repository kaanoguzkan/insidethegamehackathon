"""Restarts as choreography: corners, free kicks, throw-ins, goal kicks, penalties and kick-offs.

When play stops, each team walks to a *plan* for that kind of restart. The plan is made once, when
the restart is scheduled, from the club's tactic tags:

* **Corners.** The taker's team chooses a routine (near-post flick-on, far-post, short corner,
  edge-of-box shot) and puts two centre-backs and four attackers in the box, keeping the rest back
  as a counter-attack screen. The defence is zonal (a line on the six-yard box, two on the posts,
  one at the penalty spot) or man-to-man (each attacker picked up goal-side), with two players left
  upfield either way.
* **Free kicks.** A direct kick near goal gets a wall of three to five at 9.15 m, the goalkeeper
  covering the open post, a decoy beside the ball and rebound hunters; a wide free kick becomes a
  crossing set-up against an offside line; others are taken quickly in shape.
* **Goal kicks.** Short: the centre-backs split into the box wide, the fullbacks come to the
  touchline and the pivot offers between the lines. Long: the team pushes up around a target man.
  The opponent presses to the edge of the box, or drops, depending on its own pressing dials.
* **Throw-ins.** Three outlets form a triangle (short, diagonal, back) and are marked;
  a team with a long-throw specialist throws into a crowded box instead.
* **Penalties and kick-offs** have the players where the Laws put them.

Positions are written in the *attacking team's frame* (x toward the goal it attacks) and converted
to pitch coordinates with that team's direction of play.
"""

from __future__ import annotations

import numpy as np

from ..core import geometry as G

WALL_DIST = 9.5  # metres from the ball (law: 9.15)
CLEAR = 9.15

# Corner routines: attacking box slots as (x, lateral) where lateral is measured from the middle of
# the goal toward the corner taker's side (+) or away from it (-). Best aerial threat first.
CORNER_BOX = {
    "near": [(101.0, +5.5), (99.5, +1.0), (95.0, -2.5), (95.5, +4.5), (99.0, -8.0), (88.5, -1.0)],
    "far": [(98.5, -7.0), (99.5, -3.0), (95.0, +1.0), (96.0, -10.0), (92.0, +5.0), (87.5, 0.0)],
    "short": [(98.0, -4.0), (96.0, +2.0), (94.0, -7.0), (99.0, +6.0), (92.0, 0.0), (88.0, -3.0)],
    "edge": [(100.0, +3.0), (100.0, -3.0), (88.5, -8.0), (88.0, 0.0), (88.5, +8.0), (94.0, -12.0)],
}
# Zonal marking, best defender first: (x, lateral toward the taker's side).
ZONAL = [(99.5, +2.5), (99.5, -2.5), (93.5, 0.0), (99.5, +7.0), (99.5, -7.0), (104.2, +3.0), (104.2, -3.0), (88.5, +1.0)]
POSTS = [(104.2, +3.0), (104.2, -3.0)]


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(v[0], v[1]))
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


class SetPieceMixin:
    # ----- planning a routine when the restart is scheduled -------------------------------------

    def _plan_routine(self, kind: str, team: int, spot) -> dict | None:
        st = self.style[team]
        opp = self.style[1 - team]
        ax, ay = self.att(team, spot)
        if kind == "corner":
            weights = {"near": 0.30, "far": 0.30, "short": 0.20, "edge": 0.20}
            if st.corners != "mixed":
                weights = {k: (0.55 if k == st.corners else 0.15) for k in weights}
            delivery = self._choice(weights)
            defence = opp.corner_defence
            if defence == "mixed":
                defence = self.rng.choice(("zonal", "man"))
            return {"delivery": delivery, "side": 1 if ay > G.CY else -1, "defence": defence}
        if kind == "free_kick":
            gd = G.goal_dist(ax, ay)
            if ax >= 70.0 and gd <= 30.0 and abs(ay - G.CY) <= 22.0:
                return {"type": "direct", "wall": 5 if gd <= 19.0 else 4 if gd <= 24.0 else 3}
            if ax >= 60.0 and abs(ay - G.CY) >= 14.0:
                return {"type": "cross", "side": 1 if ay > G.CY else -1}
            return {"type": "quick"}
        if kind == "goal_kick":
            p_short = {"short": 0.85, "mixed": 0.50, "long": 0.15}[st.build_up]
            return {"mode": "short" if self.rng.random() < p_short else "long"}
        if kind == "throw_in":
            if st.long_throws and ax >= 74.0:
                return {"mode": "long", "side": 1 if ay > G.CY else -1}
            return {"mode": "short"}
        return None

    def _choice(self, weights: dict[str, float]) -> str:
        r = self.rng.random() * sum(weights.values())
        for k, w in weights.items():
            r -= w
            if r <= 0:
                return k
        return next(iter(weights))

    # ----- applying the plan each tick ------------------------------------------------------------

    def _restart_plan(self) -> dict[int, tuple[float, float, float]]:
        r = self.restart
        if "plan" not in r:
            fn = getattr(self, f"_plan_{r['kind']}", None)
            r["plan"] = fn(r) if fn else {}
        return r["plan"]

    def _restart_targets(self, t: int, tgt: np.ndarray, urg: np.ndarray) -> None:
        """Override the ordinary shape with the restart's plan (slots it does not mention keep their shape)."""
        r = self.restart
        plan = self._restart_plan()
        base = t * 11
        for slot in range(base, base + 11):
            p = plan.get(slot)
            if p is not None and self.active[slot]:
                tgt[slot] = (p[0], p[1])
                urg[slot] = p[2]
        self._keep_clear(t, r, tgt)

    def _keep_clear(self, t: int, r: dict, tgt: np.ndarray) -> None:
        """The team defending a restart stays 9.15 m from the ball (and out of the box at goal kicks)."""
        if t == r["team"] or r["kind"] in ("corner", "penalty", "kickoff"):
            return
        spot = r["spot"]
        base = t * 11
        att = r["team"]
        d_att = self.dir[att]
        for slot in range(base + 1, base + 11):
            if slot in self.over and slot != r["taker"]:
                continue
            p = tgt[slot]
            v = p - spot
            dist = float(np.hypot(v[0], v[1]))
            if dist < CLEAR:
                tgt[slot] = spot + _unit(v if dist > 1e-6 else np.array([0.0, 1.0])) * (CLEAR + 0.4)
            if r["kind"] == "goal_kick":
                ax, ay = G.to_att(float(tgt[slot][0]), float(tgt[slot][1]), d_att)
                if ax < G.BOX_DEPTH + 1.0 and abs(ay - G.CY) < G.BOX_HALF_W + 1.0:
                    tgt[slot] = G.from_att(G.BOX_DEPTH + 1.5, ay, d_att)

    # ----- helpers ---------------------------------------------------------------------------------

    def _local(self, j: int) -> int:
        return j % 11 - 1

    def _role(self, j: int) -> str:
        return self.slot_role[j // 11][self._local(j)]

    def _base_u(self, j: int) -> float:
        return float(self.u[j // 11][self._local(j)])

    def _outfield(self, team: int, exclude=()) -> list[int]:
        return [j for j in range(team * 11 + 1, team * 11 + 11) if self.active[j] and j not in exclude]

    def _aerial(self, j: int) -> float:
        pl = self.players[j]
        return pl.attrs["defending"] + 8.0 if self._role(j) == "CB" else pl.attrs["finishing"] + pl.attrs["pace"] * 0.2

    def _jit(self, a: float = 0.7) -> float:
        return self.rng.uniform(-a, a)

    # ----- corners ----------------------------------------------------------------------------------

    def _plan_corner(self, r: dict) -> dict:
        att, rt, taker = r["team"], r["routine"], r["taker"]
        de = 1 - att
        s = rt["side"]
        plan: dict[int, tuple[float, float, float]] = {}

        def put(j: int, ax: float, lat: float, urgency: float = 0.26) -> None:
            plan[j] = (*G.from_att(ax + self._jit(), G.CY + s * lat + self._jit(), self.dir[att]), urgency)

        mine = self._outfield(att, exclude=(taker,))
        cbs = sorted((j for j in mine if self._role(j) == "CB"), key=lambda j: -self.players[j].attrs["defending"])
        going = cbs[:2]
        rest = sorted((j for j in mine if j not in going), key=lambda j: -self._base_u(j))
        box = going + rest[: 6 - len(going)]
        left = [j for j in mine if j not in box]
        helper = None
        if rt["delivery"] == "short" and left:
            cx, cy = r["spot"]
            helper = min(left, key=lambda j: float(np.hypot(self.pos[j][0] - cx, self.pos[j][1] - cy)))
            left.remove(helper)
            put(helper, 101.0, +27.0, 0.38)
            rt["helper"] = helper
        for j, (ax, lat) in zip(sorted(box, key=lambda j: -self._aerial(j)), CORNER_BOX[rt["delivery"]], strict=False):
            put(j, ax, lat)
        for k, j in enumerate(left):  # the counter-attack screen
            put(j, 56.0 + 3.0 * (k % 2), (k - (len(left) - 1) / 2.0) * 13.0, 0.15)

        # Defence.
        gk = de * 11
        plan[gk] = (*G.from_att(102.3, G.CY + s * 1.2, self.dir[att]), 0.22)
        dfn = sorted(self._outfield(de), key=lambda j: self._base_u(j))
        inside, upfield = dfn[:8], dfn[8:]
        for k, j in enumerate(upfield):
            put(j, 58.0, (k - (len(upfield) - 1) / 2.0) * 12.0 + 6.0, 0.15)
        attack_spots = [
            (ax, lat) for ax, lat in CORNER_BOX[rt["delivery"]][: len(box)]
        ]
        if rt["defence"] == "man":
            posts = inside[:2]
            for j, (ax, lat) in zip(posts, POSTS, strict=False):
                put(j, ax, lat, 0.22)
            markers = list(inside[2:])
            for ax, lat in attack_spots:
                if not markers:
                    break
                tx, ty = G.from_att(ax, G.CY + s * lat, self.dir[att])
                j = min(markers, key=lambda k: float(np.hypot(self.pos[k][0] - tx, self.pos[k][1] - ty)))
                markers.remove(j)
                put(j, min(104.0, ax + 1.0), lat * 0.9, 0.38)  # goal-side of the runner
            for j in markers:
                put(j, 93.5, 0.0, 0.22)
        else:
            for j, (ax, lat) in zip(inside, ZONAL, strict=False):
                put(j, ax, lat, 0.22)
        return plan

    # ----- free kicks ---------------------------------------------------------------------------------

    def _plan_free_kick(self, r: dict) -> dict:
        att, rt, taker = r["team"], r["routine"], r["taker"]
        if rt["type"] == "quick":
            return {}
        de = 1 - att
        d = self.dir[att]
        spot = np.array(r["spot"], dtype=float)
        ax, ay = self.att(att, spot)
        plan: dict[int, tuple[float, float, float]] = {}
        mine = self._outfield(att, exclude=(taker,))
        dfn = sorted(self._outfield(de), key=lambda j: float(np.hypot(*(self.pos[j] - spot))))

        def absp(x: float, y: float) -> tuple[float, float]:
            return G.from_att(x, y, d)

        if rt["type"] == "direct":
            goal = np.array(absp(G.PITCH_L, G.CY))
            to_goal = _unit(goal - spot)
            perp = np.array([-to_goal[1], to_goal[0]])
            n = rt["wall"]
            centre = spot + to_goal * WALL_DIST
            wall = dfn[:n]
            for k, j in enumerate(wall):
                p = centre + perp * (k - (n - 1) / 2.0) * 0.75
                plan[j] = (float(p[0]), float(p[1]), 0.38)
            others = dfn[n:]
            gk = de * 11
            side = 1.0 if ay < G.CY else -1.0  # the keeper covers the post the wall does not
            plan[gk] = (*absp(102.3, G.CY + side * (1.4 if abs(ay - G.CY) > 3 else 0.0)), 0.30)
            line = [(96.5, -9.0), (96.5, -3.0), (96.5, +3.0), (96.5, +9.0)]
            for j, (x, lat) in zip(others, line, strict=False):
                plan[j] = (*absp(x, G.CY + lat), 0.22)
            for k, j in enumerate(others[len(line):]):
                plan[j] = (*absp(66.0, G.CY + (k - 0.5) * 14.0), 0.15)
            # Attackers: a decoy over the ball, rebound hunters, and the counter screen.
            order = sorted(mine, key=lambda j: float(np.hypot(*(self.pos[j] - spot))))
            if order:
                dec = order.pop(0)
                dp = spot + perp * 1.7 - to_goal * 0.5
                plan[dec] = (float(dp[0]), float(dp[1]), 0.34)
            hunters = [(min(94.0, ax + 6.0), G.CY - 6.0), (min(93.0, ax + 5.0), G.CY + 4.0), (88.5, G.CY - 12.0), (88.5, G.CY + 11.0)]
            hunters.sort(key=lambda p: p[0])
            for j, (x, y) in zip(sorted(order, key=lambda j: -self._base_u(j)), hunters, strict=False):
                plan[j] = (*absp(x + self._jit(), y + self._jit()), 0.30)
            for k, j in enumerate(sorted(order, key=lambda j: -self._base_u(j))[len(hunters):]):
                plan[j] = (*absp(56.0, G.CY + (k - 1.0) * 14.0), 0.15)
            return plan

        # A wide free kick: cross it against an offside line.
        s = rt["side"]
        box = sorted(mine, key=lambda j: -self._aerial(j))
        for j, (x, lat) in zip(box[:5], CORNER_BOX["far"][:5], strict=False):
            plan[j] = (*G.from_att(x + self._jit(), G.CY + s * lat + self._jit(), d), 0.29)
        if len(box) > 5:  # a short option beside the taker
            plan[box[5]] = (*absp(max(40.0, ax - 6.0), ay + (G.CY - ay) * 0.35), 0.30)
        for k, j in enumerate(box[6:]):
            plan[j] = (*absp(55.0, G.CY + (k - 0.5) * 14.0), 0.15)
        gk = de * 11
        plan[gk] = (*absp(102.0, G.CY - s * 0.8), 0.30)
        back = sorted(self._outfield(de), key=lambda j: self._base_u(j))
        for j, y in zip(back[:6], (-15.0, -9.0, -3.0, 3.0, 9.0, 15.0), strict=False):
            plan[j] = (*absp(92.5, G.CY + y), 0.29)
        for j, (x, lat) in zip(back[6:8], POSTS, strict=False):
            plan[j] = (*absp(x, G.CY + s * lat), 0.22)
        for k, j in enumerate(back[8:]):
            plan[j] = (*absp(60.0, G.CY + (k - 0.5) * 14.0), 0.15)
        return plan

    # ----- goal kicks ----------------------------------------------------------------------------------

    def _plan_goal_kick(self, r: dict) -> dict:
        att, rt = r["team"], r["routine"]
        long_ = rt["mode"] == "long"
        d = self.dir[att]
        mine = self._outfield(att)
        plan: dict[int, tuple[float, float, float]] = {}
        cbs = sorted((j for j in mine if self._role(j) == "CB"), key=lambda j: self.fy[att][self._local(j)])
        dms = sorted((j for j in mine if self._role(j) == "DM"), key=lambda j: self.fy[att][self._local(j)])
        sts = sorted((j for j in mine if self._role(j) == "ST"), key=lambda j: self.fy[att][self._local(j)])
        shift = 14.0 if long_ else 0.0
        n_cb = len(cbs)
        for k, j in enumerate(cbs):
            lat = 0.0 if n_cb == 1 else (k - (n_cb - 1) / 2.0) * (26.0 if n_cb == 2 else 17.0)
            x = (16.0 if long_ else 9.0) + (3.0 if (n_cb == 3 and k == 1 and not long_) else 0.0)
            plan[j] = (*G.from_att(x, G.CY + lat, d), 0.26)
        for j in mine:
            if j in plan:
                continue
            role = self._role(j)
            fyj = float(self.fy[att][self._local(j)])
            left = fyj < 0.5
            if role in ("LB", "RB"):
                x, y = 27.0 + shift, (9.0 if left else 59.0)
            elif role in ("LWB", "RWB"):
                x, y = 34.0 + shift, (7.0 if left else 61.0)
            elif role == "DM":
                x = 22.0 + shift * 1.3
                y = G.CY + (0.0 if len(dms) == 1 else (-8.0 if dms.index(j) == 0 else 8.0))
            elif role == "CM":
                x, y = 38.0 + shift * 0.7, G.CY + (fyj - 0.5) * 34.0
            elif role in ("AM", "LM", "RM"):
                x, y = 50.0 + shift * 0.4, G.CY + (fyj - 0.5) * 48.0
            elif role in ("LW", "RW"):
                x, y = 56.0 + shift * 0.3, (9.0 if left else 59.0)
            else:  # strikers: the target man in a long routine
                x = 62.0 + (-4.0 if long_ else 0.0)
                y = G.CY + (0.0 if len(sts) == 1 else (-7.0 if sts.index(j) == 0 else 7.0))
            plan[j] = (*G.from_att(x + self._jit(), y + self._jit(), d), 0.29)
        return plan

    # ----- throw-ins -------------------------------------------------------------------------------------

    def _plan_throw_in(self, r: dict) -> dict:
        att, rt, taker = r["team"], r["routine"], r["taker"]
        de = 1 - att
        d = self.dir[att]
        spot = np.array(r["spot"], dtype=float)
        ax, ay = self.att(att, spot)
        inward = 1.0 if ay < G.CY else -1.0
        plan: dict[int, tuple[float, float, float]] = {}
        if rt["mode"] == "long":
            return self._plan_long_throw(r)
        mine = sorted(self._outfield(att, exclude=(taker,)), key=lambda j: float(np.hypot(*(self.pos[j] - spot))))
        outlets = mine[:3]
        spots = [(ax - 1.0, ay + inward * 6.5), (ax + 9.0, ay + inward * 13.0), (ax - 10.0, ay + inward * 9.5)]
        # The nearest outlet takes the short option, the more advanced of the others the diagonal.
        order: list[int] = []
        if outlets:
            near, others = outlets[0], sorted(outlets[1:], key=lambda j: -self.att(att, self.pos[j])[0])
            order = [near, *others]
        for j, (x, y) in zip(order, spots, strict=False):
            plan[j] = (*G.from_att(min(G.PITCH_L - 3.0, max(3.0, x)), min(G.PITCH_W - 1.0, max(1.0, y)), d), 0.38)
        # The other team picks up the outlets (or sits off them in a low block).
        st = self.style[de]
        free = sorted(self._outfield(de), key=lambda j: float(np.hypot(*(self.pos[j] - spot))))
        tight = 1.8 + 3.0 * (1.0 - st.press_intensity) + (3.0 if st.press_height < 0.3 else 0.0)
        own_goal = np.array(G.from_att(0.0, G.CY, self.dir[de]))
        used: set[int] = set()
        for j in order:
            tx, ty = plan[j][0], plan[j][1]
            cand = [k for k in free if k not in used]
            if not cand:
                break
            k = min(cand, key=lambda q: float(np.hypot(self.pos[q][0] - tx, self.pos[q][1] - ty)))
            if float(np.hypot(self.pos[k][0] - tx, self.pos[k][1] - ty)) > 24.0:
                continue
            used.add(k)
            toward = _unit(own_goal - np.array([tx, ty]))
            p = np.array([tx, ty]) + toward * tight
            plan[k] = (float(p[0]), float(p[1]), 0.26)
        return plan

    def _plan_long_throw(self, r: dict) -> dict:
        att, rt, taker = r["team"], r["routine"], r["taker"]
        de = 1 - att
        s = rt["side"]
        d = self.dir[att]
        plan: dict[int, tuple[float, float, float]] = {}

        def put(j: int, ax: float, lat: float, urgency: float = 0.27) -> None:
            plan[j] = (*G.from_att(ax + self._jit(), G.CY + s * lat + self._jit(), d), urgency)

        mine = self._outfield(att, exclude=(taker,))
        cbs = sorted((j for j in mine if self._role(j) == "CB"), key=lambda j: -self.players[j].attrs["defending"])[:2]
        rest = sorted((j for j in mine if j not in cbs), key=lambda j: -self._base_u(j))
        box = cbs + rest[: 6 - len(cbs)]
        for j, (x, lat) in zip(sorted(box, key=lambda j: -self._aerial(j)), CORNER_BOX["far"], strict=False):
            put(j, x, lat)
        for k, j in enumerate(j for j in mine if j not in box):
            put(j, 56.0, (k - 1.0) * 13.0, 0.15)
        dfn = sorted(self._outfield(de), key=lambda j: self._base_u(j))
        plan[de * 11] = (*G.from_att(102.3, G.CY + s * 0.6, d), 0.22)
        for j, (x, lat) in zip(dfn[:8], ZONAL, strict=False):
            put(j, x, lat, 0.22)
        for k, j in enumerate(dfn[8:]):
            put(j, 58.0, (k - 0.5) * 12.0, 0.15)
        return plan

    # ----- penalties and kick-offs --------------------------------------------------------------------------

    def _plan_penalty(self, r: dict) -> dict:
        att, taker = r["team"], r["taker"]
        de = 1 - att
        d = self.dir[att]
        plan: dict[int, tuple[float, float, float]] = {}
        arc_a = [(86.5, G.CY - 14.0), (86.5, G.CY + 14.0), (84.5, G.CY - 8.0), (84.5, G.CY + 8.0), (87.5, G.CY - 21.5), (87.5, G.CY + 21.5)]
        arc_d = [(84.0, G.CY), (85.5, G.CY - 19.0), (85.5, G.CY + 19.0), (82.0, G.CY - 4.0), (82.0, G.CY + 4.0), (80.0, G.CY - 12.0), (80.0, G.CY + 12.0)]
        mine = sorted(self._outfield(att, exclude=(taker,)), key=lambda j: -self._base_u(j))
        dfn = sorted(self._outfield(de), key=lambda j: -self._base_u(j))
        for j, (x, y) in zip(mine, arc_a, strict=False):
            plan[j] = (*G.from_att(x, y, d), 0.30)
        for k, j in enumerate(mine[len(arc_a):]):
            plan[j] = (*G.from_att(60.0, G.CY + (k - 1.0) * 14.0, d), 0.15)
        for j, (x, y) in zip(dfn, arc_d, strict=False):
            plan[j] = (*G.from_att(x, y, d), 0.30)
        for k, j in enumerate(dfn[len(arc_d):]):
            plan[j] = (*G.from_att(70.0, G.CY + (k - 1.0) * 14.0, d), 0.15)
        plan[de * 11] = (*G.from_att(G.PITCH_L - 0.4, G.CY, d), 0.22)
        return plan

    def _plan_kickoff(self, r: dict) -> dict:
        att = r["team"]
        de = 1 - att
        plan: dict[int, tuple[float, float, float]] = {}
        taker = r["taker"]
        for team, front in ((att, 47.0), (de, 41.5)):
            d = self.dir[team]
            for j in self._outfield(team, exclude=(taker,)):
                u = float(self.u[team][self._local(j)])
                fyj = float(self.fy[team][self._local(j)])
                x = 12.0 + u * (front - 12.0)
                y = G.CY + (fyj - 0.5) * G.PITCH_W * 0.8
                plan[j] = (*G.from_att(x, y, d), 0.22)
            plan[team * 11] = (*G.from_att(8.0, G.CY, d), 0.15)
        # The kick-off taker's partner stands just behind the ball.
        mates = sorted(self._outfield(att, exclude=(taker,)), key=lambda j: -self._base_u(j))
        if mates:
            plan[mates[0]] = (*G.from_att(49.5, G.CY + 5.0, self.dir[att]), 0.30)
        return plan

    # ----- delivery -------------------------------------------------------------------------------------------

    def _short_corner(self, taker: int, team: int, spot, helper: int) -> None:
        end = self.pos[helper].copy()
        dist = float(np.hypot(*(end - np.array(spot))))
        c = {
            "j": helper, "end": end, "kind": "short", "dist": dist, "p": 0.93, "score": 0.0,
            "fwd": 0.0, "lane": 0.0, "prx": 0.0, "through": False, "jax": 0.0, "line": 0.0,
        }  # fmt: skip
        self._launch_pass(taker, c, "corner")

    @staticmethod
    def _wall_size(routine: dict | None) -> int:
        return int(routine["wall"]) if routine and routine.get("type") == "direct" else 0

    def _routine_label(self, kind: str, routine: dict | None) -> str | None:
        if not routine:
            return None
        return {
            "corner": routine.get("delivery"),
            "free_kick": routine.get("type"),
            "goal_kick": routine.get("mode"),
            "throw_in": routine.get("mode"),
        }.get(kind)

