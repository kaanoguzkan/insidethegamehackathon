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

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..intel.evidence import GLOSSARY, change
from ..intel.interpreter import Interpreter
from .registry import MatchRegistry

INSTRUCTIONS = (
    "Facts about a synthetic football match: score, rolling indices, window statistics, event chains "
    "and key moments. Times are display minutes. All data is synthetic and the clubs are fictional."
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


def _round(v: Any) -> Any:
    return round(v, 2) if isinstance(v, float) else v


def build_server(registry: MatchRegistry | None = None, path: str = "/mcp") -> FastMCP:
    reg = registry or MatchRegistry()
    mcp = FastMCP(
        "matchmind-match-data", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
        streamable_http_path=path,
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
        evs = [e for e in ip.events if e["type"] not in ("team_shape", "distance_milestone", "possession_change")]
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
        """Season totals for a player or club. Season history is not built yet, so this says so."""
        return {"entity": entity_id, "available": False, "reason": "season history has not been generated for this league"}

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
