"""The channel: tuning in joins the match on air or starts the next fixture from its pack, and the season endpoints around it."""

from __future__ import annotations

import time

import pytest
from apps.brain import main as brain
from apps.brain.main import create_app
from fastapi.testclient import TestClient

from matchmind.live import season as S
from matchmind.live.blobs import MemoryBlobs
from matchmind.live.channel import CHANNEL, STALE_MS, Channel
from matchmind.live.packs import write_pack
from matchmind.live.season_job import create_season
from matchmind.live.store import MemoryLiveStore, now_ms


@pytest.fixture(scope="module")
def packs(match):
    b = MemoryBlobs()
    write_pack(b, "s1/f01", match)
    write_pack(b, "s1/f02", match)  # two fixtures that happen to be the same simulated match
    return b


def seasons_with(done: tuple[str, ...] = ("f01", "f02")) -> S.MemorySeasonStore:
    st = S.MemorySeasonStore()
    create_season(st, "s1", 1, featured=True)
    st.set_current("s1")
    for fid in done:
        st.finish("s1", fid, {"RED": 1, "SAL": 2} if fid == "f01" else {"HAR": 0, "NOR": 0}, f"s1/{fid}")
    return st


def played_instantly(store, match_id, docs, **kw):  # noqa: ANN001, ANN201, ANN003
    """A stand-in for the playback loop that is over at once (the real one is tested in test_live.py)."""
    kw["on_tick"]()
    kw["on_tick"]()
    store.put_match(match_id, {**store.get_match(match_id), "status": "finished"})
    return len(docs)


def test_tuning_in_starts_the_first_fixture_and_everyone_after_joins_it(packs):
    store = MemoryLiveStore()
    started = []
    ch = Channel(store, seasons_with(), packs, MemoryBlobs(), spawn=lambda fn: started.append(fn))  # the player is not run: only started
    now = ch.tune()
    assert now["fixtureId"] == "f01" and now["round"] == 1 and now["matchId"].startswith("live-s1-f01-") and len(started) == 1
    info = store.get_match(now["matchId"])
    assert info["meta"]["matchId"] == now["matchId"] and info["physical"] == "chunks" and info["chunks"] > 1000 and info["scenario"] == "red-card-drama"
    assert ch.tune() == now and ch.tune(fixture_id="f01") == now and len(started) == 1  # a second visitor joins; nothing is started twice
    assert ch.on_air() == now and store.get_state(CHANNEL, "played") == ["f01"]


def test_when_the_match_is_over_or_its_player_is_gone_the_next_fixture_goes_on_air(packs):
    store = MemoryLiveStore()
    ch = Channel(store, seasons_with(), packs, MemoryBlobs(), spawn=lambda fn: fn(), play_fn=played_instantly)
    first = ch.tune()
    assert first["fixtureId"] == "f01" and ch.on_air() is None  # it finished at once
    second = ch.tune()
    assert second["fixtureId"] == "f02" and second["matchId"] != first["matchId"]
    third = ch.tune()  # both have been shown: the season starts over
    assert third["fixtureId"] == "f01"
    assert ch.aired("s1") == ["f01", "f02"]  # a fixture counts once it has been played to the end, and once
    # a player that stopped being heard from (the Brain scaled down mid-match) no longer holds the channel
    store.put_state(CHANNEL, "now", {**store.get_state(CHANNEL, "now"), "heartbeatMs": now_ms() - STALE_MS - 1})
    store.put_match(third["matchId"], {**store.get_match(third["matchId"]), "status": "live"})
    assert ch.on_air() is None


def test_asking_for_a_fixture_takes_the_match_on_air_off_and_the_old_player_stops(packs):
    store = MemoryLiveStore()
    stopped = []

    def play_until_switched(store, match_id, docs, **kw):  # noqa: ANN001, ANN201, ANN003
        for _ in range(5):
            try:
                time.sleep(0.01)
                kw["on_tick"]()
            except Exception as e:  # noqa: BLE001
                stopped.append(type(e).__name__)
                raise
        return 0

    started = []
    ch = Channel(store, seasons_with(), packs, MemoryBlobs(), spawn=lambda fn: started.append(fn), play_fn=play_until_switched)
    first = ch.tune()
    second = ch.tune(fixture_id="f02")
    assert second["fixtureId"] == "f02" and second["matchId"] != first["matchId"] and ch.on_air()["matchId"] == second["matchId"]
    import matchmind.live.channel as C

    monkeypatch_beat = C.HEARTBEAT_EVERY_S
    C.HEARTBEAT_EVERY_S = 0.0
    try:
        started[0]()  # the first match's player runs now and finds that the channel has moved on
    finally:
        C.HEARTBEAT_EVERY_S = monkeypatch_beat
    assert stopped == ["Switched"] and store.get_match(first["matchId"])["status"] == "finished" and store.get_match(first["matchId"])["abandoned"]
    assert ch.tune(fixture_id="f09") is None  # a fixture that has not been simulated cannot be shown
    skipped = ch.tune(skip=True)  # the next fixture, replacing the one on air
    assert skipped["matchId"] != second["matchId"] and ch.on_air()["matchId"] == skipped["matchId"]


