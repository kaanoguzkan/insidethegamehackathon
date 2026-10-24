"""Command-line entry point: ``matchmind --help``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.paths import league_dir


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
    from .tracking.frames import write_chunks

    clubs = _load_clubs()
    res = simulate(args.match_id, clubs[args.home], clubs[args.away], seed=args.seed)
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
    """Simulate a demo (or any fixture and seed) and build the full replay package (agents included)."""
    from .core.paths import replays_dir
    from .demos import get_demo
    from .runner import build_replay, write_replay
    from .sim.engine import simulate

    clubs = _load_clubs()
    if args.demo:
        demo = get_demo(args.demo)
        home, away, seed, match_id = demo.home, demo.away, demo.seed, demo.id
    else:
        if not (args.home and args.away and args.seed is not None and args.match_id):
            print("name a demo from data/demos.json, or give --home, --away, --seed and --match-id", file=sys.stderr)
            return 2
        home, away, seed, match_id = args.home, args.away, args.seed, args.match_id
    result = simulate(match_id, clubs[home], clubs[away], seed=seed)
    replay = build_replay(result, llm=args.llm)
    out = write_replay(replay, result, Path(args.out) if args.out else replays_dir() / match_id)
    i = replay.info
    print(f"{match_id}: {result.meta['score']} | {i['moments']} moments, {i['overlays']} overlays, "
          f"levels {i['levels']} -> {out}")
    return 0


def cmd_pick_demos(args: argparse.Namespace) -> int:
    """Play a fixture over a range of seeds and list the most watchable matches."""
    from .sim.pick import pick

    lo, _, hi = args.seeds.partition("-")
    for r in pick(args.home, args.away, range(int(lo), int(hi or lo) + 1), workers=args.workers)[: args.top]:
        score = "-".join(str(v) for v in r["score"].values())
        print(f"seed {r['seed']:>5}  {score:<5} pts {r['points']:>3}  reds {r['reds']}  lead changes {r['lead_changes']}  goals {r['goals']}")
        for c in r["changes"]:
            print(f"             min {c[0]:>5}  {c[1]}  {c[2]}  -> {c[3]}")
    return 0


def cmd_vision_eval(args: argparse.Namespace) -> int:
    """Read a demo match through the video model (render, detect, track) and print how close what it saw is to the simulator's truth."""
    import json
    import time

    from .core.paths import league_dir
    from .demos import get_demo
    from .live.feed import build_feed
    from .sim.engine import simulate
    from .sim.league import load_league
    from .tracking.frames import iter_chunks
    from .vision.feed import events_for_anchoring
    from .vision.track import VideoTracker

    for demo_id in args.demos:
        d = get_demo(demo_id)
        clubs = load_league(league_dir() / "league.json")
        res = simulate(d.id, clubs[d.home], clubs[d.away], seed=d.seed)
        chunks = list(iter_chunks(res))[: args.chunks or None]
        ev = events_for_anchoring(build_feed(res), res.meta["hz"]) if not args.no_events else []
        vt = VideoTracker(chunks[0].frames[0])
        t0 = time.perf_counter()
        for ch in chunks:
            a, b = ch.first_frame, ch.first_frame + ch.n
            vt.process(ch, [e for e in ev if a <= e[0] < b])
        out = {"demo": d.id, "chunks": len(chunks), "secondsPerChunk": round((time.perf_counter() - t0) / len(chunks), 3), "events": not args.no_events, **vt.stats.summary()}
        print(json.dumps(out))
    return 0


def cmd_vision_bake(args: argparse.Namespace) -> int:
    """Read demo matches through the video model once and save the result (data/vision/<demo>.mmv) for the image to carry: a live match then costs no video analysis."""
    import time

    from .core.paths import league_dir
    from .demos import get_demo
    from .live.feed import build_chunks, build_feed
    from .sim.engine import simulate
    from .sim.league import load_league
    from .vision.feed import events_for_anchoring
    from .vision.shared import SharedVision

    for demo_id in args.demos:
        d = get_demo(demo_id)
        clubs = load_league(league_dir() / "league.json")
        res = simulate(d.id, clubs[d.home], clubs[d.away], seed=d.seed)
        truth = [(end, name, data) for end, name, data in build_chunks(res)]
        sv = SharedVision(d.id, truth, events_for_anchoring(build_feed(res), res.meta["hz"]))
        sv.results, sv.baked = {}, False  # bake afresh, even if there is a file already
        t0 = time.perf_counter()
        sv.run_all()
        out = SharedVision.baked_path(d.id)
        sv.dump(out)
        print(f"{d.id}: {len(sv.results)} chunks in {time.perf_counter() - t0:.0f} s -> {out} ({out.stat().st_size // 1024} KB) {sv.stats()}", flush=True)
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

    pk = sub.add_parser("pick-demos", help="play a fixture over a range of seeds and list the most watchable matches")
    pk.add_argument("home")
    pk.add_argument("away")
    pk.add_argument("--seeds", default="1-60", help="a seed or a range such as 1-60")
    pk.add_argument("--top", type=int, default=8)
    pk.add_argument("--workers", type=int, default=None)
    pk.set_defaults(fn=cmd_pick_demos)

    ve = sub.add_parser("vision-eval", help="read demo matches through the video model and report how close the tracking it rebuilt is to the truth")
    ve.add_argument("demos", nargs="+", help="demo ids from data/demos.json")
    ve.add_argument("--chunks", type=int, default=0, help="only the first N chunks of 5 s (0: the whole match)")
    ve.add_argument("--no-events", action="store_true", help="do not use the event feed to tell players apart")
    ve.set_defaults(fn=cmd_vision_eval)

    vb = sub.add_parser("vision-bake", help="read demo matches through the video model once and save the result for the Docker image to carry")
    vb.add_argument("demos", nargs="+", help="demo ids from data/demos.json")
    vb.set_defaults(fn=cmd_vision_bake)

    r2 = sub.add_parser("build-replay", aliases=["run-local"], help="simulate a demo match and write a replay package")
    r2.add_argument("demo", nargs="?", default=None, help="a demo id from data/demos.json")
    r2.add_argument("--home", default=None)
    r2.add_argument("--away", default=None)
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
