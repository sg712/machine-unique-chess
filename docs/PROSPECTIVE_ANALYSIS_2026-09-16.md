# Fresh-data analysis: bounded results and separate supplement

Prepared 16 September 2026; original bounded run stopped on 28 September; report updated 29 September. **All 64 model policies are saved and both model-control checks passed with zero probability difference. Of 2,875 planned legal-root searches, 2,873 reached the requested depths; two exhausted three full 30-second attempts.** The original [public aggregate](../results/prospective_analysis_20260916.json) remains explicitly incomplete. This continues the [fresh source sampling](PROSPECTIVE_SAMPLE_2026-09-16.md); unfinished positions do not enter calibration results.

The first tranche selects 64 of the 256 source games using metadata and seeded hashes before model or engine outcomes: 16 calibration-development positions, 16 calibration-evaluation positions and 32 targeted endgames. Endgames have eight positions in each side/rating-group cell. All requested counts were available. Selection preserves the cohort's source-game, move-sequence and bidirectional target-versus-other-source-state exclusions. Protected evaluation positions are consumed only by the fixed quantitative analysis, not by lesson drafting or model fitting.

The engine workload is 1,090 legal-root searches for development, 1,142 for evaluation and 643 for the approximate endgame screen: 2,875 in total. Every selected source row stays visible in coverage summaries. Brier/log-loss values are reported only for complete stable numeric positions with saved model policies, separately for development and evaluation; pending, capped, mate-valued and unstable positions remain visible in the denominator.

## What was measured

The same locally pinned Maia3-5M model receives genuine chronological history and FEN-only input. Calibration uses the **actual mover and opponent ratings as separate inputs**, within the source cohort's 1400–2399 range. Targeted endgames also receive equal 1700 and equal 2000 settings. Both conditions use complete legal-move softmax probabilities at temperature one, float32, disabled clock inputs and no probability transform.

Four same-input control records check that the history and FEN code paths agree when given the same target state, including actual and fixed rating labels. A separate equal-1700 control checks that the new two-rating adapter agrees with the pinned original adapter. Controls require matching target identities, correct rating pairs and complete finite normalized legal policies; saved predictions cannot be reported until controls pass.

For calibration, every legal move is evaluated independently at depths 20 and 24, with one Stockfish18 thread, 64MB hash and cleared hash before every root. The event is whether the recorded online-game move belongs to the complete set within 20cp of the best numeric move. A position is eligible for that event only when all roots reach the requested depths with exact scores, none is mate-valued, and both depths yield the same nonempty acceptable set. **No low-Maia-probability, regret or evaluation-window filter is applied to calibration.**

The public aggregate reports Brier score, log loss and fixed reliability bins separately by source role and model condition only for eligible completed rows. Missing, capped, bound, mate-valued and unstable evidence remains in the original selected denominator. Small bins are explicitly marked sparse. These are source-game choice diagnostics on a filtered convenience sample; they are not human puzzle-success rates or evidence of learning.

Targeted endgames use complete legal-root searches at **depth14 only**. Their acceptable-set mass, capped regret and rise in probability from model rating1700 to2000 are exploratory screening quantities. A completed depth14 item is labelled approximate, never depth-stable, calibrated, trainer-ready or independently reviewed.

## Original bounded results

The final search inventory contains 2,803 exact numeric results, 70 mate-valued results and two capped searches; no roots remain never attempted, bound-valued or errored. The two capped searches belong to different development positions: both requested depth 24 and reached scored depths 21 and 23 respectively. Each used three full 30-second attempts without further depth progress. The finite continuation supervisor stopped in `needs_review` after 14 invocations; its counter, frozen plan and evidence are preserved.

| Role | Selected | Eligible | Unstable | Mate-valued | Incomplete |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibration development | 16 | 9 | 4 | 1 | 2 |
| Held-out calibration evaluation | 16 | 9 | 3 | 4 | 0 |
| Targeted endgames | 32 | 27 approximate | 0 | 5 | 0 |

Mate-valued and unstable positions are excluded from calibration, not treated as negative events. Targeted depth-14 endgames are a separate approximate screen and do not enter the calibration table below.

| Role and input | Eligible / selected | Brier score | Log loss |
| --- | ---: | ---: | ---: |
| Development, real history | 9 / 16 | 0.183920 | 0.529978 |
| Development, FEN only | 9 / 16 | 0.165351 | 0.495269 |
| Held-out evaluation, real history | 9 / 16 | 0.103714 | 0.342860 |
| Held-out evaluation, FEN only | 9 / 16 | 0.136695 | 0.487075 |

Lower scores are better for both metrics. History scores lower on this small eligible evaluation subset and higher on the development subset. Nine observations per role, outcome-dependent eligibility and a convenience source sample do not establish general superiority or population calibration. Of the 27 numeric targeted endgames, 17 have higher acceptable-set probability at equal model rating 2000 than at 1700; this is an exploratory model comparison, not a learning effect.

## Separate two-minute supplement