def test_there_is_nothing_to_tune_to_before_a_season_has_been_simulated(packs):
    store = MemoryLiveStore()
    empty = S.MemorySeasonStore()
    assert Channel(store, empty, packs, MemoryBlobs(), spawn=lambda fn: fn()).tune() is None  # no season at all
    assert Channel(store, seasons_with(()), packs, MemoryBlobs(), spawn=lambda fn: fn()).tune() is None  # planned, nothing simulated yet


@pytest.fixture()
def client(packs):
    st = seasons_with()
    with TestClient(create_app(live_store=MemoryLiveStore(), season_store=st, live_packs=packs, live_frames=MemoryBlobs())) as c:
        yield c, st


def test_the_channel_endpoints_start_a_real_match_from_a_pack_and_serve_it(client):
    c, _ = client
    assert c.get("/api/channel").json()["now"] is None
    r = c.post("/api/channel/tune", json={"speed": 20})
    assert r.status_code == 200
    now = r.json()
    assert c.post("/api/channel/tune", json={}).json()["matchId"] == now["matchId"]
    on = c.get("/api/channel").json()
    assert on["seasonId"] == "s1" and on["now"]["match"]["status"] in ("scheduled", "live") and on["now"]["match"]["home"]["short"]
    assert c.post("/api/channel/tune", json={"speed": 7}).status_code == 422 and c.post("/api/channel/tune", json={"fixtureId": "x"}).status_code == 422
    deadline = time.time() + 10
    while time.time() < deadline:  # at 20x the first chunk is due after a quarter of a second
        if c.get(f"/api/live/{now['matchId']}/chunks/0").status_code == 200:
            break
        time.sleep(0.2)
    assert c.get(f"/api/live/{now['matchId']}/chunks/0").status_code == 200
    feed = c.get(f"/api/live/{now['matchId']}/feed").json()
    assert feed["matchId"] == now["matchId"] and feed["status"] == "live" and feed["speed"] == 20.0


def test_the_season_endpoint_gives_fixtures_standings_and_progress(client):
    c, _ = client
    s = c.get("/api/season").json()
    assert s["seasonId"] == "s1" and s["total"] == 30 and s["done"] == 2 and len(s["fixtures"]) == 30
    assert s["fixtures"][0] == {"id": "f01", "round": 1, "home": "RED", "away": "SAL", "scenario": "red-card-drama", "status": "done", "score": {"RED": 1, "SAL": 2}}
    top = s["standings"][0]
    assert top["club"] == "SAL" and top["points"] == 3 and top["name"] == "Saltmarsh Town" and len(s["standings"]) == 6
    assert s["clubs"]["RED"]["primary"].startswith("#")
    assert s["aired"] == [] and all(r["played"] == 0 for r in s["standingsAired"])  # nothing has been on air yet: the table as broadcast is empty


def test_simulating_a_new_season_makes_it_current_and_only_one_at_a_time(monkeypatch, packs):
    def instant_worker(season_id, store, packs_, worker=None, **kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        return 0  # the fixtures stay pending: a season that is still being simulated

    monkeypatch.setattr(brain, "run_worker", instant_worker)
    st = seasons_with()
    st._seasons["s1"]["createdMs"] = 0  # the existing season is long finished with
    with TestClient(create_app(live_store=MemoryLiveStore(), season_store=st, live_packs=packs)) as c:
        r = c.post("/api/season/simulate")
        assert r.status_code == 200
        sid = r.json()["seasonId"]
        assert sid.startswith("season-") and st.current() == sid and c.get("/api/season").json()["seasonId"] == sid
        assert c.get("/api/season").json()["done"] == 0 and len(st.fixtures(sid)) == 30
        again = c.post("/api/season/simulate")
        assert again.status_code == 409 and again.json()["detail"]["seasonId"] == sid
        assert c.post("/api/channel/tune", json={}).status_code == 503  # nothing of the new season is simulated yet


def test_a_brain_without_a_season_job_refuses_to_simulate(packs):
    with TestClient(create_app()) as c:
        assert c.post("/api/season/simulate").status_code == 503
