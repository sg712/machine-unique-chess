# Does ordering related examples together help people recognize the idea?

Preparation draft, 8 September 2026. **No participants have been enrolled in this study, no controlled learning results exist, and this protocol is not preregistered.** This version changes the comparison proposed in [the original protocol](LEARNING_STUDY.md); that document remains as history. The public trainer remains a separate product. Neither a successful validator run nor an engine evaluation establishes a learning effect.

## What the experiment identifies

Compare **grouped practice** with **shuffled practice using exactly the same positions, explanations, feedback, board interface and exposure time**. Grouped practice places the positive examples of a family together, followed by its boundary example. Shuffled practice permutes that same item list. Both conditions show the same family label and wording, and both include the boundary examples. No ordinary-puzzle control or third arm is included in this pilot.

This estimates the effect of presenting related examples consecutively, including the transition from successful applications to a limiting case. It does not separately establish that the mining method, explanations, boundary cases or chess trainer are better than conventional practice. A later comparison can address those questions after the ordering pilot is feasible.

A family must express a concrete, conditional chess idea, supported by at least two positions from different source games. Its boundary case must show why that same move or plan is insufficient when a relevant feature changes. A common piece type, a low model probability or a clustering label is not sufficient evidence of a teaching family. A real source-game counterexample is preferable to an edited board; synthetic examples require separate provenance and are outside this pilot bank. Do not turn a statistically unusual move into a universal strategic rule.

## Material bank and independence

Aim first for **eight families**; the validator permits eight through twelve. Use the same number of training examples per family, initially two positive applications and one boundary case: 24 practice items with eight families. If more examples are added, freeze equal family counts and revise the common time budget before recruitment. The validator enforces the minimum; the family-count and difficulty review is a separate recorded gate.

Create three assessment forms, A, B and C. Each form contains exactly one unseen position per family, so the eight-family pilot uses eight items per form. Each form balances positive and boundary cases within one item; across the three forms, each family must be tested in both ways. This requires at least 48 reviewed items in the initial bank: 24 practice and 24 assessment positions. Forms should have similar phase, colour, engine evaluation and estimated difficulty distributions. Do not force a weak family or unstable answer into the bank to reach a target count.

Every item must have a distinct resolved source game ID and canonical board state. This stricter-than-necessary one-item-per-game rule makes leakage checks clear. Exclude assessment positions **and their source games** already used by the public trainer, research examples, earlier pilots or participants' prior exposure. Canonical state is the first four normalized FEN fields, excluding move counters and impossible en-passant claims. Also review near-duplicates, transpositions, positions from the same continuation, and copied games under different IDs. Exact FEN/game checks cannot detect every version of these problems.

Preserve real move history, rating and time-control metadata in the mining archive. Freeze family assignment before looking at participant outcomes. Estimate item difficulty using model probabilities and a separate calibration pool, with the limitations of model-based matching recorded. Do not describe those probabilities as observed human response rates.

## Engine acceptance, not single-answer grading

Freeze a pinned **Stockfish 18** binary and its SHA-256, one thread, a fixed hash size and all nondefault options. For every item, evaluate **every legal root move** in separate root-restricted searches at depths 20 and 24. Each search must reach its stated depth; time-bounded runs that stop early remain screening evidence. The archive must retain per-root achieved depths, nodes and engine output. The study manifest's `depth20`/`depth24` fields are the minimum achieved depth over all root moves, and `nodes20`/`nodes24` are the corresponding total nodes; they are not a claim that a single unrestricted PV covers every move.

All frozen scores are finite centipawns from the original side-to-move perspective. The pilot bank excludes positions with mate scores at either depth; do not convert mates to arbitrary large centipawn values. An acceptable move is any legal move within **20 cp** of the best score at that depth. Require the complete acceptance set to agree at depths 20 and 24. Review moves close to the threshold and unstable best-move rankings; replace unstable items before the material freeze, not after seeing an arm's results.

Record engine analysis and chess explanation review separately. `review.reviewer: "agent-reviewed"` describes an actual agent review; it does not stand in for independent chess review. A stronger player or chess researcher should check whether the family distinctions and boundary explanations hold before recruitment. No validator can infer that this review occurred.

## Allocation and identical delivery

Plan a **24-person feasibility pilot**, approximately twelve per arm. This is a practical recruitment target, not a power calculation and not a promise of a detectable effect. Eligible participants are consenting adults with an established Lichess rapid rating of 1800–2600 and no prior use of these materials. Record rating pool, date, approximate rated-game count, prior exposure and current device/input mode. Do not translate a Lichess rating into a FIDE rating.

