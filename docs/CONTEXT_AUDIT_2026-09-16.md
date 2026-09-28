# A paired test of what actual game history changes

Prepared 16 September 2026; inference completed and independently checked **27 September 2026**. All **96 paired positions are complete**, with no pending or failed positions. The freshly recomputed FEN-only baseline passes the full candidate criterion on all 96 positions; actual game history leaves **83 passing and 13 failing**. This is a sensitivity result within a selected development sample, not a population estimate or a measurement of human difficulty. The public [aggregate](../results/context_audit_20260916.json) contains the completed comparison. No new engine searches were run.

## Frozen sample

The completed census was verified against its saved input, policy, outcome, root-log, runner and checkpoint fingerprints before selection. Only the 1,032 retained editorial-eligible states were considered: every origin must have recovered history, no BOT tag, no known public exposure, and an analysis role of prior development, pilot training or new training. The legacy split label alone does not override its recorded development exposure. Protected validation/test-role states are excluded.

A stricter history audit removed five states with multiple originating observations and two lacking a source-game fingerprint. All 1,025 remaining histories were replayed from the standard initial position, validating each legal move, the exact target FEN, the ply index and the chronological last-eight-position cache. These checks preserve actual history rather than inventing predecessor positions.

The sample was frozen before inference and remained unchanged:

| Dimension | Selected |
|---|---:|
| White / Black | 48 / 48 |
| Opening / Middlegame / Endgame | 32 / 32 / 32 |
| Single / Multiple acceptable moves | 57 / 39 |
| Near an existing probability/regret gate / Interior | 36 / 60 |
| Repetition-sensitive target or threefold claim | 0 |

Each phase/side cell has exactly 16 positions. All originating source-game IDs and legacy aliases are distinct across the sample. Within each cell, seeded SHA-256 ranks were traversed round-robin over acceptable-set multiplicity and old gate proximity. Proximity means old acceptable probability at least 7.5% or old capped regret at most 75cp at either depth and either rating. Endgame cells were allocated first to protect their scarce sources. Empty subcells redistributed within their phase/side cell; no primary-cell deficit occurred. No position was replaced after inspecting new outputs.

The endgame subcells are uneven: only seven selected endgames have multiple acceptable moves, and four are near a declared model gate. This purposive diagnostic sample is not a representative chess sample or a natural phase-yield estimate.

## Paired conditions and controls

Both conditions were recomputed with **the same locally cached Maia3-5M checkpoint and the same runtime**, at hypothetical equal self/opponent ratings of 1700 and 2000. Old census probabilities were used only for sample stratification; they were not substituted for the new paired baseline.

- Checkpoint SHA-256: `ba14208b2992d85502f5fb501934abf6aaaeb355e9f3fdf90e326911f562524f`.
- Source commit: `1e13597c42d4858b7cfd7cfdae01e297263364b2`.
- CPU, two compute threads, one inter-op thread, deterministic algorithms, float32 and no AMP.
- Raw-logit temperature-one softmax over every legal move. No top-k truncation, displayed rounding or post-hoc renormalization.
- Actual history: last eight chronological source states including the target, earliest-state left padding for a shorter history.
- FEN-only: target state repeated eight times.
- Identical disabled clock inputs in both conditions. The sample includes 48 unknown, 28 rapid, 18 blitz and 2 classical source time controls; source/model mismatch is unresolved.
- Four identical-input control positions used the target alone in both code paths. Across both ratings, their maximum absolute move-probability difference was **exactly zero**, passing the predeclared `1e-6` tolerance. The controls are bound to the first four frozen target identities and complete finite legal distributions. They check agreement when the two paths receive identical tokens; they do not establish model calibration.

The legal-move engine evidence remains the original complete FEN-conditioned depth20/depth24 evidence. Giving history to Maia does not add actual history to the saved Stockfish search. Repetition/threefold sensitivity was checked using the fully replayed game stack; none of these 96 targets triggered that flag. Removing repetition-sensitive targets therefore leaves the entire sample and every aggregate unchanged. This does not test the effect of supplying actual history to Stockfish. No larger model was downloaded.

## Outcomes

For each condition, rating and depth, the builder reports acceptable-set probability, capped expected regret (300cp cap), and the existing probability/regret/candidate gates. It uses the frozen summary's conservative probability upper bound and regret lower bound, including tiny numerical probability tails, rather than silently changing the rule.

The full candidate status requires engine stability and the gates at **both depths and both ratings**: best engine score between −200 and +200cp, acceptable-set probability upper bound at most 10%, and capped expected regret lower bound at least 50cp. All 96 freshly recomputed FEN-only cases passed. With actual history, 83 still pass and 13 cross from pass to fail: **13.5% of this selected sample**. Ten crossings fail only the probability condition, two only the regret condition, and one both, across the required rating/depth combinations.

