"""The match analytics report: every analytics view of one match, JSON-ready.

``MatchAnalytics`` wraps an interpreter that has seen the whole feed (events, tracking-derived
events and the fitted models) and answers the questions an Opta-style match centre answers: who was
likely to win and when it changed, who created the most value, how the team lined up, where the
space was, who ran how far. The replay package stores ``summary()`` as ``analytics.json``; the MCP
server and the web app read the same views.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from ..core import geometry as G
from .goalkeepers import goalkeeper_report
from .measured_shape import measured_shapes
from .networks import passing_network
from .pressing import pressing_report
from .setpieces import set_piece_report
from .shots import shot_list, xg_race
from .transitions import transition_report
from .vaep import ActionValuer
from .winprob import WinProbModel
from .xgot import XGOT

KEY_PASS_MS = 5000


def jsonable(obj):
    """Plain Python for JSON: numpy scalars become numbers, tuples become lists."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


class MatchAnalytics:
    def __init__(self, ip) -> None:
        self.ip = ip
        self.clubs: list[str] = ip.clubs
        self.players: dict[str, dict] = ip.players
        self.models: dict = ip.models
        self.xgot = XGOT(self.models.get("xgot"))
        self.valuer = ActionValuer(self.models.get("vaep"))
        self.winprob: WinProbModel = ip.winprob
        self.end_ms = max((e["_ms"] for e in ip.events), default=0)
        self._values: list | None = None

    # ----- who was likely to win ---------------------------------------------------------------------------------

    def win_probability(self) -> dict:
        ser = self.winprob.series(self.ip.events, self.clubs, self.end_ms, self.ip.strength())
        return {
            "series": ser,
            "swings": self.winprob.swings(ser),
            "preMatch": ser[0]["p"] if ser else None,
            "final": ser[-1]["p"] if ser else None,
            "model": {k: self.winprob.params[k] for k in ("goal_rate", "match_minutes", "prior_minutes", "red_own", "red_opp")},
        }

    # ----- shots ---------------------------------------------------------------------------------------------------

    def shots(self) -> dict:
        shots = shot_list(self.ip.events, self.xgot)
        race = xg_race(shots, self.clubs, self.end_ms)
        per = {}
        for c in self.clubs:
            mine = [s for s in shots if s["team"] == c]
            on = [s for s in mine if s["outcome"] in ("goal", "saved")]
            per[c] = {
                "shots": len(mine), "onTarget": len(on), "goals": sum(s["outcome"] == "goal" for s in mine),
                "xg": round(sum(s["xg"] for s in mine), 2), "xgot": round(sum(s["xgot"] or 0.0 for s in mine), 2),
                "bigChances": sum(s["xg"] >= self.ip.cfg.big_chance_xg for s in mine),
            }
        return {"shots": shots, "race": race, "teams": per}

    # ----- possession value -------------------------------------------------------------------------------------------

    def action_values(self) -> list:
        if self._values is None:
            self._values = self.valuer.values(self.ip.events, self.clubs)
        return self._values

    def possession_value(self, top: int = 8) -> dict:
        vals = self.action_values()
        if not vals:
            return {"available": False}
        by_player = self.valuer.player_totals(vals)
        by_team = {c: round(sum(v.value for v in vals if v.team == c), 3) for c in self.clubs}
        best = sorted(vals, key=lambda v: -v.value)[:top]
        worst = sorted(vals, key=lambda v: v.value)[:3]
        by_type: dict[str, dict] = {}
        for v in vals:
            t = by_type.setdefault(v.type, {"n": 0, "value": 0.0})
            t["n"] += 1
            t["value"] += v.value
        names = {pid: p["name"] for pid, p in self.players.items()}
        return {
            "available": True,
            "teams": by_team,
            "players": by_player,
            "best": [self._action_row(v, names) for v in best],
            "worst": [self._action_row(v, names) for v in worst],
            "byType": {k: {"n": t["n"], "value": round(t["value"], 3)} for k, t in by_type.items()},
        }

    @staticmethod
    def _action_row(v, names: dict) -> dict:
        return {"id": v.id, "player": v.player, "name": names.get(v.player or ""), "team": v.team, "type": v.type, "ms": v.ms, "value": round(v.value, 3)}

    # ----- passing networks ---------------------------------------------------------------------------------------------

    def networks(self) -> dict:
        half = (self.ip.meta.get("periods") or [{}])[0].get("endMs", self.end_ms // 2)
        out = {}
        for c in self.clubs:
            out[c] = {
                "full": passing_network(self.ip.events, c, self.players, 0, 10**12),
                "h1": passing_network(self.ip.events, c, self.players, 0, half),
                "h2": passing_network(self.ip.events, c, self.players, half, 10**12),
            }
        return out

    # ----- formation as measured from tracking ----------------------------------------------------------------------------

    def shapes(self) -> dict:
        profiles: dict[tuple[str, str], dict[str, list]] = {}
        blocks: dict[str, list] = defaultdict(list)
        positions = {pid: p["pos"] for pid, p in self.players.items()}
        for e in self.ip.events:
            if e["type"] != "shape_profile":
                continue
            club = e["team"]
            block = e["attributes"]["block"]
            entry = {"block": block, "endMs": e["_ms"]}
            for phase in ("def", "ip"):
                pr = e["attributes"][phase]
                tot = profiles.setdefault((club, phase), {})
                for pid, (x, y, n) in pr.items():
                    a = tot.setdefault(pid, [0.0, 0.0, 0])
                    a[0] += x * n
                    a[1] += y * n
                    a[2] += n
                m = measured_shapes(pr, phase, positions)
                entry[phase] = m["label"] if m else None
            blocks[club].append(entry)
        out = {}
        for c in self.clubs:
            side = self.ip.meta["home" if c == self.clubs[0] else "away"]
            res: dict = {"designed": side.get("shapes"), "nominal": side.get("startFormation", side.get("formation")), "blocks": blocks.get(c, [])}
            for phase in ("def", "ip"):
                prof = {pid: [v[0] / v[2], v[1] / v[2], v[2]] for pid, v in profiles.get((c, phase), {}).items() if v[2]}
                m = measured_shapes(prof, phase, positions)
                regulars = sorted(prof.items(), key=lambda kv: -kv[1][2])[:10]
                res[phase] = {
                    "measured": m,
                    "players": [{"id": pid, "name": self.players.get(pid, {}).get("name"), "pos": positions.get(pid), "x": round(v[0], 1), "y": round(v[1], 1)} for pid, v in regulars],
                }
            out[c] = res
        return out

    # ----- space ---------------------------------------------------------------------------------------------------------

    def space(self) -> dict:
        series: dict[str, list] = {c: [] for c in self.clubs}
        for e in self.ip.events:
            if e["type"] == "space_control":
                a = e["attributes"]
                series[e["team"]].append({"ms": e["_ms"], "control": a["controlShare"], "finalThird": a["finalThirdControl"], "behind": a["spaceBehindM2"]})
        summary = {}
        for c, s in series.items():
            behind = [p["behind"] for p in s if p["behind"] is not None]
            summary[c] = {
                "controlShare": round(float(np.mean([p["control"] for p in s])), 3) if s else None,
                "finalThirdControl": round(float(np.mean([p["finalThird"] for p in s])), 3) if s else None,
                "spaceBehindM2": round(float(np.mean(behind)), 0) if behind else None,
            }
        return {"series": series, "teams": summary}

    # ----- passes that take opponents out of the game ----------------------------------------------------------------------

    def line_breaks(self, top: int = 6) -> dict:
        per_team = {c: {"completed": 0, "packing": 0, "lineBreaks": 0, "threeLines": 0} for c in self.clubs}
        per_player: dict[str, dict] = {}
        best = []
        for e in self.ip.events:
            if e["type"] != "pass" or e.get("outcome") != "complete" or "_bypassed" not in e:
                continue
            t = per_team[e["team"]]
            t["completed"] += 1
            t["packing"] += e["_bypassed"]
            t["lineBreaks"] += e["_lines"] >= 1
            t["threeLines"] += e["_lines"] >= 3
            p = per_player.setdefault(e["player"], {"packing": 0, "lineBreaks": 0, "passes": 0})
            p["packing"] += e["_bypassed"]
            p["lineBreaks"] += e["_lines"] >= 1
            p["passes"] += 1
            best.append((e["_bypassed"], e["_lines"], e))
        best.sort(key=lambda b: (-b[0], -b[1]))
        return {
            "teams": per_team,
            "players": per_player,
            "best": [
                {"id": e["id"], "team": e["team"], "player": e["player"], "receiver": e.get("receiver"), "ms": e["_ms"], "bypassed": b, "lines": n_lines}
                for b, n_lines, e in best[:top]
            ],
        }

    # ----- off-ball runs -------------------------------------------------------------------------------------------------------

    def runs(self) -> dict:
        passes_to: dict[str, list[dict]] = defaultdict(list)
        for e in self.ip.events:
            if e["type"] == "pass" and e.get("receiver"):
                passes_to[e["receiver"]].append(e)
        runs = []
        for e in self.ip.events:
            if e["type"] != "off_ball_run":
                continue
            a = e["attributes"]
            start, end = a["startMs"], a["startMs"] + a["durationMs"]
            played = any(start <= p["_ms"] <= end + 2500 and p["team"] == e["team"] for p in passes_to.get(e["player"], []))
            runs.append({
                "id": e["id"], "team": e["team"], "player": e["player"], "kind": a["kind"], "distanceM": a["distanceM"],
                "peakKmh": a["peakKmh"], "startMs": start, "endMs": end, "from": a["from"], "to": a["to"], "ballPlayed": played,
            })
        counts: dict[str, Counter] = {c: Counter() for c in self.clubs}
        played_counts: dict[str, Counter] = {c: Counter() for c in self.clubs}
        by_player: dict[str, Counter] = defaultdict(Counter)
        for r in runs:
            counts[r["team"]][r["kind"]] += 1
            played_counts[r["team"]][r["kind"]] += r["ballPlayed"]
            by_player[r["player"]][r["kind"]] += 1
        return {
            "runs": runs,
            "teams": {c: {k: {"n": counts[c][k], "ballPlayed": played_counts[c][k]} for k in ("in_behind", "overlap", "drop")} for c in self.clubs},
            "players": {p: dict(c) for p, c in by_player.items()},
        }

    # ----- physical load ----------------------------------------------------------------------------------------------------------

    def load(self) -> dict:
        loads = self.ip.loads
        out: dict[str, dict] = {}
        for pid, v in loads.items():
            blocks = v.get("hsrBlocks") or []
            fatigue = None
            if len(blocks) >= 3 and blocks[0] > 0:
                fatigue = round(float(np.mean(blocks[-2:])) / blocks[0], 2)  # late high-speed running relative to the first 15 minutes
            out[pid] = {**v, "fatigue": fatigue, "name": self.players.get(pid, {}).get("name"), "team": pid.split("-")[0]}
        top = sorted(out.items(), key=lambda kv: -kv[1]["hsrM"])[:5]
        return {"players": out, "top": [{"id": k, **{kk: vv for kk, vv in v.items() if kk in ("name", "team", "km", "hsrM", "sprintM", "acc", "dec")}} for k, v in top]}

    # ----- the rest, from events -------------------------------------------------------------------------------------------------------

    def set_pieces(self) -> dict:
        return set_piece_report(self.ip.events, self.ip.meta)

    def transitions(self) -> dict:
        return transition_report(self.ip.events, self.clubs)

    def goalkeepers(self) -> dict:
        return goalkeeper_report(self.ip.events, self.clubs, self.players, self.xgot)

    def pressing(self) -> dict:
        return pressing_report(self.ip.events, self.clubs)

    # ----- players ------------------------------------------------------------------------------------------------------------------------

    def players_table(self) -> list[dict]:
        events = self.ip.events
        rows: dict[str, dict] = {}

        def row(pid: str) -> dict:
            if pid not in rows:
                p = self.players[pid]
                rows[pid] = {
                    "id": pid, "name": p["name"], "team": p["team"], "pos": p["pos"], "goals": 0, "assists": 0, "shots": 0, "xg": 0.0,
                    "keyPasses": 0, "xa": 0.0, "passes": 0, "passesComplete": 0, "tackles": 0, "interceptions": 0, "pressures": 0,
                }
            return rows[pid]

        shots = [e for e in events if e["type"] == "shot"]
        passes = [e for e in events if e["type"] == "pass" and e.get("outcome") == "complete" and e.get("receiver")]
        for e in events:
            pid = e.get("player")
            if pid not in self.players:
                continue
            t = e["type"]
            if t == "pass":
                r = row(pid)
                r["passes"] += 1
                r["passesComplete"] += e.get("outcome") == "complete"
            elif t == "tackle":
                row(pid)["tackles"] += 1
            elif t == "interception":
                row(pid)["interceptions"] += 1
            elif t == "pressure":
                row(pid)["pressures"] += 1
            elif t == "goal":
                row(pid)["goals"] += 1
                a = (e.get("attributes") or {}).get("assist")
                if a in self.players:
                    row(a)["assists"] += 1
        for s in shots:
            if s["player"] not in self.players:
                continue
            r = row(s["player"])
            r["shots"] += 1
            r["xg"] += float(s.get("_xg", 0.0))
            key = next((p for p in reversed(passes) if p["team"] == s["team"] and p["receiver"] == s["player"] and 0 < s["_ms"] - p["_ms"] <= KEY_PASS_MS), None)
            if key is not None and key["player"] in self.players:
                kr = row(key["player"])
                kr["keyPasses"] += 1
                kr["xa"] += float(s.get("_xg", 0.0))
        vals = self.valuer.player_totals(self.action_values()) if self.valuer.ready else {}
        lb = self.line_breaks()["players"]
        runs = self.runs()["players"]
        for pid, r in rows.items():
            load = self.ip.loads.get(pid, {})
            r["minutes"] = load.get("minutes")
            r["value"] = vals.get(pid, {}).get("value")
            r["valueAttacking"] = vals.get(pid, {}).get("attacking")
            r["valueDefending"] = vals.get(pid, {}).get("defending")
            r["packing"] = lb.get(pid, {}).get("packing", 0)
            r["lineBreaks"] = lb.get(pid, {}).get("lineBreaks", 0)
            r["runs"] = runs.get(pid, {})
            r["km"], r["hsrM"], r["sprintM"] = load.get("km"), load.get("hsrM"), load.get("sprintM")
            r["xg"], r["xa"] = round(r["xg"], 2), round(r["xa"], 2)
            r["impact"] = round((r["value"] or 0.0) + 0.25 * r["goals"] + 0.12 * r["assists"], 3)
        return sorted(rows.values(), key=lambda r: -r["impact"])

    def player_of_the_match(self, table: list[dict] | None = None) -> dict | None:
        table = table if table is not None else self.players_table()
        outfield = [r for r in table if r["pos"] != "GK"]
        return outfield[0] if outfield else None

    # ----- everything ---------------------------------------------------------------------------------------------------------------------------

    def summary(self) -> dict:
        table = self.players_table()
        return jsonable({
            "version": 1,
            "clubs": self.clubs,
            "winProbability": self.win_probability(),
            "shots": self.shots(),
            "possessionValue": self.possession_value(),
            "networks": self.networks(),
            "shapes": self.shapes(),
            "space": self.space(),
            "lineBreaks": self.line_breaks(),
            "runs": self.runs(),
            "load": self.load(),
            "setPieces": self.set_pieces(),
            "transitions": self.transitions(),
            "goalkeepers": self.goalkeepers(),
            "pressing": self.pressing(),
            "players": table,
            "playerOfTheMatch": self.player_of_the_match(table),
            "pitch": {"length": G.PITCH_L, "width": G.PITCH_W},
        })
