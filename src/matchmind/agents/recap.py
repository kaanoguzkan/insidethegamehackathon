"""Preview, half-time and full-time recaps.

Like moment stories, a recap is written from an evidence pack (``intel.recap``) and checked by the
Verifier before it is published. The template tier below needs no model and is the fallback; the
Recap Writer agent (Foundry Agent Service in the Azure deployment) writes richer text on top.

Rules kept throughout: no pronouns for people (the data names them, nothing more), and no case
suffixes attached to numbers (Turkish before/after pairs use "X iken Y oldu").
"""

from __future__ import annotations

import re

from ..core.contracts import Chip, Cohort, Provenance, Recap
from . import templates as T

_LEAD = re.compile(r"^\s*\d+(?:\+\d+)?'\s*")

TAGS = {
    "en": {"press_high": "press high", "counter": "break fast on the counter", "direct": "play direct", "patient": "build patiently", "deep": "defend deep", "wide": "use the width"},
    "es": {"press_high": "presiona arriba", "counter": "sale rápido al contraataque", "direct": "juega directo", "patient": "construye con paciencia", "deep": "defiende atrás", "wide": "usa la amplitud"},
    "tr": {"press_high": "yüksek baskı yapar", "counter": "hızlı hücuma çıkar", "direct": "direkt oynar", "patient": "sabırla oyun kurar", "deep": "geride savunur", "wide": "genişliği kullanır"},
}
AND = {"en": " and ", "es": " y ", "tr": " ve "}

L10N: dict[str, dict[str, str]] = {
    "en": {
        "head_full_time": "Full time: {h} {hs}-{as_} {a}", "head_half_time": "Half time: {h} {hs}-{as_} {a}", "head_preview": "Preview: {h} v {a}",
        "res_draw": "{h} and {a} shared the points.", "res_win": "{w} beat {l} {ws}-{ls}.",
        "res_cb_win": "{w} came from {d} goals down to beat {l}.", "res_cb_draw": "{w} came from {d} goals down to draw with {l}.",
        "half_lead": "{w} lead {ws}-{ls} at the break.", "half_draw": "It is {hs}-{as_} at the break.",
        "stats": "Possession {h} {ph}%, {a} {pa}%. Shots {sh} to {sa}. xG {xh} to {xa}. Pass accuracy {ah}% to {aa}%.",
        "stats_casual": "{lead} had more of the ball.", "stats_even": "Neither side had much more of the ball.",
        "turning": "Turning point: {text}.", "potm": "Player of the match: {name} ({team}), goals {g}, assists {as_}, shots {s}.",
        "potm_casual": "Player of the match: {name} ({team}).",
        "half_next": "The second half to come.",
        "preview": "{h} ({fh}) {th}. {a} ({fa}) {ta}. Players to watch: {sh} and {sa}.",
        "preview_casual": "{h} take on {a}. {h} {th}; {a} {ta}. Keep an eye on {sh} and {sa}.",
        "chip_poss": "Possession", "chip_shots": "Shots", "chip_xg": "xG", "chip_pass": "Pass accuracy",
    },
    "es": {
        "head_full_time": "Final: {h} {hs}-{as_} {a}", "head_half_time": "Descanso: {h} {hs}-{as_} {a}", "head_preview": "Previa: {h} v {a}",
        "res_draw": "{h} y {a} se repartieron los puntos.", "res_win": "{w} ganó al {l} por {ws}-{ls}.",
        "res_cb_win": "{w} remontó {d} goles de desventaja y ganó al {l}.", "res_cb_draw": "{w} remontó {d} goles de desventaja y empató con el {l}.",
        "half_lead": "{w} gana {ws}-{ls} al descanso.", "half_draw": "Al descanso es {hs}-{as_}.",
        "stats": "Posesión: {h} {ph}%, {a} {pa}%. Tiros: {sh} a {sa}. xG: {xh} a {xa}. Precisión de pase: {ah}% a {aa}%.",
        "stats_casual": "{lead} tuvo más el balón.", "stats_even": "Ningún equipo tuvo mucho más el balón.",
        "turning": "Punto de inflexión: {text}.", "potm": "Jugador del partido: {name} ({team}), goles {g}, asistencias {as_}, tiros {s}.",
        "potm_casual": "Jugador del partido: {name} ({team}).",
        "half_next": "Queda la segunda parte.",
        "preview": "{h} ({fh}) {th}. {a} ({fa}) {ta}. A seguir: {sh} y {sa}.",
        "preview_casual": "{h} se mide al {a}. El {h} {th}; el {a} {ta}. Ojo a {sh} y {sa}.",
        "chip_poss": "Posesión", "chip_shots": "Tiros", "chip_xg": "xG", "chip_pass": "Precisión de pase",
    },
    "tr": {
        "head_full_time": "Maç sonu: {h} {hs}-{as_} {a}", "head_half_time": "Devre arası: {h} {hs}-{as_} {a}", "head_preview": "Ön izleme: {h} - {a}",
        "res_draw": "{h} ve {a} puanları paylaştı.", "res_win": "{w}, rakibi {l} takımını {ws}-{ls} yendi.",
        "res_cb_win": "{w}, {d} gol geriden gelerek {l} karşısında kazandı.", "res_cb_draw": "{w}, {d} gol geriden gelerek {l} ile berabere kaldı.",
        "half_lead": "Devre arasında {w} {ws}-{ls} önde.", "half_draw": "Devre arasında skor {hs}-{as_}.",
        "stats": "Topa sahip olma: {h} %{ph}, {a} %{pa}. Şut: {sh}-{sa}. xG: {xh}-{xa}. Pas isabeti: %{ah}-%{aa}.",
        "stats_casual": "Topun çoğu {lead} takımındaydı.", "stats_even": "İki takımın top oranı birbirine yakındı.",
        "turning": "Dönüm noktası: {text}.", "potm": "Maçın oyuncusu: {name} ({team}), gol {g}, asist {as_}, şut {s}.",
        "potm_casual": "Maçın oyuncusu: {name} ({team}).",
        "half_next": "İkinci yarı geliyor.",
        "preview": "{h} ({fh}) {th}. {a} ({fa}) {ta}. İzlenecek isimler: {sh} ve {sa}.",
        "preview_casual": "{h}, {a} ile karşılaşıyor. {h} {th}; {a} {ta}. {sh} ve {sa} oyuncularına dikkat.",
        "chip_poss": "Topa sahip olma", "chip_shots": "Şut", "chip_xg": "xG", "chip_pass": "Pas isabeti",
    },
}  # fmt: skip


