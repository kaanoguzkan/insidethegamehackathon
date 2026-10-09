"""Ask the match: a viewer asks a question and gets an answer that is checked against the match data.

The same rule as the rest of MatchMind: *code gets the evidence, the model only phrases it*.

    question ──▶ Planner (model, or rules) ──▶ tools run by code ──▶ Answerer (model, or a digest) ──▶ Verifier ──▶ answer
                    │ off topic                    the Match Data MCP server's tools, in process          │ reject
                    └──▶ a polite refusal, no further model call                                         └──▶ Repairer ──▶ digest of the facts

* The planner chooses from an **allow-list** of the MCP tools. Whatever it returns is validated: unknown tools are dropped, arguments the
  tool does not declare are dropped, ``match_id`` is always the request's, and at most three tools run. The question is treated as data.
* Tool results are cut to a size that keeps the answer's cost down, and become the *only* evidence: every number, player and club in the
  answer must appear in them (the same Verifier as the overlays), or the sentence is cut out, or the answer becomes a plain digest of the facts.
* Each step has a fallback that needs no model, so a slow or failing model costs the polish, never the answer.
* The result reports the tokens used and what they cost (``pricing.py``), so the cost can be watched and reduced.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..core.contracts import ToolCall
from . import verify
from .pricing import cost_usd
from .team import AgentFailure, AgentTeam

MAX_QUESTION_CHARS = 280
MAX_TOOLS = 3
MAX_RESULT_CHARS = 2200  # per tool: keeps the answerer's input (and the bill) small
TOOL_TIMEOUT_S = 25.0
# The tools the planner may choose. `list_matches` and `get_event_chain` are not useful for a question; the rest are.
ALLOWED_TOOLS = (
    "get_match_state", "get_window_stats", "compare_windows", "get_player_window", "get_season_context", "get_prediction",
    "get_win_probability", "get_key_actions", "get_space_control", "get_passing_network", "get_team_shape", "get_phases_of_play",
    "get_line_breaks", "get_off_ball_runs", "get_physical_load", "get_transitions", "get_set_piece_report", "get_shot_map",
    "get_goalkeeper_report", "get_pressing_report", "get_player_profile", "list_moments", "explain_metric",
)  # fmt: skip

# Numeric arguments with a real range. The model cannot know a tool's scale (it once asked for min_salience 5 on a 0 to 1 scale and got no moments at all), so the
# range is shown in the catalogue and every value is clamped to it before the tool runs.
ARG_RANGES: dict[str, tuple[float, float]] = {
    "min_salience": (0.0, 1.0), "min_xg": (0.0, 1.0), "top": (1, 15), "min_distance": (0.0, 60.0),
    "minute": (0, 130), "since_minute": (0, 130), "from_minute": (0, 130), "to_minute": (0, 130),
    "before_from": (0, 130), "before_to": (0, 130), "after_from": (0, 130), "after_to": (0, 130),
}

REFUSAL = {
    "en": "I can only answer questions about this match and its numbers. Try asking about the pressing, who had the momentum, the shots or the formations.",
    "es": "Solo puedo responder preguntas sobre este partido y sus números. Prueba con la presión, quién tuvo el impulso, los tiros o las formaciones.",
    "tr": "Yalnızca bu maç ve sayıları hakkındaki soruları yanıtlayabilirim. Baskıyı, kimin üstünlük kurduğunu, şutları veya dizilişleri sorabilirsin.",
}
NOTHING = {
    "en": "I could not find that in this match's data. Try asking about the pressing, momentum, shots, formations or the key moments.",
    "es": "No encontré eso en los datos de este partido. Prueba con la presión, el impulso, los tiros, las formaciones o los momentos clave.",
    "tr": "Bunu bu maçın verilerinde bulamadım. Baskıyı, üstünlüğü, şutları, dizilişleri veya kilit anları sormayı dene.",
}
DIGEST_HEAD = {
    "en": "I could not phrase a checked answer, so here are the numbers the data gives for your question:",
    "es": "No pude redactar una respuesta verificada, así que estos son los números que dan los datos para tu pregunta:",
    "tr": "Doğrulanmış bir yanıt yazamadım; verilerin sorun için verdiği sayılar şöyle:",
}

# Question words -> tools that need no argument beyond the match. The fallback planner when the model is unavailable.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    (r"press|baski|presión|presion|gegen", ("get_pressing_report", "get_transitions")),
    (r"momentum|control|chaos|who (won|dominated|controlled)|domin|impuls|üstünlük|ustunluk|baskın", ("get_match_state",)),
    (r"win prob|chance|likel|predict|probab|favou?rite|olasılık|olasilik|probabilidad", ("get_win_probability", "get_prediction")),
    (r"shot|xg|goal|expected|finish|şut|sut|tiro|disparo|gol", ("get_shot_map", "list_moments")),
    (r"keeper|goalkeeper|save|portero|kaleci", ("get_goalkeeper_report",)),
    (r"corner|free kick|set piece|throw|córner|corner|tiro libre|korner|serbest", ("get_set_piece_report",)),
    (r"sprint|fatigue|distance|physical|run|speed|km|cansancio|distancia|koşu|kosu|yorgun", ("get_physical_load",)),
    (r"line.?break|pack|progress", ("get_line_breaks",)),
    (r"best player|key player|most valuable|mvp|important|valioso|en değerli|en degerli", ("get_key_actions",)),
    (r"moment|key|highlight|happen|story|momento|an$|kilit", ("list_moments",)),
]
_TEAM_RULES: list[tuple[str, str]] = [  # (pattern, tool needing a team)
    (r"formation|shape|line.?up|dizilis|diziliş|formación|formacion", "get_team_shape"),
    (r"phase|build.?up|settled|faz|fase", "get_phases_of_play"),
    (r"passing network|who passes|pass network|pas ağı|red de pases", "get_passing_network"),
]


@dataclass
class AskResult:
    answer: str
    level: int  # 0 model answer verified first time, 1 mended, 2 digest of the facts, 3 refusal or nothing found
    tools: list[dict] = field(default_factory=list)
    verified: bool = True
    refused: bool = False
    usage: dict = field(default_factory=lambda: {"inputTokens": 0, "outputTokens": 0})
    elapsed_ms: int = 0
    trace: list[dict] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "answer": self.answer, "level": self.level, "verified": self.verified, "refused": self.refused,
            "tools": self.tools, "elapsedMs": self.elapsed_ms, "trace": self.trace,
            "usage": {**self.usage, "costUsd": cost_usd(self.usage.get("inputTokens", 0), self.usage.get("outputTokens", 0))},
        }


def clean_question(text: str) -> str:
    """Printable text, one line, bounded: the question reaches a prompt, so it is shaped before it gets there."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:MAX_QUESTION_CHARS]


