"""The words in the report: what every position does in every phase, what each tactic tag means, what each view measures.

All text is written for a reader who watches football but has not met these tools. It states what a number is
and how to read it; the numbers themselves come from the replay package.
"""

from __future__ import annotations

PHASES = ("build", "attack", "press", "block", "low")

PHASE_TEXT: dict[str, tuple[str, str]] = {
    "build": ("Build-up", "The team has the ball in its own third. The centre-backs split, the pivot drops, the fullbacks and forwards hold their width and the team tries to play out under pressure."),
    "attack": ("Settled attack", "The ball is past the first phase. Fullbacks and wing-backs push on, wide players come inside, and the team sets up for the final third while a few players stay back as cover against a counter."),
    "press": ("Press", "The other team has the ball in the zone where this team is willing to press. The front line steps up and angles its runs to cut passing lanes; the rest of the team squeezes up behind."),
    "block": ("Mid block", "The team defends in a compact shape with the ball beyond its press line. It keeps its lines close and waits for the pass that triggers the press."),
    "low": ("Low block", "The team defends deep: the ball is in its own third, or it is protecting a lead late on. Short, narrow and close to goal, it gives up possession to protect the box."),
}

CAUSES = {
    "own_third": "ball in the own third",
    "settled": "ball moved on from the own third",
    "counterpress": "just lost the ball (counter-press)",
    "regroup": "just lost the ball (dropping back)",
    "protecting_lead": "protecting a lead late on",
    "deep_line": "a deep line: the ball is near the own goal",
    "wide_carrier": "a carrier pushed to the touchline (the trap)",
    "press_zone": "the ball entered the press zone",
    "ball_beyond_press_line": "the ball is beyond the press line",
    "other": "other",
}

POSITIONS: dict[str, dict[str, str]] = {
    "GK": {"name": "Goalkeeper", "in": "Starts attacks with short or long distribution and acts as an extra passer against a press; on a high line also sweeps up behind it.", "out": "Stops shots, claims crosses and organises the back line."},
    "CB": {"name": "Centre-back", "in": "Splits wide to build, plays the first pass out of defence and steps into midfield when space opens; stays back as cover against the counter.", "out": "Marks the main striker, defends the box and the space behind, and sets the height of the defensive line."},
    "LB": {"name": "Left back", "in": "Pushes up to overlap the winger, or tucks inside as an extra midfielder, depending on the club's style.", "out": "Defends the left channel, tracks the opposing winger and closes down crosses."},
    "RB": {"name": "Right back", "in": "Pushes up to overlap the winger, or tucks inside as an extra midfielder, depending on the club's style.", "out": "Defends the right channel, tracks the opposing winger and closes down crosses."},
    "LWB": {"name": "Left wing-back", "in": "Plays as the left winger: stays high and wide to stretch the pitch, so a back three builds as a 3-2-5.", "out": "Drops into the back line to make a back five."},
    "RWB": {"name": "Right wing-back", "in": "Plays as the right winger: stays high and wide to stretch the pitch, so a back three builds as a 3-2-5.", "out": "Drops into the back line to make a back five."},
    "DM": {"name": "Holding midfielder (the pivot)", "in": "Offers the first line-breaking pass and links defence with midfield; may drop between the centre-backs to make a back three.", "out": "Screens the back line, blocks the central lanes and wins second balls."},
    "CM": {"name": "Central midfielder", "in": "Links play between the lines, supports the wide players and runs beyond the striker.", "out": "Covers the half-space, presses the ball carrier and tracks the runners coming from midfield."},
    "AM": {"name": "Attacking midfielder (the ten)", "in": "Finds pockets between the opposition lines and creates for the forwards.", "out": "Steps up beside the striker to press (a 4-2-3-1 presses as a 4-4-2) or marks the opposing pivot."},
    "LM": {"name": "Left midfielder", "in": "Holds the left touchline or tucks inside, supporting the fullback.", "out": "Forms the wide part of the midfield bank and tracks back."},
    "RM": {"name": "Right midfielder", "in": "Holds the right touchline or tucks inside, supporting the fullback.", "out": "Forms the wide part of the midfield bank and tracks back."},
    "LW": {"name": "Left winger", "in": "Stays wide to stretch the back line, or cuts inside to shoot; attacks the space behind when the nine drops.", "out": "Presses the fullback, curving the run to cut the pass inside; drops to the midfield line in a 4-5-1."},
    "RW": {"name": "Right winger", "in": "Stays wide to stretch the back line, or cuts inside to shoot; attacks the space behind when the nine drops.", "out": "Presses the fullback, curving the run to cut the pass inside; drops to the midfield line in a 4-5-1."},
    "ST": {"name": "Striker", "in": "Pins the centre-backs and finishes; as a false nine drops into midfield to link play.", "out": "Leads the press: closes the centre-backs and cuts the pass to the pivot."},
}
ROLE_ORDER = ["GK", "CB", "LB", "RB", "LWB", "RWB", "DM", "CM", "AM", "LM", "RM", "LW", "RW", "ST"]

