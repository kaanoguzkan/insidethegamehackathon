"""The Brain's live endpoints: what a viewer polls, what the dispatcher calls, and how a live match is started."""

from __future__ import annotations

import pytest
from apps.brain import main as brain
from apps.brain.main import create_app
from fastapi.testclient import TestClient

from matchmind.live import feed, pipeline
from matchmind.live.store import MemoryLiveStore, now_ms


@pytest.fixture(scope="module")
def prepared(match):
    """A match whose feed has fully arrived and been interpreted, the way the Functions would have left it."""
    docs = feed.build_feed(match)
    store = MemoryLiveStore()
    mid = match.meta["matchId"]
    feed.start_match(store, mid, match.meta, docs, scenario="red-card-drama", speed=5.0)
    store.add_docs(mid, docs)
    store.put_match(mid, {**store.get_match(mid), "status": "live", "wallStartMs": now_ms() - 600_000})
    out = pipeline.interpret(store, mid)
    return store, mid, out["newMoments"]


@pytest.fixture()
def client(prepared):
    with TestClient(create_app(live_store=prepared[0])) as c:
        yield c


def test_the_list_and_the_match_say_who_plays_and_where_the_clock_stands(client, prepared):
    _, mid, _ = prepared
    rows = client.get("/api/live").json()
    assert [r["matchId"] for r in rows] == [mid] and "players" not in rows[0]
    one = client.get(f"/api/live/{mid}").json()
    assert one["status"] == "live" and one["home"]["short"] and one["away"]["name"] and one["players"]
    assert 2_900_000 <= one["clockMs"] <= 3_100_000  # ten wall minutes at 5x from kick-off: about minute 50 of the match
    assert client.get("/api/live/nope").status_code == 404


def test_the_feed_gives_what_is_new_and_nothing_twice(client, prepared):
    _, mid, new = prepared
    events, cursor, pages = [], -1, 0
    while True:  # a viewer who joins late pages through the past
        page = client.get(f"/api/live/{mid}/feed", params={"event": cursor}).json()
        events += page["events"]
        cursor, pages = page["eventCursor"], pages + 1
        if not page["more"]:
            break
    assert pages > 1 and {e["type"] for e in events} <= feed_events() and any(e["type"] == "goal" for e in events)
    assert [e["n"] for e in events] == sorted(e["n"] for e in events)
    first = client.get(f"/api/live/{mid}/feed", params={"event": cursor}).json()
    assert [m["id"] for m in first["moments"]] == [m["id"] for m in sorted(first["moments"], key=lambda m: m["detectedAt"]["matchMs"])]
    assert set(new) <= {m["id"] for m in first["moments"]}
    assert first["overlays"], "the model-free overlays (facts, graphics, momentum) are written by the interpreter"
    again = client.get(f"/api/live/{mid}/feed", params={"event": cursor, "since": first["overlayCursor"] + 1}).json()
    assert again["events"] == [] and again["overlays"] == [] and not again["more"]


def feed_events():
    from matchmind.live.api import SHOWN_EVENTS

    return SHOWN_EVENTS


def test_the_dispatcher_writes_narrative_overlays_and_a_rerun_adds_none(client, prepared, monkeypatch):
    _, mid, new = prepared
    monkeypatch.setenv("MATCHMIND_LIVE_KEY", "k3y")
    assert client.post(f"/api/live/{mid}/beats", json={"momentIds": new[:2]}).status_code == 403
    assert client.post(f"/api/live/{mid}/beats", json={"momentIds": new[:2]}, headers={"x-live-key": "wrong"}).status_code == 403
    ok = client.post(f"/api/live/{mid}/beats", json={"momentIds": new[:2]}, headers={"x-live-key": "k3y"})
    assert ok.status_code == 200 and ok.json()["overlaysWritten"] > 0
    stories = [o for o in client.get(f"/api/live/{mid}/feed").json()["overlays"] if o["kind"] == "lower_third"]
    assert stories and all(o["provenance"]["verified"] for o in stories)
    rerun = client.post(f"/api/live/{mid}/beats", json={"momentIds": new[:2]}, headers={"x-live-key": "k3y"})
    assert rerun.json()["overlaysWritten"] == 0
    assert client.post("/api/live/nope/beats", json={"momentIds": ["x"]}, headers={"x-live-key": "k3y"}).status_code == 404


def test_the_dispatch_endpoint_fails_closed_without_a_key(client, prepared, monkeypatch):
    _, mid, new = prepared
    monkeypatch.delenv("MATCHMIND_LIVE_KEY", raising=False)
    monkeypatch.delenv("MATCHMIND_LIVE_OPEN", raising=False)
    assert client.post(f"/api/live/{mid}/beats", json={"momentIds": new[:1]}).status_code == 403  # no key configured: nobody gets in
    assert client.post(f"/api/live/{mid}/beats", json={"momentIds": new[:1]}, headers={"x-live-key": ""}).status_code == 403
    monkeypatch.setenv("MATCHMIND_LIVE_OPEN", "1")  # a development machine says so explicitly
    assert client.post(f"/api/live/{mid}/beats", json={"momentIds": new[:1]}).status_code == 200


def test_a_job_that_cannot_start_does_not_hold_the_slot(monkeypatch):
    class Broken:
        def start(self, *a):  # noqa: ANN002, ANN202
            raise RuntimeError("ARM POST answered 400")

    monkeypatch.setenv("LIVE_JOB_ID", "/subscriptions/x/jobs/y")
    monkeypatch.setattr(brain, "ContainerAppsJobStarter", lambda *a: Broken())
    with TestClient(create_app(live_store=MemoryLiveStore())) as c:
        assert c.post("/api/live/start", json={"scenario": "red-card-drama"}).status_code == 502
        monkeypatch.setattr(brain, "ContainerAppsJobStarter", lambda *a: type("Ok", (), {"start": lambda self, *a: None})())
        assert c.post("/api/live/start", json={"scenario": "red-card-drama"}).status_code == 200  # the failed attempt did not block it


def test_starting_a_live_match_claims_the_slot_so_a_second_visitor_joins_it(monkeypatch):
    started: list[tuple] = []
    monkeypatch.setattr(brain, "run_simulator", lambda **kw: started.append((kw["match_id"], kw["scenario_name"], kw["from_minute"])))
    with TestClient(create_app(live_store=MemoryLiveStore())) as c:
        assert c.post("/api/live/start", json={"scenario": "not-a-scenario"}).status_code == 422
        r = c.post("/api/live/start", json={"scenario": "red-card-drama", "fromMinute": 40})
        assert r.status_code == 200
        mid = r.json()["matchId"]
        assert mid.startswith("live-red-card-drama-")
        assert c.get(f"/api/live/{mid}").json()["status"] == "scheduled"  # visible at once, before the job has simulated anything
        second = c.post("/api/live/start", json={"scenario": "pressing-collapse"})
        assert second.status_code == 409 and second.json()["detail"]["matchId"] == mid
    import time

    for _ in range(50):
        if started:
            break
        time.sleep(0.05)
    assert started == [(mid, "red-card-drama", 40.0)]


def test_a_brain_without_a_job_refuses_to_start_a_match():
    with TestClient(create_app()) as c:  # no LIVE_JOB_ID and no local mode
        assert c.post("/api/live/start", json={"scenario": "red-card-drama"}).status_code == 503
