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


def cmd_fit_models(args: argparse.Namespace) -> int:
    """Fit win probability, possession value and post-shot xG from simulated matches."""
    from .analytics.fit import fit_models, save_models

    models = fit_models(args.matches, workers=args.workers)
    path = save_models(models)
    print(f"wrote {path}")
    print(json.dumps(models["diagnostics"], indent=1))
    return 0


def cmd_build_season(args: argparse.Namespace) -> int:
    """Simulate last season and this season's first rounds into data/league/season.json."""
    from .analytics.season import build_season, save_season

    season = build_season(workers=args.workers)
    path = save_season(season)
    n = len(season["matches"])
    print(f"wrote {path} ({n} matches, {path.stat().st_size // 1024} KB)")
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


def cmd_evals(args: argparse.Namespace) -> int:
    from .core.paths import replays_dir
    from .evals import evaluate_all, gate

    reports = evaluate_all(Path(args.root) if args.root else replays_dir())
    fails: list[str] = []
    for r in reports:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        fails += gate(r)
    if args.out:
        Path(args.out).write_text(json.dumps(reports, indent=2, ensure_ascii=False) + "\n")
    for f in fails:
        print("GATE FAIL:", f, file=sys.stderr)
    return 1 if fails else 0


def cmd_foundry_evals(args: argparse.Namespace) -> int:
    """Run Foundry's built-in evaluators over the overlay text in the replay packages."""
    import asyncio

    from .foundry_evals import run

    res = asyncio.run(run(per_group=args.samples, model=args.model))
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str) + "\n")
    return 0 if all(g["status"] == "completed" for g in res["groups"].values()) else 1


def cmd_foundry_register(args: argparse.Namespace) -> int:
    """Register the agents (their prompts) in the Foundry project."""
    from .foundry_agents import register

    for a in register(model=args.model):
        print(f"{a['name']:26s} version {a['version']}  ({a['model']})")
    return 0


def cmd_foundry_host(args: argparse.Namespace) -> int:
    """Upload the newsroom as a Foundry hosted agent (a new version)."""
    from .foundry_host import build_zip, deploy

    if args.zip_only:
        z = build_zip(Path(args.zip_only))
        print(f"{z} ({z.stat().st_size / 1e6:.1f} MB)")
        return 0
    res = deploy(model=args.model)
    print(f"{res['name']} version {res['version']}: {res['status']}")
    return 0 if "active" in res["status"].lower() else 1


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


def cmd_build_pdf(args: argparse.Namespace) -> int:
    """Write report.pdf into replay packages (every committed one unless ids are given)."""
    from .core.paths import replays_dir
    from .report import build_report

    root = Path(args.root) if args.root else replays_dir()
    ids = args.ids or sorted(p.name for p in root.iterdir() if (p / "meta.json").exists())
    for match_id in ids:
        pkg = root / match_id
        if not (pkg / "meta.json").exists():
            print(f"no replay package at {pkg}; build it with: matchmind build-replay {match_id}", file=sys.stderr)
            return 1
        out = build_report(pkg, Path(args.out) / f"{match_id}.pdf" if args.out else None)
        print(f"{match_id}: {out} ({out.stat().st_size // 1024} KB)")
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

    f = sub.add_parser("fit-models", help="fit win probability, possession value and post-shot xG to data/league/models.json")
    f.add_argument("--matches", type=int, default=60)
    f.add_argument("--workers", type=int, default=None)
    f.set_defaults(fn=cmd_fit_models)

    bs = sub.add_parser("build-season", help="simulate the league's history (last season and this season so far) to data/league/season.json")
    bs.add_argument("--workers", type=int, default=None)
    bs.set_defaults(fn=cmd_build_season)

    s = sub.add_parser("simulate", help="simulate a match and write events + tracking chunks")
    s.add_argument("--match-id", default="m0001")
    s.add_argument("--home", default="HAR")
    s.add_argument("--away", default="NOR")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--scenario", default=None, help="scenario name in data/scenarios or a YAML path")
    s.add_argument("--out", default="out")
    s.set_defaults(fn=cmd_simulate)

    ev = sub.add_parser("evals", help="measure quality over replay packages; exits 1 if a gate fails")
    ev.add_argument("--root", default=None)
    ev.add_argument("--out", default=None)
    ev.set_defaults(fn=cmd_evals)

    fe = sub.add_parser("foundry-evals", help="score the overlay text with Microsoft Foundry's evaluators (needs FOUNDRY_PROJECT_ENDPOINT)")
    fe.add_argument("--samples", type=int, default=12, help="overlays per group (agent-written and template)")
    fe.add_argument("--model", default=None, help="deployment that judges the text (default MATCHMIND_LLM_MODEL)")
    fe.add_argument("--out", default=None, help="write the results here as JSON")
    fe.set_defaults(fn=cmd_foundry_evals)

    fr = sub.add_parser("foundry-register", help="register the agents as Foundry prompt agents (needs FOUNDRY_PROJECT_ENDPOINT)")
    fr.add_argument("--model", default=None, help="model deployment the agents use (default MATCHMIND_LLM_MODEL)")
    fr.set_defaults(fn=cmd_foundry_register)

    fh = sub.add_parser("foundry-host", help="upload the newsroom as a Foundry hosted agent (needs FOUNDRY_PROJECT_ENDPOINT)")
    fh.add_argument("--model", default=None, help="model deployment the hosted agent calls (default MATCHMIND_LLM_MODEL)")
    fh.add_argument("--zip-only", default=None, metavar="PATH", help="only write the zip here, do not upload")
    fh.set_defaults(fn=cmd_foundry_host)

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

    pdf = sub.add_parser("build-pdf", help="write the printable match report (report.pdf) for replay packages")
    pdf.add_argument("ids", nargs="*", help="replay ids; default: every package in data/replays")
    pdf.add_argument("--root", default=None, help="folder holding the packages")
    pdf.add_argument("--out", default=None, help="write <id>.pdf into this folder instead of the package")
    pdf.set_defaults(fn=cmd_build_pdf)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
