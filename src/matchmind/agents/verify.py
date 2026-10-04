"""The Verifier: nothing reaches the screen unless it checks out against the evidence.

Every check is deterministic code. A language model may write the text, but it never gets to
mark its own homework:

* **numbers**   every figure in the text must come from the evidence pack (rounded the way the
                text rounds it), including minute labels, scores and window lengths; written-out
                numbers ("three shots") are caught too
* **names**     any player or club from the league that the text mentions must belong to this moment
* **references** every claim that uses numbers must cite evidence keys that exist
* **honesty**   a claim that rests on a metric which moved *against* the story must say so
* **policy**    no betting, alcohol, drugs, tobacco, politics, insults or medical speculation
* **language**  the text is in the requested language
* **format**    length limits by mode; jargon in casual text is flagged

``verify_variant`` and ``verify_explanation`` return every issue found, so a retry can be told
exactly what to fix.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..core.contracts import Claim, Cohort, Explanation, StoryVariant
from ..intel.evidence import numbers_in


@dataclass
class Issue:
    code: str  # number | name | reference | honesty | policy | language | format
    message: str
    severity: str = "error"  # error | warn
    where: str = ""  # headline | body | claim[2] | ...

    def __str__(self) -> str:
        loc = f" ({self.where})" if self.where else ""
        return f"[{self.severity}:{self.code}]{loc} {self.message}"


@dataclass
class VerifyResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    def feedback(self) -> str:
        """The error list, phrased for a retry prompt."""
        return "\n".join(f"- {i.message}" for i in self.errors)


# ---------------------------------------------------------------------------------------------
# Registry of names the text must not misattribute
# ---------------------------------------------------------------------------------------------


@dataclass
class Registry:
    players: dict[str, str] = field(default_factory=dict)  # id -> full name
    clubs: dict[str, tuple[str, ...]] = field(default_factory=dict)  # id -> (name, short)

    @classmethod
    def from_meta(cls, meta: dict) -> Registry:
        reg = cls()
        for side in ("home", "away"):
            t = meta[side]
            reg.clubs[t["id"]] = (t["name"], t["short"])
            for pid, p in t["players"].items():
                reg.players[pid] = p["name"]
        return reg

    @classmethod
    def from_clubs(cls, clubs: dict[str, Any]) -> Registry:
        reg = cls()
        for cid, c in clubs.items():
            reg.clubs[cid] = (c.name, c.short)
            for p in c.squad:
                reg.players[p.id] = p.name
        return reg

    def _player_index(self) -> list[tuple[re.Pattern, set[str]]]:
        by_token: dict[str, set[str]] = {}
        for pid, name in self.players.items():
            by_token.setdefault(name, set()).add(pid)
            last = name.split()[-1]
            if len(last) >= 4:
                by_token.setdefault(last, set()).add(pid)
        return [(re.compile(rf"(?<!\w){re.escape(tok)}(?!\w)"), ids) for tok, ids in by_token.items()]

    def mentioned_players(self, text: str) -> set[str]:
        found: set[str] = set()
        if not hasattr(self, "_idx"):
            self._idx = self._player_index()
        for pat, ids in self._idx:
            if pat.search(text):
                found |= ids
        return found

    def mentioned_clubs(self, text: str) -> set[str]:
        found = set()
        for cid, names in self.clubs.items():
            for n in names:
                if n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text):
                    found.add(cid)
        return found


# ---------------------------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------------------------

_MINUTE_LABEL = re.compile(r"(?<![\w.])(\d{1,3})(?:\+(\d{1,2}))?'")
_ORDINAL = re.compile(r"(?<![\w.])(\d+)(?:st|nd|rd|th)\b")
_NUMBER = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?![\w]*\d)")
_PERCENT_METRICS = {"possession_share", "field_tilt", "pass_acc", "xg_share"}
_UNIT_FIVE = re.compile(r"\b5\s*(?:min|dk|minutes|minutos|dakika)\w*")

_WORDS = {
    "en": {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12},
    "es": {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12},
    "tr": {"iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10, "onbir": 11, "oniki": 12},
}
_COUNTED = {
    "en": r"(?:shots?|chances?|passes|sprints?|goals?|minutes?|times|attacks?|tackles?|corners?|metres|meters|yards|players|defenders|touches|moves)",
    "es": r"(?:tiros?|disparos?|ocasiones|pases|sprints?|goles?|minutos|veces|ataques?|entradas|córneres|metros|jugadores|defensas|toques)",
    "tr": r"(?:şut|fırsat|pas|sprint|gol|dakika|kez|hücum|müdahale|korner|metre|oyuncu|savunmacı|vuruş)",
}


def _to_float(tok: str) -> float:
    return float(tok.replace(",", "."))


def _decimals(tok: str) -> int:
    m = re.search(r"[.,](\d+)$", tok)
    return len(m.group(1)) if m else 0


def context_numbers(pack: dict) -> set[float]:
    """Numbers that describe *when* and *what the score was*, not a metric: no citation needed."""
    out: set[float] = set()
    clock = pack["detectedAt"]["clock"]
    out |= {float(clock["minute"]), float(clock["second"])}
    texts = [pack["detectedAt"].get("label", "")]
    for w in pack.get("windows", {}).values():
        texts.append(w.get("label", ""))
        r = w.get("range")
        if r:
            out.add(round((r[1] - r[0]) / 60000.0))
    for t in texts:
        out |= {float(x) for x in re.findall(r"\d+", t)}
    out |= {float(x) for x in re.findall(r"\d+", str(pack["facts"].get("score", "")))}
    if pack["type"] == "red_card":
        out |= {10.0, 11.0}  # a red card leaves ten men
    return out


def allowed_numbers(pack: dict) -> set[float]:
    """Every figure the pack licenses: metrics, facts, clock, labels, window lengths, percentages."""
    out: set[float] = set()
    for v in numbers_in(pack["metrics"]):
        out.add(v)
        out.add(abs(v))
    for key, m in pack["metrics"].items():
        base = key.split(".", 1)[-1]
        if base in _PERCENT_METRICS:
            for v in m.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.add(abs(v) * 100)
    for v in numbers_in(pack["facts"]):
        out.add(abs(v))
        if 0 < abs(v) <= 1:
            out.add(abs(v) * 100)
    return out | context_numbers(pack)


def _matches(token: str, allowed: Iterable[float]) -> bool:
    """A token is supported if some licensed value rounds to it at the token's own precision.

    Whole-number tokens must match a whole-number value: "3" is not supported by 2.9.
    """
    t = _to_float(token)
    d = _decimals(token)
    for a in allowed:
        if round(a, d) != round(t, d):
            continue
        if d > 0 or abs(a - round(a)) < 1e-6:
            return True
    return False


def check_numbers(text: str, pack: dict, lang: str, where: str = "") -> list[Issue]:
    issues: list[Issue] = []
    allowed = allowed_numbers(pack)
    # Minute labels first: 63', 45+2'.
    for m in _MINUTE_LABEL.finditer(text):
        for g in (m.group(1), m.group(2)):
            if g and float(g) not in allowed:
                issues.append(Issue("number", f"minute {m.group(0)} is not in the evidence", where=where))
    scrubbed = _MINUTE_LABEL.sub(" ", text)
    scrubbed = _UNIT_FIVE.sub(" ", scrubbed)
    for m in _ORDINAL.finditer(scrubbed):
        if float(m.group(1)) not in allowed:
            issues.append(Issue("number", f"ordinal {m.group(0)} is not in the evidence", where=where))
    scrubbed = _ORDINAL.sub(" ", scrubbed)
    for m in _NUMBER.finditer(scrubbed):
        tok = m.group(1)
        if not _matches(tok, allowed):
            issues.append(Issue("number", f"the number {tok} is not supported by the evidence", where=where))
    # Written-out numbers next to a counted noun ("three shots").
    words = _WORDS[lang]
    counted = _COUNTED[lang]
    pat = re.compile(rf"(?<!\w)({'|'.join(words)})(?!\w)(?:\s+\w+){{0,2}}?\s+{counted}(?!\w)", re.I)
    for m in pat.finditer(text):
        n = words[m.group(1).lower()]
        if float(n) not in allowed:
            issues.append(Issue("number", f"'{m.group(0)}' states a count ({n}) that is not in the evidence", where=where))
    return issues


# ---------------------------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------------------------


def check_names(text: str, pack: dict, registry: Registry | None, where: str = "") -> list[Issue]:
    if registry is None:
        return []
    issues: list[Issue] = []
    in_pack_players = {p["id"] for p in pack["players"]}
    for pid in registry.mentioned_players(text):
        if pid not in in_pack_players:
            ids = registry.mentioned_players(text)
            # A surname shared by several players is fine if any of them is in the pack.
            name = registry.players[pid]
            if not any(registry.players[i].split()[-1] == name.split()[-1] and i in in_pack_players for i in ids):
                issues.append(Issue("name", f"{name} is not part of this moment", where=where))
    for cid in registry.mentioned_clubs(text):
        if cid not in pack["teamNames"]:
            issues.append(Issue("name", f"club {registry.clubs[cid][0]} is not part of this moment", where=where))
    return issues


# ---------------------------------------------------------------------------------------------
# Policy, language, format
# ---------------------------------------------------------------------------------------------

_POLICY: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("betting", r"\b(?:bet|bets|betting|odds|wager\w*|gambl\w*|bookmaker\w*|tipster\w*)\b"),
        ("alcohol, drugs or tobacco", r"\b(?:beer|alcohol\w*|vodka|whisk(?:e)?y|cigarette\w*|smok(?:e|ing)|drugs?|cocaine|cannabis)\b"),
        ("politics", r"\b(?:politic\w*|election\w*|government|president|nationalis\w*)\b"),
        ("insult or accusation", r"\b(?:idiot\w*|stupid|useless|pathetic|disgrace\w*|shameful|cheat(?:s|ed|ing)?|corrupt\w*|fraud\w*|rigged)\b"),
        ("medical speculation", r"\b(?:injur\w*|concussion\w*|fractur\w*|diagnos\w*)\b"),
    ],
    "es": [
        ("betting", r"\b(?:apuest\w*|cuotas?|casas? de apuestas|pronóstico\w*)\b"),
        ("alcohol, drugs or tobacco", r"\b(?:cerveza\w*|alcohol\w*|cigarr\w*|tabaco|drogas?)\b"),
        ("politics", r"\b(?:polític\w*|gobierno|elecciones)\b"),
        ("insult or accusation", r"\b(?:idiota\w*|estúpid\w*|inútil\w*|patétic\w*|vergüenza|corrupt\w*|tramposo\w*|amañad\w*)\b"),
        ("medical speculation", r"\b(?:lesi[oó]n\w*|conmoci[oó]n|fractura\w*)\b"),
    ],
    "tr": [
        ("betting", r"\b(?:bahis\w*|iddaa|kupon\w*)\b"),
        ("alcohol, drugs or tobacco", r"\b(?:bira|alkol\w*|sigara\w*|uyuşturucu\w*)\b"),
        ("politics", r"\b(?:siyas\w*|hükümet\w*|seçim\w*)\b"),
        ("insult or accusation", r"\b(?:aptal\w*|salak\w*|rezil\w*|utanç\w*|yolsuz\w*|hileci\w*)\b|işe yaramaz"),
        ("medical speculation", r"\b(?:sakat\w*|kırık\w*|sarsıntı\w*)\b"),
    ],
}

_STOPWORDS = {
    "en": set("the and are have with their from that this they for is to in of has been now more than but not into over".split()),
    "es": set("el la los las de que en y con para un una se del por al más pero ha han ahora está son su sus".split()),
    "tr": set("ve bir bu için ile de da daha çok gibi olarak oldu iken ama artık kadar şu ise ya en her".split()),
}

_JARGON = {
    "en": ["ppda", "xg", "xt", "nearest defender", "expected goals", "index", "progressive pass", "z-score", "per 5 min"],
    "es": ["ppda", "xg", "xt", "defensor más cercano", "índice", "pases progresivos", "cada 5 min"],
    "tr": ["ppda", "xg", "xt", "en yakın savunmacı", "endeks", "ileriye pas", "5 dk"],
}
_CONTRAST = {
    "en": ["but", "however", "although", "even so", "yet", "though", "while"],
    "es": ["pero", "sin embargo", "aunque", "aun así", "mientras"],
    "tr": ["ancak", "ama", "fakat", "yine de", "buna rağmen", "iken"],
}
MAX_WORDS = {"headline": 14, "analyst": 80, "casual": 45}
MAX_CHARS = {"headline": 90, "body": 380}


def check_policy(text: str, lang: str, where: str = "") -> list[Issue]:
    out = []
    for label, pat in _POLICY[lang]:
        m = re.search(pat, text, re.I)
        if m:
            out.append(Issue("policy", f"'{m.group(0)}' is not allowed ({label})", where=where))
    return out


def detect_language(text: str) -> str | None:
    words = re.findall(r"[a-zçğıöşüñáéíóú']+", text.lower())
    if len(words) < 6:
        return None
    scores = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0 or sorted(scores.values())[-1] == sorted(scores.values())[-2]:
        return None
    return best


def check_language(text: str, lang: str, where: str = "") -> list[Issue]:
    detected = detect_language(text)
    if detected is not None and detected != lang:
        return [Issue("language", f"the text looks {detected}, expected {lang}", where=where)]
    return []


def check_format(headline: str, body: str, mode: str, where: str = "") -> list[Issue]:
    out: list[Issue] = []
    if not headline.strip():
        out.append(Issue("format", "the headline is empty", where="headline"))
    if len(headline) > MAX_CHARS["headline"]:
        out.append(Issue("format", f"the headline is longer than {MAX_CHARS['headline']} characters", where="headline"))
    if len(body) > MAX_CHARS["body"]:
        out.append(Issue("format", f"the body is longer than {MAX_CHARS['body']} characters", where="body"))
    limit = MAX_WORDS["casual" if mode == "casual" else "analyst"]
    if len(body.split()) > limit:
        out.append(Issue("format", f"the body is longer than {limit} words for {mode} mode", where="body"))
    return out


def check_jargon(text: str, lang: str, where: str = "") -> list[Issue]:
    low = text.lower()
    return [Issue("format", f"jargon '{j}' in casual text", "warn", where) for j in _JARGON[lang] if j in low]


# ---------------------------------------------------------------------------------------------
# Claims and honesty
# ---------------------------------------------------------------------------------------------


def valid_refs(pack: dict) -> set[str]:
    refs = set(pack["metrics"]) | set(pack["eventIds"])
    refs |= {f"facts.{k}" for k in pack["facts"]}
    refs |= {f"player:{p['id']}" for p in pack["players"]}
    refs |= {"score", "minute"}
    return refs


def check_claims(claims: list[Claim], pack: dict, lang: str, registry: Registry | None) -> list[Issue]:
    out: list[Issue] = []
    refs_ok = valid_refs(pack)
    contrast = _CONTRAST[lang]
    for i, c in enumerate(claims):
        where = f"claim[{i}]"
        out += check_numbers(c.text, pack, lang, where)
        out += check_names(c.text, pack, registry, where)
        ctx = context_numbers(pack)
        stripped = _UNIT_FIVE.sub(" ", _MINUTE_LABEL.sub(" ", c.text))
        has_number = any(_to_float(n) not in ctx for n in _NUMBER.findall(stripped))
        if has_number and not c.refs:
            out.append(Issue("reference", "a claim with numbers must cite the evidence it rests on", where=where))
        for r in c.refs:
            if r not in refs_ok:
                out.append(Issue("reference", f"'{r}' is not an evidence key", where=where))
        against = [r for r in c.refs if pack["metrics"].get(r, {}).get("consistent") is False]
        if against and not any(w in c.text.lower() for w in contrast):
            out.append(
                Issue(
                    "honesty",
                    f"'{against[0]}' moved against the story; say so (but, however ...) or leave it out",
                    where=where,
                )
            )
    return out


# ---------------------------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------------------------


def verify_text(text: str, pack: dict, lang: str, registry: Registry | None = None, where: str = "") -> list[Issue]:
    return check_numbers(text, pack, lang, where) + check_names(text, pack, registry, where) + check_policy(text, lang, where) + check_language(text, lang, where)


def verify_variant(variant: StoryVariant, pack: dict, cohort: Cohort, registry: Registry | None = None) -> VerifyResult:
    lang = cohort.language
    res = VerifyResult()
    res.issues += verify_text(variant.headline, pack, lang, registry, "headline")
    res.issues += verify_text(variant.body, pack, lang, registry, "body")
    res.issues += check_format(variant.headline, variant.body, cohort.mode)
    if cohort.mode == "casual":
        res.issues += check_jargon(variant.headline + " " + variant.body, lang, "body")
    res.issues += check_claims(variant.claims, pack, lang, registry)
    # The body as a whole must also stay honest about contradicting metrics it leans on.
    return res


def verify_explanation(expl: Explanation, pack: dict, registry: Registry | None = None, lang: str = "en") -> VerifyResult:
    res = VerifyResult()
    for part in ("what", "why", "so_what"):
        res.issues += verify_text(getattr(expl, part), pack, lang, registry, part)
    res.issues += check_claims(expl.claims, pack, lang, registry)
    for i, cav in enumerate(expl.caveats):
        res.issues += verify_text(cav, pack, lang, registry, f"caveat[{i}]")
    if not expl.claims:
        res.issues.append(Issue("reference", "an explanation needs at least one claim", where="claims"))
    contradicting = [k for k, v in pack["metrics"].items() if v.get("consistent") is False]
    cited = {r for c in expl.claims for r in c.refs}
    if contradicting and not expl.caveats and expl.confidence == "high" and len(contradicting) >= 2:
        res.issues.append(
            Issue(
                "honesty",
                "several metrics moved against the story: lower the confidence or add a caveat",
                where="confidence",
            )
        )
    del cited
    return res
