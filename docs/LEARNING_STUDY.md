# Does grouped practice improve play on unseen positions?

Protocol draft, 7 September 2026. **Not preregistered, not recruiting, and no completed controlled results.** This document is an executable study specification for the experimenter, not evidence that the trainer works. Existing website users are not automatically participants. The older single-session baseline file is not a randomized study.

## Question and comparison

Does 15 minutes of practice with the eight Machine Unique Chess groups improve move quality on new positions more than 15 minutes of ordinary puzzle practice?

Randomize consenting adults with an established Lichess rapid rating of 1800–2600, who have not used this trainer or read its worked examples. Record rating pool, rating date, approximate games played and prior exposure. Recruit a **feasibility pilot of 24 participants**, 12 per arm; this number is a practical pilot target, not a power calculation or a promise of significance. Do not infer a FIDE rating from a Lichess rating.

- **Grouped practice:** 15 minutes using examples from the eight groups, with replay and concise explanation.
- **Ordinary-puzzle practice:** 15 minutes using conventional positions, with the same board, time allowance, number of opportunities, feedback format and explanation length. Match the pools on an independently estimated difficulty distribution and broad game phase, rather than using easy controls. Freeze the matching specification before recruitment.

This comparison estimates the effect of the whole grouped-practice package. It cannot isolate the effect of clustering, explanation, or engine-human disagreement separately. A later third arm could use exactly the same selected positions in shuffled order to isolate the value of grouping.

## Materials to freeze before recruitment

Create three test forms, A, B and C. Each contains 12 positions: eight selected positions (one per group) and four ordinary comparison positions. Exclude every public study/drill position and every worked example. Also exclude participants who report having previously seen a test item; retain the participant and treat that item as a prespecified missing response. Record the exposure report before revealing any answer.

The three forms and both training pools must have disjoint source games and canonical board states. Canonical state here means the first four FEN fields; this does not prove opening-family independence. Check transpositions and near-duplicate continuations manually and document exclusions. No item is reused across phases for the same participant. Keep the answer manifest private until collection closes.

Verify every test item at Stockfish 17.1 depths 20 and 24 with fixed engine options and no unreported early time stop. Record achieved depth, nodes, settings and binary hash. Use consistent root-restricted searches for candidate scores. Require no mate scores in the test bank and a stable acceptance set between depths; replace unstable items before freezing, never after seeing treatment differences. Review cases near the acceptance boundary. Store best score and score for each legal move, so quality scoring does not depend on exact first-choice agreement. If exhaustive move verification is too expensive, reduce the item bank before recruitment rather than treating unsearched moves as wrong.

Estimate difficulty using held-out source games or a separate pilot pool; the site's fitted item curves include their source positions and are not independent calibration. Difficulty matching is approximate until real response data are available. Do not use the same participants to choose items and then to test effectiveness without reporting that dependence.

Archive a manifest containing item ID, FEN, source game ID, phase/form, group or ordinary label, accepted moves, per-move evaluations and engine settings. Hash the manifest. Review it with `experiments/33_validate_study_manifest.py` before registering the final protocol. The validator checks structural separation and acceptance-set consistency; it does not replace engine analysis, matching or chess review.

## Assignment and schedule

An experimenter generates a concealed 1:1 allocation using random permuted blocks of four within two rapid-rating strata (1800–2200 and >2200–2600). Save the seed and allocation file privately before the first assignment. Assign the six form orders ABC, ACB, BAC, BCA, CAB and CBA evenly within each arm, to the extent possible. Reveal the arm only after the baseline is complete. Analyze under the originally assigned arm.

1. **Baseline:** 12 positions, maximum 60 seconds each, no hints or correctness feedback.
2. **Practice:** 15 minutes in the assigned arm; record actual time and items attempted.
3. **Immediate test:** the next unseen form, same timing and no feedback.
4. **Delayed test:** final unseen form, seven days later with a permitted window of ±2 days. Record the actual interval and intervening chess practice. Offer explanations after this test or after study withdrawal.

Use the same device/input mode where possible. Ask participants not to use engines, outside assistance or another board during assessment. Record interruptions. No assessment item contributes to a public leaderboard or advertised rating.

## Outcomes and analysis fixed in advance

**Primary pilot outcome:** between-arm difference in immediate-test acceptable-move rate on the eight selected items, adjusting for baseline acceptable-move rate and rating stratum. A move is acceptable if its frozen evaluation is within **20 centipawns** of the best frozen score. This tolerance is operational and will receive 10/50-centipawn sensitivity analyses.

**Secondary outcomes:** delayed acceptable-move rate, exact engine-match rate, capped centipawn loss (cap 300 for a descriptive summary), time taken, and acceptable-move rate on ordinary positions. Report ordinary-position results separately; success on related items alone is not broad improvement in chess strength. No claim of Elo gain is planned.

Report participant counts, denominators, individual trajectories, means and uncertainty. For the pilot, use an assignment-respecting randomization analysis of participant-level baseline-adjusted differences, alongside a participant bootstrap interval; describe the particular frozen item bank as the scope of inference. A mixed-effects logistic model with participant and item intercepts is exploratory at this small sample size and may not converge. Do not treat every move as an independent participant.

Before a larger confirmatory study, use pilot variance and attrition estimates to simulate participant-and-item sample sizes for a prespecified practically meaningful improvement (provisionally 10 percentage points), 80% power and a two-sided 5% test. Finalize this choice and the confirmatory analysis before collecting that study. Report all outcomes; do not stop early because a p-value looks favourable.

## Missing responses and exclusions

- Timeout or a submitted legal move outside the acceptance set counts as unsuccessful; record these separately.
- Illegal input prevented by the board is not a submitted response. A technical failure that prevents an item from appearing is missing, not automatically a chess error.
- Keep randomized participants in the assigned group. Report completion, dropout and reasons by arm. Do not silently replace dropouts to obtain 24 completers.
- Missing immediate or delayed assessments require explicit sensitivity bounds (all missing outcomes unsuccessful / successful), alongside available-response summaries. Report that missingness limits inference; do not describe an available-case result as a complete intention-to-treat estimate.
- Prespecified disqualifying events are lack of consent, duplicate participation, or documented external assistance. Record the reason and show counts by arm. Do not exclude poor performers or surprising answers.

## Participant information and data handling

Before assignment, explain the purpose, tasks, approximate duration, voluntary participation and right to stop. Obtain explicit study consent separately from ordinary site sign-in. Store pseudonymous IDs in the response table; keep any contact details needed for the delayed session in a separate restricted file. Specify a retention/deletion date before recruitment. Share aggregate findings and only appropriately consented, de-identified records. This protocol does not authorize sending recruitment messages or enrolling existing users.

## Required record format

Use one row per displayed item in `docs/study_responses.csv` (currently header only). `phase` is baseline, immediate or delayed; `arm` is grouped or ordinary. `status` is answered, timeout, technical_failure, previously_seen or withdrawn. Preserve the raw chosen UCI move, time, item ID and manifest hash. Derive correctness from the frozen answer manifest during analysis; never replace raw responses with scores alone.

Before recruitment: finish and review the verified item bank and matched training pools, freeze consent and allocation, register the final protocol, and choose the experimenter responsible for collection. **Until those steps and actual participant sessions are complete, the public claim remains: learning effectiveness is untested.**