Generate concealed permuted blocks of four within rapid-rating strata 1800–2200 and 2201–2600. Allocate the next unused slot within a participant's stratum **after baseline**. The script creates 24 potential slots in each stratum so either stratum can fill; those 48 empty slots do not represent 48 participants. Stop after 24 participants have been randomized in total, and do not replace dropouts. An incompletely filled block can produce a small final arm imbalance; report it instead of changing allocation after the fact.

Within each stratum and arm, cycle the six form orders ABC, ACB, BAC, BCA, CAB and CBA in randomly permuted sets. This counterbalances which form is baseline, immediate and delayed as enrolment permits. The allocation file and seed are private; an experimenter who is screening or testing a participant must not choose their slot or reveal a future arm. If a separate allocator is unavailable, finalize an equivalent concealed procedure before recruitment.

1. **Baseline:** one test form, 60 seconds per item, no hint, family label, answer or correctness feedback. Collect any prior-exposure report before a response and before revealing an answer. Include a common practice interaction on a position outside the bank to learn the controls.
2. **Practice:** all 24 items in the initial eight-family bank, one fixed 60-second slot each: 30 seconds to choose a move and 30 seconds for identical explanation/replay feedback. An early response does not lengthen feedback or allow an extra item. A timeout still receives the same explanation. The grouped arm randomizes family order and puts the two positive cases before the boundary; the shuffled arm permutes the complete same list. Both use the same orientation relative to the side to move, prompts, controls, sounds, explanation visibility and timer behavior.
3. **Immediate assessment:** the next unseen form, 60 seconds per item, no feedback, with the same instructions and controls as baseline.
4. **Delayed assessment:** the remaining unseen form seven days later, permitted window days 5–9 inclusive. Record exact elapsed days and intervening chess practice. Release test feedback only after this assessment or after withdrawal.

The initial appointment is about 45–55 minutes including consent, instructions and a short standardized break, plus about 10–15 minutes for the delayed appointment. A 12-family bank would lengthen the planned practice to 36 minutes and each assessment to 12 minutes; decide feasibility before freeze. Pauses and technical interruptions must be logged. Record actual exposure, not only the planned order. Ask participants not to use another board, engine or outside assistance during assessments.

## Outcomes and small-sample analysis

**Primary pilot outcome:** the between-arm difference in immediate-test acceptable-move rate, adjusted for participant baseline acceptable-move rate and rating stratum. Use the same complete frozen acceptance sets for both arms. A move that differs from Stockfish's first choice can still be correct.

Report participant-level results and item-level descriptive results with uncertainty. A participant is the randomization unit; 24 people solving eight positions are not 192 independent participants. The primary model is a linear participant-level ANCOVA on immediate acceptable-move fraction, with assigned arm, baseline fraction and rating stratum. For the pilot, use an assignment-respecting randomization analysis that preserves the observed stratum/block counts, together with a participant bootstrap interval. Treat these as estimates for this particular frozen item bank. A model with crossed participant/item effects is exploratory and may be unstable at this sample size.

Secondary outcomes are delayed acceptable-move rate with the same baseline adjustment; acceptable-move rate separately on positive and boundary cases; exact engine-match rate; capped centipawn loss (300 cp cap for submitted legal moves); response time; completed exposure; and retention. Sensitivity analyses use 10 cp and 50 cp acceptance thresholds derived from the saved full-legal depth-24 scores, with depth-20 threshold stability reported. A timeout is unsuccessful for acceptable-move rate, but has no invented numerical centipawn loss. Do not infer general chess improvement, an Elo gain or real-world transfer from this task alone.

Before a larger confirmatory study, use pilot variance, item variance and attrition to simulate participant and item sample sizes for a prespecified practically meaningful effect. A provisional target is ten percentage points, 80% power and a two-sided 5% error rate; finalize it before confirmatory data collection. Report all planned outcomes. Do not stop based on an attractive p-value.

## Raw records, missingness and consent

Keep one raw row per displayed item with pseudonymous participant ID, allocation slot, assigned arm, stratum, phase, form, item ID, frozen bank hash, sequence index, presented/submitted times, elapsed milliseconds, chosen UCI move, status, exposure report and interruption notes. For practice, also record explanation-open time, actual feedback duration and replay interaction. Keep raw chosen moves; derive correctness from the private frozen bank later.

Statuses are `answered`, `timeout`, `technical_failure`, `previously_seen` and `withdrawn`. A legal move outside the acceptance set and a timeout count as unsuccessful. An item that never appears because of a technical failure is missing. Illegal input should be prevented by the board, not converted silently into a scored submission. Previously seen items are missing according to the prespecified exposure rule. Record denominators by participant and arm.

