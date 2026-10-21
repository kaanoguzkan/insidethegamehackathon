"""Stream sessions: a demo match played to a viewer through the incremental pipeline, all in this process."""

from __future__ import annotations

import time
from concurrent.futures import Future

import pytest

from matchmind.live import session as S
from matchmind.live.pipeline import Intel


@pytest.fixture(scope="module")
def intel():
    return Intel.load()


@pytest.fixture(scope="module")
def hub(intel):
    h = S.StreamHub(intel=intel, tick_s=0.02, max_sessions=6)
    h.speeds = (*S.SPEEDS, 2000.0)
    h.preload(["red-card-drama"])
    return h


def wait(hub, sid, status=("finished", "stopped", "failed"), timeout=90.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        info = hub.store.get_match(sid)
        if info and info.get("status") in status and hub.sessions[sid].finished_at is not None:
            return info
        time.sleep(0.05)
    raise AssertionError(f"session {sid} did not finish: {hub.store.get_match(sid)}")


def test_a_fast_session_finds_the_story_and_finds_it_the_same_way_every_time(hub, intel):
    s = hub.start("red-card-drama", speed=2000.0)
    info = wait(hub, s.id)
    assert info["status"] == "finished" and s.error is None
    first = {m["id"]: (m["type"], m["detectedAt"]["matchMs"]) for m in hub.store.moments(s.id)}
    types = [t for t, _ in first.values()]
    assert types.count("goal") == 6 and "red_card" in types, "the six goals and the red card of the match are found as it is played"
    assert hub.store.overlays_since(s.id, 0), "facts and graphics are written as the match goes"
    slower = S.StreamHub(intel=intel, tick_s=0.3)  # other timing, same pipeline: the ids and the moments must not depend on when the ticks fall
    slower.speeds = (500.0,)
    s2 = slower.start("red-card-drama", speed=500.0)
    wait(slower, s2.id)
    assert {m["id"]: (m["type"], m["detectedAt"]["matchMs"]) for m in slower.store.moments(s2.id)} == first


def test_a_session_only_holds_what_the_clock_has_reached(hub):
    s = hub.start("red-card-drama", speed=10.0, from_minute=0.0)
    try:
        time.sleep(1.5)  # 15 match seconds
        docs = hub.store.docs(s.id)
        assert docs and max(d["arrivalMs"] for d in docs) <= 20_000, "nothing from the viewer's future is in their store"
        assert hub.store.get_match(s.id)["status"] == "live"
        total = len(hub.source("red-card-drama").docs)
        assert len(docs) < total / 10
    finally:
        hub.stop(s.id)
    assert wait(hub, s.id)["status"] == "stopped"


def test_sessions_do_not_share_a_clock_or_a_store(hub):
    a = hub.start("red-card-drama", speed=2000.0)
    b = hub.start("red-card-drama", speed=1.0)
    try:
        wait(hub, a.id)
        assert hub.store.get_match(a.id)["status"] == "finished"
        elapsed_ms = (time.time() * 1000 - hub.store.get_match(b.id)["wallStartMs"]) * 1.0  # speed 1: match ms played so far, whatever the machine
        assert max(d["arrivalMs"] for d in hub.store.docs(b.id)) <= elapsed_ms + 1500
        assert len(hub.store.docs(b.id)) < len(hub.store.docs(a.id)) / 5
        assert hub.store.docs(a.id) and {d["matchId"] for d in hub.store.docs(a.id)} == {a.id}
    finally:
        hub.stop(b.id)
        wait(hub, b.id)


def test_every_new_moment_is_handed_to_the_dispatcher_once(intel):
    seen: list[str] = []

    def dispatch(store, sid, ids, cohorts):
        seen.extend(ids)
        fut: Future = Future()
        fut.set_result(None)
        return fut

    h = S.StreamHub(intel=intel, tick_s=0.02, dispatch=dispatch)
    h.speeds = (2000.0,)
    s = h.start("red-card-drama", speed=2000.0)
    wait(h, s.id)
    assert sorted(seen) == sorted(m["id"] for m in h.store.moments(s.id)) and len(seen) == len(set(seen)) > 5


def test_too_many_sessions_are_refused_and_a_finished_one_is_released(intel):
    h = S.StreamHub(intel=intel, tick_s=0.02, max_sessions=1, keep_finished_s=0.0)
    h.speeds = (1.0, 2000.0)
    a = h.start("red-card-drama", speed=1.0)
    with pytest.raises(S.StreamBusy):
        h.start("red-card-drama", speed=1.0)
    h.stop(a.id)
    wait(h, a.id)
    b = h.start("red-card-drama", speed=1.0)  # the stopped session was swept: its slot is free again
    assert h.store.get_match(a.id) is None and b.id != a.id
    h.stop(b.id)


def test_an_unknown_demo_or_speed_is_refused(hub):
    with pytest.raises(KeyError):
        hub.start("not-a-demo")
    with pytest.raises(ValueError):
        hub.start("red-card-drama", speed=3.0)


def test_a_viewer_who_stops_polling_ends_the_match(intel):
    h = S.StreamHub(intel=intel, tick_s=0.02, idle_stop_s=0.2)
    s = h.start("red-card-drama", speed=1.0)
    time.sleep(0.5)
    h.sweep()
    assert wait(h, s.id)["status"] == "stopped"


def test_the_dispatcher_is_given_the_viewers_cohorts_and_a_new_profile_joins_them(intel):
    from matchmind.core.contracts import Cohort

    got: list[list[str]] = []

    def dispatch(store, sid, ids, cohorts):
        got.append([c.key for c in cohorts])
        fut: Future = Future()
        fut.set_result(None)
        return fut

    h = S.StreamHub(intel=intel, tick_s=0.02, dispatch=dispatch)
    h.speeds = (1.0,)
    s = h.start("red-card-drama", speed=1.0, cohorts=[Cohort(mode="analyst", language="tr", perspective="SAL")])
    try:
        assert s.cohorts[0].key == "analyst/tr/SAL/-"
        assert h.add_cohort(s.id, Cohort(language="es")) and [c.key for c in s.cohorts] == ["analyst/tr/SAL/-", "casual/es/neutral/-"]
        from matchmind.agents.service import InvalidCohort

        with pytest.raises(InvalidCohort):
            h.add_cohort(s.id, Cohort(perspective="XXX"))
        with pytest.raises(InvalidCohort):
            h.start("red-card-drama", speed=1.0, cohorts=[Cohort(focusPlayer="NOPE-99")])
    finally:
        h.stop(s.id)


def test_analytics_and_recaps_follow_the_match_and_are_written_once_per_kind(intel):
    asked: list[tuple[str, list[str]]] = []

    def recap(store, sid, kind, pack, cohorts):
        asked.append((kind, [c.key for c in cohorts]))
        return None

    h = S.StreamHub(intel=intel, tick_s=0.02, recap=recap)
    h.speeds = (2000.0,)
    s = h.start("red-card-drama", speed=2000.0, cohorts=[S.Cohort(mode="analyst", language="es", perspective="SAL", focusPlayer=None)])
    wait(h, s.id)
    a = h.store.get_state(s.id, "analytics")
    assert a["version"] >= 2, "refreshed while the match was on, and once more at the end"
    assert a["data"]["winProbability"]["series"] and a["data"]["shots"] and a["data"]["players"]
    assert [k for k, _ in asked] == ["preview", "half_time", "full_time"], "in the order the match reaches them, once each"
    assert all(c == ["analyst/es/SAL/-"] for _, c in asked)
    h.sessions[s.id].finished_at = None  # a viewer who switches profile later gets the recaps already due written for the new one
    assert h.add_cohort(s.id, S.Cohort(language="tr"))
    assert [k for k, _ in asked[3:]] == ["preview", "half_time", "full_time"] and asked[3][1] == ["casual/tr/neutral/-"]