def _pct(pack: dict, club: str, key: str) -> int:
    return round(pack["metrics"][f"{club}.{key}"]["value"] * 100)


def _val(pack: dict, club: str, key: str) -> float:
    return pack["metrics"][f"{club}.{key}"]["value"]


def render(pack: dict, cohort: Cohort, moments: dict[str, dict] | None = None) -> Recap:
    """The template recap writer: true by construction, in the cohort's language and mode."""
    kind = pack["type"].removeprefix("recap_")
    lang, analyst = cohort.language, cohort.mode == "analyst"
    L = L10N[lang]
    clubs = list(pack["teamNames"])
    short = pack["teamShort"]
    h, a = clubs
    sc = pack["facts"]["score"]
    f: dict = {"h": short[h], "a": short[a], "hs": sc[h], "as_": sc[a]}
    if kind == "preview":
        fm, st = pack["facts"]["formations"], pack["facts"]["styles"]
        tags = lambda c: AND[lang].join(TAGS[lang][t] for t in st[c]) or {"en": "play their own game", "es": "juega su partido", "tr": "kendi oyununu oynar"}[lang]  # noqa: E731
        f.update(fh=fm[h], fa=fm[a], th=tags(h), ta=tags(a), sh=pack["players"][0]["name"], sa=pack["players"][1]["name"])
        text = fill(L["preview" if analyst else "preview_casual"], f)
        chips: list[Chip] = []
        key_moments: list[dict] = []
        potm = None
    else:
        f.update(_result_parts(pack, kind, short))
        parts = [fill(L[_result_key(pack, kind)], f)]
        if analyst:
            f.update(ph=_pct(pack, h, "possession_share"), pa=_pct(pack, a, "possession_share"), sh=int(_val(pack, h, "shots")), sa=int(_val(pack, a, "shots")),
                     xh=T.num(_val(pack, h, "xg"), lang, 1), xa=T.num(_val(pack, a, "xg"), lang, 1),
                     ah=_pct(pack, h, "pass_acc"), aa=_pct(pack, a, "pass_acc"))
            parts.append(fill(L["stats"], f))
        else:
            ph, pa = _pct(pack, h, "possession_share"), _pct(pack, a, "possession_share")
            parts.append(fill(L["stats_casual"], {"lead": short[h if ph > pa else a]}) if abs(ph - pa) >= 6 else L["stats_even"])
        moments = moments or {}
        key_moments = _key_moments(pack, cohort, moments)
        turning = moments.get(pack["facts"].get("turningMoment") or "")
        if turning is not None:
            parts.append(fill(L["turning"], {"text": _LEAD.sub("", T.render(turning, cohort).headline)}))
        potm = pack["facts"].get("potm")
        if potm:
            pl = next((p for p in pack["players"] if p["id"] == potm["id"]), None)
            if pl:
                key = "potm" if analyst else "potm_casual"
                parts.append(fill(L[key], {"name": pl["name"], "team": short[pl["team"]], "g": potm["goals"], "as_": potm["assists"], "s": potm["shots"]}))
        if kind == "half_time":
            parts.append(L["half_next"])
        text = " ".join(parts)
        chips = [
            Chip(label=L["chip_poss"], value=f"{_pct(pack, h, 'possession_share')}% – {_pct(pack, a, 'possession_share')}%"),
            Chip(label=L["chip_shots"], value=f"{int(_val(pack, h, 'shots'))} – {int(_val(pack, a, 'shots'))}"),
            Chip(label=L["chip_xg"], value=f"{T.num(_val(pack, h, 'xg'), lang, 1)} – {T.num(_val(pack, a, 'xg'), lang, 1)}"),
            Chip(label=L["chip_pass"], value=f"{_pct(pack, h, 'pass_acc')}% – {_pct(pack, a, 'pass_acc')}%"),
        ]
    headline = fill(L[f"head_{kind}"], f)
    return Recap(
        cohort=cohort.key, kind=kind, headline=headline, summary=text, key_moments=key_moments,
        player_of_the_match=({"id": potm["id"], "goals": potm["goals"], "assists": potm["assists"], "shots": potm["shots"]} if potm else None),
        stats=chips, provenance=Provenance(agents=["template"], verified=True, evidenceRef=pack["id"], fallbackLevel=2),
    )  # fmt: skip