def _range_hint(arg: str) -> str:
    lo, hi = ARG_RANGES.get(arg, (None, None))
    return "" if lo is None else f"({lo:g}-{hi:g})"


def catalogue(tools: list[Any]) -> list[dict]:
    """The planner's view of the tools: name, arguments (required marked with *) and one sentence. Small on purpose: tokens cost money."""
    out = []
    for t in tools:
        if t.name not in ALLOWED_TOOLS:
            continue
        props, req = t.inputSchema.get("properties", {}), t.inputSchema.get("required", [])
        args = [f"{k}{'*' if k in req else ''}{_range_hint(k)}" for k in props if k != "match_id"]
        out.append({"name": t.name, "args": args, "returns": (t.description or "").split(".")[0][:110]})
    return out


def rule_plan(question: str, teams: dict[str, str], tool_info: dict[str, set[str]]) -> list[dict]:
    """A deterministic planner: keywords to tools. Used when the model is slow, down or returns nothing usable."""
    q = question.lower()
    chosen: list[str] = []
    for pattern, names in _RULES:
        if re.search(pattern, q):
            chosen += [n for n in names if n not in chosen]
    calls = [{"name": n, "args": {}} for n in chosen if n in tool_info]
    mentioned = [tid for tid, name in teams.items() if tid.lower() in q.split() or name.lower() in q or name.split()[0].lower() in q]
    for pattern, tool in _TEAM_RULES:
        if re.search(pattern, q) and tool in tool_info:
            for tid in (mentioned or list(teams))[:2]:
                calls.append({"name": tool, "args": {"team": tid}})
    return calls[:MAX_TOOLS] or [{"name": n, "args": {}} for n in ("get_match_state", "list_moments") if n in tool_info]