All changes below are **actual history minus FEN-only**, paired on the same position. Probability changes are **percentage points (pp)**, not relative percentages. The acceptable sets are the same at depths 20 and 24 for these verified positions, so the acceptable-probability changes are identical at both depths; regret still depends on each depth's complete root scores.

| Hypothetical rating | First-choice changes | Mean Δ acceptable probability | Median Δ acceptable probability | Mean Δ capped regret, depth 20 | Mean Δ capped regret, depth 24 |
|---|---:|---:|---:|---:|---:|
| 1700 | 14 / 96 | +0.572pp | −0.066pp | −2.729cp | −2.824cp |
| 2000 | 17 / 96 | +0.916pp | −0.014pp | −2.825cp | −2.929cp |

History changes the first-choice move on some positions while leaving most first choices unchanged. First-choice changes and full-criterion crossings are separate outcomes; the table does not identify them as the same positions. The positive mean probability changes coexist with slightly negative medians: the effect is heterogeneous, not a uniform increase in acceptable-move probability. Individual paired probability changes range from −3.922 to +13.220pp at 1700 and from −3.065 to +26.529pp at 2000.

| Selected phase | Pairs | Still pass with history | Pass-to-fail crossings |
|---|---:|---:|---:|
| Opening | 32 | 27 | 5 |
| Middlegame | 32 | 28 | 4 |
| Endgame | 32 | 28 | 4 |

By side, 5 of 48 White-to-move positions and 8 of 48 Black-to-move positions cross from pass to fail. These small, deliberately balanced subgroups do not establish phase or side effects in general chess. Because selection already required retention under the old model/engine criterion and every new FEN-only case also passes, this audit cannot estimate how often history would make initially failing positions pass.

The result shows that adding actual game context can change this model-based selection decision for some previously retained development positions. It does not show improved human prediction, easier puzzles, teaching benefit, or novel chess knowledge. No individual board, answer, source ID or raw prediction is public. Human calibration and trainer-readiness remain false; **zero positions are promoted to the trainer**.

## Reproduction and power handling

`scripts/context_audit_20260916.py prepare` creates a new ignored private directory and refuses to overwrite a previous selection. The current 96-case selection manifest SHA-256 is `347565e5e4b946c77725c56c6e044a176e91503b326094a2a2c9a97114c3c277`; its input SHA-256 is `b0c54bf874bc2e50dfa3bbacf4526b3e02eae7d13812a2acf9a62d81f6e5720b`.

The current private directory is `data/mining_v3/context-audit-20260916-final`; the original uninferred preparation is preserved. The default `run` command points to the final directory.

`run` checks for confirmed AC power before model loading and before each eight-position paired batch. On battery or unknown power, it saves a paused status without model inference. Completed batches are atomic and resumable under a process lock. A changed script, adapter, imported metric/summary helper, Python-chess version, input or inference runtime is rejected rather than mixed into the run. `report` rebuilds only the public aggregate from the private paired evidence.

The completed workload is 384 real prediction distributions, saved in 12 eight-position paired batches, plus 16 identical-input control distributions saved separately. The completion record is dated `2026-09-27T17:56:10Z`. The run kept the frozen model, selection, settings and census unchanged. Batch timing alone excludes model loading and controls and is not an end-to-end runtime benchmark.

Independent read-only verification on 27 September checked the selection/input fingerprints, all frozen script/dependency fingerprints, all 16 source-census fingerprints, the local checkpoint and model-source fingerprints, the shared runtime fingerprint, all saved batch fingerprints and the controls. It replayed the 96 selected histories, checked distinct source games/aliases and permitted development roles, and confirmed complete finite legal-move probabilities for every saved distribution. The largest real-distribution normalization discrepancy was `1.92543e-7`, within the frozen `2e-6` tolerance; no probabilities were renormalized. Recomputed acceptable-set masses, capped regrets, paired means/medians, first choices and criterion transitions agree with the saved aggregate. Running the existing report construction in memory reproduced the public JSON **byte for byte**, without rewriting it. No new inference was performed and no protected prospective rows were inspected for this verification.

All 19 focused tests passed again on 27 September. They cover legal replay, actual repetition, ambiguous-source rejection, bounded deterministic selection, source-alias separation, multi-answer mass, regret capping, top-choice versus criterion changes, paired identity, controls, pending counts and AC-only behavior.

This remains a selected-development model-sensitivity diagnostic. It cannot establish a person's puzzle difficulty, calibrated human choice probabilities, teaching benefit or novel chess knowledge.
