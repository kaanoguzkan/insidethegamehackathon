import asyncio
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from matchmind.core.paths import replays_dir
from matchmind.intel.pipeline import interpret_match
from matchmind.mcp_server.registry import MatchRegistry, UnknownMatch
from matchmind.mcp_server.server import build_server, ms_at


@pytest.fixture(scope="module")
def registry(match):
    ip, _ = interpret_match(match)
    reg = MatchRegistry()
    reg.register("t0001", ip)
    return reg


def call(registry, tool, args=None):
    async def go():
        server = build_server(registry)
        async with connect(server._mcp_server) as client:
            res = await client.call_tool(tool, args or {})
            return res

    return asyncio.run(go())


def data(res):
    assert not res.isError, res.content
    if res.structuredContent is not None:
        return res.structuredContent.get("result", res.structuredContent)
    return json.loads(res.content[0].text)


def test_server_advertises_the_planned_tools(registry):
    async def go():
        async with connect(build_server(registry)._mcp_server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    names = asyncio.run(go())
    assert {"get_match_state", "get_window_stats", "compare_windows", "get_event_chain", "get_player_window", "get_season_context", "list_moments", "explain_metric", "list_matches"} <= names


def test_match_state_has_score_and_indices(registry, match):
    d = data(call(registry, "get_match_state", {"match_id": "t0001"}))
    assert d["score"] == match.meta["score"]
    assert 0 <= d["chaosIndex"] <= 100 and set(d["momentum"]) == {"HAR", "NOR"}


def test_state_at_an_earlier_minute_shows_the_score_then(registry):
    d = data(call(registry, "get_match_state", {"match_id": "t0001", "minute": 1}))
    assert sum(d["score"].values()) == 0


def test_window_stats_are_windowed(registry):
    a = data(call(registry, "get_window_stats", {"match_id": "t0001", "team": "HAR", "from_minute": 10, "to_minute": 20}))
    b = data(call(registry, "get_window_stats", {"match_id": "t0001", "team": "HAR", "from_minute": 10, "to_minute": 40}))
    assert a["stats"]["passes"] < b["stats"]["passes"] and a["minutes"] == 10.0


def test_compare_windows_precomputes_the_delta(registry):
    d = data(call(registry, "compare_windows", {"match_id": "t0001", "team": "HAR", "metric": "passes", "before_from": 5, "before_to": 15, "after_from": 20, "after_to": 30}))
    assert d["delta"] == pytest.approx(d["after"] - d["before"])


def test_event_chain_returns_ordered_neighbours(registry, match):
    shot = next(e for e in match.events if e["type"] == "shot")
    chain = data(call(registry, "get_event_chain", {"match_id": "t0001", "event_id": shot["id"], "before": 2, "after": 2}))
    assert shot["id"] in [e["id"] for e in chain] and 3 <= len(chain) <= 5


def test_player_window_counts_actions(registry, match):
    pid = match.meta["home"]["lineup"][5]
    d = data(call(registry, "get_player_window", {"match_id": "t0001", "player_id": pid, "from_minute": 0, "to_minute": 90}))
    assert d["player"] == pid and d["actions"]["pass"] > 0


def test_moments_and_glossary(registry):
    ms = data(call(registry, "list_moments", {"match_id": "t0001", "min_salience": 0.5}))
    assert all(m["salience"] >= 0.5 for m in ms)
    d = data(call(registry, "explain_metric", {"name": "NOR.ppda"}))
    assert "pressing" in d["definition"]


def test_season_context_rejects_entities_it_does_not_know(registry):
    d = data(call(registry, "get_season_context", {"entity_id": "NOBODY-99"}))
    assert d["available"] is False and "unknown" in d["reason"]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_match_state", {"match_id": "nope"}),
        ("get_window_stats", {"match_id": "t0001", "team": "XXX", "from_minute": 0, "to_minute": 5}),
        ("get_window_stats", {"match_id": "t0001", "team": "HAR", "from_minute": 20, "to_minute": 10}),
        ("get_window_stats", {"match_id": "t0001", "team": "HAR", "from_minute": -5, "to_minute": 10}),
        ("compare_windows", {"match_id": "t0001", "team": "HAR", "metric": "bogus", "before_from": 0, "before_to": 5, "after_from": 5, "after_to": 10}),
        ("get_event_chain", {"match_id": "t0001", "event_id": "nope"}),
        ("get_player_window", {"match_id": "t0001", "player_id": "ZZZ-99", "from_minute": 0, "to_minute": 5}),
        ("explain_metric", {"name": "made_up"}),
    ],
)
def test_bad_input_is_a_tool_error_not_a_crash(registry, tool, args):
    assert call(registry, tool, args).isError