def validate_plan(tools: list[Any], match_id: str, teams: dict[str, str], tool_info: dict[str, dict]) -> list[dict]:
    """Whatever the planner proposed, reduced to what is safe to run: allow-listed tools, declared arguments, this match, at most three."""
    calls: list[dict] = []
    for t in tools:
        if len(calls) >= MAX_TOOLS:
            break  # the cap counts tools that can run: an invalid proposal does not use up the budget
        name = getattr(t, "name", "")
        if name not in tool_info:
            continue
        try:
            raw = json.loads(getattr(t, "args", "") or "{}")
        except ValueError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        schema = tool_info[name]
        args = {k: v for k, v in raw.items() if k in schema["properties"] and k != "match_id" and isinstance(v, (str, int, float, bool))}
        for k, v in list(args.items()):  # a team argument must be one of this match's teams
            if k == "team" and v not in teams:
                match = next((tid for tid, n in teams.items() if str(v).lower() in (tid.lower(), n.lower())), None)
                if match is None:
                    args.pop(k)
                else:
                    args[k] = match
            if isinstance(v, str) and len(v) > 40:
                args.pop(k, None)
            elif k in ARG_RANGES and isinstance(v, (int, float)) and not isinstance(v, bool):
                lo, hi = ARG_RANGES[k]
                args[k] = min(max(v, lo), hi)
        if any(r != "match_id" and r not in args for r in schema["required"]):
            continue  # a tool call missing a required argument cannot run
        calls.append({"name": name, "args": {"match_id": match_id, **args}})
    return calls


def _prune(x: Any, depth: int, items: int) -> Any:
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: _prune(v, depth - 1, items) for k, v in x.items()} if depth > 0 else "..."
    if isinstance(x, list):
        return [_prune(v, depth - 1, items) for v in x[:items]] if depth > 0 else "..."
    return x


def compact(obj: Any, limit: int) -> Any:
    """A tool result reduced to at most ``limit`` characters of JSON while it stays data: lists are trimmed, deep levels dropped and floats rounded,
    in steps, until it fits. Cutting the text instead would leave a string that neither the answerer nor the digest could use."""
    for depth, items in ((6, 8), (5, 5), (4, 3), (3, 2), (3, 1), (2, 1)):
        out = _prune(obj, depth, items)
        if len(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str)) <= limit:
            return out
    return {"truncated": json.dumps(obj, ensure_ascii=False, default=str)[:limit]}


