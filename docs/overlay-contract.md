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

## Provenance

Every overlay says how it was made, so a renderer or an auditor never has to guess:

| Field | Values |
|---|---|
| `provenance.fallbackLevel` | 0 written by a model and verified first time; 1 after a retry, or mended by the Repairer (it only cuts out what failed); 2 template text; 3 stat graphic |
| `provenance.agents` | The agents that touched it, in order: `editor`, `router`, `cache`, `explainer`, `storyteller`, `localizer`, `composer`, `verifier`, `repairer`, `template`, `producer`. A cached overlay lists `cache` first, then the agents that originally wrote it |
| `provenance.verified` | True only if the Producer re-ran the Verifier on exactly this text and it passed (earned, not asserted) |
| `provenance.model` | `agent-team@<prompt version>` for model text, `template@<prompt version>` for templates, `offline-template@...` for the offline client |
| `provenance.evidenceRef` | The moment id whose evidence pack licensed the text |

## Timing

`displayAt` is on the match clock, so a renderer shows an overlay when *its* playback clock reaches it.
In the live design the viewer sits about 15 seconds behind the simulator (a broadcast delay), which is the
budget the agent workflow has to produce text; each beat carries a deadline and degrades to templates
rather than running late. The Brain's live endpoint (`POST /api/beats`, [brain-api.md](brain-api.md)) tightens that to a hard five seconds
for a request: a late model call costs only the upgrade from template text, never the overlay.

## Pitch graphics

`kind: "pitch_graphic"` overlays carry a `graphic` with geometry in pitch metres (x 0 to 105 along the pitch,
y 0 to 68 across), so a broadcaster's engine can draw them on its own pitch:

```json
{ "kind": "pitch_graphic", "anchor": {"type": "pitch"},
  "graphic": { "type": "offside_line", "team": "HAR",
    "shapes": [ {"shape": "line", "points": [{"x": 62.4, "y": 0}, {"x": 62.4, "y": 68}], "style": "dashed", "label": "Offside line"},
                {"shape": "circle", "points": [{"x": 64.1, "y": 21.0}], "radius": 1.4, "label": "Marco Quinski: 1.7 m beyond"} ] } }
```

Shapes are `line`, `arrow`, `polygon`, `circle` and `text`, with a style (`solid`, `dashed`, `dotted`) and an
emphasis (`primary`, `secondary`, `muted`). Graphic types are `offside_line` (measured from tracking when the
receiver is flagged), `run` (an off-ball run), `line_break` (a line-breaking pass) and `shot_trace` (a shot with
its xG). Captions are in the cohort's language and graphics share one lane, so they never pile up.

The match center also draws live layers straight from the tracking frame (pitch control, team shape, offside line,
passing options, run trails); those are a feature of the reference renderer, not part of the contract.
