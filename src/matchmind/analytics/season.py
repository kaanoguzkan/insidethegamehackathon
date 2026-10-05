"""Season context: the history a match sits in, the way Opta's broadcast facts and match previews use it.

``matchmind build-season`` simulates a fictional back-story for the Lumen League (all 30 fixtures of
last season and the first four rounds of this one), condenses every match to a record of results,
goals, team style and player numbers, and writes ``data/league/season.json``. From that, a match gets:

* the league table, recent form and unbeaten / clean-sheet runs going into it
* the head-to-head history between the two clubs
* season totals for every player, and the records a goal can break
* team strengths (from expected goals for and against) and a Poisson **prediction** of the result
* milestone detection for live goals ("his 5th of the season", "the fastest goal in the league's history")
* **player radars** (per-90 numbers as percentiles among positional peers) and "plays like" matches

All of it is synthetic and fits the same shape as real data, so a real provider's history could replace it.
"""

from __future__ import annotations

import itertools
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ..core.paths import league_dir
from ..sim.engine import simulate
from ..sim.league import load_league
from ..sim.teams import GROUP
from .store import load_models

LAST_SEASON = "2025/26"
THIS_SEASON = "2026/27"
ROUNDS_PLAYED = 4
FEATURED_ROUND = 5
FEATURED = [("HAR", "NOR"), ("RED", "SAL"), ("KES", "ALD")]  # the three scripted fixtures are round 5
SEED0 = 40000
PRIOR_MATCHES = 3.0  # pseudo-matches of league-average form that shrink team strengths
MIN_RADAR_MINUTES = 90

RADAR_AXES = {
    "ATT": [("shots", "Shots"), ("xg", "xG"), ("xa", "xA"), ("keyPasses", "Key passes"), ("packing", "Packing"), ("value", "Value added"), ("sprintM", "Sprint distance")],
    "MID": [("passes", "Passes"), ("keyPasses", "Key passes"), ("packing", "Packing"), ("lineBreaks", "Line breaks"), ("duels", "Tackles + interceptions"), ("value", "Value added"), ("hsrM", "High-speed running")],
    "DEF": [("tackles", "Tackles"), ("interceptions", "Interceptions"), ("pressures", "Pressures"), ("passAcc", "Pass accuracy"), ("packing", "Packing"), ("value", "Value added"), ("hsrM", "High-speed running")],
    "GK": [("saves", "Saves"), ("goalsPrevented", "Goals prevented"), ("claims", "Claims"), ("longShare", "Long distribution"), ("passAcc", "Pass accuracy")],
}
TEAM_AXES = [
    ("pressing", "Pressing", "ppda", True), ("possession", "Possession", "possession", False), ("directness", "Directness", "longShare", False),
    ("tempo", "Tempo", "tempo", False), ("chances", "Chance creation", "xg", False), ("defence", "Defence", "xgAgainst", True),
    ("counterpress", "Counter-pressing", "counterpressRate", False), ("lines", "Line-breaking", "lineBreaks", False),
]  # (key, label, field, lower is better)


# ----- the fixtures ---------------------------------------------------------------------------------------------------


