"""Command-line entry point: ``matchmind --help``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.paths import league_dir, scenarios_dir


def _load_clubs():
    from .sim.league import load_league

    return load_league(league_dir() / "league.json")


def cmd_report_realism(args: argparse.Namespace) -> int:
    from .sim import realism

    samples = realism.run_realism(args.matches, workers=args.workers)
    rows = realism.evaluate(samples)
    print(realism.format_report(rows, args.matches))
    return 0 if all(r.ok for r in rows) else 1


def cmd_build_league_data(args: argparse.Namespace) -> int:
    """Write league.json, the fitted xT grid and the index baselines into data/league/."""
    from .intel.baselines import compute_baselines
    from .intel.xt import fit_xt
    from .sim.engine import simulate
    from .sim.league import generate_league, save_league

    out = Path(args.out) if args.out else league_dir()
    clubs = generate_league()
    save_league(clubs, out / "league.json")
    print(f"wrote {out / 'league.json'}")

    ids = list(clubs)
    fits = []
    for i in range(args.matches):
        h, a = ids[i % len(ids)], ids[(i * 7 + 1) % len(ids)]
        if h == a:
            a = ids[(ids.index(a) + 1) % len(ids)]
        res = simulate(f"x{i:04d}", clubs[h], clubs[a], seed=9000 + i)
        fits.append((res.events, res.meta))
    grid = fit_xt(fits)
    grid.save(out / "xt_grid.json")
    print(f"wrote {out / 'xt_grid.json'} (fitted from {len(fits)} matches)")

    base = compute_baselines(args.matches, workers=args.workers)
    (out / "baselines.json").write_text(json.dumps(base, indent=1) + "\n")
    print(f"wrote {out / 'baselines.json'}")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from .sim.engine import simulate
    from .sim.scenarios import load_scenario
    from .tracking.frames import write_chunks

    clubs = _load_clubs()
    scenario = None
    home, away, seed = args.home, args.away, args.seed
    if args.scenario:
        path = Path(args.scenario)
        if not path.exists():
            path = scenarios_dir() / f"{args.scenario}.yaml"
        scenario = load_scenario(path)
        home, away, seed = scenario.home, scenario.away, scenario.seed
    res = simulate(args.match_id, clubs[home], clubs[away], seed=seed, scenario=scenario)
    out = Path(args.out) / args.match_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(json.dumps(res.meta))
    with (out / "events.jsonl").open("w") as f:
        for e in res.events:
            f.write(json.dumps(e) + "\n")
    n = write_chunks(res, out / "tracking")
    print(f"{res.meta['home']['name']} {res.meta['score'][res.meta['home']['id']]}-"
          f"{res.meta['score'][res.meta['away']['id']]} {res.meta['away']['name']}: "
          f"{len(res.events)} events, {n} tracking chunks -> {out}")
    return 0


def cmd_export_schemas(args: argparse.Namespace) -> int:
    from .core.contracts import schema_models

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, model in schema_models().items():
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
        print(f"wrote {path}")
    return 0


def cmd_build_replay(args: argparse.Namespace) -> int:
    """Simulate a scenario and build the full replay package (agents included)."""
    from .core.paths import replays_dir
    from .runner import build_replay, write_replay
    from .sim.engine import simulate
    from .sim.scenarios import load_scenario

    clubs = _load_clubs()
    path = Path(args.scenario)
    if not path.exists():
        path = scenarios_dir() / f"{args.scenario}.yaml"
    sc = load_scenario(path)
    seed = args.seed if args.seed is not None else sc.seed
    match_id = args.match_id or sc.id
    result = simulate(match_id, clubs[sc.home], clubs[sc.away], seed=seed, scenario=sc)
    replay = build_replay(result, llm=args.llm)
    out = write_replay(replay, result, Path(args.out) if args.out else replays_dir() / match_id)
    i = replay.info
    print(f"{sc.id}: {result.meta['score']} | {i['moments']} moments, {i['overlays']} overlays, "
          f"levels {i['levels']} -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="matchmind", description="MatchMind: explainable football match intelligence")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report-realism", help="check simulated league averages against target bands")
    r.add_argument("--matches", type=int, default=40)
    r.add_argument("--workers", type=int, default=None)
    r.set_defaults(fn=cmd_report_realism)

    b = sub.add_parser("build-league-data", help="write league, xT grid and index baselines to data/league/")
    b.add_argument("--matches", type=int, default=36)
    b.add_argument("--workers", type=int, default=None)
    b.add_argument("--out", default=None)
    b.set_defaults(fn=cmd_build_league_data)

    s = sub.add_parser("simulate", help="simulate a match and write events + tracking chunks")
    s.add_argument("--match-id", default="m0001")
    s.add_argument("--home", default="HAR")
    s.add_argument("--away", default="NOR")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--scenario", default=None, help="scenario name in data/scenarios or a YAML path")
    s.add_argument("--out", default="out")
    s.set_defaults(fn=cmd_simulate)

    e = sub.add_parser("export-schemas", help="write JSON Schemas for the public contracts to schemas/")
    e.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "schemas"))
    e.set_defaults(fn=cmd_export_schemas)

    r2 = sub.add_parser("build-replay", aliases=["run-local"], help="simulate a scenario and write a replay package")
    r2.add_argument("scenario", help="scenario name in data/scenarios or a YAML path")
    r2.add_argument("--seed", type=int, default=None)
    r2.add_argument("--match-id", default=None)
    r2.add_argument("--llm", default=None, help="offline (default), openai or foundry")
    r2.add_argument("--out", default=None)
    r2.set_defaults(fn=cmd_build_replay)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
