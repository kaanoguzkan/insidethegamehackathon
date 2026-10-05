# Overlay contract

Overlays are renderer-agnostic JSON: `schemas/overlay.schema.json`, generated from the pydantic model in
`core/contracts.py` (`matchmind export-schemas`; a test keeps them in sync). A broadcaster's graphics
engine can consume them as-is; the web app is a reference renderer.

Key fields: `kind` (lower_third, stat_card, shot_card, pass_card, speed_badge, player_tag, card_badge,
momentum_bar, control_meter, recap_card, ticker), `displayAt.matchMs` and `durationMs` on the **match
clock**, `priority` 1 (must show) to 5, `cohort`, `content` (headline, body, chips), `anchor` (screen
region or a player to follow) and `provenance` (agents, verified, evidence ref, fallback level, model and
prompt version).

## Cohorts

A cohort is `mode / language / perspective / focusPlayer`. Narrative overlays are written once per
cohort. Stat graphics have no narrative, so they are produced once per language with `mode = "any"` and
match every viewer who reads that language (`Cohort.covers`, mirrored in `web/src/lib/cohort.ts` and
tested on both sides).

## Timing

`displayAt` is on the match clock, so a renderer shows an overlay when *its* playback clock reaches it.
In the live design the viewer sits about 15 seconds behind the simulator (a broadcast delay), which is the
budget the agent workflow has to produce text; each beat carries a deadline and degrades to templates
rather than running late.
