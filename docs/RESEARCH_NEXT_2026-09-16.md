# From surprising moves to lessons people can use

16 September 2026. Research synthesis and proposed next experiments.

The strongest direction for Machine Unique Chess connects three pieces of evidence: **a sound move that is unlikely under a human-play model, a specific decision that can be explained, and improvement on new positions without help**. We have substantial evidence for the first piece and useful new drafts for the second. The third remains untested.

This pass reviewed 12 primary sources, reconciled 1,032 safe development candidates against saved searches, drafted six chess cases, and simulated the sensitivity of the proposed learning design. No additional engine searches were needed. The completed census, its selection rules, and the live trainer bank remain unchanged.

## What changed our understanding

### More White positions is no longer the main data problem

The full screen already contains **124,405 observations of each side**. The safe editorial pool has 481 White and 551 Black positions, but **841 middlegames, 151 openings and only 40 endgames**. This describes the selected pool under the existing filters, not the frequency of useful concepts in chess.

Next acquisition should address missing lesson types and source coverage. There is no sub-1800 representative mover in this pool, and 481 time controls are unknown. A Maia rating setting does not substitute for data from players at that rating. Another undirected large run would likely deepen the collection's existing imbalances.

### The answer often needs to be a set

**129/1,032 candidates have multiple acceptable moves.** In 55 cases, summing Maia 2000 probability across acceptable moves gives at least twice the mass of the exact-top-score tie set. These comparisons already respect ties for the top engine score.

The frozen 20cp rule should stay identifiable. Using 30cp instead leaves 849 candidates satisfying depth agreement and the probability gate; 50cp leaves 598. This is sensitivity of an already selected collection, not a discovery that one tolerance is correct. Future v3 practice needs versioned acceptable sets and feedback on good alternatives before new positions are released.

### The best draft explanations describe concrete decisions

Six private cases now address recapture support against a fork, an intermediate attack on the queen, removing a relative pin, active rook defense, preserving the right passed pawn, and liquidation by direct capture. These are **case hypotheses**, not six validated new chess concepts. Several involve defensive resources rather than winning material.

Each draft separates board facts, exact saved continuations, strategic interpretation, and unresolved questions. A legal engine line illustrates a lesson without proving every sentence of an explanation. Independent review and trainer-readiness flags remain false.

This gives a better editorial direction than repeated “quiet move” descriptions: explain the threat, the choice it creates, and the opponent's relevant reply. A future lesson title should name the decision after multiple examples and a contrasting case support it.

### Rare under Maia is not the same as difficult for a person

The [literature audit](RESEARCH_LITERATURE_2026-09-16.md) distinguishes move matching, probability calibration, and actual learning. Maia-3's headline benchmark uses history and a particular blitz population; the completed large census used FEN-conditioned probabilities. Neither validates a displayed percentage as a puzzle success rate.

History is already a demonstrated sensitivity in the earlier small-model pilot: **322/2,000 first choices changed** between history and FEN-only conditions at fixed 2000 inputs. That is an existing result, not a new finding here. The new editorial analysis cannot extend it to accepted-set classifications because its saved bundle contains only FEN-conditioned policies. The next comparison should ask which candidate decisions change when the same model receives genuine context.

### Giving the answer and teaching the decision need separate tests

The literature includes a small grandmaster concept-transfer demonstration, a newer chess-club experiment reporting weaker gains with help on demand, and work comparing move recommendations with signals about when to pay attention. Their interventions and evidence quality differ. The two newer human-assistance working papers were accessible only through primary abstracts and indexed records; full methods still need checking. They motivate testing staged help, not assuming our preferred interface works.

The existing study compares **grouped versus shuffled order of identical material**. It cannot itself establish that mined positions outperform ordinary puzzles or that explanations cause learning. Giving stronger hints to only one arm would confound the question.

In the new hypothetical simulations, with **24 people and eight assessment items**, an assumed ten-percentage-point benefit was detected in only **21–24%** of trials across the declared scenarios. This is a planning illustration, not a forecast from participant data. Keep the first study about feasibility and report uncertainty rather than declaring success or failure from a small hypothesis test.

## Next experiments, in order

These are specifications for further work, not jobs launched by this research pass.

### A. Finish a small, contrasting teaching bank

For each promising explanation, seek a second positive example from another source game and a real contrasting case where the rule fails or the alternative becomes preferable. Use only editorial/development material while defining the rule. Record rejected matches as well as successes.