TAG_TEXT: dict[str, dict[str, str]] = {
    "fullbacks": {"hold": "fullbacks hold their line", "overlap": "fullbacks overlap: they run past the winger on the outside", "inverted": "fullbacks are inverted: they step inside next to the pivot to build"},
    "pivot": {"stay": "the pivot stays in midfield", "drop": "the pivot drops between the centre-backs to make a back three"},
    "striker": {"target": "a target nine who stays on the last line", "false9": "a false nine who drops into midfield, with the wingers running in behind"},
    "build_up": {"short": "builds short from the goalkeeper", "mixed": "mixes short and long from the goalkeeper", "long": "goes long from the goalkeeper"},
    "corners": {"mixed": "varies its corners", "near": "targets the near post at corners", "far": "targets the far post at corners", "short": "plays short corners", "edge": "plays corners to the edge of the box"},
    "corner_defence": {"zonal": "defends corners by zone", "man": "defends corners man for man", "mixed": "mixes zonal and man marking at corners"},
    "press_scheme": {"zonal": "presses by zone: it holds a shape and closes the ball down when it enters the zone", "wide_trap": "presses with a trap: it closes from the inside to steer the ball to the touchline, then jumps on it with one more player", "man": "presses man for man: each player picks up a nearby opponent as well as pressing the ball"},
    "on_loss": {"counterpress": "counter-presses: it swarms the ball for about five seconds after losing it", "regroup": "regroups: it contains for two seconds, then drops back into shape"},
    "on_win": {"counter": "breaks at once after winning the ball", "keep": "keeps its shape and builds after winning the ball"},
}
TAG_ORDER = ["press_scheme", "on_loss", "on_win", "build_up", "fullbacks", "pivot", "striker", "corners", "corner_defence"]


def role_note(role: str, style: dict) -> str:
    """What this club asks of this position, on top of the general job."""
    out = []
    fb, pv, st = style.get("fullbacks"), style.get("pivot"), style.get("striker")
    if role in ("LB", "RB"):
        if fb == "overlap":
            out.append("Overlaps: runs past the winger on the outside.")
        elif fb == "inverted":
            out.append("Inverted: steps inside next to the pivot when the team builds.")
    if role == "DM" and pv == "drop":
        out.append("Drops between the centre-backs to build from the back.")
    if role == "ST" and st == "false9":
        out.append("Drops off the last line into midfield; the wingers run in behind.")
    scheme = style.get("press_scheme")
    if scheme == "wide_trap" and role in ("ST", "AM", "LW", "RW", "LM", "RM"):
        out.append("In the press, closes from the inside to push the carrier toward the touchline.")
    if scheme == "man" and role not in ("GK", "CB"):
        out.append("Picks up a nearby opponent in the press rather than holding a zone.")
    return " ".join(out)


WHAT = {
    "win": "The chance each result is the right one, minute by minute, from the score, the time left, the expected goals so far and any sending-off. A goal moves it by the width of the step.",
    "shots": "Every shot, sized by expected goals (xG: the chance a shot of that kind, from there, becomes a goal). Post-shot xG (xGOT) also uses where in the goal mouth it went, so it separates a good finish from a good chance.",
    "value": "Possession value gives every pass, carry and shot a score: the change in the chance the team scores minus the chance it concedes within the next few actions. It finds the actions that mattered, including ones that never become an assist.",
    "space": "Pitch control is who would reach each part of the pitch first, from where the players are standing. Control share is the share of the pitch a team controls; the block area is the size of the shape its ten outfield players make while defending.",
    "breaks": "Packing counts the opponents a forward pass takes out of the game; a line-breaking pass goes through a defensive line rather than around it.",
    "network": "Each player sits at the average place he passed from; a line joins two players for each completed pass between them, and thicker means more.",
    "runs": "Off-ball runs seen in the tracking: running in behind the defence, an overlap by a fullback, and a forward dropping into midfield. 'Ball played' says whether the run was found.",
    "load": "Distance covered, high-speed running (above 19.8 km/h), sprint distance (above 25 km/h) and accelerations. The fatigue index compares high-speed running in the last half hour with the first fifteen minutes.",
    "trans": "What happens in the seconds after the ball changes hands: how often the team wins it straight back (counter-press), turns the ball over high up the pitch, and breaks quickly for a shot.",
    "press": "PPDA is passes the opponent makes per defensive action of the pressing team, so a lower number means a harder press. It is shown by zone of the pitch, with what set each press off.",
    "set": "Shots and expected goals that come from each kind of corner, free kick and goal kick, and how the team defends corners.",
    "gk": "Goals prevented is the post-shot xG a keeper faced minus the goals he conceded: above zero means he saved more than an average keeper would.",
    "season": "The league's simulated history: where each club stands, its form, and a Poisson-model prediction of the result from each side's expected goals for and against.",
}

TRUST = [
    "All data is synthetic: the league, clubs, crests and players are fictional, and the matches are simulated at 5 Hz.",
    "Numbers are computed by code from events and tracking; no number in this report was written or estimated by a language model.",
    "Win probability, possession value and post-shot xG are fitted on simulated matches, so the ranking of actions and players is meaningful but the absolute values belong to the simulator, not to real football.",
    "Pitch control uses a simplified time-to-reach model (7 m/s, no velocity or ball), so read it as 'who is closer', not as a physical prediction.",
    "Shapes drawn in the tactics section are schematics: depth is an ordering between a team's back and front lines, not a measurement. The measured line height, length and width are averages over the time the team spent in each phase.",
    "Formations measured from tracking agree with the designed back-line count in about 85% of cases and with the exact label in about 39%; treat the measured label as 'what the average positions say'.",
]