def evidence_pack(results: dict[str, Any], registry: verify.Registry, minute: float | None) -> dict:
    """A pack shaped for the Verifier, whose evidence is whatever the tools returned: every number anywhere in the results is licensed,
    and every player and club of the match may be named (a question can be about any of them)."""
    text = json.dumps(results, ensure_ascii=False, default=str)
    return {
        "type": "chat", "metrics": {}, "windows": {}, "eventIds": [], "subjectTeam": None,
        "facts": {"results": results, "numbers": [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", text)]},
        "detectedAt": {"clock": {"minute": int(minute or 90), "second": 0}, "label": ""},
        "players": [{"id": pid, "name": name} for pid, name in registry.players.items()],
        "teamNames": {cid: v[0] for cid, v in registry.clubs.items()},
    }


def verify_answer(answer: str, pack: dict, lang: str, registry: verify.Registry, mode: str) -> list[verify.Issue]:
    issues = verify.verify_text(answer, pack, lang, registry, "answer")
    limit = verify.MAX_WORDS["casual" if mode == "casual" else "analyst"] + 25
    if len(answer.split()) > limit:
        issues.append(verify.Issue("format", f"the answer is longer than {limit} words", where="answer"))
    return [i for i in issues if i.severity == "error"]


_SENTENCES = re.compile(r"(?<=[.!?…])\s+")


def mend(answer: str, pack: dict, lang: str, registry: verify.Registry, mode: str) -> str | None:
    """Cut out the sentences that fail the Verifier and keep the rest, if what is left still passes (it never adds a word)."""
    kept = [s for s in _SENTENCES.split(answer.strip()) if s and not verify.verify_text(s, pack, lang, registry, "answer")]
    if not kept or len(kept) == len(_SENTENCES.split(answer.strip())):
        return None
    fixed = " ".join(kept)
    return fixed if not verify_answer(fixed, pack, lang, registry, mode) else None


def digest(results: dict[str, Any], lang: str, limit: int = 8) -> str:
    """No model: the facts the tools returned for the question, as short lines of name and value."""
    lines: list[str] = []

    def walk(prefix: str, x: Any, depth: int) -> None:
        if len(lines) >= limit or depth > 3:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                walk(f"{prefix}{k} " if prefix else f"{k} ", v, depth + 1)
        elif isinstance(x, list):
            for v in x[:2]:
                walk(prefix, v, depth + 1)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            lines.append(f"{prefix.strip()}: {round(x, 2) if isinstance(x, float) else x}")
        elif isinstance(x, str) and 0 < len(x) <= 28 and not prefix.strip().endswith(("id", "Id", "matchId")):
            lines.append(f"{prefix.strip()}: {x}")

    for name, res in results.items():
        walk(f"{name}: ", res, 0)
    head = DIGEST_HEAD.get(lang, DIGEST_HEAD["en"])
    return head + " " + "; ".join(lines) if lines else NOTHING.get(lang, NOTHING["en"])


async def ask(
    team: AgentTeam, mcp: Any, registry: verify.Registry, *, match_id: str, question: str, language: str = "en", mode: str = "casual",
    minute: float | None = None, deadline_s: float = 30.0,
) -> AskResult:
    t0 = time.monotonic()
    result = AskResult(answer="", level=3)
    left = lambda: max(deadline_s - (time.monotonic() - t0), 0.2)  # noqa: E731

    def note(agent: str, outcome: str, since: float) -> None:
        result.trace.append({"agent": agent, "outcome": outcome, "ms": round((time.monotonic() - since) * 1000, 1)})

    question = clean_question(question)
    tools = await mcp.list_tools()
    tool_info = {t.name: {"properties": t.inputSchema.get("properties", {}), "required": t.inputSchema.get("required", [])} for t in tools if t.name in ALLOWED_TOOLS}
    teams = {cid: v[0] for cid, v in registry.clubs.items()}

    # 1. Plan
    s = time.monotonic()
    try:
        plan = await team.plan(
            {"question": question, "tools": catalogue(tools), "teams": [{"id": k, "name": v} for k, v in teams.items()], "minute": minute},
            timeout_s=min(left(), 12.0), usage=result.usage,
        )
        if plan.refuse and not plan.tools:
            result.answer, result.level, result.refused = REFUSAL.get(language, REFUSAL["en"]), 3, True
            note("planner", "refused: off topic", s)
            result.elapsed_ms = round((time.monotonic() - t0) * 1000)
            return result
        calls = validate_plan(plan.tools, match_id, teams, tool_info)
        note("planner", f"ok: {', '.join(c['name'] for c in calls) or 'nothing usable'}", s)
    except AgentFailure as e:
        calls = []
        note("planner", f"failed: {e.reason}"[:160], s)
    if not calls:  # the model was unavailable, or chose nothing runnable: keywords decide
        s = time.monotonic()
        calls = validate_plan(
            [ToolCall(name=c["name"], args=json.dumps(c["args"])) for c in rule_plan(question, teams, tool_info)], match_id, teams, tool_info
        )
        note("router", f"rules: {', '.join(c['name'] for c in calls) or 'nothing'}", s)

    # 2. Run the tools (code, in parallel; each bounded)
    def parse(out: Any) -> Any:
        """A tool result as plain data. FastMCP returns ``(content, structured)`` for a tool that returns a dict and just the content blocks
        for one that returns a list (each block a JSON text)."""
        content, structured = out if isinstance(out, tuple) else (out, None)
        if isinstance(structured, dict):
            return structured["result"] if set(structured) == {"result"} else structured
        items = []
        for block in content or []:
            text = getattr(block, "text", "")
            try:
                items.append(json.loads(text))
            except ValueError:
                items.append(text)
        return items[0] if len(items) == 1 else items

    async def run(call: dict) -> tuple[str, Any]:
        try:
            out = parse(await asyncio.wait_for(mcp.call_tool(call["name"], call["args"]), min(TOOL_TIMEOUT_S, left())))
            if out in ([], {}, None) and len(call["args"]) > 1:  # nothing came back: the filters the model chose may be what emptied it, so ask again without them
                out = parse(await asyncio.wait_for(mcp.call_tool(call["name"], {"match_id": call["args"]["match_id"]}), min(TOOL_TIMEOUT_S, left())))
            return call["name"], out
        except Exception as e:  # noqa: BLE001 - a tool that fails is reported as missing, not fatal
            return call["name"], {"error": str(e)[:120]}

    async def run_all(chosen: list[dict]) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for name, res in await asyncio.gather(*(run(c) for c in chosen)):
            if isinstance(res, dict) and set(res) == {"error"}:
                continue  # a failed tool is not evidence
            results[name if name not in results else f"{name}#2"] = compact(res, MAX_RESULT_CHARS)
        return results

    s = time.monotonic()
    usable = await run_all(calls)
    note("tools", f"{len(usable)} of {len(calls)} gave data", s)
    if not usable:  # the model's choice did not run (wrong arguments, say): the keyword planner gets one go before giving up
        s = time.monotonic()
        calls = validate_plan(
            [ToolCall(name=c["name"], args=json.dumps(c["args"])) for c in rule_plan(question, teams, tool_info)], match_id, teams, tool_info
        )
        usable = await run_all(calls)
        note("router", f"rules after a failed plan: {len(usable)} of {len(calls)} gave data", s)
    result.tools = [{"name": c["name"], "args": {k: v for k, v in c["args"].items() if k != "match_id"}} for c in calls]
    if not usable:
        result.answer, result.level = NOTHING.get(language, NOTHING["en"]), 3
        result.elapsed_ms = round((time.monotonic() - t0) * 1000)
        return result

    # 3. Answer, verify, mend
    pack = evidence_pack(usable, registry, minute)
    s = time.monotonic()
    try:
        out = await team.answer(
            {"question": question, "results": usable, "language": language, "mode": mode, "teams": [{"id": k, "name": v} for k, v in teams.items()]},
            timeout_s=min(left(), 20.0), usage=result.usage,
        )
        text = " ".join(out.answer.split())
        issues = verify_answer(text, pack, language, registry, mode)
        if not issues:
            result.answer, result.level = text, 0
            note("answerer", "ok", s)
        else:
            fixed = mend(text, pack, language, registry, mode)
            if fixed:
                result.answer, result.level = fixed, 1
                note("repairer", f"mended: {issues[0].message}"[:160], s)
            else:
                note("verifier", f"rejected: {issues[0].message}"[:160], s)
    except AgentFailure as e:
        note("answerer", f"failed: {e.reason}"[:160], s)
    if not result.answer:
        result.answer, result.level = digest(usable, language), 2
        note("digest", "facts only", time.monotonic())
    result.elapsed_ms = round((time.monotonic() - t0) * 1000)
    return result
