# Three contrasting lesson drafts from the saved development corpus

16 September 2026. AI-assisted research and authoring; no independent chess review or participant results.

**Three provisional lesson families now have two positive examples and one real contrasting case each.** The nine cases come from separate originating games, including legacy aliases, and distinct canonical positions. They contain concrete prompts, explanations for every accepted answer, ten continuation questions, and exact saved engine comparisons. They are development drafts, not validated concepts or an assessment bank.

This completes a small version of experiment A in [the research agenda](RESEARCH_NEXT_2026-09-16.md). Three of the original six hypotheses supplied starting cases; six additional cases were retrieved from the admitted editorial pool. The other three hypotheses remain deferred rather than being padded with superficially similar positions.

## What the contrasts teach

| Proposed family | Connection between the two positive examples | Real boundary from another game | Remaining limitation |
|---|---|---|---|
| Calculate a checking fork through the recapture | A defense can remove the other fork target, support an interposition, change the recapturing piece, or remove the checking tempo. The learner must calculate the capture sequence. | A checking knight fork does not collect the additional attacked piece because the knight can be recaptured immediately. | The original pawn-supported interposition remains one particular instance. This is a familiar tactical decision family, not a newly discovered chess concept. |
| A queen counterattack needs a surviving reciprocal capture | A piece attacks the opposing queen while its own queen remains attacked; the saved lines preserve a reciprocal queen capture. | The opposing queen itself captures and leaves the square under counterattack, so the supposed reciprocal capture disappears. | Unshown queen replies and intermediate checks need independent review; both positive examples concern avoiding a worse position. |
| Repair the recapture, not just the pin | Relocating the valuable rear piece onto a defended square changes how an exchange can be recaptured, rather than simply retreating the front piece. | Moving the queen away from one relative pin leaves a different pawn pinned to the king. Another queen square makes the needed pawn recapture legal. | The boundary involves two pins and may belong in a more advanced follow-up. The explanatory family is conditional, not “always move the rear piece.” |

The boundary cases were not created by altering a board. They are distinct real source-game positions already covered by the completed legal-root searches. Some short illustrative continuations are newly authored legal variations, clearly labeled as unscored rather than passed off as saved best play.

## What was searched and checked

The reproducible builder first calls the existing completed-bundle verifier and editorial eligibility gate. It then inspects boards and continuations only for the **1,032 admitted retained development/training states**. Every origin must be recovered, without a BOT tag or known public exposure, and every origin's role must be `prior_development`, `pilot_train`, or `new_train`. Protected validation/test cases are excluded before board inspection.

The mechanism screens examined **73,142 saved legal roots** across the admitted states. Their broad retrieval counts were:

| Screen | Matching roots | Distinct states | Accepted matching roots |
|---|---:|---:|---:|
| Non-queen move attacking the opposing queen while its own queen is attacked | 83 | 38 | 12 across 11 states |
| Relocation of a rook/queen behind one friendly blocker on an opposing slider's ray | 1,255 | 220 | 42 across 39 states |
| Opponent knight check also attacking nonpawn material within six plies of an inferior saved root | 912 | 242 | Not applicable: this screen requires a loss of at least 100cp at both depths |

These screens overlap. They are fallible geometric retrieval rules, not family labels, prevalence estimates, or a ranking of teaching quality. The third screen reads the depth-24 continuation while requiring the score-loss condition at both saved depths. Finding a fork inside a principal variation does not prove that the fork caused the inferior evaluation.

The selected nine cases comprise six White-to-move and three Black-to-move positions; one opening, seven middlegames and one endgame under the existing phase labels. This deliberately selected set is not balanced or representative. The broad screen output, seven specific rejected/deferred/reserve near-match decisions, and the reasons for rejecting generic matches are retained privately. The seven decisions are not an exhaustive adjudication of every screen hit.

For the final bank the compiler:

- Recomputed every selected outcome against the unchanged complete legal-root evidence and replayed **710 roots and 13,920 saved PV plies**.
- Attached **62 exact depth-20/depth-24 root citations** to accepted answers and comparison moves, each retaining its saved-root fingerprint.
- Checked **41 board facts through 68 executable assertions** about occupancy, attacks, checks and legal recaptures.
- Checked **ten continuation questions** against either an exact saved PV prefix or an explicitly labeled legality-only assertion.
- Required a separate authored discussion for **every accepted move**. Three cases have multiple accepted answers. In one case an alternative lies exactly on the 20cp tolerance boundary at depth 24; the prose names that sensitivity and explains the higher-scoring alternative as well.
- Rejected repeated identities, canonical states, originating games or legacy aliases across all lesson roles. It bound the output to the frozen evidence, unchanged seed packet and original drafts, current builder, and separately authored private notes.
- Preserved every readiness gate as false and refused exports outside the ignored private directory or over an existing export.

**No engine searches, model inference, fresh mining, trainer additions or human approvals were performed for this work.** The compiler validates evidence links and specific chess facts; it cannot validate a causal explanation or learning benefit. Fifteen focused tests cover source leakage, alias overlap, canonical duplication, corrupt questions, missed accepted alternatives, source changes, geometry boundaries, gate promotion and export protections.

## What was not promoted

The active-rook-defense, passed-pawn-preservation and capture-first-liquidation drafts still lack a sufficiently specific second positive and a different-game boundary. Common pieces, similar evaluations or generic activity are insufficient evidence for a family. The exact pawn-interposition mechanism was retained as a subcase rather than pretending a second identical mechanism had been found.

The private drafts retain all accepted alternatives and expose nearby exclusions. A 20cp threshold is an operational rule, not an assertion that a 21cp move is a human blunder. Saved evaluation differences support comparisons, but a single saved continuation does not exhaust the opponent's replies. Negative best evaluations are described as damage limitation, not winning combinations.

## How this changes the next step

An independent reviewer now has nine actual cases to accept, revise or reject, rather than six isolated labels. Review should first check the chess explanation without its suggested family title, then assess whether the positive pair and boundary isolate the same decision. The advanced two-pin contrast may need to be split from the simpler examples.

If the families survive that review, their definitions can be frozen before selecting unseen assessment items. The nine development cases are not eligible to become unseen tests of these definitions. This bank also does not meet the existing eight-family, 48-item study target; it is a concrete first subset for editorial review.

The builder is [lesson_family_research.py](../scripts/lesson_family_research.py). Its scan and compilation modes write only private outputs. Compilation takes the private authored notes and a new ignored output directory; it never starts an engine. The final readable artifact is titled **Contrasting lesson drafts** and includes the positions, all accepted answers, prompts, continuation questions, exact saved lines and unresolved checks.
