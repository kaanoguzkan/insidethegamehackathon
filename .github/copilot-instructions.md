# Instructions for GitHub Copilot in this repository

MatchMind turns synthetic football events into explained, personalized match intelligence.
Read `SOLUTION PLAN.md` (status section first) and `docs/architecture.md` before changing behaviour.

## Rules that must not be broken
- **Code computes, models explain.** Numbers come from deterministic code (`intel/`, `tracking/`). A
  language model may only write or localize text, and every sentence it writes must pass
  `agents/verify.py`. Never loosen the Verifier to make a test pass; license the number in the
  evidence pack instead.
- **Evidence or it did not happen.** Agents may use only what is in an evidence pack. Metrics flagged
  `consistent: false` must be admitted, not cherry-picked.
- **Degrade, never drop.** A failing model must fall back to the template tier (`agents/templates.py`),
  never to silence.
- **Messages in the agent workflow are immutable** and edge conditions are mutually exclusive
  (`agents/workflow.py`); a shared mutable message once made two branches fire.
- All data is synthetic and the clubs and players are fictional. Do not add real names, crests or logos.
- No pronouns for people in generated text; no case suffixes attached to numbers (Turkish).

## Working here
- Python 3.12 with `uv`: `uv sync`, `uv run pytest -m "not slow"`, `uv run ruff check src tests apps`.
- Web: `cd web && pnpm install && pnpm typecheck && pnpm test && pnpm build`.
- After changing the simulator, run `uv run matchmind report-realism`; every metric must stay in its band.
- After changing templates, prompts or contracts: `uv run matchmind export-schemas`, rebuild packages with
  `uv run matchmind build-replay <scenario>` and run `uv run matchmind evals`.
- Check exit codes directly; do not pipe test output into `tail` in a chain you rely on.
