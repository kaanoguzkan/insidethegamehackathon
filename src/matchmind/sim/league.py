"""The fictional "Lumen League": six clubs with distinct playing styles and generated squads.

Everything here is invented. Club names, crests and players are fictional, and generated
player names are checked against a denylist of well-known real footballers so the dataset
cannot be mistaken for (or infringe on) real people.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .teams import ATTRS, Club, Player, Style

LEAGUE_NAME = "Lumen League"
LEAGUE_SEED = 2026

# (id, name, short, primary, secondary, strength, style)
_CLUBS: list[tuple[str, str, str, str, str, float, Style]] = [
    (
        "HAR", "Harbour City", "Harbour", "#5BA8E0", "#FFFFFF", 1.08,
        # Positional play: fullbacks step inside, a false nine, short goal kicks and short corners.
        Style("4-3-3", press_intensity=0.80, press_height=0.80, directness=0.25, tempo=0.65,
              width=0.70, line_height=0.80, counter_bias=0.30,
              fullbacks="inverted", pivot="stay", striker="false9", build_up="short",
              corners="short", corner_defence="zonal"),
    ),
    (
        "NOR", "Northbridge Athletic", "Northbridge", "#C8102E", "#FFFFFF", 1.04,
        # Gegenpress and fast breaks: overlapping fullbacks, a dropping pivot, man-marked corners.
        Style("4-2-3-1", press_intensity=0.85, press_height=0.70, directness=0.60, tempo=0.75,
              width=0.55, line_height=0.60, counter_bias=0.80,
              fullbacks="overlap", pivot="drop", build_up="mixed", corners="near", corner_defence="man"),
    ),
    (
        "RED", "Redmoor United", "Redmoor", "#7A1F2B", "#E8D9B0", 1.00,
        # Direct and physical: flat banks of four, long goal kicks, far-post corners, a long throw.
        Style("4-4-2", press_intensity=0.50, press_height=0.45, directness=0.70, tempo=0.55,
              width=0.60, line_height=0.45, counter_bias=0.60,
              fullbacks="overlap", build_up="long", corners="far", corner_defence="man", long_throws=True),
    ),
    (
        "KES", "Kestrel Vale", "Kestrel", "#1F7A4D", "#F2C94C", 0.97,
        # A back three with wing-backs as the width: 5-4-1 out of possession, 3-2-5 in it.
        Style("3-4-3", press_intensity=0.60, press_height=0.55, directness=0.45, tempo=0.60,
              width=0.90, line_height=0.55, counter_bias=0.50,
              build_up="mixed", corners="mixed", corner_defence="zonal"),
    ),
    (
        "ALD", "Aldergate Rovers", "Aldergate", "#2B2D6E", "#C9CCE8", 0.94,
        # A low block with a back five and a counter-attacking pair: long goal kicks, man-marked corners.
        Style("5-3-2", press_intensity=0.40, press_height=0.20, directness=0.70, tempo=0.50,
              width=0.50, line_height=0.25, counter_bias=0.85,
              build_up="long", corners="far", corner_defence="man"),
    ),
    (
        "SAL", "Saltmarsh Town", "Saltmarsh", "#E58A1F", "#1B1B1B", 0.92,
        # A lone pivot who drops into a back three to build, overlapping fullbacks, edge-of-box corners.
        Style("4-1-4-1", press_intensity=0.55, press_height=0.50, directness=0.50, tempo=0.55,
              width=0.65, line_height=0.50, counter_bias=0.55,
              fullbacks="overlap", pivot="drop", build_up="short", corners="edge", corner_defence="mixed"),
    ),
]  # fmt: skip

# Squad template: 25 players per club.
_SQUAD = (
    ["GK"] * 3 + ["CB"] * 4 + ["LB"] * 2 + ["RB"] * 2 + ["DM"] * 2 + ["CM"] * 4
    + ["AM"] * 2 + ["LW"] * 2 + ["RW"] * 2 + ["ST"] * 2
)  # fmt: skip

# Mean attributes by position:      pace stam pass  vis  drib fin  def  agg  keep
_POS_MEANS = {
    "GK": (50, 60, 58, 60, 40, 25, 50, 50, 74),
    "CB": (62, 70, 62, 58, 50, 35, 76, 72, 10),
    "LB": (74, 78, 66, 62, 64, 42, 68, 62, 10),
    "RB": (74, 78, 66, 62, 64, 42, 68, 62, 10),
    "DM": (62, 80, 72, 70, 62, 45, 72, 72, 10),
    "CM": (66, 80, 74, 72, 68, 55, 60, 62, 10),
    "AM": (70, 72, 76, 78, 76, 66, 42, 52, 10),
    "LW": (80, 74, 68, 68, 78, 68, 38, 50, 10),
    "RW": (80, 74, 68, 68, 78, 68, 38, 50, 10),
    "ST": (74, 70, 60, 62, 68, 78, 32, 58, 10),
}  # fmt: skip

_NUMBERS = {
    "GK": [1, 13, 31], "CB": [4, 5, 15, 25], "LB": [3, 18], "RB": [2, 22],
    "DM": [6, 14], "CM": [8, 16, 20, 28], "AM": [10, 21], "LW": [11, 17],
    "RW": [7, 19], "ST": [9, 23],
}  # fmt: skip

_FIRST_NAMES = [
    "Adrian", "Alex", "Andre", "Ben", "Callum", "Dario", "Declan", "Elias", "Emil", "Felix",
    "Gabriel", "Hugo", "Idris", "Ivan", "Jonas", "Kai", "Karim", "Leon", "Luca", "Malik",
    "Marco", "Mateo", "Nico", "Noah", "Omar", "Oscar", "Pablo", "Rafael", "Reuben", "Samuel",
    "Stefan", "Tariq", "Theo", "Tomas", "Viktor", "Yusuf", "Zane", "Ayo", "Bruno", "Cem",
    "Dani", "Eren", "Finn", "Gustav", "Hassan", "Ilya", "Joel", "Kofi", "Lars", "Mehmet",
]  # fmt: skip
_ONSETS = [
    "Bra", "Cal", "Dor", "Fen", "Gar", "Hal", "Jor", "Kel", "Lan", "Mar", "Nor", "Ol", "Pel",
    "Quin", "Rav", "Sol", "Tal", "Tre", "Ul", "Vas", "Vor", "Wex", "Yar", "Zan", "Ash", "Bel",
    "Dev", "Eld", "Fal", "Grey", "Hol", "Ivar", "Kov", "Lor", "Mor", "Oss", "Pran", "Rowe",
]  # fmt: skip
_MIDDLES = ["a", "e", "i", "o", "an", "en", "ar", "el", "or", "in", "ad", "er"]
_ENDINGS = [
    "ton", "ford", "ley", "man", "son", "ez", "ov", "stein", "berg", "wick", "ham", "ard",
    "ini", "ado", "ell", "ski", "dal", "mont", "sen", "worth",
]  # fmt: skip

# Famous real surnames we never want to generate, even by accident.
_DENYLIST = {
    "messi", "ronaldo", "haaland", "salah", "kane", "mbappe", "neymar", "benzema", "modric",
    "rooney", "gerrard", "lampard", "beckham", "henry", "bergkamp", "drogba", "zidane",
    "maldini", "pirlo", "xavi", "iniesta", "ramos", "pique", "casillas", "buffon", "neuer",
    "kroos", "ozil", "pogba", "kante", "sterling", "foden", "saka", "rice", "bellingham",
    "debruyne", "hazard", "aguero", "vardy", "son", "mane", "firmino", "suarez", "cavani",
    "lewandowski", "muller", "ibrahimovic", "totti", "cantona", "giggs", "scholes", "terry",
    "ferdinand", "vidic", "van dijk", "alisson", "ederson", "walker", "stones", "trippier",
}  # fmt: skip


def _surname(rng: random.Random) -> str:
    parts = [rng.choice(_ONSETS)]
    if rng.random() < 0.55:
        parts.append(rng.choice(_MIDDLES))
    parts.append(rng.choice(_ENDINGS))
    return "".join(parts).capitalize()


def _player_name(rng: random.Random, used: set[str]) -> str:
    while True:
        first, last = rng.choice(_FIRST_NAMES), _surname(rng)
        full = f"{first} {last}"
        if last.lower() in _DENYLIST or full in used:
            continue
        used.add(full)
        return full


def _clip(v: float, lo: float = 35, hi: float = 95) -> int:
    return int(round(min(hi, max(lo, v))))


def _make_squad(club_id: str, strength: float, rng: random.Random, used: set[str]) -> list[Player]:
    counters: dict[str, int] = {}
    squad: list[Player] = []
    for pos in _SQUAD:
        k = counters.get(pos, 0)
        counters[pos] = k + 1
        means = _POS_MEANS[pos]
        shift = (strength - 1.0) * 40
        # A player's overall quality moves all of their attributes together, plus per-attribute noise.
        form = rng.gauss(0, 4)
        attrs = {
            a: _clip(m + shift + form + rng.gauss(0, 5), 5 if a == "keeping" and pos != "GK" else 35)
            for a, m in zip(ATTRS, means, strict=True)
        }
        if pos != "GK":
            attrs["keeping"] = 10
        number = _NUMBERS[pos][k]
        squad.append(
            Player(
                id=f"{club_id}-{number:02d}",
                club=club_id,
                number=number,
                name=_player_name(rng, used),
                pos=pos,
                age=rng.randint(19, 35),
                attrs=attrs,
            )
        )
    return squad


def generate_league(seed: int = LEAGUE_SEED) -> dict[str, Club]:
    """Build the six clubs and their squads. Deterministic for a given seed."""
    used: set[str] = set()
    clubs: dict[str, Club] = {}
    for cid, name, short, primary, secondary, strength, style in _CLUBS:
        rng = random.Random(f"{seed}:{cid}")
        clubs[cid] = Club(
            id=cid,
            name=name,
            short=short,
            colors={"primary": primary, "secondary": secondary},
            strength=strength,
            style=style,
            squad=_make_squad(cid, strength, rng, used),
        )
    return clubs


def league_to_dict(clubs: dict[str, Club]) -> dict:
    return {"league": LEAGUE_NAME, "clubs": [c.to_dict() for c in clubs.values()]}


def league_from_dict(d: dict) -> dict[str, Club]:
    return {c["id"]: Club.from_dict(c) for c in d["clubs"]}


def save_league(clubs: dict[str, Club], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(league_to_dict(clubs), indent=1) + "\n")


def load_league(path: Path | None = None) -> dict[str, Club]:
    """Load the committed league file, or generate the default league if there is none."""
    if path is not None and path.exists():
        return league_from_dict(json.loads(path.read_text()))
    return generate_league()
