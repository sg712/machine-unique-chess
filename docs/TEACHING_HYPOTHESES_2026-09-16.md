# Teaching hypotheses from the private editorial packet

**Six AI-assisted teaching drafts now connect specific board facts to saved engine comparisons. None is a reviewed lesson or a validated new chess concept.** The private drafts contain three White-to-move and three Black-to-move positions, exact saved continuations at depths 20 and 24, plausible Maia alternatives, lesson prompts, and explicit counterexamples to overbroad explanations.

This memo intentionally contains no private positions, answers, source-game identifiers, or candidate identifiers. The original packet, engine evidence and readiness decisions are unchanged. No engine search or model inference was run for this work.

## What the packet already rules out

The existing 24-position packet was deliberately selected for editorial diversity; it is not a random sample of the retained pool. Within this packet:

- **12 positions have multiple accepted moves.** A trainer that accepts only the top move would reject other moves that meet the same frozen acceptance rule.
- **10 positions have a negative best saved evaluation; one has a zero evaluation.** Some examples teach resistance or preserving drawing chances. Describing all of them as winning moves would misstate the evidence.
- **Two accepted sets contain a capture and one contains a check.** Rarity in a human-move model does not imply a quiet move.
- **One accepted continuation stops after 15 plies.** A saved line ending during checks does not establish a forced perpetual, especially when the root search used a position without full game-history context.

The accepted set is the existing set within 20 centipawns of the best saved root score. This is an operational selection rule, not a boundary between humanly correct moves and blunders. The private screening notes also identify alternatives within 50 centipawns so that marginal exclusions remain visible.

## Six concrete directions for lessons

| Teaching hypothesis | Concrete mechanism identified in the draft | Why this could be more useful than naming the moving piece | What remains uncertain |
|---|---|---|---|
| Supply the recapture, or remove the fork target | One defense removes a bishop from a future knight fork; another pawn move supports an interposition and its recapture. A superficially similar pawn move does not. | Asks the learner to calculate a threat sequence and explain why two different defenses work. | Both accepted moves need full independent review. The later continuations differ between saved depths. |
| Answer an attack with a forcing counterattack | A bishop attacks the opposing queen while its own queen remains attacked; a later pawn attack allows a reciprocal queen trade that preserves another piece. | Teaches looking for an intermediate threat before automatically retreating an attacked queen. | The side remains worse in the saved evaluation. Unshown queen replies must be checked before calling the sequence forced. |
| Change the recapture geometry before countercapturing | A rook shifts onto a knight-defended square, making a pawn countercapture possible without simply losing the rook to the queen. | Explains a relative pin and why saving the attacked minor piece immediately can be inferior. | Other opponent captures and near-best rook alternatives need review. The pawn was legally movable throughout; this is not an absolute pin. |
| Trade passive defense for active rook play | A protected rook challenges the opposing rook, then reaches enemy pawns if the exchange is declined. | Connects a square's defender, move order and access to counterplay. | The saved line ends during checks. Neither a forced draw nor the evaluation of every rook-exchange ending has been established here. |
| Choose the capture that preserves the right passer | A rook improves its square before capturing, so it can remove a flank pawn and protect its own pawn afterward. | Makes the learner compare the resulting pawn races instead of taking the nearest pawn automatically. | The saved advantage is not a proved win. One legal illustration deliberately shows an avoidable rook blunder and must never be passed off as best play. |
| Take the useful pawn before central liquidation | A direct knight capture leads to a saved exchange sequence; a tempting maneuver permits different minor-piece trades and king-pawn damage. | Gives a concrete capture-first counterexample to blanket quiet-move descriptions. | The bishop and king-cover explanation is a hypothesis, not a causal result. It needs contrasting branches that isolate those features. |

The first three have the clearest immediate board mechanisms for independent editorial review. The active-rook case is a useful fourth comparison but needs a more complete account of its defensive ending. The remaining two offer promising strategic questions with weaker explanatory certainty. This ordering is an editorial judgment, not a computed teaching-quality score.

## What was actually verified

The compiler in `scripts/draft_teaching_cases.py` checked the unchanged packet as follows:

- Replayed **all 1,578 saved roots and 30,806 principal-variation plies** across the 24 positions, checking legality, SAN, saved board frames, depth coverage, acceptance flags and score-loss consistency.
- Checked **33 stated board facts through 96 executable assertions** covering piece locations, attacks, legal recaptures and checks.
- Attached **36 exact saved depth-20/depth-24 root citations** to the six drafts. Each citation retains its saved-root fingerprint, score, acceptance status and Maia probabilities.
- Required the packet fingerprint and each selected case's evidence fingerprint to match the notes. All origin analysis roles must remain within the previously admitted editorial roles; untouched holdout or unknown roles are rejected.
- Kept machine-checkable facts separate from strategic explanations. New legal illustrative variations are explicitly labeled as **board-only variations with no engine score**.

These checks establish that the cited moves and board relationships exist. They do **not** establish that the prose is the best explanation, that an opponent reply is forced, that an advantage converts to a win, or that a person learns from the lesson. Maia probabilities are model predictions, not observed response frequencies.

Twelve focused tests cover corrupted continuations, changed evidence, incorrect board assertions, holdout rejection, readiness promotion, unsaved comparisons, private output enforcement and overwrite refusal. No private candidate data is embedded in those tests or the compiler.

## How to use the drafts

The detailed notes remain in the ignored local directory `data/mining_v3/teaching-drafts-20260916-v2/`. `Teaching research drafts.md` is the readable version; `drafts.json` contains the structured assertions and citations. The separate source notes are also private. This revision corrects three prose ambiguities found in a second AI-assisted check; that check is not independent chess review. The earlier draft and existing review exports have been preserved.

1. Have an independent chess reviewer assess the proposed explanation before reading the suggested lesson label, to reduce agreement by suggestion.
2. Check the unsaved opponent sidelines and distinguish a legal illustration from a best-response continuation. Keep all accepted alternatives in view.
3. Look for counterexamples within editorial/development material: positions where the same superficial feature suggests a different move. Do not inspect untouched evaluation material to improve a draft.
4. Turn a mechanism into a family only after matching examples, near duplicates and counterexamples have been reviewed. A descriptive phrase from one position is not a discovered concept.
5. Test whether explanations improve choices on new positions, not merely recall of a displayed move. The separate study-design memo describes how to evaluate that claim.

All six readiness gates remain **false**: chess review, independent chess review, near-duplicate review, family validation, public-exposure review and trainer readiness. These drafts have not been added to the public trainer.
