# Metrics, indices and detection

Every threshold lives in `src/matchmind/intel/config.py` with its reasoning beside it.

## Window metrics

Per team over a time window: passes and accuracy, possession (time-based), tempo (passes per minute of
possession), progressive passes, final-third entries, field tilt, shots, xG, big chances, xT gained,
pressures, tackles, interceptions, sprints and front-line sprints, high regains, and PPDA. Match level:
possession changes and duels per minute, long-ball share, average possession length, event rate.

* **xG** and **xPass** are shared between the simulator and the interpreter (`core/models.py`), so the
  numbers a match is generated from are the numbers it is explained with.
* **xT** is fitted from simulated matches (`matchmind build-league-data`), not assumed.
* **Pass difficulty** is `10 x (1 - xPass)`, with pressure and lane blockage measured from tracking.

## Indices

* **Control vs chaos (0-100).** Mean of four z-scores (possession changes per minute, duels per minute,
  long-ball share, inverse possession length) against baselines measured over simulated five-minute
  windows, passed through a logistic. 50 is a typical five minutes of this league.
* **Pressure.** PPDA, pressures per minute and high regains, z-scored.
* **Rhythm.** Tempo, event rate, stoppage rate.

## Moment detection

| Moment | Trigger |
|---|---|
| goal, red card, penalty | the event |
| big chance | a shot of at least 0.30 xG |
| pressing collapse / surge | over 8 minutes against the 15 before: nearest-defender distance in the opponent half moves by 2.0 m or more, the pressure-event rate moves the same way by 25% or more, held at two consecutive minute evaluations |
| momentum swing | new leader of the 5-minute xT+xG gap ahead by 0.16, old leader ahead by 0.06 in the previous 10 minutes; once per 20 minutes |
| control / chaos flip | 3-minute mean chaos differs from the previous 10-minute mean by 22 points and crosses 50 |
| rhythm break | tempo changes by 30% against the previous 10 minutes |
| tactical shift | defensive line moves 7 m or width 10 m (3-minute vs 10-minute means of the defensive shape, sampled only while the opponent has the ball in the middle of the pitch), at two consecutive evaluations |
| fatigue drop | after 55', 10-minute sprint rate 60% below the first-half rate |
| physical highlight | a new match-best sprint of 33 km/h or a shot of 100 km/h |

### Why pressing is not detected from PPDA

In a five-minute window a team makes 0-3 defensive actions in the build-up zone, so PPDA jumps by a factor
of two on one tackle and flip-flopped between "collapse" and "surge". A 24-seed study measured candidate
rules against how often they fired by chance in the first hour of unscripted matches:

| Rule (8/15-minute windows) | False alarms per team-match | Scripted collapse caught |
|---|---|---|
| nearest-defender gap of 2.0 m alone | 15% | 92% |
| gap of 2.0 m plus pressure rate down 25%, held two minutes (chosen) | 4% | 88% |
| gap of 3.0 m alone | 2% | 71% |

On the full pipeline over 16 seeds, after teams learned to change shape with the ball (see
[tactics.md](tactics.md)), the chosen rule caught 15, a median 9 minutes after the change, and never fired as
a false collapse in 16 unscripted controls.

### Tactical shifts and shape that breathes with the ball

When teams change shape with possession, a defensive line legitimately sits higher or deeper depending on
who has the ball and where, and a naive detector fired 5.9 times a match. Defensive shape is now sampled
only while the opponent has the ball in the middle zone (35-75 m from the defending team's own goal), which
brought the noise down to a 99th percentile of 8.4 m for the change in line height and 10.0 m for width
(3-minute against 10-minute means, 30 matches). Operating points, with false alarms per match and how
often the scripted high-line change by Aldergate at 60:00 was found in 20 seeds:

| Line / width threshold | False alarms per match | Scripted shift found |
|---|---|---|
| 6.5 m / 10 m | 1.0 | 17/20 |
| **7 m / 10 m (chosen)** | **0.7** | **17/20** |
| 7.5 m / 10 m | 0.6 | 16/20 |
| 8 m / 10 m | 0.4 | 14/20 |

The other detectors are noisier than the pressing detector (roughly 3.4 chaos flips and 2.7 momentum swings
per match, 1.0 tactical shifts); they carry lower salience.

## Evidence packs

A pack holds the moment type and time, the teams and players involved, `metrics` (each with before,
after, delta, percentage change, all computed from the rounded numbers shown), a `consistent` flag per
metric (does it move with or against the story?), the windows compared, the event ids behind it and a
glossary of the metrics it mentions. Agents cite its keys; the Verifier checks against it.

## How the generated text is measured

Three layers, from cheapest to most independent:

1. **The Verifier** runs on every text before it is shown (numbers, names, references, policy, language, length). It is deterministic and has adversarial tests.
2. **Quality gates** (`matchmind evals`, CI-gated) over the three replay packages: numeric fidelity, verification rate, language correctness, persona
   separation (analyst text 3 to 5 times as number-dense as casual text), honesty about contradicting metrics, recaps verified, analytics
   consistency checks, and the same figures for the unreliable-model and outage runs. See the README's measured results.
3. **Live and independent measurements**: the live fast path's latency and fallback rates ([agents.md](agents.md#measured-on-the-deployed-brain)), and Foundry's
   groundedness, relevance, coherence and fluency evaluators over a sample of overlay text ([foundry.md](foundry.md#evaluations)).