Keep randomized participants under their original arm. Report all dropouts and reasons; do not exclude poor scores or unexpected choices. Prespecified disqualifying events are lack of consent, duplicate participation or documented outside assistance. Report available-response results together with extreme missing-outcome bounds (all unsuccessful / all successful), and distinguish those from a complete intention-to-treat estimate. If an entire baseline is missing, document the prespecified handling before collection rather than inventing an adjustment after seeing outcomes.

Consent must explain the purpose, tasks, approximate duration, voluntary nature, right to stop, data collected and retention/deletion date. Ordinary site registration is not study consent. Store any contact information for the delayed appointment separately from pseudonymous responses with restricted access. Share only appropriately consented, de-identified records or aggregates. This protocol and its tools do not authorize contacting people or enrolling existing users.

## Executable bank contract

`scripts/mining_v2_study.py` accepts the following JSON structure. The placeholders below are a schema illustration, not an analyzed position. `scores_20` and `scores_24` must contain **all** legal moves; the abbreviated dictionaries here do not constitute a valid bank.

```json
{
  "schema_version": 2,
  "engine": {
    "name": "Stockfish 18",
    "binary_sha256": "64 lowercase hexadecimal characters",
    "threads": 1,
    "hash_mb": 128
  },
  "items": [{
    "id": "family-name-training-1",
    "fen": "complete FEN",
    "game_id": "resolved unique source game identifier",
    "role": "training",
    "form": null,
    "family": "family-name",
    "kind": "positive",
    "explanation": "Concrete position explanation checked against the engine branches.",
    "scores_20": {"e2e4": 31},
    "scores_24": {"e2e4": 28},
    "accepted20": ["e2e4"],
    "accepted24": ["e2e4"],
    "engine": {"depth20": 20, "depth24": 24, "nodes20": 100000, "nodes24": 500000,
               "all_scores_exact": false, "verified": false},
    "review": {"chess": false, "near_duplicates": false, "reviewer": null}
  }],
  "readiness": {
    "consent_ready": false,
    "preregistered": false,
    "allocation_concealed": false,
    "retention_policy_ready": false,
    "delivery_reviewed": false,
    "difficulty_reviewed": false,
    "independent_chess_reviewed": false,
    "public_exposure_reviewed": false
  }
}
```

Assessment items use `role: "test"`, `form: "A"`, `"B"` or `"C"`, and `kind: "positive"` or `"boundary"`. Their explanations remain in the private bank and are not included in the rendered assessment materials. Extra provenance, history, branch checks, review notes and mining scores can be retained as additional fields. Candidate engine metrics do not justify flipping review flags to true. `engine.all_scores_exact` and `engine.verified` must be true from actual complete verification before a bank can pass; bound-only or unfinished searches remain draft evidence.

Run with the repository's Python environment, which includes python-chess:

```sh
python scripts/mining_v2_study.py validate /private/path/bank.json --public-game-ids /private/path/public-game-ids.json
python scripts/mining_v2_study.py export /private/path/bank.json --output /private/path/review-run --seed 712 --draft
```

The example seed is suitable for a material rehearsal only. Generate and protect a fresh allocation seed before recruitment. Pass `--strict` to require all manual gates during validation. Omit `--draft` only after material validation and every recorded readiness gate pass. Export refuses to overwrite existing files, preserving a frozen allocation.

Exports are `readiness.json` with concrete failures and counts, `private-bank.json` with the evidence and test answers, `private-allocation.json` with empty allocation slots and the seed, `materials.json` with identical training content and answer-free assessment forms, and `material-review.html` for local visual review. The HTML can switch between grouped and shuffled order; it is a material reviewer, **not a timed response-collection client**. Unpublished assessment FENs remain private even though their answers are omitted. Do not commit an actual frozen test bank or private allocation to the public website repository.

The tool automatically checks public trainer/research FENs available in this repository. The optional public source-ID file supplements those checks; omitting it does not establish source-game independence. The `public_exposure_reviewed` gate requires a complete exposure/source audit. Canonical checks, reported engine metadata and boolean review gates are auditable declarations, not independent certification.

Before recruiting, resolve every material failure, complete actual independent chess and exposure review, freeze difficulty matching and delivery, test the timed response collector, finalize consent/retention/allocation, and preregister the final protocol. **Until then, the deliverable is an experiment prepared for review, and learning effectiveness remains untested.**
