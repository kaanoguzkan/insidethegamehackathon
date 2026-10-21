"""A season: the schedule, the table, claiming fixtures from several workers, and the season job."""

from __future__ import annotations

import threading

from matchmind.live import season as S
from matchmind.live.blobs import MemoryBlobs
from matchmind.live.packs import read_pack
from matchmind.live.season_job import create_season, run_worker, simulate_fixture


def test_the_schedule_is_a_double_round_robin_that_opens_with_the_three_stories():
    sched = S.schedule()
    assert len(sched) == 30 and {r for r, _, _ in sched} == set(range(1, 11))
    assert all(sum(1 for r, *_ in sched if r == k) == 3 for k in range(1, 11))
    for k in range(1, 11):  # every club plays once in every round
        assert sorted(c for r, h, a in sched if r == k for c in (h, a)) == sorted(S.CLUB_ORDER)
    pairs = [(h, a) for _, h, a in sched]
    assert len(set(pairs)) == 30 and all(a != h for h, a in pairs)  # every ordered pair exactly once: home and away
    assert [(h, a) for r, h, a in sched if r == 1] == [("RED", "SAL"), ("HAR", "NOR"), ("KES", "ALD")]


def test_a_planned_season_gives_the_demo_matches_to_round_one_and_its_own_seeds_to_the_rest():
    season, fx = S.plan("s1", 7, featured=True)
    assert season["total"] == 30 and [f["id"] for f in fx[:3]] == ["f01", "f02", "f03"]
    assert [f["scenario"] for f in fx[:3]] == ["red-card-drama", "pressing-collapse", "eight-goal-thriller"] and all(f["scenario"] is None for f in fx[3:])
    assert [f["seed"] for f in fx[:3]] == [19, 34, 1] and len({f["seed"] for f in fx}) == 30
    _, other = S.plan("s2", 7, featured=False)
    assert [f["seed"] for f in other[:3]] != [19, 34, 1] and all(f["status"] == "pending" for f in other)


def test_the_table_counts_only_finished_fixtures_and_orders_by_points_then_goal_difference():
    fx = [
        {"home": "A", "away": "B", "status": "done", "score": {"A": 2, "B": 0}},
        {"home": "C", "away": "A", "status": "done", "score": {"C": 1, "A": 1}},
        {"home": "B", "away": "C", "status": "done", "score": {"B": 3, "C": 0}},
        {"home": "B", "away": "A", "status": "pending", "score": None},
    ]
    t = S.standings(fx, {"A": "Alpha", "B": "Bravo", "C": "Charlie"})
    assert [(r["club"], r["points"], r["gd"], r["played"]) for r in t] == [("A", 4, 2, 2), ("B", 3, 1, 2), ("C", 1, -3, 2)]
    assert t[0]["name"] == "Alpha" and (t[0]["won"], t[0]["drawn"], t[0]["lost"], t[0]["gf"], t[0]["ga"]) == (1, 1, 0, 3, 1)


def test_several_workers_simulate_each_fixture_exactly_once():
    store = S.MemorySeasonStore()
    create_season(store, "s1", 1, featured=False)
    seen: list[str] = []
    lock = threading.Lock()

    def fake(fx, clubs, packs):  # noqa: ANN001, ANN202
        with lock:
            seen.append(fx["id"])
        return {fx["home"]: 1, fx["away"]: 0}

    done = []
    threads = [threading.Thread(target=lambda i=i: done.append(run_worker("s1", store, MemoryBlobs(), f"w{i}", simulate_one=fake, clubs={}))) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(seen) == [f"f{i:02d}" for i in range(1, 31)] and sum(done) == 30  # nobody did a fixture twice, nobody left one
    assert all(f["status"] == "done" and f["pack"] == f"s1/{f['id']}" for f in store.fixtures("s1"))


def test_an_abandoned_claim_is_taken_over_and_a_failure_goes_back_to_pending():
    store = S.MemorySeasonStore()
    create_season(store, "s1", 1, featured=False)
    first = store.claim("s1", "dead-worker")
    assert first["id"] == "f01" and store.claim("s1", "other")["id"] == "f02"  # f01 is held, so the next one is handed out
    store._fixtures["s1"]["f01"]["claimedMs"] = 1  # the claim is ancient
    assert store.claim("s1", "rescuer")["id"] == "f01"
    calls = {"n": 0}

    def flaky(fx, clubs, packs):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if fx["id"] == "f03" and calls["n"] < 4:
            raise RuntimeError("boom")
        return {fx["home"]: 0, fx["away"]: 0}

    run_worker("s1", store, MemoryBlobs(), "w", simulate_one=flaky, clubs={})
    f03 = next(f for f in store.fixtures("s1") if f["id"] == "f03")
    assert f03["status"] == "done"  # it failed once, went back to pending, and was claimed again


def test_a_real_fixture_is_simulated_into_a_pack_with_its_score(tmp_path):
    from matchmind.core.paths import league_dir
    from matchmind.sim.league import load_league

    store, packs = S.MemorySeasonStore(), MemoryBlobs()
    create_season(store, "s9", 3, featured=True)
    fx = store.claim("s9", "t")  # f01: Redmoor v Saltmarsh, the red-card match
    score = simulate_fixture(fx, load_league(league_dir() / "league.json"), packs)
    assert set(score) == {"RED", "SAL"} and score == {"RED": 4, "SAL": 2}  # seed 19: the demo's result
    pack = read_pack(packs, "s9/f01")
    assert pack is not None and pack.match_id == "s9-f01" and pack.meta["seed"] == 19 and pack.n_chunks > 1000
