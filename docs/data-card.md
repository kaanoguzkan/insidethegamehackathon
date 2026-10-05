# Data card: the Lumen League

**What it is.** Synthetic, football-realistic matches for six fictional clubs (Harbour City, Northbridge
Athletic, Redmoor United, Kestrel Vale, Aldergate Rovers, Saltmarsh Town), 25 generated players each. No
real person, club, crest, footage or data is used. Player names are generated from syllables and checked
against a denylist of well-known real surnames.

**How it is made.** `sim/engine.py`: 22 players and a ball at 5 Hz, nine formations that change shape with
the ball (`sim/tactics.py`), choreographed set pieces (`sim/setpieces.py`), pressing and stand-off
distances driven by style dials, goal-side marking, transitions, set pieces,
stamina and substitutions, fouls and cards, with xG and xPass models shared with the interpreter. Matches
are deterministic for a seed.

**Realism.** `matchmind report-realism` checks 19 league averages against target bands for typical
top-flight football; a test enforces them. Means over 100 matches:

| Metric (per match, both teams unless noted) | Mean | Band |
|---|---|---|
| Goals | 2.58 | 2.4-3.2 |
| Shots / on target | 26.2 / 7.8 | 20-30 / 6.5-11.5 |
| Passes / completion | 1,103 / 79% | 850-1,150 / 78-86% |
| Possession of the larger side | 56% | 35-65% |
| Distance per outfield starter | 11.9 km | 9.5-12 |
| Fastest player speed | 34.8 km/h | 31-36.5 |
| Sprints per team | 73 | 35-120 |
| Tackles / interceptions / fouls | 32.2 / 34.5 / 20.1 | 28-55 / 14-40 / 18-30 |
| Corners / throw-ins / goal kicks | 10.7 / 67.8 / 26.2 | 7-14 / 60-110 / 12-28 |
| Clearances / offsides / yellow cards | 32.4 / 5.1 / 2.8 | 28-70 / 3-11 / 1.5-5.5 |
| Pressure events | 217 | 200-520 |

Adding phase shapes and set pieces meant re-calibrating (see [tactics.md](tactics.md)). Calibration fixed structural problems, not just numbers: unmarked attackers in the box (shots came from
the six-yard box), pressure events that ignored the pressing dial, teleporting set-piece takers (250 km/h
"sprints"), and excess penalties (about 3 a match; now about 0.3).

**Formats.** Events: JSON, `matchId`, `seq`, `type`, `clock`, `team`, `player`, `location`/`end` in metres
on a 105 x 68 m pitch (home attacks +x in the first half). Tracking: 5 Hz, 22 player slots plus the ball,
0.1 m integers, a ball-in-play flag; a slot table records substitutions.

**Known limits.** Simplified physics and tactics (no aerial duels, injuries or weather), no real
league's distributions, and styles are exaggerated so stories are detectable. It is a stand-in for a data
provider, not a model of any real team.
