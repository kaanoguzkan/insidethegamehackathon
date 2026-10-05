"""Data model for the fictional league: players, clubs, playing styles and formations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .tactics import FORMATIONS_FULL, TAGS, formation_names

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

    # Tags (see tactics.py): how the shape is played and how set pieces are taken and defended.
    fullbacks: str = "hold"  # overlap | inverted | hold
    pivot: str = "stay"  # stay | drop (the holding midfielder drops between the centre-backs)
    striker: str = "target"  # target | false9
    build_up: str = "mixed"  # short | mixed | long (goal kicks and restarts)
    corners: str = "mixed"  # near | far | short | edge | mixed
    corner_defence: str = "zonal"  # zonal | man | mixed
    long_throws: bool = False  # a throw-in specialist hurls it into the box

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def tags(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in TAGS}

    @classmethod
    def from_dict(cls, d: dict) -> Style:
        s = cls(**d)
        for k, allowed in TAGS.items():
            if getattr(s, k) not in allowed:
                raise ValueError(f"style tag {k}={getattr(s, k)!r} is not one of {allowed}")
        return s


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


def formation_slots(name: str) -> list[tuple[str, float, float]]:
    """Base (nominal) slots, goalkeeper first: ``(role, depth, width)``."""
    try:
        return FORMATIONS_FULL[name]["base"]
    except KeyError:
        raise ValueError(f"unknown formation {name!r}; choose from {formation_names()}") from None


# Kept for callers that only want the nominal formations.
FORMATIONS = {k: v["base"] for k, v in FORMATIONS_FULL.items()}
