"""Evaluations: quality as numbers.

Run over a replay package's overlays and recaps (``matchmind evals``) and in CI. They measure the
properties the design promises, using the same checks the live system relies on:

* **numeric fidelity**  share of narrative texts whose numbers and names all trace to evidence
* **verification rate** share that pass every Verifier rule (numbers, names, policy, language, format)
* **persona separation** how different analyst and casual text for the same moment really is
                        (readability gap and number density), so "personalized" means something
* **language correctness** detected language equals the cohort's language
* **honesty**           moments with contradicting metrics whose explanation admits it
* **degradation**       how many overlays were agent-written, retried or template, per model-health run

Custom evaluators here are plain functions so they can also run as Foundry evaluators.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean

from .agents import verify as V
from .core.contracts import Cohort


def _words(t: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", t, re.UNICODE)


def readability(text: str) -> float:
    """A crude, language-independent reading-difficulty score: longer words and sentences score higher."""
    words = _words(text)
    sents = max(1, len(re.findall(r"[.!?]", text)))
    if not words:
        return 0.0
    return round(mean(len(w) for w in words) * 2 + len(words) / sents * 0.5, 2)


def number_density(text: str) -> float:
    words = max(1, len(text.split()))
    return round(len(re.findall(r"\d+(?:[.,]\d+)?", text)) / words, 3)


def evaluate_package(pkg: Path) -> dict:
    meta = json.loads((pkg / "meta.json").read_text())
    moments = {m["id"]: m for m in json.loads((pkg / "moments.json").read_text())}
    overlays = json.loads((pkg / "overlays.json").read_text())
    recaps = json.loads((pkg / "recaps.json").read_text())
    reg = V.Registry.from_meta(meta)

    narrative = [o for o in overlays if o["kind"] in ("lower_third", "ticker") and o["momentId"] in moments]
    ok_all = ok_num = ok_lang = 0
    for o in narrative:
        pack = moments[o["momentId"]]
        c = Cohort(**o["cohort"])
        text = f"{o['content']['headline']}. {o['content']['body']}"
        issues = [i for i in V.verify_text(text, pack, c.language, reg) if i.severity == "error"]
        ok_all += not issues
        ok_num += not [i for i in issues if i.code in ("number", "name")]
        ok_lang += V.detect_language(text) in (None, c.language)

    # Persona separation: the same moment for an analyst and a casual viewer, same language.
    by_moment: dict[tuple, dict] = {}
    for o in narrative:
        if o["kind"] == "lower_third" and o["cohort"]["perspective"] == "neutral":
            by_moment.setdefault((o["momentId"], o["cohort"]["language"]), {})[o["cohort"]["mode"]] = o["content"]["body"]
    pairs = [v for v in by_moment.values() if {"analyst", "casual"} <= set(v)]
    sep = {
        "pairs": len(pairs),
        "readability_gap": round(mean(readability(p["analyst"]) - readability(p["casual"]) for p in pairs), 2) if pairs else 0.0,
        "analyst_number_density": round(mean(number_density(p["analyst"]) for p in pairs), 3) if pairs else 0.0,
        "casual_number_density": round(mean(number_density(p["casual"]) for p in pairs), 3) if pairs else 0.0,
    }

    # Honesty: where evidence disagrees with the story, did the explanation say so?
    mixed = [m for m in moments.values() if any(v.get("consistent") is False for v in m["metrics"].values()) and m.get("explanations")]
    admitted = sum(1 for m in mixed if m["explanations"]["en"]["caveats"])

    recap_ok = 0
    for r in recaps:
        pack_issues = r["provenance"]["verified"] and r["provenance"]["fallbackLevel"] in (0, 2)
        recap_ok += bool(pack_issues)

    levels: dict[str, int] = {}
    for o in narrative:
        k = str(o["provenance"]["fallbackLevel"])
        levels[k] = levels.get(k, 0) + 1

    n = max(1, len(narrative))
    return {
        "matchId": meta["matchId"],
        "narrativeOverlays": len(narrative),
        "verificationRate": round(ok_all / n, 4),
        "numericFidelity": round(ok_num / n, 4),
        "languageCorrectness": round(ok_lang / n, 4),
        "personaSeparation": sep,
        "honesty": {"mixedEvidenceMoments": len(mixed), "admitted": admitted, "rate": round(admitted / len(mixed), 3) if mixed else 1.0},
        "recapsVerified": f"{recap_ok}/{len(recaps)}",
        "levels": levels,
        "modelHealth": meta["package"].get("variants", {}),
    }


def evaluate_all(root: Path) -> list[dict]:
    return [evaluate_package(p) for p in sorted(root.iterdir()) if (p / "meta.json").exists()]


# Thresholds the CI gate enforces.
GATES = {"numericFidelity": 1.0, "verificationRate": 1.0, "languageCorrectness": 0.99}


def gate(report: dict) -> list[str]:
    fails = [f"{report['matchId']}: {k} {report[k]} < {v}" for k, v in GATES.items() if report[k] < v]
    sep = report["personaSeparation"]
    if sep["pairs"] and not sep["analyst_number_density"] > sep["casual_number_density"]:
        fails.append(f"{report['matchId']}: analyst text is not denser in numbers than casual text")
    if report["honesty"]["rate"] < 1.0:
        fails.append(f"{report['matchId']}: some contradicting evidence was not admitted ({report['honesty']})")
    return fails