def test_second_half_minutes_map_past_the_first_halfs_stoppage(registry):
    ip = registry.get("t0001")
    assert ms_at(ip, 30) == 30 * 60000
    assert ms_at(ip, 60) == ip.p2_start_ms + 15 * 60000


def test_registry_loads_a_committed_replay_by_re_simulating_its_scenario():
    reg = MatchRegistry()
    assert "pressing-collapse" in reg.ids()
    ip = reg.get("pressing-collapse")
    committed = json.loads((replays_dir() / "pressing-collapse" / "meta.json").read_text())["score"]
    assert sum(1 for e in ip.events if e["type"] == "goal") == sum(committed.values()), "the re-simulation is the committed match"
    with pytest.raises(UnknownMatch):
        reg.get("does-not-exist")


@pytest.mark.parametrize("bad", ["../etc/passwd", "..", "../../data/league", "a/b", "/etc", "PRESSING", "pressing-collapse/../x", "", "x" * 200, "pressing-collapse\x00"])
def test_match_ids_cannot_escape_the_replay_directory(bad):
    reg = MatchRegistry()
    with pytest.raises(UnknownMatch):
        reg.get(bad)


def test_only_listed_matches_load_and_slugs_alone_are_not_enough():
    reg = MatchRegistry()
    with pytest.raises(UnknownMatch):
        reg.get("valid-slug-but-not-listed")


def test_live_registration_rejects_unsafe_ids(match):
    ip, _ = interpret_match(match)
    with pytest.raises(ValueError):
        MatchRegistry().register("../x", ip)


def test_the_cache_is_bounded_and_evicts_the_least_recently_used(monkeypatch, match):
    ip, _ = interpret_match(match)
    reg = MatchRegistry(max_cached=2)
    monkeypatch.setattr(reg, "_disk_ids", lambda: ["a", "b", "c"])
    loads = []
    monkeypatch.setattr(reg, "_load", lambda mid: loads.append(mid) or ip)
    for mid in ("a", "b", "a", "c"):
        reg.get(mid)
    assert list(reg._cache) == ["a", "c"]  # b was least recently used
    reg.get("b")
    assert loads == ["a", "b", "c", "b"]


def test_concurrent_requests_load_a_match_once(monkeypatch, match):
    import threading
    import time

    ip, _ = interpret_match(match)
    reg = MatchRegistry()
    monkeypatch.setattr(reg, "_disk_ids", lambda: ["slow"])
    calls = []

    def slow_load(mid):
        calls.append(mid)
        time.sleep(0.2)
        return ip

    monkeypatch.setattr(reg, "_load", slow_load)
    threads = [threading.Thread(target=lambda: reg.get("slow")) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert calls == ["slow"]


def test_preload_loads_every_listed_match_off_the_event_loop_and_survives_a_bad_one():
    import asyncio
    import threading

    from matchmind.mcp_server.registry import preload

    seen: list[tuple[str, bool]] = []

    class Stub:
        def ids(self):
            return ["a", "bad", "c"]

        def get(self, match_id):
            seen.append((match_id, threading.current_thread() is threading.main_thread()))
            if match_id == "bad":
                raise RuntimeError("cannot load")

    loaded = asyncio.run(preload(Stub(), delay_s=0))
    assert loaded == ["a", "c"] and [m for m, _ in seen] == ["a", "bad", "c"]
    assert not any(on_main for _, on_main in seen), "the loads ran in worker threads, not on the event loop's thread"
