"""The interpreter: events and physical facts in, explained *moments* out.

It is a streaming state machine. ``ingest`` takes one document at a time (a feed event, an
analyzer event or a physics enrichment) and returns whatever became knowable:

* **moments** - things worth telling, each with an *evidence pack* (see ``evidence.py``)
* **facts** - small structured statements that template overlays render without any model
* **snapshots** - the match state every minute (momentum, control vs chaos, pressure, rhythm)

Nothing here calls a language model. Numbers are computed, thresholds are explicit
(``config.py``) and every moment carries the evidence behind it, so the agents downstream
explain rather than invent.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field

from ..analytics.season import goal_milestones
from ..analytics.winprob import WinProbModel
from ..core import geometry as G
from ..core.clock import clock_from_ms, label
from ..core.models import pass_difficulty, xg, xpass
from ..sim.teams import GROUP
from . import detectors
from .config import InterpreterConfig
from .evidence import change, glossary_for
from .metrics import compute_window, indices, window_slice
from .xt import XTGrid

ASSIST_KINDS = ("through", "cross", "cutback")
SHOT_TIMEOUT_MS = 6000


@dataclass
class InterpretOutput:
    moments: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    snapshots: list[dict] = field(default_factory=list)

    def extend(self, other: InterpretOutput) -> None:
        self.moments.extend(other.moments)
        self.facts.extend(other.facts)
        self.snapshots.extend(other.snapshots)

    def __bool__(self) -> bool:
        return bool(self.moments or self.facts or self.snapshots)


class Interpreter:
    def __init__(
        self,
        meta: dict,
        cfg: InterpreterConfig | None = None,
        baselines: dict | None = None,
        xt: XTGrid | None = None,
        season: dict | None = None,
        models: dict | None = None,
    ) -> None:
        self.meta = meta
        self.models = models or {}
        self.winprob = WinProbModel.from_dict(self.models.get("winprob"))
        self.match_id = meta["matchId"]
        self.cfg = cfg or InterpreterConfig()
        self.baselines = baselines or {}
        self.xt = xt or XTGrid(None)
        self.season = season or {}
        self.clubs = [meta["home"]["id"], meta["away"]["id"]]
        self.club_names = {meta[s]["id"]: meta[s]["name"] for s in ("home", "away")}
        self.club_short = {meta[s]["id"]: meta[s]["short"] for s in ("home", "away")}
        self.players: dict[str, dict] = {}
        for side in ("home", "away"):
            for pid, p in meta[side]["players"].items():
                self.players[pid] = {**p, "team": meta[side]["id"], "group": GROUP[p["pos"]]}

        self.attack_dirs: dict[int, dict[str, int]] = {}
        self.p2_start_ms: int | None = None
        for p in meta.get("periods", []):
            self._register_period(p["period"], p["startMs"], p["attackDirection"])

        self.events: list[dict] = []  # normalised, sorted by _ms
        self.times: list[int] = []
        self.by_id: dict[str, dict] = {}
        self.latest_ms = 0
        self.next_eval_ms = self.cfg.eval_every_ms
        self.score = {c: 0 for c in self.clubs}
        self.pending_shots: dict[str, dict] = {}
        self.pending_goals: dict[str, dict] = {}
        self.moment_n = 0
        self.fact_n = 0
        self.last_moment_at: dict[tuple[str, str], int] = {}
        self.recent_moments: list[dict] = []
        self.player_stats: dict[str, Counter] = {}
        self.max_speed_kmh = 0.0
        self.max_shot_kmh = 0.0
        self.max_sprint_kmh = 0.0
        self.loads: dict[str, dict] = {}
        self.load_cards_done: set[int] = set()
        self.goal_log: list[dict] = []
        self.last_run_card: dict[tuple[str, str], int] = {}
        self.history: list[dict] = []  # snapshots, for timelines and recaps
        self.all_moments: list[dict] = []

    def strength(self) -> tuple[float, float]:
        """Pre-match scoring strength of (home, away) from the season model, or 1.0 each."""
        st = (self.season or {}).get("prediction", {}).get("strength")
        return (float(st[self.clubs[0]]), float(st[self.clubs[1]])) if st else (1.0, 1.0)

    def win_probability(self, club: str, ms: int, inclusive: bool = True) -> float:
        """Percent chance ``club`` wins, from the score, time left, xG so far and any red cards at ``ms``."""
        marks, shots = self.winprob.timeline(self.events)
        p = self.winprob.at(marks, shots, self.clubs, ms, inclusive, self.strength())
        return 100.0 * p["home" if club == self.clubs[0] else "away"]

    def leverage(self, club: str, ms: int) -> tuple[dict, float]:
        """Win probability of ``club`` just before and after an event at ``ms``, as an evidence metric, and the swing."""
        before = self.win_probability(club, ms, inclusive=False)
        after = self.win_probability(club, ms, inclusive=True)
        return change(before, after, 0), abs(after - before) / 100.0

    # ----- setup ---------------------------------------------------------------------------------------------

    def _register_period(self, period: int, start_ms: int, directions: dict[str, int]) -> None:
        self.attack_dirs[period] = dict(directions)
        if period == 2:
            self.p2_start_ms = start_ms

    def minute_label(self, ms: int) -> str:
        return label(clock_from_ms(ms, self.p2_start_ms))

    def name(self, pid: str | None) -> str | None:
        return self.players[pid]["name"] if pid in self.players else None

    # ----- ingest ---------------------------------------------------------------------------------------------

    def ingest(self, doc: dict, arrival_ms: int | None = None) -> InterpretOutput:
        out = InterpretOutput()
        ms = doc["clock"]["matchMs"] if "clock" in doc else 0
        self.latest_ms = max(self.latest_ms, arrival_ms if arrival_ms is not None else ms)

        t = doc.get("type")
        if t == "physics":
            self._on_physics(doc, out)
        elif t == "period_start":
            self._register_period(
                doc["attributes"].get("period", doc["clock"]["period"]),
                doc["clock"]["matchMs"],
                doc["attributes"]["attackDirection"],
            )
        elif t == "player_load":
            self.loads.update(doc["attributes"]["players"])
        else:
            self._on_event(doc, out)

        self._expire_pending(out)
        self._evaluate_due(out)
        return out

    def _normalise(self, e: dict) -> dict:
        r = dict(e)
        r["_ms"] = e["clock"]["matchMs"]
        team = e.get("team")
        dirs = self.attack_dirs.get(e["clock"]["period"], {})
        if team in dirs:
            d = dirs[team]
            if "location" in e:
                r["_ax"], r["_ay"] = G.to_att(e["location"]["x"], e["location"]["y"], d)
            if "end" in e:
                r["_eax"], r["_eay"] = G.to_att(e["end"]["x"], e["end"]["y"], d)
        return r

    def _insert(self, r: dict) -> None:
        i = bisect_right(self.times, r["_ms"])
        self.times.insert(i, r["_ms"])
        self.events.insert(i, r)
        self.by_id[r["id"]] = r

    def _on_event(self, e: dict, out: InterpretOutput) -> None:
        r = self._normalise(e)
        self._insert(r)
        t = r["type"]
        team = r.get("team")
        attrs = r.get("attributes", {})

        if t == "shot":
            r["_xg"] = self._shot_xg(r, pressure=None)
            self.pending_shots[r["id"]] = {"shot": r, "physics": None, "goal": None, "t": r["_ms"]}
        elif t == "goal":
            self.score[team] += 1
            shot_id = self._shot_for_goal(r)
            if shot_id:
                self.pending_shots[shot_id]["goal"] = r
                self._try_finalise_shot(shot_id, out)
            else:
                self._emit_goal(r, None, out)
        elif t == "pass":
            r["_xpass"] = None
        elif t == "card":
            if r.get("outcome") == "red":
                wp, swing = self.leverage(team, r["_ms"])
                self._moment(
                    out, "red_card", r["_ms"], subject=team, beneficiary=self._other(team),
                    metrics={f"{team}.win_prob": wp}, events=[r["id"]], players=[r["player"]], magnitude=swing,
                    extra={"card": "red", "secondYellow": bool(attrs.get("secondYellow")), "winProbSwing": round(swing, 2)},
                )  # fmt: skip
            self._fact(out, "card_event", r["_ms"], team, r["player"], {"card": r.get("outcome"), "secondYellow": bool(attrs.get("secondYellow"))}, priority=2)
        elif t == "foul" and attrs.get("inBox"):
            self._moment(
                out, "penalty", r["_ms"], subject=team, beneficiary=self._other(team),
                metrics={}, events=[r["id"]], players=[r["player"], self._pid_from(attrs.get("fouled"))],
                extra={"fouled": attrs.get("fouled")},
            )  # fmt: skip
        elif t == "substitution":
            self._fact(out, "substitution", r["_ms"], team, r["player"], {"on": r["player"], "off": attrs.get("off")}, priority=4)
        elif t == "corner":
            self._fact(out, "set_piece", r["_ms"], team, r.get("player"), {"kind": "corner", "routine": attrs.get("routine")}, priority=4)
        elif t == "free_kick" and attrs.get("routine") in ("direct", "cross"):
            dist = round(G.goal_dist(r["_ax"], r["_ay"]), 1) if "_ax" in r else None
            self._fact(
                out, "set_piece", r["_ms"], team, r.get("player"),
                {"kind": "free_kick", "routine": attrs["routine"], "wall": attrs.get("wall"), "distanceM": dist}, priority=4,
            )  # fmt: skip
        elif t == "throw_in" and attrs.get("routine") == "long":
            self._fact(out, "set_piece", r["_ms"], team, r.get("player"), {"kind": "long_throw", "routine": "long"}, priority=4)
        elif t == "formation_change":
            self._fact(out, "formation_change", r["_ms"], team, None, {"to": attrs.get("formation"), "from": attrs.get("previous")}, priority=2)
        elif t == "top_speed":
            self._on_top_speed(r, out)
        elif t == "sprint":
            peak = attrs.get("peakKmh", 0.0)
            self.max_sprint_kmh = max(self.max_sprint_kmh, peak)
            if peak >= self.cfg.speed_badge_kmh:
                self._fact(out, "speed_badge", r["_ms"], team, r["player"], {"peakKmh": peak, "distanceM": attrs.get("distanceM")}, priority=4)
        elif t == "distance_milestone":
            self._fact(out, "distance_badge", r["_ms"], team, r["player"], {"km": attrs.get("km")}, priority=5)
        elif t == "off_ball_run":
            self._on_run(r, out)
        elif t == "player_load":
            self._on_load(r, out)

        self._count_player(r)

    # ----- runs and load ---------------------------------------------------------------------------------------

    def _on_run(self, r: dict, out: InterpretOutput) -> None:
        a = r["attributes"]
        floor = self.cfg.run_card_m.get(a["kind"])
        if floor is None or a["distanceM"] < floor:
            return
        key = (r["team"], a["kind"])
        last = self.last_run_card.get(key)
        if last is not None and r["_ms"] - last < self.cfg.run_card_cooldown_ms:
            return
        self.last_run_card[key] = r["_ms"]
        self._fact(out, "run_card", a["startMs"], r["team"], r["player"],
                   {"kind": a["kind"], "distanceM": a["distanceM"], "peakKmh": a["peakKmh"]}, priority=4)  # fmt: skip

    def _on_load(self, r: dict, out: InterpretOutput) -> None:
        self.loads.update(r["attributes"]["players"])
        periods = self.meta.get("periods", [])
        half_end = periods[0].get("endMs") if periods else None
        if half_end and r["_ms"] >= half_end and 1 not in self.load_cards_done:
            self.load_cards_done.add(1)
            self._load_cards(half_end, out, half=True)

    def _load_cards(self, ms: int, out: InterpretOutput, half: bool) -> None:
        for club in self.clubs:
            mine = {pid: v for pid, v in self.loads.items() if pid.startswith(f"{club}-")}
            if not mine:
                continue
            pid, v = max(mine.items(), key=lambda kv: kv[1]["hsrM"])
            self._fact(out, "load_card", ms, club, pid,
                       {"km": v["km"], "hsrM": v["hsrM"], "sprintM": v["sprintM"], "acc": v["acc"], "half": half}, priority=4)  # fmt: skip

    def _on_physics(self, doc: dict, out: InterpretOutput) -> None:
        r = self.by_id.get(doc["ref"])
        if r is None:
            return
        r["physics"] = doc["physics"]
        if r["type"] == "pass":
            self._rate_pass(r, out)
        elif r["type"] == "shot":
            pend = self.pending_shots.get(r["id"])
            if pend is not None:
                pend["physics"] = doc["physics"]
                r["_xg"] = self._shot_xg(r, pressure=doc["physics"].get("pressure"))
                self._try_finalise_shot(r["id"], out)

    # ----- passes ------------------------------------------------------------------------------------------------

    def _rate_pass(self, r: dict, out: InterpretOutput) -> None:
        ph = r["physics"]
        kind = r["attributes"].get("passType", "medium")
        p = xpass(
            ph["distanceM"], kind=kind,
            pressure_receiver=ph.get("pressureReceiver", 0.0),
            pressure_passer=ph.get("pressurePasser", 0.0),
            lane_block=ph.get("laneBlock", 0.0),
            forward=ph.get("forwardM", 0.0),
        )  # fmt: skip
        r["_xpass"] = p
        r["_diff"] = pass_difficulty(p)
        r["_bypassed"] = int(ph.get("bypassed", 0))
        r["_lines"] = int(ph.get("linesBroken", 0))
        if r.get("outcome") == "complete" and (r["_lines"] >= 3 or r["_bypassed"] >= self.cfg.packing_card):
            self._fact(
                out, "line_break_card", r["_ms"] + 800, r["team"], r["player"],
                {"bypassed": r["_bypassed"], "lines": r["_lines"], "receiver": r.get("receiver"), "distanceM": ph["distanceM"]},
                priority=3,
            )  # fmt: skip
        if r.get("outcome") == "complete" and r["_diff"] >= self.cfg.key_pass_difficulty:
            self._fact(
                out, "pass_card", r["_ms"] + 800, r["team"], r["player"],
                {"difficulty": r["_diff"], "distanceM": ph["distanceM"], "ballSpeedKmh": ph.get("ballSpeedKmh"),
                 "passType": kind, "receiver": r.get("receiver")},
                priority=3,
            )  # fmt: skip

    # ----- shots and goals ---------------------------------------------------------------------------------------

    def _shot_xg(self, r: dict, pressure: float | None) -> float:
        a = r["attributes"]
        if "_ax" not in r:
            return 0.05
        pr = pressure if pressure is not None else (0.5 if a.get("underPressure") else 0.1)
        assist = a.get("assist") if a.get("assist") in ASSIST_KINDS else "open"
        sit = a.get("situation")
        return xg(
            r["_ax"], r["_ay"],
            body="head" if a.get("bodyPart") == "head" else "foot",
            assist="free_kick" if sit == "free_kick" else assist,
            pressure=pr, penalty=bool(a.get("penalty")), direct_free_kick=sit == "free_kick",
        )  # fmt: skip

    def _shot_for_goal(self, goal: dict) -> str | None:
        for sid, pend in self.pending_shots.items():
            s = pend["shot"]
            if s["player"] == goal["player"] and s.get("outcome") == "goal" and 0 <= goal["_ms"] - s["_ms"] < 4000:
                return sid
        return None

    def _try_finalise_shot(self, sid: str, out: InterpretOutput, force: bool = False) -> None:
        pend = self.pending_shots.get(sid)
        if pend is None:
            return
        s = pend["shot"]
        have_phys = pend["physics"] is not None
        need_goal = s.get("outcome") == "goal"
        if not force and not (have_phys and (pend["goal"] is not None or not need_goal)):
            return
        del self.pending_shots[sid]
        ph = pend["physics"] or {}
        speed = ph.get("shotSpeedKmh")
        xg_v = s["_xg"]
        self._fact(
            out, "shot_card", s["_ms"] + 1200, s["team"], s["player"],
            {"xg": round(xg_v, 2), "shotSpeedKmh": speed, "distanceM": round(G.goal_dist(s["_ax"], s["_ay"]), 1) if "_ax" in s else None,
             "outcome": s.get("outcome"), "bodyPart": s["attributes"].get("bodyPart")},
            priority=2 if s.get("outcome") == "goal" else 3,
        )  # fmt: skip
        if speed and speed >= self.cfg.fast_shot_kmh and speed > self.max_shot_kmh:
            self._moment(
                out, "physical_highlight", s["_ms"], subject=s["team"], beneficiary=None,
                metrics={f"{s['team']}.shot_speed_kmh": {"value": speed}}, events=[s["id"]], players=[s["player"]],
                extra={"kind": "fastest_shot"},
            )  # fmt: skip
        if speed:
            self.max_shot_kmh = max(self.max_shot_kmh, speed)
        if s.get("outcome") == "goal":
            self._emit_goal(pend["goal"], s, out)
        elif xg_v >= self.cfg.big_chance_xg:
            self._moment(
                out, "big_chance", s["_ms"], subject=s["team"], beneficiary=None,
                metrics={f"{s['team']}.xg_shot": {"value": round(xg_v, 2)}, **({f"{s['team']}.shot_speed_kmh": {"value": speed}} if speed else {})},
                events=[s["id"]], players=[s["player"]],
                extra={"outcome": s.get("outcome"), "bodyPart": s["attributes"].get("bodyPart"),
                       "assistType": s["attributes"].get("assist"), "xg": round(xg_v, 2)},
            )  # fmt: skip

    def _emit_goal(self, goal: dict | None, shot: dict | None, out: InterpretOutput) -> None:
        if goal is None:
            return
        team = goal["team"]
        xg_v = shot["_xg"] if shot else None
        assist = goal["attributes"].get("assist")
        ph = (shot or {}).get("physics") or {}
        self._fact(
            out, "goal_card", goal["_ms"], team, goal["player"],
            {"scorer": goal["player"], "assist": assist, "xg": round(xg_v, 2) if xg_v is not None else None,
             "score": dict(self.score), "shotSpeedKmh": ph.get("shotSpeedKmh")},
            priority=1,
        )  # fmt: skip
        clock = goal["clock"]
        new_goal = {"team": team, "player": goal["player"], "minute": clock["minute"] + clock["second"] / 60.0}
        for ms in goal_milestones(self.season, self.goal_log, new_goal, self._other(team)):
            self._fact(out, "milestone_card", goal["_ms"] + 1500, ms["team"], ms.get("player"), {k: v for k, v in ms.items() if k not in ("player", "team")}, priority=3)
        self.goal_log.append(new_goal)
        metrics = {f"{team}.xg_shot": {"value": round(xg_v, 2)}} if xg_v is not None else {}
        wp, swing = self.leverage(team, goal["_ms"])
        metrics[f"{team}.win_prob"] = wp
        self._moment(
            out, "goal", goal["_ms"], subject=team, beneficiary=team,
            metrics=metrics,
            events=[e for e in (shot["id"] if shot else None, goal["id"]) if e],
            players=[goal["player"], assist],
            magnitude=swing,
            extra={"assist": assist, "xg": round(xg_v, 2) if xg_v is not None else None, "winProbSwing": round(swing, 2),
                   "bodyPart": (shot or {}).get("attributes", {}).get("bodyPart"),
                   "assistType": (shot or {}).get("attributes", {}).get("assist"),
                   "situation": (shot or {}).get("attributes", {}).get("situation")},
        )  # fmt: skip

    def _expire_pending(self, out: InterpretOutput) -> None:
        for sid in [k for k, p in self.pending_shots.items() if self.latest_ms - p["t"] > SHOT_TIMEOUT_MS]:
            self._try_finalise_shot(sid, out, force=True)

    # ----- physical highlights ------------------------------------------------------------------------------------

    def _on_top_speed(self, r: dict, out: InterpretOutput) -> None:
        peak = r["attributes"].get("peakKmh", 0.0)
        if peak >= self.cfg.top_speed_kmh and peak > self.max_speed_kmh:
            self._moment(
                out, "physical_highlight", r["_ms"], subject=r["team"], beneficiary=None,
                metrics={f"{r['team']}.peak_kmh": {"value": peak}}, events=[r["id"]], players=[r["player"]],
                extra={"kind": "top_speed"},
            )  # fmt: skip
        self.max_speed_kmh = max(self.max_speed_kmh, peak)

    # ----- per-player counters --------------------------------------------------------------------------------------

    def _count_player(self, r: dict) -> None:
        pid = r.get("player")
        if not pid:
            return
        c = self.player_stats.setdefault(pid, Counter())
        t = r["type"]
        if t == "pass":
            c["passes"] += 1
            c["pass_complete"] += r.get("outcome") == "complete"
        elif t == "shot":
            c["shots"] += 1
            c["goals"] += r.get("outcome") == "goal"
        elif t in ("tackle", "interception"):
            c["def_actions"] += 1
        elif t == "sprint":
            c["sprints"] += 1

    # ----- helpers -------------------------------------------------------------------------------------------------------

    def _other(self, club: str | None) -> str | None:
        if club not in self.clubs:
            return None
        return self.clubs[1 - self.clubs.index(club)]

    @staticmethod
    def _pid_from(name_or_id: str | None) -> str | None:
        return name_or_id

    def _fact(self, out: InterpretOutput, type_: str, ms: int, team: str | None, player: str | None, values: dict, priority: int = 3) -> None:
        self.fact_n += 1
        out.facts.append(
            {
                "id": f"{self.match_id}-f{self.fact_n:04d}",
                "matchId": self.match_id,
                "type": type_,
                "matchMs": int(ms),
                "clock": clock_from_ms(int(ms), self.p2_start_ms),
                "team": team,
                "player": player,
                "values": values,
                "priority": priority,
            }
        )

    # ----- moments ----------------------------------------------------------------------------------------------------------

    def _moment(
        self,
        out: InterpretOutput,
        type_: str,
        ms: int,
        *,
        subject: str | None,
        beneficiary: str | None,
        metrics: dict,
        events: list[str],
        players: list[str | None],
        windows: dict | None = None,
        extra: dict | None = None,
        magnitude: float = 0.5,
    ) -> dict | None:
        key = (type_, subject or "")
        if type_ not in ("goal", "red_card", "penalty", "big_chance", "physical_highlight"):
            last = self.last_moment_at.get(key)
            if last is not None and ms - last < self.cfg.cooldown_for(type_):
                return None
        self.last_moment_at[key] = ms
        self.moment_n += 1
        clock = clock_from_ms(int(ms), self.p2_start_ms)
        pack = {
            "id": f"{self.match_id}-mo-{self.moment_n:03d}",
            "matchId": self.match_id,
            "type": type_,
            "detectedAt": {"matchMs": int(ms), "clock": clock, "label": label(clock)},
            "salience": 0.0,
            "subjectTeam": subject,
            "beneficiaryTeam": beneficiary,
            "teamNames": dict(self.club_names),
            "teamShort": dict(self.club_short),
            "windows": windows or {},
            "metrics": metrics,
            "facts": {"score": dict(self.score), **(extra or {})},
            "eventIds": [e for e in events if e],
            "players": [
                {"id": p, "name": self.name(p), "team": self.players[p]["team"], "pos": self.players[p]["pos"]}
                for p in dict.fromkeys(x for x in players if x in self.players)
            ],
            "glossary": glossary_for(metrics),
            "status": "detected",
        }
        pack["salience"] = detectors.salience(self, pack, magnitude)
        out.moments.append(pack)
        self.all_moments.append(pack)
        self.recent_moments.append(pack)
        return pack

    # ----- evaluation ticks ------------------------------------------------------------------------------------------------

    def _evaluate_due(self, out: InterpretOutput) -> None:
        while self.latest_ms - self.cfg.eval_lag_ms >= self.next_eval_ms:
            self._evaluate(self.next_eval_ms, out)
            self.next_eval_ms += self.cfg.eval_every_ms

    def window(self, t0: int, t1: int) -> dict:
        evs = window_slice(self.events, self.times, t0, t1)
        return compute_window(evs, t0, t1, self.clubs, self.players, self.xt.value, self.cfg.big_chance_xg)

    def _evaluate(self, t: int, out: InterpretOutput) -> None:
        cfg = self.cfg
        now = self.window(t - cfg.window_ms, t)
        prev = self.window(t - cfg.window_ms - cfg.prev_window_ms, t - cfg.window_ms)
        idx_now = indices(now, self.clubs, self.baselines)
        idx_prev = indices(prev, self.clubs, self.baselines)

        xt_sum = {c: now[c]["xt"] + 0.02 for c in self.clubs}
        tot = sum(xt_sum.values())
        snap = {
            "id": f"{self.match_id}-s{len(self.history) + 1:03d}",
            "matchId": self.match_id,
            "matchMs": t,
            "clock": clock_from_ms(t, self.p2_start_ms),
            "momentum": {c: round(xt_sum[c] / tot, 3) for c in self.clubs},
            "control": idx_now["control"],
            "chaos": idx_now["chaos"],
            "pressure": idx_now["pressure"],
            "rhythm": idx_now["rhythm"],
            "ppda": {c: (round(now[c]["ppda"], 1) if now[c]["ppda"] is not None else None) for c in self.clubs},
            "possession": {c: round(now[c]["possession_share"], 3) for c in self.clubs},
            "score": dict(self.score),
        }
        self.history.append(snap)
        out.snapshots.append(snap)

        if t >= cfg.min_play_ms:
            for cand in detectors.detect_window_moments(self, t, now, prev, idx_now, idx_prev):
                self._moment(out, **cand)

    def finish(self) -> InterpretOutput:
        """Flush anything still pending (end of match)."""
        out = InterpretOutput()
        for sid in list(self.pending_shots):
            self._try_finalise_shot(sid, out, force=True)
        if self.loads and 2 not in self.load_cards_done:
            self.load_cards_done.add(2)
            periods = self.meta.get("periods", [])
            end = periods[-1].get("endMs") if periods else self.latest_ms
            self._load_cards(end or self.latest_ms, out, half=False)
        return out

