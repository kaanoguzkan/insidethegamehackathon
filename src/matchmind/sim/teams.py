"""Data model for the fictional league: players, clubs, playing styles and formations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

ATTRS = (
    "pace",
    "stamina",
    "passing",
    "vision",
    "dribbling",
    "finishing",
    "defending",
    "aggression",
    "keeping",
)

# Position groups, used for lineup selection and for "front three"-style metrics.
GROUP = {
    "GK": "GK",
    "CB": "DEF", "LB": "DEF", "RB": "DEF", "LWB": "DEF", "RWB": "DEF",
    "DM": "MID", "CM": "MID", "AM": "MID", "LM": "MID", "RM": "MID",
    "LW": "ATT", "RW": "ATT", "ST": "ATT",
}  # fmt: skip

# Which squad positions can fill a formation role, best fit first.
ROLE_COMPAT = {
    "GK": ["GK"],
    "CB": ["CB"],
    "LB": ["LB", "RB", "CB"],
    "RB": ["RB", "LB", "CB"],
    "LWB": ["LB", "LW", "RB"],
    "RWB": ["RB", "RW", "LB"],
    "DM": ["DM", "CM", "CB"],
    "CM": ["CM", "DM", "AM"],
    "AM": ["AM", "CM", "LW", "RW"],
    "LM": ["LW", "CM", "AM"],
    "RM": ["RW", "CM", "AM"],
    "LW": ["LW", "RW", "AM", "ST"],
    "RW": ["RW", "LW", "AM", "ST"],
    "ST": ["ST", "AM", "LW", "RW"],
}


@dataclass
class Player:
    id: str
    club: str
    number: int
    name: str
    pos: str
    age: int
    attrs: dict[str, int]

    @property
    def overall(self) -> float:
        if self.pos == "GK":
            return self.attrs["keeping"] * 0.7 + self.attrs["passing"] * 0.15 + self.attrs["vision"] * 0.15
        a = self.attrs
        return (
            a["pace"] + a["stamina"] + a["passing"] + a["vision"] + a["dribbling"]
            + a["finishing"] + a["defending"]
        ) / 7.0  # fmt: skip

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Player:
        return cls(**d)


@dataclass
class Style:
    """How a club plays. Every field except ``formation`` is a 0..1 dial."""

    formation: str = "4-3-3"
    press_intensity: float = 0.6  # how hard pressers go after the ball
    press_height: float = 0.5  # how far up the pitch the team is willing to press
    directness: float = 0.4  # long/forward passing vs patient build-up
    tempo: float = 0.55  # decision speed and passing rhythm
    width: float = 0.6  # how wide the team stretches
    line_height: float = 0.5  # how high the defensive line sits
    counter_bias: float = 0.5  # how hard the team breaks after winning the ball

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Style:
        return cls(**d)


@dataclass
class Club:
    id: str
    name: str
    short: str
    colors: dict[str, str]
    strength: float
    style: Style
    squad: list[Player] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "short": self.short,
            "colors": self.colors,
            "strength": self.strength,
            "style": self.style.to_dict(),
            "squad": [p.to_dict() for p in self.squad],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Club:
        return cls(
            id=d["id"],
            name=d["name"],
            short=d["short"],
            colors=d["colors"],
            strength=d["strength"],
            style=Style.from_dict(d["style"]),
            squad=[Player.from_dict(p) for p in d["squad"]],
        )

    def player(self, player_id: str) -> Player:
        for p in self.squad:
            if p.id == player_id:
                return p
        raise KeyError(player_id)


# Formation slots, goalkeeper first: (role, depth, width). Depth is only an ordering used
# to stretch the team between its back and front lines; width is a 0..1 position across
# the pitch measured from the team's own left.
FORMATIONS: dict[str, list[tuple[str, float, float]]] = {
    "4-3-3": [
        ("GK", 0.03, 0.50),
        ("LB", 0.25, 0.10), ("CB", 0.22, 0.36), ("CB", 0.22, 0.64), ("RB", 0.25, 0.90),
        ("DM", 0.42, 0.50), ("CM", 0.54, 0.30), ("CM", 0.54, 0.70),
        ("LW", 0.80, 0.12), ("ST", 0.88, 0.50), ("RW", 0.80, 0.88),
    ],
    "4-2-3-1": [
        ("GK", 0.03, 0.50),
        ("LB", 0.25, 0.10), ("CB", 0.22, 0.36), ("CB", 0.22, 0.64), ("RB", 0.25, 0.90),
        ("DM", 0.42, 0.38), ("DM", 0.42, 0.62),
        ("LM", 0.66, 0.15), ("AM", 0.70, 0.50), ("RM", 0.66, 0.85),
        ("ST", 0.88, 0.50),
    ],
    "4-4-2": [
        ("GK", 0.03, 0.50),
        ("LB", 0.25, 0.10), ("CB", 0.22, 0.36), ("CB", 0.22, 0.64), ("RB", 0.25, 0.90),
        ("LM", 0.54, 0.10), ("CM", 0.50, 0.38), ("CM", 0.50, 0.62), ("RM", 0.54, 0.90),
        ("ST", 0.84, 0.40), ("ST", 0.84, 0.60),
    ],
    "3-5-2": [
        ("GK", 0.03, 0.50),
        ("CB", 0.22, 0.26), ("CB", 0.20, 0.50), ("CB", 0.22, 0.74),
        ("LWB", 0.52, 0.05), ("CM", 0.52, 0.34), ("DM", 0.42, 0.50), ("CM", 0.52, 0.66), ("RWB", 0.52, 0.95),
        ("ST", 0.84, 0.40), ("ST", 0.84, 0.60),
    ],
    "4-1-4-1": [
        ("GK", 0.03, 0.50),
        ("LB", 0.25, 0.10), ("CB", 0.22, 0.36), ("CB", 0.22, 0.64), ("RB", 0.25, 0.90),
        ("DM", 0.40, 0.50),
        ("LM", 0.60, 0.12), ("CM", 0.58, 0.38), ("CM", 0.58, 0.62), ("RM", 0.60, 0.88),
        ("ST", 0.88, 0.50),
    ],
}  # fmt: skip


def formation_slots(name: str) -> list[tuple[str, float, float]]:
    try:
        return FORMATIONS[name]
    except KeyError:
        raise ValueError(f"unknown formation {name!r}; choose from {sorted(FORMATIONS)}") from None