On 29 September, after the original stopping rule had been reached and reported, a separate check was authorized for **only the two unfinished development roots**. It permits one full 120-second attempt per root at the original requested depth 24, with the same engine, one thread, 64MB hash, cleared hash, 600-second invocation cap and AC-only policy. At most six invocations permit recovery from interruptions; exhausted full attempts are not retried. No other position or source-cohort row is added.

The supplement completed on 29 September in one invocation. Both selected roots reached scored depth 24 with exact numeric results, using 71.724 and 53.239 seconds respectively, within their 120-second limits. There were no interrupted, exhausted or unresolved opportunities. Combining these two results with the saved baseline gives 2,875 requested-depth searches in the supplemented view: 2,805 numeric and 70 mate-valued. The original 30-second result above remains unchanged at 2,873/2,875.

Only one affected development position becomes eligible. The other has different acceptable sets at depths 20 and 24 and remains excluded. Supplemented development therefore has **10 eligible / 16 selected**, five unstable positions, one mate-valued position and none incomplete. Root completion does not override mate or stability exclusions.

| Development result and input | Eligible / selected | Brier score | Log loss |
| --- | ---: | ---: | ---: |
| Original bounded run, real history | 9 / 16 | 0.183920 | 0.529978 |
| With supplement, real history | 10 / 16 | 0.167142 | 0.490569 |
| Original bounded run, FEN only | 9 / 16 | 0.165351 | 0.495269 |
| With supplement, FEN only | 10 / 16 | 0.152560 | 0.467246 |

The changed scores include one additional eligible source-game observation; they do not measure a change to the model or a learning effect. **Held-out evaluation remains unchanged at 9/16**, with the scores and exclusions in the original table. Targeted endgames also remain unchanged: 27 approximate depth-14 cases and five mate exclusions. No evaluation or targeted searches, model predictions or probability transformations were rerun or fitted.

The separate plan binds the stopped baseline and its evidence inventory. Extending a cap after seeing its failures is a post-baseline analysis, not completion under the original cap or an independent replication. Both the original and supplemented diagnostics retain their small, outcome-dependent denominators.

## Limits on the original laptop work

The runner requires confirmed AC power before model loading, between model batches and during each engine search. It stops an individual search after 30 seconds and caps one invocation at ten minutes, with a short engine-stop grace period and bounded shutdown overhead. A watchdog interrupts an in-progress search on power loss. Capped evidence keeps its actually achieved scored depth: a later unscored engine update cannot promote an earlier score to depth24.

Each root attempt is saved separately. Completed exact searches are reused; incomplete searches are retained and eligible for retry. Never-attempted roots come first globally, so a few expensive early roots cannot consume every future invocation and starve later positions. After all new roots are attempted, retries are ordered by fewest prior attempts. The fixed caps and scoring rules remain unchanged.

An exclusive run lock prevents concurrent writers. Active, paused, interrupted and failed states are explicit; reporting recognizes a stale active state after a process exits. Every report binds its exact read policy/root/control files through a private inventory and a public inventory digest, as well as the frozen source, plan, input, checkpoint, runtime and helper hashes.

## Local evidence and continuation

The current ignored private output is `data/mining_v3/prospective-analysis-20260916`. The source cohort is `data/mining_v3/prospective-20260916-v2`.

The original run is stopped for review; do not restart it or reset its helper. Preserve its frozen script, plan, all attempt files and final inventory. The separate supplement uses `scripts/prospective_extension_20260929.py`, private output `data/mining_v3/prospective-extension-20260929` and a [separate public aggregate](../results/prospective_extension_20260929.json). Its preparation and reporting require no inference; its `run` command requires confirmed AC power. Completed baseline searches and all saved model policies are reused without rerunning the model.

The [pinned model provenance](../results/prospective_model_provenance_20260916.json) documents that the August2026 source games postdate the published May2026 checkpoint and the paper's declared January2023–July2025 training period. This is documentary temporal separation, not a full private training-corpus membership audit or proof of new players or board patterns. No probability transform is fitted, and no item is promoted to the trainer.

Eighteen focused prospective tests passed again on 27 September, including actual mover/opponent tensor order, complete accepted sets, capped/mate/unstable exclusions, separate targeted screening, source-state leakage, deterministic tranche selection, control identities, power interruption, scored-depth integrity, fair retry scheduling and exact evidence inventories. Nineteen separate context-audit tests also pass. An independent final audit validated the full 2,953-file baseline evidence inventory, frozen input/script/model/engine hashes and controls, and reproduced all role-specific coverage and calibration scores. The completed context results are independent of the prospective analysis.

On 29 September, the separate runner passed 17 focused mocked tests, including a stalled power check, an engine that ignores its stop request, immutable evidence, cap exhaustion, interruption recovery and baseline preservation. Independent code review passed. The final read-only audit verified both exact depth-24 results, one invocation, two immutable reservations and two immutable attempts; all five evidence-file hashes and the frozen manifest match. It revalidated the original baseline and controls, recomputed supplemented development eligibility and scores, and confirmed identical evaluation and targeted summaries. No new model predictions were run. The final actual results were verified in an offline `/research` render, retaining the original baseline tables and displaying separate supplemental comparisons.
