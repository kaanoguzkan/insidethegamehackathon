"""The stream endpoints, end to end through the Brain: kick off a match, poll it, stop it."""

from __future__ import annotations

import time

import pytest
from apps.brain.main import create_app
from fastapi.testclient import TestClient

from matchmind.live import session as S
from matchmind.live.pipeline import Intel


@pytest.fixture(scope="module")
def client():
    hub = S.StreamHub(intel=Intel.load(), tick_s=0.05, max_sessions=3)
    hub.speeds = (*S.SPEEDS, 500.0)
    hub.preload(["red-card-drama"])
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MATCHMIND_STREAM_START_PER_MIN", "1000")  # the limiter is on by default; these tests start many matches
        with TestClient(create_app(stream_hub_override=hub)) as c:
            yield c


def test_the_demos_are_listed_with_their_clubs(client):
    d = client.get("/api/stream/demos").json()
    assert {x["id"] for x in d["demos"]} >= {"red-card-drama", "pressing-collapse", "six-goal-thriller"}
    rc = next(x for x in d["demos"] if x["id"] == "red-card-drama")
    assert rc["home"]["name"] == "Redmoor United" and rc["away"]["short"] == "Saltmarsh" and 5.0 in d["speeds"]


def test_a_started_match_is_polled_to_the_end_and_serves_its_tracking(client):
    r = client.post("/api/stream", json={"demo": "red-card-drama", "speed": 500.0})
    assert r.status_code == 200, r.text
    sid = r.json()["streamId"]
    assert sid.startswith("s-red-card-drama-") and r.json()["status"] in ("scheduled", "live")
    cursor, since, events, moments, overlays = -1, 0, [], {}, {}
    for _ in range(400):
        page = client.get(f"/api/stream/{sid}/feed", params={"event": cursor, "since": since}).json()
        events += page["events"]
        cursor, since = page["eventCursor"], page["overlayCursor"]
        moments.update({m["id"]: m for m in page["moments"]})
        overlays.update({o["id"]: o for o in page["overlays"]})
        if page["status"] == "finished" and not page["more"]:
            break
        time.sleep(0.1)
    assert page["status"] == "finished"
    assert sum(e["type"] == "goal" for e in events) == 3 and moments and overlays
    meta = client.get(f"/api/stream/{sid}/meta").json()
    assert meta["home"]["id"] == "RED" and meta["matchId"] == "red-card-drama"
    ch = client.get(f"/api/stream/{sid}/chunks/0")
    assert ch.status_code == 200 and ch.headers["content-encoding"] == "gzip"
    assert client.get(f"/api/stream/{sid}/chunks/99999").status_code == 404
    assert client.get(f"/api/stream/{sid}").json()["clockMs"] > 5_000_000


def test_bad_requests_get_the_right_status(client):
    assert client.post("/api/stream", json={"demo": "nope"}).status_code == 404
    assert client.post("/api/stream", json={"demo": "red-card-drama", "speed": 3}).status_code == 422
    assert client.post("/api/stream", json={"demo": "../etc"}).status_code == 422
    assert client.get("/api/stream/s-unknown/feed").status_code == 404
    assert client.get("/api/stream/s-unknown/chunks/0").status_code == 404


def test_a_match_can_be_stopped_and_the_slots_are_limited(client):
    ids = []
    for _ in range(3):
        r = client.post("/api/stream", json={"demo": "red-card-drama", "speed": 1})
        assert r.status_code == 200, r.text
        ids.append(r.json()["streamId"])
    busy = client.post("/api/stream", json={"demo": "red-card-drama", "speed": 1})
    assert busy.status_code == 503 and busy.headers["retry-after"] == "30"
    for sid in ids:
        assert client.delete(f"/api/stream/{sid}").json()["stopping"] is True
    for _ in range(100):
        if all(client.get(f"/api/stream/{sid}").json()["status"] == "stopped" for sid in ids):
            break
        time.sleep(0.1)
    assert all(client.get(f"/api/stream/{sid}").json()["status"] == "stopped" for sid in ids)


def test_a_viewers_profile_is_checked_and_can_change_during_the_match(client):
    bad = client.post("/api/stream", json={"demo": "red-card-drama", "speed": 1, "cohorts": [{"perspective": "XXX"}]})
    assert bad.status_code == 422
    ok = client.post("/api/stream", json={"demo": "red-card-drama", "speed": 1, "cohorts": [{"mode": "analyst", "language": "es", "perspective": "RED"}]})
    assert ok.status_code == 200, ok.text
    sid = ok.json()["streamId"]
    try:
        r = client.post(f"/api/stream/{sid}/cohorts", json={"mode": "casual", "language": "tr"})
        assert r.status_code == 200 and r.json()["cohort"] == "casual/tr/neutral/-"
        assert client.post(f"/api/stream/{sid}/cohorts", json={"language": "en", "perspective": "ZZZ"}).status_code == 422
        assert client.post("/api/stream/s-unknown/cohorts", json={}).status_code == 404
    finally:
        client.delete(f"/api/stream/{sid}")
