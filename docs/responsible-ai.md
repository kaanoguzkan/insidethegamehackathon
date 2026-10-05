# Responsible AI

* **Synthetic data only.** No personal data, no real people, clubs, crests, footage or music.
* **Grounding by construction.** Text comes from an evidence pack; a deterministic Verifier rejects any
  number, player or club the pack does not license. Tests try to slip invented numbers, wrong players,
  hallucinated minutes, banned words, wrong languages, written-out counts and cherry-picked metrics past it.
* **Honesty about mixed evidence.** Metrics that move against a story are flagged and must be admitted;
  confidence drops when several disagree. The evidence drawer shows them.
* **Policy.** No betting, alcohol, drugs, tobacco, politics, insults or accusations, and no medical
  speculation, in English, Spanish and Turkish. Model-side content filters (Foundry, Azure AI Content
  Safety) are an additional layer in the Azure deployment, not a replacement.
* **No pronouns for people** in generated text, and no gender assumptions: the data names players and
  nothing more.
* **Transparency.** Every overlay says how it was made (agent team, after a retry, or template) and links
  to its evidence.
* **Human in the loop.** The design allows a producer approval step; it is not built.
* **Accessibility.** Screen-reader live region, reduced motion, high contrast, full keyboard control and a
  shape cue (not only colour) separating the two teams.
* **Limits.** Real-model behaviour is unmeasured (no model was available while building). The policy word
  lists are small and are not a substitute for a content-safety service.
