# The match report (PDF)

Every replay package ships a printable report, `report.pdf`, about 17 pages, that explains the match, the
tactics, every position and every analytics view in plain language. It is built from the package alone
(`meta.json`, `analytics.json`, `moments.json`, `events.json`, `recaps.json`), so it can be rebuilt at any time,
and every sentence is assembled from numbers in the data: no language model writes any of it.

```bash
uv run matchmind build-pdf                      # every package in data/replays
uv run matchmind build-pdf pressing-collapse    # one package
uv run matchmind build-pdf --out reports/       # write <id>.pdf elsewhere
```

`matchmind build-replay` writes the report with the package when the `report` extra (reportlab) is installed
(`uv sync --extra report`; the dev group has it too). The match center links to it (**Report (PDF)** in the top
bar) and the Brain serves it at `GET /api/matches/{id}/report.pdf` for committed packages.

## What is in it

| Part | What it explains |
|---|---|
| Cover | Result, biggest swing, player of the match, how long each team spent in its main phase, the system's own full-time recap, contents |
| 1. The story of the match | Win probability with each goal's swing, the key moments with the reason and what each means, the expected-goals race |
| 2. Tactics | Each team in six shapes drawn on a pitch (nominal, build-up, settled attack, press, mid block, low block); rest defence; a timeline of the phases and the time in each; the line height, length and width measured in each phase; what usually sets each phase off; designed against measured formation; the club's tactic tags in words |
| 3. Every position | All eleven places for both teams: the general job in and out of possession, what this club asks of it (inverted fullbacks, a dropping pivot, a false nine, a press trap or man-marking), the player who filled it and his numbers |
| 4. The analytics | Shots and xG with a shot map; possession value; space and pitch control; packing and line breaks; passing networks drawn on the pitch; off-ball runs; physical load; transitions and pressing; set pieces; goalkeepers; season context and prediction. Each starts with a line saying what the numbers measure |
| 5. Every player | One table per team: minutes, passes, goals, assists, xG, xA, tackles, interceptions, pressures, packing, value, distance |
| 6. All nine formations compared | Build-up, attack, press and block shapes and rest defence of every formation, and what each press scheme and transition tag means |
| 7. What to trust | The caveats: synthetic data, fitted-on-simulation models, simplified pitch control, schematic shapes, formation-recognition accuracy |

## Notes

* The shape drawings are schematic. Depth is an ordering between a team's back and front lines, so the drawing
  shows who stands level with whom and how wide, not distances; the measured line height, length and width in the
  table beside them are real averages from the simulator.
* The text is English. The package carries the other languages' recaps, but the report's explanations are not
  translated yet.
* The layout uses only reportlab's built-in fonts, so the file is small (about 75 KB) and opens anywhere.
