"""The analytics tools of the Match Data MCP server, called through a real MCP client session."""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from matchmind.analytics import load_models
from matchmind.analytics.season import context_for, load_season
from matchmind.core.paths import league_dir
from matchmind.intel.baselines import load_baselines
from matchmind.intel.pipeline import interpret_match
from matchmind.intel.xt import XTGrid
from matchmind.mcp_server.registry import MatchRegistry
from matchmind.mcp_server.server import build_server


@pytest.fixture(scope="module")
def registry(match):
    ctx = context_for(load_season(), "HAR", "NOR")
    ip, _ = interpret_match(match, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"), season=ctx, models=load_models())
    reg = MatchRegistry()
    reg.register("t0001", ip)
    return reg


def call(registry, tool, args=None):
    async def go():
        async with connect(build_server(registry)._mcp_server) as client:
            return await client.call_tool(tool, args or {})

    return asyncio.run(go())


def data(res):
    assert not res.isError, res.content
    if res.structuredContent is not None:
        return res.structuredContent.get("result", res.structuredContent)
    return json.loads(res.content[0].text)


def test_the_server_advertises_the_analytics_tools(registry):
    async def go():
        async with connect(build_server(registry)._mcp_server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    names = asyncio.run(go())
    want = {
        "get_win_probability", "get_key_actions", "get_space_control", "get_passing_network", "get_team_shape", "get_line_breaks", "get_off_ball_runs",
        "get_physical_load", "get_transitions", "get_set_piece_report", "get_shot_map", "get_goalkeeper_report", "get_pressing_report",
        "get_player_profile", "get_prediction", "get_season_context",
    }
    assert want <= names and len(names) >= 24


def test_win_probability_at_a_minute_and_its_swings(registry, match):
    d = data(call(registry, "get_win_probability", {"match_id": "t0001", "minute": 60}))
    assert d["at"] and abs(sum(d["at"].values()) - 1) < 1e-3
    assert len(d["swings"]) == sum(match.meta["score"].values())
    pre = data(call(registry, "get_win_probability", {"match_id": "t0001", "minute": 0}))
    assert pre["at"] == pre["preMatch"]


def test_key_actions_rank_players_by_possession_value(registry):
    d = data(call(registry, "get_key_actions", {"match_id": "t0001", "top": 3}))
    assert d["available"] and len(d["bestActions"]) == 3 and len(d["players"]) == 3
    assert d["bestActions"][0]["value"] >= d["bestActions"][-1]["value"]
    assert d["players"][0]["impact"] >= d["players"][-1]["impact"]


def test_space_control_over_a_window(registry):
    d = data(call(registry, "get_space_control", {"match_id": "t0001", "team": "HAR", "from_minute": 10, "to_minute": 25}))
    assert d["available"] and 0 < d["controlShare"] < 1 and d["windows"] >= 25
    assert call(registry, "get_space_control", {"match_id": "t0001", "team": "XXX", "from_minute": 1, "to_minute": 5}).isError


def test_passing_network_halves_and_validation(registry):
    full = data(call(registry, "get_passing_network", {"match_id": "t0001", "team": "HAR"}))
    h1 = data(call(registry, "get_passing_network", {"match_id": "t0001", "team": "HAR", "half": "1"}))
    assert full["stats"]["completedPasses"] > h1["stats"]["completedPasses"] > 0
    assert call(registry, "get_passing_network", {"match_id": "t0001", "team": "HAR", "half": "3"}).isError


def test_team_shape_reports_designed_and_measured(registry):
    d = data(call(registry, "get_team_shape", {"match_id": "t0001", "team": "HAR"}))
    assert d["nominal"] == "4-3-3" and d["defending"]["label"] and d["inPossession"]["label"] and d["byBlock"]


def test_runs_filter_by_kind_and_distance(registry):
    all_runs = data(call(registry, "get_off_ball_runs", {"match_id": "t0001"}))
    long = data(call(registry, "get_off_ball_runs", {"match_id": "t0001", "kind": "in_behind", "min_distance": 20}))
    assert all_runs["total"] > long["total"] and all(r["kind"] == "in_behind" and r["distanceM"] >= 20 for r in long["runs"])
    assert call(registry, "get_off_ball_runs", {"match_id": "t0001", "kind": "sideways"}).isError


def test_load_line_breaks_transitions_and_friends(registry):
    ld = data(call(registry, "get_physical_load", {"match_id": "t0001", "top": 2}))
    assert len(ld["top"]) == 2 and ld["top"][0]["hsrM"] >= ld["top"][1]["hsrM"]
    one = data(call(registry, "get_physical_load", {"match_id": "t0001", "player_id": ld["top"][0]["id"]}))
    assert one["hsrM"] == ld["top"][0]["hsrM"]
    assert call(registry, "get_physical_load", {"match_id": "t0001", "player_id": "NOPE-1"}).isError
    lb = data(call(registry, "get_line_breaks", {"match_id": "t0001", "top": 3}))
    assert len(lb["best"]) == 3 and lb["best"][0]["bypassed"] >= lb["best"][-1]["bypassed"]
    tr = data(call(registry, "get_transitions", {"match_id": "t0001"}))
    assert set(tr) == {"HAR", "NOR"}
    assert "teams" in data(call(registry, "get_set_piece_report", {"match_id": "t0001"}))
    assert set(data(call(registry, "get_goalkeeper_report", {"match_id": "t0001"}))) == {"HAR", "NOR"}
    assert set(data(call(registry, "get_pressing_report", {"match_id": "t0001"}))) == {"HAR", "NOR"}


def test_shot_map_filters(registry):
    all_shots = data(call(registry, "get_shot_map", {"match_id": "t0001"}))
    big = data(call(registry, "get_shot_map", {"match_id": "t0001", "team": "HAR", "min_xg": 0.1}))
    assert len(big["shots"]) <= len(all_shots["shots"]) and all(s["team"] == "HAR" and s["xg"] >= 0.1 for s in big["shots"])


def test_player_profile_has_a_radar_and_peers(registry):
    key = data(call(registry, "get_key_actions", {"match_id": "t0001", "top": 1}))["players"][0]["id"]
    d = data(call(registry, "get_player_profile", {"match_id": "t0001", "player_id": key}))
    assert d["player"]["id"] == key and d["radar"] and len(d["radar"]["similar"]) == 3
    assert call(registry, "get_player_profile", {"match_id": "t0001", "player_id": "NOPE-1"}).isError


def test_season_context_and_prediction(registry):
    club = data(call(registry, "get_season_context", {"entity_id": "NOR"}))
    assert club["available"] and club["kind"] == "club" and club["table"]["played"] == 4 and len(club["form"]) <= 5
    pid = next(iter(load_season()["matches"][-1]["players"]))["id"]
    player = data(call(registry, "get_season_context", {"entity_id": pid}))
    assert player["available"] and player["kind"] == "player" and player["totals"]["matches"] >= 1
    assert not data(call(registry, "get_season_context", {"entity_id": "XYZ"}))["available"]
    pred = data(call(registry, "get_prediction", {"match_id": "t0001"}))
    assert pred["available"] and abs(pred["prediction"]["home"] + pred["prediction"]["draw"] + pred["prediction"]["away"] - 1) < 0.01
