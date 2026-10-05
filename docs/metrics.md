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
| tactical shift | defensive line moves 14 m or width 10 m (3-minute vs 10-minute means), at two consecutive evaluations |
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

On the full pipeline over 16 seeds the chosen rule caught 15, a median 6 minutes after the change, and
never fired as a false collapse in 16 unscripted controls. Line height has a standard deviation of about
6 m on its own, which is why tactical shifts need 14 m. The other detectors are noisier (roughly 2.5 chaos
flips, 2.5 tactical shifts and 1.8 momentum swings per match); they carry lower salience.

## Evidence packs

A pack holds the moment type and time, the teams and players involved, `metrics` (each with before,
after, delta, percentage change, all computed from the rounded numbers shown), a `consistent` flag per
metric (does it move with or against the story?), the windows compared, the event ids behind it and a
glossary of the metrics it mentions. Agents cite its keys; the Verifier checks against it.
