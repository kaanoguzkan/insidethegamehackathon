"""Choosing demo matches: play a fixture over a range of seeds and say what happened in each.

Nothing is scripted, so a match worth watching is found, not written: a seed where a manager reacted to the
score or to a sending-off, where the result turned, where there were goals. ``pick`` runs the seeds in parallel
and returns one summary per seed; the best are then built into replay packages and listed in ``data/demos.json``.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

from ..core.paths import league_dir
from .engine import simulate
from .league import load_league


def summarise(home: str, away: str, seed: int) -> dict:
    clubs = load_league(league_dir() / "league.json")
    res = simulate(f"pick-{seed}", clubs[home], clubs[away], seed=seed)
    goals = [(e["clock"]["minute"], e["team"]) for e in res.events if e["type"] == "goal"]
    reds = [(e["clock"]["minute"], e["team"]) for e in res.events if e["type"] == "card" and e.get("outcome") == "red"]
    score = [0, 0]
    lead_changes = 0
    last_leader = 0
    for _, team in goals:
        score[0 if team == home else 1] += 1
        leader = (score[0] > score[1]) - (score[0] < score[1])
        lead_changes += leader != 0 and last_leader != 0 and leader != last_leader
        last_leader = leader or last_leader
    changes = res.stats["manager_changes"]
    late_shape = [c for c in changes if c["minute"] >= 50 and c["reason"] != "man down"]
    points = (
        2 * min(len(goals), 5)
        + 3 * len(reds[:1])
        + 4 * lead_changes
        + 3 * min(len(changes), 3)
        + 2 * len(late_shape[:2])
        - 6 * (not goals)
    )
    return {
        "seed": seed, "score": res.meta["score"], "goals": goals, "reds": reds, "lead_changes": lead_changes,
        "changes": [(c["minute"], c["team"], c["reason"], c["formation"]) for c in changes], "points": points,
    }  # fmt: skip


def _job(args: tuple[str, str, int]) -> dict:
    return summarise(*args)


def pick(home: str, away: str, seeds: range, *, workers: int | None = None) -> list[dict]:
    """Every seed's summary, most watchable first."""
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(_job, [(home, away, s) for s in seeds]))
    return sorted(rows, key=lambda r: -r["points"])
