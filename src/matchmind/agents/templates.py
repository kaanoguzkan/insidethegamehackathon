"""Deterministic, localized text for every moment and fact type.

Templates are written from the evidence pack and nothing else, so everything they say is
true by construction and passes the Verifier. They serve three purposes:

1. the **template tier** of the degradation ladder (when a model is slow or fails a check, the
   overlay still lands on time, in the right language);
2. the **offline model** used in tests, CI and the zero-cost replay build;
3. **stat-card overlays** (shot speed, pass difficulty ...) that never need a language model.

Languages: English, Spanish, Turkish. Casual text avoids jargon; analyst text leads with
numbers. A club-side perspective changes tone only, never facts.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.contracts import Chip, Claim, Cohort, Explanation, StoryVariant

# ---------------------------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------------------------


def num(v: float | int | None, lang: str = "en", digits: int | None = None) -> str:
    """Format a number as it appears in the pack (trailing .0 dropped), localized."""
    if v is None:
        return "?"
    if digits is not None:
        s = f"{round(float(v), digits):.{digits}f}"
    else:
        f = float(v)
        s = str(int(f)) if f == int(f) else str(round(f, 2))
    if "." in s:
        s = s.rstrip("0").rstrip(".") if digits is None else s
    return s.replace(".", ",") if lang in ("es", "tr") else s


def pct(v: float | None, lang: str) -> str:
    return num(abs(v), lang) if v is not None else "?"


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def fill(template: str, sheet: dict[str, Any]) -> str:
    return template.format_map(_Safe(sheet))


# ---------------------------------------------------------------------------------------------
# Fact sheets: pull the named values a template needs out of an evidence pack
# ---------------------------------------------------------------------------------------------


def _m(pack: dict, key: str) -> dict:
    return pack["metrics"].get(key) or {}


def _name(pack: dict, pid: str | None) -> str | None:
    for p in pack["players"]:
        if p["id"] == pid:
            return p["name"]
    return None


def _team(pack: dict, club: str | None) -> str:
    if club is None:
        return ""
    return pack.get("teamShort", {}).get(club) or pack["teamNames"].get(club, club)


def _score_text(pack: dict) -> str:
    sc = pack["facts"]["score"]
    clubs = list(sc)
    return f"{_team(pack, clubs[0])} {sc[clubs[0]]}-{sc[clubs[1]]} {_team(pack, clubs[1])}"


def sheet(pack: dict, lang: str) -> dict[str, Any]:
    """Everything a template for this moment type might reference, localized."""
    t = pack["type"]
    s_club, b_club = pack.get("subjectTeam"), pack.get("beneficiaryTeam")
    other = next((c for c in pack["teamNames"] if c != s_club), None) if s_club else None
    sh: dict[str, Any] = {
        "minute": pack["detectedAt"]["label"],
        "team": _team(pack, s_club),
        "opp": _team(pack, other or b_club),
        "ben": _team(pack, b_club),
        "score": _score_text(pack),
        "after_label": pack["windows"].get("after", {}).get("label", ""),
        "before_label": pack["windows"].get("before", {}).get("label", ""),
    }
    f = pack["facts"]
    players = pack["players"]
    sh["player"] = players[0]["name"] if players else ""
    if t == "goal":
        sh.update(
            scorer=players[0]["name"] if players else "",
            assist=_name(pack, f.get("assist")) or "",
            xg=num(f.get("xg"), lang, 2) if f.get("xg") is not None else "",
            situation=f.get("situation") or "",
            head=f.get("bodyPart") == "head",
            team=_team(pack, s_club),
        )
    elif t == "red_card":
        sh.update(player=players[0]["name"] if players else "", second=bool(f.get("secondYellow")))
    elif t == "penalty":
        sh.update(
            player=players[0]["name"] if players else "",
            fouled=_name(pack, f.get("fouled")) or "",
            ben=_team(pack, b_club),
        )
    elif t == "big_chance":
        sh.update(
            shooter=players[0]["name"] if players else "", xg=num(f.get("xg"), lang, 2),
            outcome=f.get("outcome") or "",
        )
    elif t in ("pressure_collapse", "pressure_surge"):
        c, o = s_club, next((x for x in pack["teamNames"] if x != s_club), None)
        d, pr, sp = _m(pack, f"{c}.nearest_defender_m"), _m(pack, f"{c}.pressures_per_min"), _m(pack, f"{c}.front_sprints")
        pp = _m(pack, f"{o}.progressive_passes")
        xt = _m(pack, f"{o}.xt")
        sh.update(
            d_before=num(d.get("before"), lang), d_after=num(d.get("after"), lang),
            r_before=num(pr.get("before"), lang), r_after=num(pr.get("after"), lang),
            r_pct=pct(pr.get("changePct"), lang),
            sp_before=num(sp.get("before"), lang), sp_after=num(sp.get("after"), lang),
            pp_before=num(pp.get("before"), lang), pp_after=num(pp.get("after"), lang),
            xt_before=num(xt.get("before"), lang), xt_after=num(xt.get("after"), lang),
            opp=_team(pack, o), team=_team(pack, c),
            xt_down=bool(xt) and xt.get("consistent") is False,
            pp_up=bool(pp) and pp.get("consistent") is True,
            sp_ok=bool(sp) and sp.get("consistent") is True and sp.get("before") not in (None, 0),
        )
    elif t == "momentum_swing":
        c = s_club
        o = next((x for x in pack["teamNames"] if x != c), None)
        a, b = _m(pack, f"{c}.xt"), _m(pack, f"{o}.xt")
        sh.update(
            xt_a_before=num(a.get("before"), lang), xt_a_after=num(a.get("after"), lang),
            xt_b_before=num(b.get("before"), lang), xt_b_after=num(b.get("after"), lang),
            team=_team(pack, c), opp=_team(pack, o),
        )
    elif t == "chaos_flip":
        ch, to = _m(pack, "match.chaos_index"), _m(pack, "match.turnovers_per_min")
        sh.update(
            c_before=num(ch.get("before"), lang), c_after=num(ch.get("after"), lang),
            t_before=num(to.get("before"), lang), t_after=num(to.get("after"), lang),
            to_chaos=f.get("direction") == "control_to_chaos",
            controller=_team(pack, f.get("controller")),
        )
    elif t == "rhythm_break":
        c = s_club
        tm = _m(pack, f"{c}.tempo")
        sh.update(
            tp_before=num(tm.get("before"), lang), tp_after=num(tm.get("after"), lang),
            faster=f.get("direction") == "faster", trigger=f.get("trigger") or "",
        )
    elif t == "tactical_shift":
        c = s_club
        ln, wd = _m(pack, f"{c}.line_height_m"), _m(pack, f"{c}.width_m")
        sh.update(
            l_before=num(ln.get("before"), lang), l_after=num(ln.get("after"), lang),
            w_before=num(wd.get("before"), lang), w_after=num(wd.get("after"), lang),
            higher=f.get("line") == "higher", deeper=f.get("line") == "deeper",
            wider=f.get("width") == "wider", narrower=f.get("width") == "narrower",
            line_shifted=bool(f.get("lineShifted")),
        )
    elif t == "fatigue_drop":
        c = s_club
        sr = _m(pack, f"{c}.sprint_rate")
        sh.update(sr_before=num(sr.get("before"), lang), sr_after=num(sr.get("after"), lang))
    elif t == "physical_highlight":
        kind = f.get("kind")
        sh["kind"] = kind
        if kind == "top_speed":
            sh["kmh"] = num(_m(pack, f"{s_club}.peak_kmh").get("value"), lang)
        else:
            sh["kmh"] = num(_m(pack, f"{s_club}.shot_speed_kmh").get("value"), lang)
    return sh


# ---------------------------------------------------------------------------------------------
# Templates: (headline, body) per moment type, language and mode
# ---------------------------------------------------------------------------------------------

# Each entry is a function (sheet) -> (headline, body). Functions rather than format strings so a
# sentence can include optional clauses (an assist, a caveat) without ugly empty gaps.

SITUATION = {
    "en": {"corner": "from a corner", "free_kick": "from a free kick", "penalty": "from the spot"},
    "es": {"corner": "de córner", "free_kick": "de tiro libre", "penalty": "de penalti"},
    "tr": {"corner": "kornerden", "free_kick": "serbest vuruştan", "penalty": "penaltıdan"},
}


def _en_goal(s: dict, analyst: bool) -> tuple[str, str]:
    where = SITUATION["en"].get(s["situation"], "")
    if analyst:
        a = f" Assist: {s['assist']}." if s["assist"] else ""
        x = f" xG {s['xg']}." if s["xg"] else ""
        return f"{s['minute']} Goal, {s['team']}: {s['scorer']}", f"{s['scorer']} scores for {s['team']} {where}. {s['score']}.{x}{a}".replace(" .", ".")
    a = f" {s['assist']} set it up." if s["assist"] else ""
    return f"Goal for {s['team']}!", f"{s['scorer']} scores{(' ' + where) if where else ''}. It's {s['score']}.{a}"


def _es_goal(s: dict, analyst: bool) -> tuple[str, str]:
    where = SITUATION["es"].get(s["situation"], "")
    if analyst:
        a = f" Asistencia: {s['assist']}." if s["assist"] else ""
        x = f" xG {s['xg']}." if s["xg"] else ""
        return f"{s['minute']} Gol, {s['team']}: {s['scorer']}", f"{s['scorer']} marca para {s['team']} {where}. {s['score']}.{x}{a}".replace(" .", ".")
    a = f" {s['assist']} dio el pase." if s["assist"] else ""
    return f"¡Gol del {s['team']}!", f"{s['scorer']} marca{(' ' + where) if where else ''}. Es {s['score']}.{a}"


def _tr_goal(s: dict, analyst: bool) -> tuple[str, str]:
    where = SITUATION["tr"].get(s["situation"], "")
    lead = f"{s['team']} adına " + (f"{where} " if where else "")
    if analyst:
        a = f" Asist: {s['assist']}." if s["assist"] else ""
        x = f" xG {s['xg']}." if s["xg"] else ""
        return f"{s['minute']} Gol, {s['team']}: {s['scorer']}", f"{s['scorer']}, {lead}golü attı. {s['score']}.{x}{a}"
    a = f" Pası {s['assist']} verdi." if s["assist"] else ""
    return f"{s['team']} golü buldu!", f"{s['scorer']} {where + ' ' if where else ''}attı. Skor {s['score']}.{a}"


def _en_red(s, analyst):
    why = " (second yellow)" if s["second"] else ""
    return (
        f"{s['minute']} Red card, {s['team']}",
        f"{s['player']} is sent off{why}. {s['team']} play on with ten." if analyst else f"{s['player']} is sent off{why}, so {s['team']} are down to ten men.",
    )


def _es_red(s, analyst):
    why = " (doble amarilla)" if s["second"] else ""
    return (
        f"{s['minute']} Roja, {s['team']}",
        f"{s['player']} es expulsado{why}. {s['team']} se queda con diez." if analyst else f"{s['player']} ve la roja{why}: el {s['team']} se queda con diez jugadores.",
    )


def _tr_red(s, analyst):
    why = " (ikinci sarı)" if s["second"] else ""
    return (
        f"{s['minute']} Kırmızı kart, {s['team']}",
        f"{s['player']} oyundan atıldı{why}. {s['team']} on kişi devam ediyor." if analyst else f"{s['player']} kırmızı kart gördü{why}; {s['team']} on kişi kaldı.",
    )


def _en_pen(s, analyst):
    return (
        f"{s['minute']} Penalty to {s['ben']}",
        f"{s['player']} fouls {s['fouled']} in the box; {s['ben']} have a penalty." if s["fouled"] else f"{s['team']} concede a penalty.",
    )


def _es_pen(s, analyst):
    return (
        f"{s['minute']} Penalti para {s['ben']}",
        f"{s['player']} derriba a {s['fouled']} dentro del área; penalti para {s['ben']}." if s["fouled"] else f"{s['team']} concede un penalti.",
    )


def _tr_pen(s, analyst):
    return (
        f"{s['minute']} {s['ben']} lehine penaltı",
        f"{s['player']}, {s['fouled']} oyuncusuna ceza sahasında faul yaptı; {s['ben']} penaltı kazandı." if s["fouled"] else f"{s['team']} penaltı verdi.",
    )


def _en_chance(s, analyst):
    res = {"saved": "saved", "blocked": "blocked", "off_target": "off target", "post": "off the post"}.get(s["outcome"], "missed")
    if analyst:
        return f"{s['minute']} Big chance, {s['team']}", f"{s['shooter']} gets a {s['xg']} xG chance for {s['team']}; it is {res}."
    return f"Big chance for {s['team']}!", f"{s['shooter']} had a great opportunity, but it was {res}."


def _es_chance(s, analyst):
    res = {"saved": "parada", "blocked": "bloqueada", "off_target": "fuera", "post": "al poste"}.get(s["outcome"], "fallada")
    if analyst:
        return f"{s['minute']} Ocasión clara, {s['team']}", f"{s['shooter']} tiene una ocasión de {s['xg']} xG para {s['team']}; la ocasión termina {res}."
    return f"¡Gran ocasión del {s['team']}!", f"{s['shooter']} tuvo una oportunidad clarísima, pero fue {res}."


def _tr_chance(s, analyst):
    res = {"saved": "kurtarıldı", "blocked": "bloke edildi", "off_target": "auta gitti", "post": "direkten döndü"}.get(s["outcome"], "değerlendirilemedi")
    if analyst:
        return f"{s['minute']} Net fırsat, {s['team']}", f"{s['shooter']} için {s['xg']} xG değerinde fırsat; şut {res}."
    return f"{s['team']} için büyük fırsat!", f"{s['shooter']} harika bir fırsat yakaladı ama şut {res}."


def _en_pcol(s, analyst):
    if analyst:
        body = f"Nearest defender in {s['opp']}'s half: {s['d_before']} m to {s['d_after']} m. Pressures per minute {s['r_before']} to {s['r_after']}, {s['r_pct']}% fewer."
        if s["sp_ok"]:
            body += f" Front-line sprints per 5 min: {s['sp_before']} to {s['sp_after']}."
        if s["pp_up"]:
            body += f" {s['opp']}'s progressive passes per 5 min: {s['pp_before']} to {s['pp_after']}."
        if s["xt_down"]:
            body += f" But their threat is down (xT {s['xt_before']} to {s['xt_after']}) against the deeper block."
        return f"{s['minute']} {s['team']} have stopped pressing", body
    body = f"{s['team']} can't keep the press going, so {s['opp']} now have more time on the ball."
    if s["xt_down"]:
        body += f" Even so, {s['team']}'s deeper block is limiting the danger."
    return f"{s['team']} are sitting back", body


def _es_pcol(s, analyst):
    if analyst:
        body = f"Defensor más cercano al balón en campo del {s['opp']}: de {s['d_before']} m a {s['d_after']} m. Presiones por minuto de {s['r_before']} a {s['r_after']}, un {s['r_pct']}% menos."
        if s["sp_ok"]:
            body += f" Sprints de la línea de ataque cada 5 min: de {s['sp_before']} a {s['sp_after']}."
        if s["pp_up"]:
            body += f" Pases progresivos del {s['opp']} cada 5 min: de {s['pp_before']} a {s['pp_after']}."
        if s["xt_down"]:
            body += f" Pero su amenaza baja (xT de {s['xt_before']} a {s['xt_after']}) ante el bloque más bajo."
        return f"{s['minute']} El {s['team']} ha dejado de presionar", body
    body = f"El {s['team']} ya no aguanta la presión, así que el {s['opp']} tiene más tiempo con el balón."
    if s["xt_down"]:
        body += f" Aun así, el bloque más bajo del {s['team']} limita el peligro."
    return f"El {s['team']} se echa atrás", body


def _tr_pcol(s, analyst):
    # Before/after pairs use "X iken Y oldu" (it was X, it became Y): grammatical for any number,
    # unlike case suffixes, which depend on how the number is pronounced.
    if analyst:
        body = (
            f"{s['opp']} yarı sahasında topa en yakın savunmacı {s['d_before']} m iken {s['d_after']} m oldu. "
            f"Dakikadaki baskı sayısı {s['r_before']} iken {s['r_after']} oldu (yüzde {s['r_pct']} düşüş)."
        )
        if s["sp_ok"]:
            body += f" Hücum hattının 5 dakikadaki sprint sayısı {s['sp_before']} iken {s['sp_after']} oldu."
        if s["pp_up"]:
            body += f" {s['opp']} ileriye pas sayısı (5 dk) {s['pp_before']} iken {s['pp_after']} oldu."
        if s["xt_down"]:
            body += f" Ancak derin blok karşısında tehdit düştü (xT {s['xt_before']} iken {s['xt_after']} oldu)."
        return f"{s['minute']} {s['team']} baskıyı bıraktı", body
    body = f"{s['team']} baskıyı sürdüremiyor; {s['opp']} artık topla daha rahat oynuyor."
    if s["xt_down"]:
        body += f" Yine de {s['team']} geriye çekilerek tehlikeyi sınırlıyor."
    return f"{s['team']} geriye çekildi", body


def _en_psurge(s, analyst):
    if analyst:
        return (
            f"{s['minute']} {s['team']} step up the press",
            f"Nearest defender in {s['opp']}'s half: {s['d_before']} m to {s['d_after']} m. Pressures per minute {s['r_before']} to {s['r_after']}.",
        )
    return f"{s['team']} are pressing high", f"{s['team']} are closing down much quicker, giving {s['opp']} less time on the ball."


def _es_psurge(s, analyst):
    if analyst:
        return (
            f"{s['minute']} El {s['team']} adelanta la presión",
            f"Defensor más cercano al balón en campo del {s['opp']}: de {s['d_before']} m a {s['d_after']} m. Presiones por minuto de {s['r_before']} a {s['r_after']}.",
        )
    return f"El {s['team']} presiona arriba", f"El {s['team']} cierra mucho más rápido y el {s['opp']} tiene menos tiempo con el balón."


def _tr_psurge(s, analyst):
    if analyst:
        return (
            f"{s['minute']} {s['team']} baskıyı artırdı",
            f"{s['opp']} yarı sahasında topa en yakın savunmacı {s['d_before']} m iken {s['d_after']} m oldu. "
            f"Dakikadaki baskı sayısı {s['r_before']} iken {s['r_after']} oldu.",
        )
    return f"{s['team']} yüksek baskı yapıyor", f"{s['team']} çok daha hızlı kapatıyor, {s['opp']} topla daha az vakit buluyor."


def _en_swing(s, analyst):
    if analyst:
        return f"{s['minute']} Momentum swings to {s['team']}", f"Threat created (xT plus xG) per 5 min: {s['team']} {s['xt_a_before']} to {s['xt_a_after']}, {s['opp']} {s['xt_b_before']} to {s['xt_b_after']}."
    return f"{s['team']} take control", f"The momentum has swung: {s['team']} are now the more dangerous side."


def _es_swing(s, analyst):
    if analyst:
        return f"{s['minute']} El impulso pasa al {s['team']}", f"Amenaza generada (xT más xG) cada 5 min: {s['team']} de {s['xt_a_before']} a {s['xt_a_after']}, {s['opp']} de {s['xt_b_before']} a {s['xt_b_after']}."
    return f"El {s['team']} toma el control", f"El impulso ha cambiado: ahora el {s['team']} es el equipo más peligroso."


def _tr_swing(s, analyst):
    if analyst:
        return (
            f"{s['minute']} Momentum {s['team']} tarafına geçti",
            f"5 dakikada üretilen tehdit (xT artı xG): {s['team']} {s['xt_a_before']} iken {s['xt_a_after']} oldu, "
            f"{s['opp']} {s['xt_b_before']} iken {s['xt_b_after']} oldu.",
        )
    return f"{s['team']} kontrolü aldı", f"Oyunun gidişatı değişti: artık daha tehlikeli olan taraf {s['team']}."


def _en_chaos(s, analyst):
    if s["to_chaos"]:
        return (
            (f"{s['minute']} The game turns chaotic", f"Chaos index {s['c_before']} to {s['c_after']}. Possession changes per minute {s['t_before']} to {s['t_after']}.")
            if analyst else ("The game has opened up", "Play has become scrappy, with the ball changing hands far more often.")
        )
    return (
        (f"{s['minute']} {s['controller']} settle the game", f"Chaos index {s['c_before']} to {s['c_after']}. Possession changes per minute {s['t_before']} to {s['t_after']}.")
        if analyst else (f"{s['controller']} calm things down", "The game has settled, with longer, tidier spells of possession.")
    )


def _es_chaos(s, analyst):
    if s["to_chaos"]:
        return (
            (f"{s['minute']} El partido se vuelve caótico", f"Índice de caos de {s['c_before']} a {s['c_after']}. Cambios de posesión por minuto de {s['t_before']} a {s['t_after']}.")
            if analyst else ("El partido se abre", "El juego se ha vuelto embarullado y el balón cambia de manos mucho más a menudo.")
        )
    return (
        (f"{s['minute']} {s['controller']} serena el partido", f"Índice de caos de {s['c_before']} a {s['c_after']}. Cambios de posesión por minuto de {s['t_before']} a {s['t_after']}.")
        if analyst else (f"{s['controller']} calma el juego", "El partido se ha asentado, con posesiones más largas y ordenadas.")
    )


def _tr_chaos(s, analyst):
    figures = (
        f"Kaos endeksi {s['c_before']} iken {s['c_after']} oldu. "
        f"Dakikadaki top kaybı sayısı {s['t_before']} iken {s['t_after']} oldu."
    )
    if s["to_chaos"]:
        return (f"{s['minute']} Maç kaosa döndü", figures) if analyst else ("Maç açıldı", "Oyun karıştı; top çok daha sık el değiştiriyor.")
    return (
        (f"{s['minute']} {s['controller']} oyunu yatıştırdı", figures)
        if analyst else (f"{s['controller']} oyunu sakinleştirdi", "Maç oturdu; daha uzun ve düzenli top sahipliği var.")
    )


def _en_rhythm(s, analyst):
    word = "up" if s["faster"] else "down"
    if analyst:
        return f"{s['minute']} {s['team']} change tempo", f"Passes per minute of possession {s['tp_before']} to {s['tp_after']}: the tempo is {word}."
    return (f"{s['team']} speed things up", "They are moving the ball much faster now.") if s["faster"] else (f"{s['team']} slow it down", "They have slowed the game right down.")


def _es_rhythm(s, analyst):
    word = "sube" if s["faster"] else "baja"
    if analyst:
        return f"{s['minute']} El {s['team']} cambia el ritmo", f"Pases por minuto de posesión de {s['tp_before']} a {s['tp_after']}: el ritmo {word}."
    return (f"El {s['team']} acelera", "Ahora mueven el balón mucho más rápido.") if s["faster"] else (f"El {s['team']} frena el juego", "Han bajado mucho el ritmo del partido.")


def _tr_rhythm(s, analyst):
    word = "yükseldi" if s["faster"] else "düştü"
    if analyst:
        return (
            f"{s['minute']} {s['team']} tempoyu değiştirdi",
            f"Top sahipliğinin dakikasında pas sayısı {s['tp_before']} iken {s['tp_after']} oldu: tempo {word}.",
        )
    return (f"{s['team']} hızlandı", "Topu artık çok daha hızlı dolaştırıyorlar.") if s["faster"] else (f"{s['team']} oyunu yavaşlattı", "Oyunun temposunu iyice düşürdüler.")


def _en_shift(s, analyst):
    parts = []
    if s["line_shifted"]:
        parts.append(f"defensive line {'higher' if s['higher'] else 'deeper'}: {s['l_before']} m to {s['l_after']} m from their own goal")
    if not parts or s["wider"] or s["narrower"]:
        parts.append(f"width {s['w_before']} m to {s['w_after']} m")
    if analyst:
        return f"{s['minute']} {s['team']} change shape", "; ".join(parts).capitalize() + "."
    return (f"{s['team']} rejig their shape", f"{s['team']} are now defending {'higher up the pitch' if s['higher'] else 'deeper'}.") if s["line_shifted"] else (f"{s['team']} change shape", f"{s['team']} are playing {'wider' if s['wider'] else 'narrower'} than before.")


def _es_shift(s, analyst):
    parts = []
    if s["line_shifted"]:
        parts.append(f"línea defensiva {'más alta' if s['higher'] else 'más baja'}: de {s['l_before']} m a {s['l_after']} m de su portería")
    if not parts or s["wider"] or s["narrower"]:
        parts.append(f"anchura de {s['w_before']} m a {s['w_after']} m")
    if analyst:
        return f"{s['minute']} El {s['team']} cambia su forma", "; ".join(parts).capitalize() + "."
    return (f"El {s['team']} reajusta su estructura", f"El {s['team']} defiende ahora {'más arriba' if s['higher'] else 'más atrás'}.") if s["line_shifted"] else (f"El {s['team']} cambia su forma", f"El {s['team']} juega {'más ancho' if s['wider'] else 'más estrecho'} que antes.")


def _tr_shift(s, analyst):
    parts = []
    if s["line_shifted"]:
        parts.append(f"savunma hattı {'daha önde' if s['higher'] else 'daha geride'}: kendi kalesinden {s['l_before']} m iken {s['l_after']} m oldu")
    if not parts or s["wider"] or s["narrower"]:
        parts.append(f"saha genişliği {s['w_before']} m iken {s['w_after']} m oldu")
    if analyst:
        return f"{s['minute']} {s['team']} diziliş değiştirdi", "; ".join(parts).capitalize() + "."
    if s["line_shifted"]:
        return f"{s['team']} dizilişini değiştirdi", f"{s['team']} artık {'daha önde' if s['higher'] else 'daha geride'} savunuyor."
    return f"{s['team']} dizilişini değiştirdi", f"{s['team']} öncekinden {'daha geniş' if s['wider'] else 'daha dar'} oynuyor."


def _en_fatigue(s, analyst):
    if analyst:
        return f"{s['minute']} {s['team']} are tiring", f"Sprints per 5 min: {s['sr_before']} in the first half to {s['sr_after']} now."
    return f"{s['team']} are running out of steam", f"{s['team']}'s players are sprinting far less than earlier in the game."


def _es_fatigue(s, analyst):
    if analyst:
        return f"{s['minute']} El {s['team']} se cansa", f"Sprints cada 5 min: de {s['sr_before']} en la primera parte a {s['sr_after']} ahora."
    return f"Al {s['team']} se le acaban las fuerzas", f"Los jugadores del {s['team']} hacen muchos menos sprints que antes."


def _tr_fatigue(s, analyst):
    if analyst:
        return f"{s['minute']} {s['team']} yoruluyor", f"5 dakikadaki sprint sayısı: ilk yarıda {s['sr_before']}, şimdi {s['sr_after']}."
    return f"{s['team']} yoruluyor", f"{s['team']} oyuncuları maçın başına göre çok daha az sprint atıyor."


def _en_phys(s, analyst):
    if s["kind"] == "top_speed":
        return (f"{s['minute']} Top speed: {s['player']}", f"{s['player']} reaches {s['kmh']} km/h, the fastest sprint of the match so far.")
    return (f"{s['minute']} Fastest shot: {s['player']}", f"{s['player']} strikes it at {s['kmh']} km/h, the hardest shot of the match so far.")


def _es_phys(s, analyst):
    if s["kind"] == "top_speed":
        return (f"{s['minute']} Velocidad máxima: {s['player']}", f"{s['player']} alcanza {s['kmh']} km/h, el sprint más rápido del partido hasta ahora.")
    return (f"{s['minute']} Disparo más fuerte: {s['player']}", f"{s['player']} dispara a {s['kmh']} km/h, el tiro más potente del partido hasta ahora.")


def _tr_phys(s, analyst):
    if s["kind"] == "top_speed":
        return (f"{s['minute']} En yüksek hız: {s['player']}", f"{s['player']} {s['kmh']} km/s hıza ulaştı; maçın şimdiye kadarki en hızlı sprinti.")
    return (f"{s['minute']} En sert şut: {s['player']}", f"{s['player']} {s['kmh']} km/s hızla vurdu; maçın şimdiye kadarki en sert şutu.")


_BUILDERS = {
    "goal": {"en": _en_goal, "es": _es_goal, "tr": _tr_goal},
    "red_card": {"en": _en_red, "es": _es_red, "tr": _tr_red},
    "penalty": {"en": _en_pen, "es": _es_pen, "tr": _tr_pen},
    "big_chance": {"en": _en_chance, "es": _es_chance, "tr": _tr_chance},
    "pressure_collapse": {"en": _en_pcol, "es": _es_pcol, "tr": _tr_pcol},
    "pressure_surge": {"en": _en_psurge, "es": _es_psurge, "tr": _tr_psurge},
    "momentum_swing": {"en": _en_swing, "es": _es_swing, "tr": _tr_swing},
    "chaos_flip": {"en": _en_chaos, "es": _es_chaos, "tr": _tr_chaos},
    "rhythm_break": {"en": _en_rhythm, "es": _es_rhythm, "tr": _tr_rhythm},
    "tactical_shift": {"en": _en_shift, "es": _es_shift, "tr": _tr_shift},
    "fatigue_drop": {"en": _en_fatigue, "es": _es_fatigue, "tr": _tr_fatigue},
    "physical_highlight": {"en": _en_phys, "es": _es_phys, "tr": _tr_phys},
}

# Perspective: a fan of one club hears the same facts with a different tone.
_TONE_PREFIX = {
    "en": {"good": "Good news for {club}. ", "bad": "Worrying for {club}. "},
    "es": {"good": "Buenas noticias para {club}. ", "bad": "Mala noticia para {club}. "},
    "tr": {"good": "{club} için iyi haber. ", "bad": "{club} için kötü haber. "},
}
_POSITIVE_FOR_BENEFICIARY = {
    "pressure_collapse", "pressure_surge", "momentum_swing", "goal", "penalty", "fatigue_drop",
}
_NEGATIVE_FOR_SUBJECT = {"pressure_collapse", "fatigue_drop", "red_card", "penalty"}
_DANGER_TYPES = {"big_chance"}


def club_tone(pack: dict, club: str) -> str | None:
    """'good', 'bad' or None: how the moment reads for a fan of ``club``."""
    t = pack["type"]
    ben, subj = pack.get("beneficiaryTeam"), pack.get("subjectTeam")
    if t == "goal":
        return "good" if subj == club else "bad"
    if t == "red_card":
        return "bad" if subj == club else "good"
    if t == "penalty":
        return "good" if ben == club else "bad"
    if t in _POSITIVE_FOR_BENEFICIARY:
        if ben == club:
            return "good"
        if t in _NEGATIVE_FOR_SUBJECT and subj == club:
            return "bad"
        if t in ("pressure_collapse", "pressure_surge", "momentum_swing") and ben and ben != club:
            return "bad"
    if t in _DANGER_TYPES:
        return "good" if subj == club else "bad"
    return None


def render(pack: dict, cohort: Cohort, club_names: dict[str, str] | None = None) -> StoryVariant:
    """The template tier: a verified-by-construction story for one cohort, in its language."""
    lang = cohort.language
    builder = _BUILDERS.get(pack["type"])
    if builder is None:
        raise KeyError(f"no template for moment type {pack['type']!r}")
    s = sheet(pack, lang)
    headline, body = builder[lang](s, cohort.mode == "analyst")
    if cohort.perspective != "neutral" and cohort.mode == "casual":
        tone = club_tone(pack, cohort.perspective)
        club = (club_names or pack.get("teamShort", {})).get(cohort.perspective, cohort.perspective)
        if tone:
            body = fill(_TONE_PREFIX[lang][tone], {"club": club}) + body
    chips = _chips(pack, lang)
    return StoryVariant(
        cohort=cohort.key, headline=_clip(headline, 90), body=_clip(body, 380),
        chips=chips, claims=claims_from_text(body, pack),
    )


def _chips(pack: dict, lang: str) -> list[Chip]:
    t = pack["type"]
    label = {"en": {"min": "Minute"}, "es": {"min": "Minuto"}, "tr": {"min": "Dakika"}}[lang]
    chips = [Chip(label=label["min"], value=pack["detectedAt"]["label"])]
    if t in ("pressure_collapse", "pressure_surge"):
        d = pack["metrics"].get(f"{pack['subjectTeam']}.nearest_defender_m")
        if d:
            chips.append(Chip(label={"en": "Nearest defender", "es": "Defensor cercano", "tr": "En yakın savunmacı"}[lang], value=f"{num(d['before'], lang)} → {num(d['after'], lang)} m"))
    if t == "big_chance" and pack["facts"].get("xg") is not None:
        chips.append(Chip(label="xG", value=num(pack["facts"]["xg"], lang, 2)))
    return chips


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------------------------------------
# Claims and the explanation
# ---------------------------------------------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)")


def claims_from_text(text: str, pack: dict) -> list[Claim]:
    """Split text into sentences and attach, as refs, the evidence keys whose numbers it uses."""
    out = []
    for sent in (x.strip() for x in _SENTENCE.split(text) if x.strip()):
        nums = {float(n.replace(",", ".")) for n in _NUMBER.findall(sent)}
        refs = []
        for key, m in pack["metrics"].items():
            vals = {v for v in m.values() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            vals |= {abs(v) for v in vals}
            if nums & vals:
                refs.append(key)
        out.append(Claim(text=sent, refs=refs))
    return out


TAGS = {
    "goal": "goal", "red_card": "discipline", "penalty": "discipline", "big_chance": "chance",
    "pressure_collapse": "pressing_collapse", "pressure_surge": "pressing_surge",
    "momentum_swing": "momentum", "chaos_flip": "control_vs_chaos", "rhythm_break": "tempo",
    "tactical_shift": "shape", "fatigue_drop": "fatigue", "physical_highlight": "physical",
}


_METRIC_NAMES = {
    "en": {"ppda": "PPDA", "xt": "threat created", "possession_share": "possession", "progressive_passes": "progressive passes",
           "final_third_entries": "final-third entries", "front_sprints": "front-line sprints", "high_regains": "high regains",
           "pressures_per_min": "pressures per minute", "nearest_defender_m": "nearest-defender distance",
           "players_near_ball": "players near the ball"},
    "es": {"ppda": "PPDA", "xt": "amenaza creada", "possession_share": "posesión", "progressive_passes": "pases progresivos",
           "final_third_entries": "entradas al último tercio", "front_sprints": "sprints de la línea de ataque",
           "high_regains": "recuperaciones altas", "pressures_per_min": "presiones por minuto",
           "nearest_defender_m": "distancia del defensor más cercano", "players_near_ball": "jugadores cerca del balón"},
    "tr": {"ppda": "PPDA", "xt": "üretilen tehdit", "possession_share": "topa sahip olma", "progressive_passes": "ileriye paslar",
           "final_third_entries": "son üçte bire girişler", "front_sprints": "hücum hattı sprintleri",
           "high_regains": "yüksek top kazanma", "pressures_per_min": "dakikadaki baskı sayısı",
           "nearest_defender_m": "en yakın savunmacı mesafesi", "players_near_ball": "topa yakın oyuncular"},
}
_CAVEAT = {
    "en": "Not every indicator agrees: {names} moved the other way.",
    "es": "No todos los indicadores coinciden: {names} se movieron en sentido contrario.",
    "tr": "Tüm göstergeler aynı yönde değil: {names} ters yönde hareket etti.",
}


def explain(pack: dict, lang: str = "en") -> Explanation:
    """The template Explainer: what changed, why, what it means, each backed by evidence keys.

    ``what`` is the headline, ``why`` the numbers, ``so_what`` the plain-language reading of the same
    evidence, and any metric that moved against the story is admitted in ``caveats``.
    """
    s = sheet(pack, lang)
    headline, body = _BUILDERS[pack["type"]][lang](s, True)
    what = headline.split(" ", 1)[1] if headline[:1].isdigit() else headline
    _, so_what = _BUILDERS[pack["type"]][lang](s, False)
    caveats = []
    contradicting = [k for k, v in pack["metrics"].items() if v.get("consistent") is False]
    if contradicting:
        names = ", ".join(_METRIC_NAMES[lang].get(k.split(".", 1)[1], k.split(".", 1)[1].replace("_", " ")) for k in contradicting)
        caveats.append(_CAVEAT[lang].format(names=names))
    consistent = [v.get("consistent") for v in pack["metrics"].values() if "consistent" in v]
    confidence = "high"
    if consistent:
        share = sum(1 for c in consistent if c) / len(consistent)
        confidence = "high" if share >= 0.75 else ("medium" if share >= 0.5 else "low")
    return Explanation(
        what=what, why=body, so_what=so_what, claims=claims_from_text(body, pack),
        tactical_tag=TAGS.get(pack["type"], "other"), confidence=confidence, caveats=caveats,
    )


# ---------------------------------------------------------------------------------------------
# Fact cards (template overlays: no model, no moment)
# ---------------------------------------------------------------------------------------------

_FACT_LABELS = {
    "en": {"xg": "xG", "speed": "Speed", "dist": "Distance", "diff": "Difficulty", "kmh": "km/h", "m": "m", "shot": "Shot", "score": "Score", "on": "On", "off": "Off"},
    "es": {"xg": "xG", "speed": "Velocidad", "dist": "Distancia", "diff": "Dificultad", "kmh": "km/h", "m": "m", "shot": "Tiro", "score": "Marcador", "on": "Entra", "off": "Sale"},
    "tr": {"xg": "xG", "speed": "Hız", "dist": "Mesafe", "diff": "Zorluk", "kmh": "km/s", "m": "m", "shot": "Şut", "score": "Skor", "on": "Giren", "off": "Çıkan"},
}
_OUTCOME = {
    "en": {"goal": "Goal", "saved": "Saved", "blocked": "Blocked", "off_target": "Off target", "post": "Off the post"},
    "es": {"goal": "Gol", "saved": "Parada", "blocked": "Bloqueado", "off_target": "Fuera", "post": "Poste"},
    "tr": {"goal": "Gol", "saved": "Kurtarış", "blocked": "Bloke", "off_target": "Auta", "post": "Direk"},
}
_PASS_TYPE = {
    "en": {"through": "Through ball", "cross": "Cross", "long": "Long pass", "switch": "Switch of play", "medium": "Pass", "short": "Short pass", "back": "Pass back", "free_kick": "Free-kick pass", "corner": "Corner"},
    "es": {"through": "Pase al hueco", "cross": "Centro", "long": "Pase largo", "switch": "Cambio de juego", "medium": "Pase", "short": "Pase corto", "back": "Pase atrás", "free_kick": "Pase de falta", "corner": "Córner"},
    "tr": {"through": "Ara pası", "cross": "Orta", "long": "Uzun pas", "switch": "Kanat değişimi", "medium": "Pas", "short": "Kısa pas", "back": "Geri pas", "free_kick": "Serbest vuruş pası", "corner": "Korner"},
}


def fact_card(fact: dict, lang: str, names: dict[str, str]) -> tuple[str, str, list[Chip], str] | None:
    """(headline, body, chips, kind) for a template overlay, or None if the fact is not shown."""
    v = fact["values"]
    L = _FACT_LABELS[lang]
    player = names.get(fact.get("player") or "", "")
    t = fact["type"]
    if t == "shot_card":
        out = _OUTCOME[lang].get(v.get("outcome"), "")
        chips = [Chip(label=L["xg"], value=num(v["xg"], lang, 2))]
        if v.get("shotSpeedKmh"):
            chips.append(Chip(label=L["speed"], value=f"{num(v['shotSpeedKmh'], lang)} {L['kmh']}"))
        if v.get("distanceM"):
            chips.append(Chip(label=L["dist"], value=f"{num(v['distanceM'], lang)} {L['m']}"))
        return f"{L['shot']}: {player}", out, chips, "shot_card"
    if t == "pass_card":
        chips = [Chip(label=L["diff"], value=f"{num(v['difficulty'], lang)}/10"), Chip(label=L["dist"], value=f"{num(v['distanceM'], lang)} {L['m']}")]
        if v.get("ballSpeedKmh"):
            chips.append(Chip(label=L["speed"], value=f"{num(v['ballSpeedKmh'], lang)} {L['kmh']}"))
        recv = names.get(v.get("receiver") or "", "")
        return _PASS_TYPE[lang].get(v.get("passType"), _PASS_TYPE[lang]["medium"]) + f": {player}", (f"→ {recv}" if recv else ""), chips, "pass_card"
    if t == "speed_badge":
        return player, "", [Chip(label=L["speed"], value=f"{num(v['peakKmh'], lang)} {L['kmh']}")], "speed_badge"
    if t == "distance_badge":
        return player, "", [Chip(label=L["dist"], value=f"{num(v['km'], lang)} km")], "player_tag"
    if t == "card_event":
        card = {"en": {"yellow": "Yellow card", "red": "Red card"}, "es": {"yellow": "Tarjeta amarilla", "red": "Tarjeta roja"}, "tr": {"yellow": "Sarı kart", "red": "Kırmızı kart"}}[lang].get(v.get("card"), "")
        return card, player, [], "card_badge"
    if t == "substitution":
        off = names.get(v.get("off") or "", "")
        return f"{L['on']}: {player}", f"{L['off']}: {off}", [], "stat_card"
    return None
