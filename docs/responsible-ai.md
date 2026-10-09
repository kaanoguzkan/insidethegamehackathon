# Responsible AI

* **Synthetic data only.** No personal data, no real people, clubs, crests, footage or music.
* **Grounding by construction.** Text comes from an evidence pack; a deterministic Verifier rejects any
  number, player or club the pack does not license. Tests try to slip invented numbers, wrong players,
  hallucinated minutes, banned words, wrong languages, written-out counts and cherry-picked metrics past it.
  The live model's first runs were refused for exactly these reasons (invented evidence keys, player ids written into the text, a banned
  word); the prompts and the data shown to the model were changed, not the Verifier.
* **Repair only removes.** When the Verifier refuses a model text, the Repairer may cut out the failing sentence, headline or claim and check the
  rest again. It never adds or rewrites words, so repair cannot introduce a fact; a text it cannot make pass becomes verified template text.
* **Honesty about mixed evidence.** Metrics that move against a story are flagged and must be admitted;
  confidence drops when several disagree. The evidence drawer shows them.
* **Policy.** No betting, alcohol, drugs, tobacco, politics, insults or accusations, and no medical
  speculation, in English, Spanish and Turkish. Foundry's default content filter sits on the model deployment as an additional layer; it has
  not been tuned or red-teamed by this project, and it is not a replacement for the Verifier's checks.
* **No pronouns for people** in generated text, and no gender assumptions: the data names players and
  nothing more.
* **Transparency.** Every overlay says how it was made (agent team, after a retry or repair, or template), which agents touched it and whether the
  Verifier passed it, and links to its evidence. In Live AI the evidence drawer shows the agents (`E R C ✓`), the time and whether it came from the
  cache, and says so plainly when the text is a template.
* **Untrusted input.** The model only ever sees evidence packs and values the server controls. The two request fields that reach the prompt,
  a cohort's `perspective` and `focusPlayer`, must be one of the match's club and player ids, so a caller cannot put instructions into them (and
  the Verifier would check the output anyway). Prompts and answers are not written to traces unless `MATCHMIND_TRACE_CONTENT=1`.
* **A public service that guards itself.** The live endpoint is open to the internet and spends model tokens, so it has a per-client rate limit, a cap on
  simultaneous requests, an admin key for the expensive options and a ceiling on the model deployment's tokens a minute
  ([running-on-azure.md](running-on-azure.md)). Budgets alert but do not stop spending; these guards are what bound it.
* **Independent evaluation.** Foundry's groundedness, relevance, coherence and fluency evaluators score the overlay text next to our own checks
  ([foundry.md](foundry.md)). The sample is small, the judge is from the same model family as the writer, and red-teaming has not been run.
* **Human in the loop.** The design allows a producer approval step; it is not built.
* **Accessibility.** Screen-reader live region (the Live AI status is announced), reduced motion, high contrast, full keyboard control and a
  shape cue (not only colour) separating the two teams.
* **Limits.** Real-model behaviour is measured on one model and a small sample (45 live calls, 30 evaluated overlays per group). The policy word lists
  are small and are not a substitute for a content-safety service. A model that is slow or wrong costs the upgrade, never correctness: the template
  text is always there, but it reads plainer.