def fill(template: str, sheet: dict) -> str:
    return template.format_map(T._Safe(sheet))


def _result_key(pack: dict, kind: str) -> str:
    facts = pack["facts"]
    if kind == "half_time":
        return "half_draw" if facts["winner"] is None and facts["score"][list(facts["score"])[0]] == facts["score"][list(facts["score"])[1]] else "half_lead"
    if facts["comeback"]:
        return "res_cb_win" if facts["winner"] == facts["comeback"] else "res_cb_draw"
    return "res_draw" if facts["winner"] is None else "res_win"


def _result_parts(pack: dict, kind: str, short: dict) -> dict:
    facts = pack["facts"]
    clubs = list(facts["score"])
    sc = facts["score"]
    lead = max(clubs, key=lambda c: sc[c])
    other = next(c for c in clubs if c != lead)
    out = {"w": short[lead], "l": short[other], "ws": sc[lead], "ls": sc[other], "d": facts["deficit"]}
    if facts["comeback"]:
        w = facts["comeback"]
        out.update(w=short[w], l=short[next(c for c in clubs if c != w)])
    return out


def _key_moments(pack: dict, cohort: Cohort, moments: dict[str, dict]) -> list[dict]:
    out = []
    for mid in pack.get("keyMoments", []):
        m = moments.get(mid)
        if m is None:
            continue
        v = T.render(m, cohort)
        out.append({"momentId": mid, "label": m["detectedAt"]["label"], "text": _LEAD.sub("", v.headline)})
    return out


async def write_recap(team, pack: dict, cohort: Cohort, moments: dict[str, dict], registry) -> Recap:
    """Ask the Recap Writer; verify the text; fall back to the template tier if anything is wrong."""
    from . import verify as V
    from .team import AgentFailure

    lang = cohort.language
    try:
        out = await team.recap(pack, cohort, moments)
    except AgentFailure:
        return render(pack, cohort, moments)
    issues = V.verify_text(f"{out.headline}. {out.summary}", pack, lang, registry, "recap")
    if any(i.severity == "error" for i in issues):
        return render(pack, cohort, moments)
    return out.model_copy(update={"provenance": Provenance(agents=["recap_writer", "verifier"], verified=True, evidenceRef=pack["id"], fallbackLevel=0)})
