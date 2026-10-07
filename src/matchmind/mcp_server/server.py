"""The Match Data MCP server.

Agents get facts about a match through these tools instead of reading a database, so the data
layer can change (local simulation, Cosmos DB, a real provider) without touching a prompt. The
same server is used by the Explainer (through Agent Framework's ``MCPStreamableHTTPTool``), by the
hosted recap agent in Foundry, and by GitHub Copilot in VS Code for ad-hoc questions such as
"who controlled the last 15 minutes?".

Times are *display minutes* (second half restarts at 45). Every tool validates its inputs and
returns small, rounded JSON.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..analytics.report import MatchAnalytics, jsonable
from ..analytics.season import context_for, load_season, radars
from ..intel.evidence import GLOSSARY, change
from ..intel.interpreter import Interpreter
from .registry import MatchRegistry

INSTRUCTIONS = (
    "Facts about a synthetic football match: score, rolling indices, window statistics, event chains, "
    "key moments and Opta-style analytics (win probability, possession value, pitch control, passing "
    "networks, measured formations, line-breaking passes, off-ball runs, physical load, set pieces, "
    "transitions, goalkeepers, season context and predictions). Times are display minutes. All data is "
    "synthetic and the clubs are fictional."
)

WINDOW_FIELDS = (
    "passes", "pass_acc", "possession_share", "tempo", "ppda", "pressures_per_min", "high_regains",
    "progressive_passes", "final_third_entries", "field_tilt", "shots", "xg", "big_chances", "goals",
    "xt", "sprints", "front_sprints", "tackles", "interceptions", "fouls",
)  # fmt: skip
PLAYER_EVENTS = ("pass", "carry", "dribble", "shot", "tackle", "interception", "pressure", "sprint", "foul", "goal")


def ms_at(ip: Interpreter, minute: float) -> int:
    """Display minute -> match clock milliseconds."""
    if minute < 0 or minute > 130:
        raise ValueError("minute must be between 0 and 130")
    if ip.p2_start_ms is None or minute <= 45:
        return int(minute * 60000)
    return int(ip.p2_start_ms + (minute - 45) * 60000)


def _team(ip: Interpreter, team: str) -> str:
    if team not in ip.clubs:
        raise ValueError(f"team must be one of {ip.clubs}")
    return team


def _an(ip: Interpreter) -> MatchAnalytics:
    """The analytics for a match, built once per interpreter."""
    if getattr(ip, "_analytics", None) is None:
        ip._analytics = MatchAnalytics(ip)
    return ip._analytics


def _round(v: Any) -> Any:
    return round(v, 2) if isinstance(v, float) else v


def transport_security() -> TransportSecuritySettings | None:
    """DNS-rebinding protection that also accepts the service's own public name.

    The MCP library only accepts requests addressed to localhost unless told otherwise, which turns away every
    request through a public ingress (421). ``MATCHMIND_ALLOWED_HOSTS`` lists the host names the service answers to
    (comma separated, no scheme) and ``MATCHMIND_ALLOWED_ORIGINS`` the browser origins; localhost stays allowed.
    Unset, the library's localhost-only default applies.
    """
    split = lambda v: [x.strip() for x in v.split(",") if x.strip()]  # noqa: E731
    hosts = split(os.environ.get("MATCHMIND_ALLOWED_HOSTS", ""))
    if not hosts:
        return None
    origins = split(os.environ.get("MATCHMIND_ALLOWED_ORIGINS", ""))
    local = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*hosts, *local],
        allowed_origins=[*(f"https://{h}" for h in hosts), *origins, *(f"http://{h}" for h in local)],
    )


def build_server(registry: MatchRegistry | None = None, path: str = "/mcp") -> FastMCP:
    reg = registry or MatchRegistry()
    mcp = FastMCP(
        "matchmind-match-data", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
        streamable_http_path=path, transport_security=transport_security(),
    )

    @mcp.tool()
    def list_matches() -> list[str]:
        """Ids of the matches that can be queried."""
        return reg.ids()

    @mcp.tool()
    def get_match_state(match_id: str, minute: float | None = None) -> dict:
        """Score and the latest rolling indices (momentum, chaos, pressure, possession) at a minute (default: full time)."""
        ip = reg.get(match_id)
        ms = ms_at(ip, minute) if minute is not None else 10**9
        snaps = [s for s in ip.history if s["matchMs"] <= ms]
        score = {c: sum(1 for e in ip.events if e["type"] == "goal" and e["team"] == c and e["_ms"] <= ms) for c in ip.clubs}
        out: dict = {"matchId": match_id, "score": score, "teams": ip.club_names}
        if snaps:
            s = snaps[-1]
            out["asOf"] = s["clock"]
            out["momentum"] = s["momentum"]
            out["chaosIndex"] = s["chaos"]
            out["controller"] = s["control"]["controller"]
            out["pressureIndex"] = s["pressure"]
            out["possession"] = s["possession"]
        return out

    @mcp.tool()
    def get_window_stats(match_id: str, team: str, from_minute: float, to_minute: float) -> dict:
        """A team's statistics over a window of display minutes, plus match-level rhythm figures."""
        ip = reg.get(match_id)
        _team(ip, team)
        t0, t1 = ms_at(ip, from_minute), ms_at(ip, to_minute)
        if t1 <= t0:
            raise ValueError("to_minute must be after from_minute")
        w = ip.window(t0, t1)
        return {
            "team": team, "from": from_minute, "to": to_minute, "minutes": round(w["minutes"], 1),
            "stats": {k: _round(w[team][k]) for k in WINDOW_FIELDS if k in w[team]},
            "match": {k: _round(v) for k, v in w["match"].items()},
        }

    @mcp.tool()
    def compare_windows(match_id: str, team: str, metric: str, before_from: float, before_to: float, after_from: float, after_to: float) -> dict:
        """Before/after for one metric over two windows, with delta and percentage change precomputed."""
        ip = reg.get(match_id)
        _team(ip, team)
        if metric not in WINDOW_FIELDS:
            raise ValueError(f"metric must be one of {list(WINDOW_FIELDS)}")
        a = ip.window(ms_at(ip, before_from), ms_at(ip, before_to))
        b = ip.window(ms_at(ip, after_from), ms_at(ip, after_to))
        return {"team": team, "metric": metric, **change(a[team].get(metric), b[team].get(metric), 2)}

    @mcp.tool()
    def get_event_chain(match_id: str, event_id: str, before: int = 3, after: int = 3) -> list[dict]:
        """Events around one event, in order, for evidence chains."""
        ip = reg.get(match_id)
        if event_id not in ip.by_id:
            raise ValueError(f"unknown event {event_id!r}")
        before, after = max(0, min(before, 10)), max(0, min(after, 10))
        evs = [e for e in ip.events if e["type"] not in ("team_shape", "distance_milestone", "possession_change", "space_control", "shape_profile", "player_load", "phase_change")]
        i = next(k for k, e in enumerate(evs) if e["id"] == event_id) if any(e["id"] == event_id for e in evs) else None
        if i is None:
            return [_slim(ip.by_id[event_id])]
        return [_slim(e) for e in evs[max(0, i - before) : i + after + 1]]

    @mcp.tool()
    def get_player_window(match_id: str, player_id: str, from_minute: float, to_minute: float) -> dict:
        """Counts of a player's actions over a window of display minutes."""
        ip = reg.get(match_id)
        if player_id not in ip.players:
            raise ValueError(f"unknown player {player_id!r}")
        t0, t1 = ms_at(ip, from_minute), ms_at(ip, to_minute)
        counts = {k: 0 for k in PLAYER_EVENTS}
        for e in ip.events:
            if t0 <= e["_ms"] <= t1 and e.get("player") == player_id and e["type"] in counts:
                counts[e["type"]] += 1
        p = ip.players[player_id]
        return {"player": player_id, "name": p["name"], "team": p["team"], "position": p["pos"], "from": from_minute, "to": to_minute, "actions": counts}

    @mcp.tool()
    def get_season_context(entity_id: str) -> dict:
        """Season context for a club (table position, form, runs, strengths) or a player (season totals), plus the league records."""
        season = load_season()
        if not season:
            return {"entity": entity_id, "available": False, "reason": "season history has not been generated (matchmind build-season)"}
        clubs = season["clubs"]
        ctx = context_for(season, *(clubs[:2]))
        if entity_id in clubs:
            row = next(r for r in ctx["standings"] if r["club"] == entity_id)
            other = next(c for c in clubs if c != entity_id)
            c2 = context_for(season, entity_id, other)
            return {"entity": entity_id, "available": True, "kind": "club", "table": row, "form": c2["form"][entity_id], "streaks": c2["streaks"][entity_id],
                    "rating": c2["ratings"][entity_id], "season": ctx["season"], "roundsPlayed": ctx["played"]}
        if entity_id in ctx["players"]:
            return {"entity": entity_id, "available": True, "kind": "player", "season": ctx["season"], "totals": ctx["players"][entity_id], "topScorers": ctx["topScorers"]}
        return {"entity": entity_id, "available": False, "reason": f"unknown club or player; clubs are {clubs}"}

    @mcp.tool()
    def get_prediction(match_id: str) -> dict:
        """The pre-match model: win/draw/loss probabilities, expected goals, likeliest scores, and the table and form behind them."""
        ip = reg.get(match_id)
        s = ip.season
        if not s:
            return {"available": False, "reason": "no season context for this match"}
        return {"available": True, "prediction": s["prediction"], "table": [r for r in s["standings"] if r["club"] in ip.clubs], "form": s["form"],
                "headToHead": s["headToHead"], "ratings": {c: s["ratings"][c] for c in ip.clubs}}

    @mcp.tool()
    def get_win_probability(match_id: str, minute: float | None = None) -> dict:
        """Win/draw/loss probabilities at a minute (default: full time) and how each goal or red card moved them."""
        ip = reg.get(match_id)
        wp = _an(ip).win_probability()
        ms = ms_at(ip, minute) if minute is not None else 10**9
        at = [p for p in wp["series"] if p["matchMs"] <= ms and p["tag"] == "tick"]
        return {"clubs": {"home": ip.clubs[0], "away": ip.clubs[1]}, "preMatch": wp["preMatch"], "at": at[-1]["p"] if at else None,
                "swings": [{**x, "label": ip.minute_label(x["matchMs"])} for x in wp["swings"]], "model": wp["model"]}

    @mcp.tool()
    def get_key_actions(match_id: str, top: int = 6) -> dict:
        """The most valuable actions of the match and the players ranked by possession value (the VAEP / OBV idea)."""
        ip = reg.get(match_id)
        an = _an(ip)
        pv = an.possession_value(top=max(1, min(top, 15)))
        if not pv.get("available"):
            return {"available": False, "reason": "possession-value model not fitted (matchmind fit-models)"}
        table = an.players_table()
        return {"available": True, "bestActions": [{**a, "label": ip.minute_label(a["ms"])} for a in pv["best"]],
                "players": [{k: r[k] for k in ("id", "name", "team", "pos", "value", "impact", "goals", "assists")} for r in table[: max(1, min(top, 15))]]}

    @mcp.tool()
    def get_space_control(match_id: str, team: str, from_minute: float, to_minute: float) -> dict:
        """Pitch control from tracking: the share of the pitch and of the final third a team could reach first, and the space the opposition controls behind its defensive line."""
        ip = reg.get(match_id)
        _team(ip, team)
        t0, t1 = ms_at(ip, from_minute), ms_at(ip, to_minute)
        rows = [p for p in _an(ip).space()["series"][team] if t0 < p["ms"] <= t1]
        if not rows:
            return {"team": team, "available": False}
        behind = [p["behind"] for p in rows if p["behind"] is not None]
        return {"team": team, "available": True, "controlShare": round(sum(p["control"] for p in rows) / len(rows), 3),
                "finalThirdControl": round(sum(p["finalThird"] for p in rows) / len(rows), 3),
                "spaceBehindLineM2": round(sum(behind) / len(behind)) if behind else None, "windows": len(rows)}

    @mcp.tool()
    def get_passing_network(match_id: str, team: str, half: str = "full", top: int = 8) -> dict:
        """Who passes to whom: players at their average pass position and the strongest links. half is 'full', '1' or '2'."""
        ip = reg.get(match_id)
        _team(ip, team)
        key = {"full": "full", "1": "h1", "2": "h2"}.get(half)
        if key is None:
            raise ValueError("half must be 'full', '1' or '2'")
        net = _an(ip).networks()[team][key]
        return {**net, "edges": net["edges"][: max(1, min(top, 30))]}

    @mcp.tool()
    def get_team_shape(match_id: str, team: str) -> dict:
        """The formation as designed and as measured from tracking, out of possession and in possession, and how it changed by 15-minute block."""
        ip = reg.get(match_id)
        _team(ip, team)
        sh = _an(ip).shapes()[team]
        return {"team": team, "nominal": sh["nominal"], "designed": sh["designed"],
                "defending": sh["def"]["measured"], "inPossession": sh["ip"]["measured"], "byBlock": sh["blocks"]}

    @mcp.tool()
    def get_phases_of_play(match_id: str, team: str) -> dict:
        """How long the team spent in each phase of play (build-up, settled attack, press, mid block, low block), what set each press off, and the shape measured in each (line height, length, width), beside the shapes as designed."""
        ip = reg.get(match_id)
        _team(ip, team)
        ph = _an(ip).phases()[team]
        side = ip.meta["home" if team == ip.meta["home"]["id"] else "away"]
        tags = {k: side["style"].get(k) for k in ("press_scheme", "on_loss", "on_win", "pivot", "fullbacks", "striker")}
        return {"team": team, "designed": side.get("shapes"), "tags": tags, "share": ph["share"], "entries": ph["entries"],
                "causes": ph["causes"], "measured": ph["measured"]}

    @mcp.tool()
    def get_line_breaks(match_id: str, top: int = 5) -> dict:
        """Packing (opponents bypassed by completed passes) and line-breaking passes per team, with the best passes."""
        ip = reg.get(match_id)
        lb = _an(ip).line_breaks(top=max(1, min(top, 15)))
        return {"teams": lb["teams"], "best": [{**b, "label": ip.minute_label(b["ms"])} for b in lb["best"]]}

    @mcp.tool()
    def get_off_ball_runs(match_id: str, team: str | None = None, kind: str | None = None, min_distance: float = 0.0) -> dict:
        """Off-ball runs detected from tracking (in_behind, overlap, drop), with whether the ball was played to the runner."""
        ip = reg.get(match_id)
        if team is not None:
            _team(ip, team)
        if kind is not None and kind not in ("in_behind", "overlap", "drop"):
            raise ValueError("kind must be in_behind, overlap or drop")
        runs = _an(ip).runs()
        sel = [r for r in runs["runs"] if (team is None or r["team"] == team) and (kind is None or r["kind"] == kind) and r["distanceM"] >= min_distance]
        return {"counts": runs["teams"], "runs": [{**r, "label": ip.minute_label(r["startMs"])} for r in sel[:40]], "total": len(sel)}

    @mcp.tool()
    def get_physical_load(match_id: str, player_id: str | None = None, top: int = 5) -> dict:
        """Distance, high-speed running, sprint distance and accelerations from tracking, with a fatigue index (late vs early high-speed running)."""
        ip = reg.get(match_id)
        ld = _an(ip).load()
        if player_id is not None:
            if player_id not in ld["players"]:
                raise ValueError(f"no load data for {player_id!r}")
            return {"player": player_id, **ld["players"][player_id]}
        return {"top": ld["top"][: max(1, min(top, 15))]}

    @mcp.tool()
    def get_transitions(match_id: str) -> dict:
        """Counter-pressing (regaining the ball within five seconds), high turnovers, quick entries and fast breaks per team."""
        ip = reg.get(match_id)
        return {c: {k: v for k, v in t.items() if k != "fastBreakList"} | {"fastBreakList": t["fastBreakList"][:5]} for c, t in _an(ip).transitions().items()}

    @mcp.tool()
    def get_set_piece_report(match_id: str) -> dict:
        """What each routine produced (corners, free kicks, long throws, goal kicks) and what each defence conceded."""
        return _an(reg.get(match_id)).set_pieces()

    @mcp.tool()
    def get_shot_map(match_id: str, team: str | None = None, min_xg: float = 0.0) -> dict:
        """Shots with xG and post-shot xG, and per-team totals."""
        ip = reg.get(match_id)
        if team is not None:
            _team(ip, team)
        sh = _an(ip).shots()
        return {"teams": sh["teams"], "shots": [{**s, "label": ip.minute_label(s["ms"])} for s in sh["shots"] if (team is None or s["team"] == team) and s["xg"] >= min_xg]}

    @mcp.tool()
    def get_goalkeeper_report(match_id: str) -> dict:
        """Shot-stopping against post-shot xG (goals prevented), claims, sweeping and distribution for each keeper."""
        return _an(reg.get(match_id)).goalkeepers()

    @mcp.tool()
    def get_pressing_report(match_id: str) -> dict:
        """Where each team presses (high, middle, low) and what triggers it (a back pass, a bad pass)."""
        return _an(reg.get(match_id)).pressing()

    @mcp.tool()
    def get_player_profile(match_id: str, player_id: str) -> dict:
        """A player's numbers in this match, a radar (percentiles among positional peers over the history) and the three players he most resembles."""
        ip = reg.get(match_id)
        if player_id not in ip.players:
            raise ValueError(f"unknown player {player_id!r}")
        row = next((r for r in _an(ip).players_table() if r["id"] == player_id), None)
        if row is None:
            return {"player": player_id, "available": False, "reason": "the player has no recorded actions"}
        return jsonable({"player": row, "radar": radars(load_season(), [row]).get(player_id)})

    @mcp.tool()
    def list_moments(match_id: str, since_minute: float = 0.0, min_salience: float = 0.0) -> list[dict]:
        """Key moments the interpreter detected, with their type, time and salience."""
        ip = reg.get(match_id)
        t0 = ms_at(ip, since_minute)
        return [
            {"id": m["id"], "type": m["type"], "label": m["detectedAt"]["label"], "salience": m["salience"],
             "team": m["subjectTeam"], "beneficiary": m["beneficiaryTeam"]}
            for m in ip.all_moments if m["detectedAt"]["matchMs"] >= t0 and m["salience"] >= min_salience
        ]  # fmt: skip

    @mcp.tool()
    def explain_metric(name: str) -> dict:
        """Plain-language definition of a metric used in evidence packs."""
        base = name.split(".")[-1]
        if base not in GLOSSARY:
            raise ValueError(f"unknown metric {name!r}; known: {sorted(GLOSSARY)}")
        return {"metric": base, "definition": GLOSSARY[base]}

    return mcp


def _slim(e: dict) -> dict:
    out = {k: e[k] for k in ("id", "type", "team", "player", "outcome") if k in e}
    out["clock"] = f"{e['clock']['minute']}:{e['clock']['second']:02d}"
    if "location" in e:
        out["at"] = e["location"]
    return out
