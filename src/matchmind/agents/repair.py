"""The Repairer: a rule-based agent that mends model text the Verifier rejected, instead of discarding it.

Most rejections are small and mechanical: one sentence with a banned word, a figure that is not in the evidence, a name
the registry does not know, a claim citing a key that does not exist, a body a few words too long. Throwing the whole
variant away for that wastes a model call that already finished, and the fast path has no time for another.

The Repairer cuts out only what failed, then asks the Verifier again. It never adds words, so it cannot introduce a fact:

* a failing sentence is dropped (if none is left, the variant is not repairable);
* a failing headline is replaced by the template headline for the same moment and cohort;
* a failing claim is dropped (claims are optional support, the sentences are verified directly);
* a body over the length limit loses its last sentences, keeping at least one;
* a variant in the wrong language is not repairable: the whole text is wrong.

A repaired variant is accepted only if the Verifier then passes it, and it is reported as fallback level 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.contracts import Cohort, StoryVariant
from . import templates, verify

_SENTENCES = re.compile(r"(?<=[.!?…])\s+")


@dataclass
class Repair:
    variant: StoryVariant
    actions: list[str] = field(default_factory=list)


def _errors(issues: list[verify.Issue]) -> list[verify.Issue]:
    return [i for i in issues if i.severity == "error"]


def repair(variant: StoryVariant, pack: dict, cohort: Cohort, registry: verify.Registry | None = None) -> Repair | None:
    """The variant with its failing parts removed, or None if what is left is not worth showing."""
    lang, actions = cohort.language, []

    headline = variant.headline
    if _errors(verify.verify_text(headline, pack, lang, registry, "headline")) or _errors(verify.check_format(headline, "x", cohort.mode)):
        headline = templates.render(pack, cohort).headline
        actions.append("headline from template")

    sentences = [s for s in _SENTENCES.split(variant.body.strip()) if s]
    kept = [s for s in sentences if not _errors(verify.verify_text(s, pack, lang, registry, "body"))]
    if len(kept) < len(sentences):
        actions.append(f"dropped {len(sentences) - len(kept)} sentence(s)")
    if not kept:
        return None
    while len(kept) > 1 and _errors(verify.check_format(headline, " ".join(kept), cohort.mode)):
        kept.pop()
        actions.append("trimmed to length")

    claims = [c for c in variant.claims if not _errors(verify.check_claims([c], pack, lang, registry))]
    if len(claims) < len(variant.claims):
        actions.append(f"dropped {len(variant.claims) - len(claims)} claim(s)")

    fixed = variant.model_copy(update={"headline": headline, "body": " ".join(kept), "claims": claims})
    if not actions or not verify.verify_variant(fixed, pack, cohort, registry).ok:
        return None
    return Repair(fixed, actions)