One attractive example does not establish a family. If six families survive, development requires at least **18 reviewed examples**: two positives and a boundary example per family. This is not yet the formal eight-family, 48-item study bank. Choose assessment items separately after family definitions are frozen, preserving all-origin game and canonical-position exclusions.

Each case needs an acceptable set, the relevant opponent reply, a continuation question, a tempting alternative, and a limit to the proposed idea. Independent chess review should adjudicate the explanation. Preserve source and evidence hashes; an AI-authored “review complete” label is not approval.

**Useful failure:** a family collapses into unrelated tactics, or its boundary case contradicts the explanation. Reject or narrow the family instead of keeping a vague label.

### B. Run a bounded context audit before another census

Develop a small diagnostic sample covering phase, side, acceptable-set multiplicity and score margin, with separate originating games. Freeze selection before seeing new model outputs. Use the editorial pool; do not open protected assessment boards to tune the audit.

Compare the **same pinned Maia model** in FEN-only and genuine-history conditions first. Preserve normalization, temperature, rating inputs, history truncation and missingness. Then compare model sizes or Maia-2 rapid as separate factors. A larger model versus a smaller model with different history would not isolate the cause. Keep the engine's original FEN context fixed in the paired comparison; flag repetition-sensitive positions for separate analysis.

Report changes in acceptable-set probability, expected regret and candidate-pass status at each rating. Distinguish an exact first-choice change from crossing the research criterion. Save paired outputs separately from the census and recover missing time controls before interpreting source differences.

**Useful failure:** surprise disappears with history, or classification depends mainly on model/time-control mismatch. Such cases become context-sensitive candidates rather than evidence of a human blind spot.

### C. Separate calibration sampling from targeted mining

For calibration, sample fresh games independently of model surprise and engine quality. Freeze the target population, archive period, known checkpoint training cutoffs, exclusions and development/evaluation split first. Use actual player/opponent ratings within model support. Source-game behavior and later puzzle responses need separate evaluations.

At fixed complete-root settings, evaluate the event “the recorded move belongs to the acceptable set.” Score its predicted probability with Brier score, log loss and reliability summaries; report game-level uncertainty and repeat-player sensitivity. Fit any probability transform on development games and evaluate it on sealed games. Sparse low-probability bins need counts and intervals. Stratified or oversampled designs must state target weights; a balanced diagnostic sample is not automatically representative of online chess.

For mining, create separate prospective queues:

| Queue | Supplies | Does not establish |
|---|---|---|
| Underrepresented phases/source bands | Endgames and source populations missing from the pool | Equal natural yield across phases |
| Contrasting cases | Decisions where a proposed rule applies or fails | A concept family without review |
| Transitional model problems | Moves whose acceptable-set probability rises across model rating settings | A particular human's readiness to learn |
| Ordinary engine-sound material | A potential control for testing the mining method | A matched control until difficulty, exposure and teaching are specified |

Do not use these selected teaching queues as a calibration denominator. Start with small batches, inspect source and family yield, and expand when a batch supplies a missing piece of evidence. Preserve screened candidates and rejection reasons so examples remain traceable.

### D. Keep the human questions separable

| Question | Comparison required | Status |
|---|---|---|
| Does grouping help? | Same lessons and exposure, grouped versus shuffled | Existing feasibility protocol; no responses |
| Does staged help improve learning? | Same material and grouping, prespecified help policies | Proposed separate experiment |
| Does the mining method add value? | Mined versus suitable comparison material, matched instruction | Needs separate design and control bank |
| Does the lesson transfer? | Unseen related and boundary positions, unaided; delayed follow-up | Endpoint to preserve across studies |

A first success would be a measured improvement on unseen decisions from a frozen bank. Elo, general chess strength, human-unknown knowledge, and the engine's internal reasoning require additional evidence.

## Deliverables

- [Twelve-source literature audit](RESEARCH_LITERATURE_2026-09-16.md) and [corrected bibliography](../BIBLIOGRAPHY.md).
- [Candidate diagnostics](EDITORIAL_DIAGNOSTICS_2026-09-16.md), [aggregate](../results/editorial_diagnostics_20260916.json), and reproducible builder.
- [Teaching hypotheses](TEACHING_HYPOTHESES_2026-09-16.md), with six detailed drafts in the private development directory.
- [Study-design sensitivity](STUDY_DESIGN_SENSITIVITY_2026-09-16.md), [simulation output](../results/study_design_sensitivity_20260916.json), and reproducible builder.

The priority is **explain a few decisions well, test the behavioral instrument, then mine to fill explicit gaps**. Existing engine evidence is already large enough to support that work.