def _one_factorisation(ids: list[str], first: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Split the 15 pairings of six clubs into five rounds, with ``first`` as the last one."""
    last = {frozenset(p) for p in first}
    rest = [frozenset(p) for p in itertools.combinations(ids, 2) if frozenset(p) not in last]

    def matchings(edges: list[frozenset]) -> list[list[frozenset]]:
        out: list[list[frozenset]] = []

        def rec(chosen: list[frozenset], used: set[str], start: int) -> None:
            if len(chosen) == len(ids) // 2:
                out.append(list(chosen))
                return
            for i in range(start, len(edges)):
                e = edges[i]
                if not (e & used):
                    rec(chosen + [e], used | e, i + 1)

        rec([], set(), 0)
        return out

    options = matchings(rest)

    def solve(avail: list[frozenset], rounds: list[list[frozenset]]) -> list[list[frozenset]] | None:
        if len(rounds) == 4:
            return rounds if not avail else None
        for m in options:
            if all(e in avail for e in m):
                got = solve([e for e in avail if e not in m], rounds + [m])
                if got:
                    return got
        return None

    rounds = solve(rest, []) or []
    return [[tuple(sorted(e)) for e in r] for r in rounds] + [list(first)]


def fixtures(ids: list[str]) -> dict:
    """``{season: {round: [(home, away), ...]}}`` for last season (two legs) and this season's first four rounds."""
    five = _one_factorisation(ids, FEATURED)
    this: dict[int, list[tuple[str, str]]] = {}
    for r, ms in enumerate(five[:ROUNDS_PLAYED], start=1):
        this[r] = [(a, b) if (r + k) % 2 == 0 else (b, a) for k, (a, b) in enumerate(ms)]
    last: dict[int, list[tuple[str, str]]] = {}
    for r, ms in enumerate(five, start=1):
        last[r] = [(a, b) if (r + k) % 2 else (b, a) for k, (a, b) in enumerate(ms)]
        last[r + 5] = [(b, a) for a, b in last[r]]
    return {LAST_SEASON: last, THIS_SEASON: this}


# ----- condensing a simulated match -------------------------------------------------------------------------------------


def _minute(e: dict) -> float:
    return round(e["clock"]["minute"] + e["clock"]["second"] / 60.0, 2)


def condense(ip, report: dict, season: str, round_no: int) -> dict:
    """The record of one match that the season keeps: result, goals, team style, player numbers."""
    clubs = ip.clubs
    score = [0, 0]
    goals = []
    for e in ip.events:
        if e["type"] == "goal":
            score[clubs.index(e["team"])] += 1
            a = e.get("attributes") or {}
            shot = next((s for s in reversed(ip.events) if s["type"] == "shot" and s["player"] == e["player"] and 0 <= e["_ms"] - s["_ms"] < 4000), None)
            goals.append({"team": e["team"], "player": e["player"], "minute": _minute(e), "assist": a.get("assist"),
                          "xg": round(float(shot.get("_xg", 0.0)), 3) if shot else None, "situation": ((shot or {}).get("attributes") or {}).get("situation")})
    w = ip.window(0, max(e["_ms"] for e in ip.events))
    shots = report["shots"]["teams"]
    tr = report["transitions"]
    sp = report["setPieces"]["teams"]
    teams = {}
    lines: dict[str, list[float]] = {c: [] for c in clubs}
    widths: dict[str, list[float]] = {c: [] for c in clubs}
    for e in ip.events:
        if e["type"] == "team_shape":
            a = e["attributes"]
            if "lineHeightDefM" in a:
                lines[e["team"]].append(a["lineHeightDefM"])
                widths[e["team"]].append(a["widthDefM"])
    for i, c in enumerate(clubs):
        o = clubs[1 - i]
        mine = w[c]
        corners = sum(r["n"] for r in sp[c]["taken"].get("corner", {}).values())
        teams[c] = {
            "possession": round(mine["possession_share"], 3), "passes": mine["passes"], "passAcc": round(mine["pass_acc"] or 0.0, 3),
            "longShare": round(w["match"]["long_ball_share"] or 0.0, 3), "ppda": round(mine["ppda"], 2) if mine["ppda"] is not None else None,
            "pressuresPerMin": round(mine["pressures_per_min"], 2), "tempo": round(mine["tempo"], 1) if mine["tempo"] else None,
            "shots": shots[c]["shots"], "xg": shots[c]["xg"], "xgAgainst": shots[o]["xg"], "goals": score[i], "onTarget": shots[c]["onTarget"],
            "finalThirdEntries": mine["final_third_entries"], "packing": mine["packing"], "lineBreaks": mine["line_breaks"],
            "counterpressRate": tr[c]["counterpressRate"], "fastBreaks": tr[c]["fastBreaks"], "corners": corners,
            "lineHeightM": round(float(np.mean(lines[c])), 1) if lines[c] else None, "widthM": round(float(np.mean(widths[c])), 1) if widths[c] else None,
        }
    gk = report["goalkeepers"]
    players = []
    for r in report["players"]:
        row = {k: r.get(k) for k in ("id", "name", "team", "pos", "minutes", "goals", "assists", "shots", "xg", "keyPasses", "xa", "passes", "passesComplete", "tackles", "interceptions", "pressures", "value", "valueAttacking", "valueDefending", "packing", "lineBreaks", "km", "hsrM", "sprintM")}
        g = gk.get(r["team"])
        if g and g["player"] == r["id"]:
            row["gk"] = {k: g[k] for k in ("saves", "goalsPrevented", "claims", "longShare", "passCompletion", "xgotFaced", "shotsFaced")}
        players.append(row)
    cards = [{"team": e["team"], "player": e["player"], "card": e.get("outcome")} for e in ip.events if e["type"] == "card"]
    return {"id": f"{season}-r{round_no:02d}-{clubs[0]}-{clubs[1]}", "season": season, "round": round_no, "home": clubs[0], "away": clubs[1],
            "score": score, "goals": goals, "cards": cards, "teams": teams, "players": players}


def _sim(job: tuple[str, int, str, str, int]) -> dict:
    from ..intel.baselines import load_baselines
    from ..intel.pipeline import interpret_match
    from ..intel.xt import XTGrid
    from .report import MatchAnalytics

    season, round_no, h, a, seed = job
    clubs = load_league(league_dir() / "league.json")
    res = simulate(f"{season}-{round_no}-{h}-{a}", clubs[h], clubs[a], seed=seed)
    ip, _ = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"), models=load_models())
    return condense(ip, MatchAnalytics(ip).summary(), season, round_no)


def build_season(workers: int | None = None, seed0: int = SEED0) -> dict:
    ids = list(load_league(league_dir() / "league.json"))
    fx = fixtures(ids)
    jobs = []
    for season, rounds in fx.items():
        for r, ms in rounds.items():
            for h, a in ms:
                jobs.append((season, r, h, a, seed0 + len(jobs)))
    if workers == 1:
        matches = [_sim(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            matches = list(ex.map(_sim, jobs))
    return {"version": 1, "clubs": ids, "lastSeason": LAST_SEASON, "season": THIS_SEASON, "roundsPlayed": ROUNDS_PLAYED, "matches": matches}


def save_season(season: dict, path: Path | None = None) -> Path:
    path = path or league_dir() / "season.json"
    path.write_text(json.dumps(season, separators=(",", ":"), ensure_ascii=False) + "\n")
    return path


def load_season(path: Path | None = None) -> dict:
    path = path or league_dir() / "season.json"
    return json.loads(path.read_text()) if path.exists() else {}


# ----- context for a match ------------------------------------------------------------------------------------------------


def _order(m: dict) -> tuple:
    return (0 if m["season"] == LAST_SEASON else 1, m["round"])


def standings(matches: list[dict], ids: list[str]) -> list[dict]:
    t = {c: {"club": c, "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "pts": 0} for c in ids}
    for m in matches:
        for side, c in enumerate((m["home"], m["away"])):
            gf, ga = m["score"][side], m["score"][1 - side]
            r = t[c]
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if gf > ga:
                r["won"] += 1
                r["pts"] += 3
            elif gf == ga:
                r["drawn"] += 1
                r["pts"] += 1
            else:
                r["lost"] += 1
    rows = sorted(t.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["club"]))
    for i, r in enumerate(rows, start=1):
        r["gd"] = r["gf"] - r["ga"]
        r["pos"] = i
    return rows


def _results(matches: list[dict], club: str) -> list[tuple[str, int, int]]:
    out = []
    for m in sorted(matches, key=_order):
        if club in (m["home"], m["away"]):
            side = 0 if m["home"] == club else 1
            gf, ga = m["score"][side], m["score"][1 - side]
            out.append(("W" if gf > ga else "D" if gf == ga else "L", gf, ga))
    return out


def _run(results: list[tuple[str, int, int]], pred) -> int:
    n = 0
    for r in reversed(results):
        if not pred(r):
            break
        n += 1
    return n


def poisson_grid(lam_h: float, lam_a: float, n: int = 8) -> np.ndarray:
    ph = np.array([math.exp(-lam_h) * lam_h**k / math.factorial(k) for k in range(n + 1)])
    pa = np.array([math.exp(-lam_a) * lam_a**k / math.factorial(k) for k in range(n + 1)])
    return np.outer(ph, pa)


def ratings(matches: list[dict], ids: list[str]) -> tuple[dict, float]:
    """Attack and defence strength per club from expected goals for and against, shrunk to the league mean."""
    xgf: dict[str, list[float]] = {c: [] for c in ids}
    xga: dict[str, list[float]] = {c: [] for c in ids}
    for m in matches:
        for c, o in ((m["home"], m["away"]), (m["away"], m["home"])):
            xgf[c].append(m["teams"][c]["xg"])
            xga[c].append(m["teams"][o]["xg"] if o in m["teams"] else m["teams"][c]["xgAgainst"])
    lg = float(np.mean([x for v in xgf.values() for x in v])) if any(xgf.values()) else 1.3
    out = {}
    for c in ids:
        n = len(xgf[c])
        att = (sum(xgf[c]) + PRIOR_MATCHES * lg) / (n + PRIOR_MATCHES) / lg
        dfn = (sum(xga[c]) + PRIOR_MATCHES * lg) / (n + PRIOR_MATCHES) / lg
        out[c] = {"att": round(att, 3), "def": round(dfn, 3), "xgFor": round(float(np.mean(xgf[c])), 2) if n else None, "xgAgainst": round(float(np.mean(xga[c])), 2) if n else None, "matches": n}
    return out, lg


def predict(home: str, away: str, rat: dict, lg: float) -> dict:
    lam_h = lg * rat[home]["att"] * rat[away]["def"]
    lam_a = lg * rat[away]["att"] * rat[home]["def"]
    g = poisson_grid(lam_h, lam_a)
    win = float(np.tril(g, -1).sum())
    draw = float(np.trace(g))
    lose = float(np.triu(g, 1).sum())
    flat = sorted(((float(g[i, j]), i, j) for i in range(g.shape[0]) for j in range(g.shape[1])), reverse=True)[:3]
    return {
        "home": round(win, 3), "draw": round(draw, 3), "away": round(lose, 3), "xg": {home: round(lam_h, 2), away: round(lam_a, 2)},
        "scores": [{"score": [i, j], "p": round(p, 3)} for p, i, j in flat],
        "strength": {home: round(lam_h / lg, 3), away: round(lam_a / lg, 3)},
    }


def records(matches: list[dict], players: dict[str, str]) -> dict:
    fastest = None
    most_goals = (0, None)
    biggest = (0, None)
    highest = (0, None)
    for m in matches:
        for g in m["goals"]:
            if fastest is None or g["minute"] < fastest["minute"]:
                fastest = {"minute": g["minute"], "player": g["player"], "team": g["team"], "match": m["id"], "season": m["season"]}
        per: dict[str, int] = {}
        for g in m["goals"]:
            per[g["player"]] = per.get(g["player"], 0) + 1
        for p, n in per.items():
            if n > most_goals[0]:
                most_goals = (n, {"player": p, "match": m["id"], "season": m["season"]})
        margin = abs(m["score"][0] - m["score"][1])
        if margin > biggest[0]:
            biggest = (margin, {"match": m["id"], "score": m["score"], "home": m["home"], "away": m["away"], "season": m["season"]})
        if sum(m["score"]) > highest[0]:
            highest = (sum(m["score"]), {"match": m["id"], "score": m["score"], "home": m["home"], "away": m["away"], "season": m["season"]})
    return {
        "fastestGoal": fastest, "mostGoalsByPlayer": {"n": most_goals[0], **(most_goals[1] or {})},
        "biggestWin": {"margin": biggest[0], **(biggest[1] or {})}, "highestScoring": {"goals": highest[0], **(highest[1] or {})},
    }


def context_for(season: dict, home: str, away: str) -> dict:
    """What a match between ``home`` and ``away`` inherits from the season so far (empty if there is no season data)."""
    if not season:
        return {}
    ids = season["clubs"]
    allm = season["matches"]
    cur = [m for m in allm if m["season"] == season["season"]]
    table = standings(cur, ids)
    names = {p["id"]: p["name"] for m in allm for p in m["players"]}
    form, streaks = {}, {}
    for c in (home, away):
        res = _results(allm, c)
        form[c] = "".join(r[0] for r in res[-5:])
        streaks[c] = {
            "unbeaten": _run(res, lambda r: r[0] != "L"), "winless": _run(res, lambda r: r[0] != "W"), "wins": _run(res, lambda r: r[0] == "W"),
            "cleanSheets": _run(res, lambda r: r[2] == 0), "scoredIn": _run(res, lambda r: r[1] > 0),
        }
    meetings = [m for m in sorted(allm, key=_order) if {m["home"], m["away"]} == {home, away}]
    rec = {home: 0, away: 0, "draw": 0}
    for m in meetings:
        d = m["score"][0] - m["score"][1]
        rec["draw" if d == 0 else (m["home"] if d > 0 else m["away"])] += 1
    tally: dict[str, dict] = {}
    for m in cur:
        for p in m["players"]:
            t = tally.setdefault(p["id"], {"goals": 0, "assists": 0, "shots": 0, "xg": 0.0, "minutes": 0.0, "matches": 0})
            t["goals"] += p.get("goals") or 0
            t["assists"] += p.get("assists") or 0
            t["shots"] += p.get("shots") or 0
            t["xg"] = round(t["xg"] + (p.get("xg") or 0.0), 2)
            t["minutes"] += p.get("minutes") or 0.0
            t["matches"] += 1
    rat, lg = ratings(allm, ids)
    top = sorted(((pid, t["goals"]) for pid, t in tally.items()), key=lambda kv: -kv[1])[:3]
    return {
        "season": season["season"], "round": FEATURED_ROUND, "played": ROUNDS_PLAYED, "standings": table, "form": form, "streaks": streaks,
        "headToHead": {"record": rec, "meetings": [{"season": m["season"], "round": m["round"], "home": m["home"], "away": m["away"], "score": m["score"]} for m in meetings[-4:]]},
        "players": tally, "topScorers": [{"id": pid, "name": names.get(pid), "goals": n} for pid, n in top], "records": records(allm, names),
        "ratings": rat, "prediction": predict(home, away, rat, lg),
    }


# ----- live milestones -----------------------------------------------------------------------------------------------------


def goal_milestones(ctx: dict, goals: list[dict], new: dict, concede_club: str) -> list[dict]:
    """Milestones a just-scored goal triggers. ``goals`` are this match's earlier goals; ``new`` is the goal."""
    if not ctx:
        return []
    out: list[dict] = []
    pid, club = new["player"], new["team"]
    prior_goals = ctx["players"].get(pid, {}).get("goals", 0)
    this_match = sum(1 for g in goals if g["player"] == pid) + 1
    season_n = prior_goals + this_match
    if this_match == 3:
        out.append({"kind": "hat_trick", "player": pid, "team": club})
    elif season_n in (1, 5, 10, 15):
        out.append({"kind": "season_goals", "player": pid, "team": club, "n": season_n})
    fast = ctx["records"].get("fastestGoal")
    if fast and new["minute"] < fast["minute"]:
        out.append({"kind": "fastest_goal", "player": pid, "team": club, "minute": new["minute"], "previous": fast["minute"]})
    cs = ctx["streaks"].get(concede_club, {}).get("cleanSheets", 0)
    if cs >= 2 and not any(g["team"] == club for g in goals):
        out.append({"kind": "ends_clean_sheet_run", "team": concede_club, "n": cs})
    return out[:2]


# ----- radars and "plays like" ----------------------------------------------------------------------------------------------


def _per90(p: dict, key: str) -> float | None:
    mins = p.get("minutes") or 0.0
    gk = p.get("gk") or {}
    if key in ("saves", "goalsPrevented", "claims", "longShare"):
        return {"saves": gk.get("saves"), "goalsPrevented": gk.get("goalsPrevented"), "claims": gk.get("claims"), "longShare": gk.get("longShare")}.get(key)
    if key == "passAcc":
        return (p["passesComplete"] / p["passes"]) if p.get("passes") else None
    if key == "duels":
        return ((p.get("tackles") or 0) + (p.get("interceptions") or 0)) * 90.0 / mins if mins else None
    v = p.get(key)
    return None if v is None or not mins else float(v) * 90.0 / mins


def _table(season: dict) -> dict[str, list[dict]]:
    """Per player across the whole history: summed numbers, grouped by position group."""
    agg: dict[str, dict] = {}
    for m in season["matches"]:
        for p in m["players"]:
            a = agg.setdefault(p["id"], {"id": p["id"], "name": p["name"], "team": p["team"], "pos": p["pos"], "minutes": 0.0, "gk": []})
            for k in ("goals", "assists", "shots", "xg", "xa", "keyPasses", "passes", "passesComplete", "tackles", "interceptions", "pressures", "value", "packing", "lineBreaks", "hsrM", "sprintM", "km"):
                a[k] = a.get(k, 0.0) + (p.get(k) or 0.0)
            a["minutes"] += p.get("minutes") or 0.0
            if p.get("gk"):
                a["gk"].append(p["gk"])
    groups: dict[str, list[dict]] = {"ATT": [], "MID": [], "DEF": [], "GK": []}
    for a in agg.values():
        if a["gk"]:
            n = len(a["gk"])
            a["gk"] = {"saves": sum(g["saves"] for g in a["gk"]) / n * 90 / 90, "goalsPrevented": sum(g["goalsPrevented"] for g in a["gk"]) / n,
                       "claims": sum(g["claims"] for g in a["gk"]) / n, "longShare": float(np.mean([g["longShare"] or 0.0 for g in a["gk"]]))}
        else:
            a["gk"] = None
        if a["minutes"] >= MIN_RADAR_MINUTES:
            groups[GROUP[a["pos"]]].append(a)
    return groups


def radars(season: dict, rows: list[dict]) -> dict:
    """Radar axes (percentile among positional peers) and the three most similar players, for ``rows``."""
    if not season:
        return {}
    groups = _table(season)
    dist: dict[str, dict[str, np.ndarray]] = {}
    for g, peers in groups.items():
        dist[g] = {}
        for key, _ in RADAR_AXES[g]:
            vals = [v for p in peers if (v := _per90(p, key)) is not None]
            dist[g][key] = np.array(sorted(vals)) if vals else np.array([0.0])
    out: dict = {}
    for r in rows:
        g = GROUP.get(r["pos"])
        if g is None or (r.get("minutes") or 0) < 20:
            continue
        axes, vec = [], []
        for key, label in RADAR_AXES[g]:
            v = _per90(r, key)
            d = dist[g][key]
            pct = float((d < v).sum() + 0.5 * (d == v).sum()) / len(d) if v is not None else 0.0
            axes.append({"key": key, "label": label, "value": None if v is None else round(v, 3), "pct": round(pct, 2)})
            vec.append(pct)
        out[r["id"]] = {"group": g, "axes": axes}
        peers = groups[g]
        cand = []
        for p in peers:
            if p["id"] == r["id"]:
                continue
            pv = []
            for key, _ in RADAR_AXES[g]:
                v = _per90(p, key)
                d = dist[g][key]
                pv.append(float((d < v).sum() + 0.5 * (d == v).sum()) / len(d) if v is not None else 0.0)
            a, b = np.array(vec) - 0.5, np.array(pv) - 0.5
            den = float(np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
            cand.append((float(a @ b) / den, p))
        cand.sort(key=lambda c: -c[0])
        out[r["id"]]["similar"] = [{"id": p["id"], "name": p["name"], "team": p["team"], "similarity": round(s, 2)} for s, p in cand[:3]]
    return out


def team_radars(season: dict, clubs: list[str]) -> dict:
    """Team style on eight axes, scaled 0-1 between the lowest and highest club in the league."""
    if not season:
        return {}
    agg: dict[str, dict[str, list[float]]] = {c: {} for c in season["clubs"]}
    for m in season["matches"]:
        for c, t in m["teams"].items():
            for _, _, field, _ in TEAM_AXES:
                if t.get(field) is not None:
                    agg[c].setdefault(field, []).append(float(t[field]))
    means = {c: {f: float(np.mean(v)) for f, v in d.items()} for c, d in agg.items()}
    out = {}
    for c in clubs:
        axes = []
        for key, label, field, lower in TEAM_AXES:
            vals = [means[k][field] for k in means if field in means[k]]
            lo, hi = min(vals), max(vals)
            v = means[c].get(field)
            scaled = 0.5 if v is None or hi == lo else (v - lo) / (hi - lo)
            axes.append({"key": key, "label": label, "value": None if v is None else round(v, 3), "scaled": round(1.0 - scaled if lower else scaled, 2)})
        out[c] = axes
    return out
