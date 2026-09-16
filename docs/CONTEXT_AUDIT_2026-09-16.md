# A paired test of what actual game history changes

16 September 2026. Prepared development audit; **model inference is paused for battery power**. No history effect has been measured by this audit yet. The public [aggregate](../results/context_audit_20260916.json) correctly contains 0 completed pairs and 96 pending positions. No engine jobs are involved.

## Frozen sample

The completed census was verified against its saved input, policy, outcome, root-log, runner and checkpoint fingerprints before selection. Only the 1,032 retained editorial-eligible states were considered: every origin must have recovered history, no BOT tag, no known public exposure, and an analysis role of prior development, pilot training or new training. The legacy split label alone does not override its recorded development exposure. Protected validation/test-role states are excluded.

A stricter history audit removed five states with multiple originating observations and two lacking a source-game fingerprint. All 1,025 remaining histories were replayed from the standard initial position, validating each legal move, the exact target FEN, the ply index and the chronological last-eight-position cache. These checks preserve actual history rather than inventing predecessor positions.

The sample is frozen before inference:

| Dimension | Selected |
|---|---:|
| White / Black | 48 / 48 |
| Opening / Middlegame / Endgame | 32 / 32 / 32 |
| Single / Multiple acceptable moves | 57 / 39 |
| Near an existing probability/regret gate / Interior | 36 / 60 |
| Repetition-sensitive target or threefold claim | 0 |

Each phase/side cell has exactly 16 positions. All originating source-game IDs and legacy aliases are distinct across the sample. Within each cell, seeded SHA-256 ranks are traversed round-robin over acceptable-set multiplicity and old gate proximity. Proximity means old acceptable probability at least 7.5% or old capped regret at most 75cp at either depth and either rating. Endgame cells are allocated first to protect their scarce sources. Empty subcells redistribute within their phase/side cell; no primary-cell deficit occurred. No position will be replaced after inspecting new outputs.

The endgame subcells are uneven: only seven selected endgames have multiple acceptable moves, and four are near a declared model gate. This purposive diagnostic sample is not a representative chess sample or a natural phase-yield estimate.

## Paired conditions and controls

Both conditions will be recomputed with **the same locally cached Maia3-5M checkpoint and the same runtime**, at hypothetical equal self/opponent ratings of 1700 and 2000. Old census probabilities are used only for sample stratification; they are not substituted for the new paired baseline.

- Checkpoint SHA-256: `ba14208b2992d85502f5fb501934abf6aaaeb355e9f3fdf90e326911f562524f`.
- Source commit: `1e13597c42d4858b7cfd7cfdae01e297263364b2`.
- CPU, two compute threads, one inter-op thread, deterministic algorithms, float32 and no AMP.
- Raw-logit temperature-one softmax over every legal move. No top-k truncation, displayed rounding or post-hoc renormalization.
- Actual history: last eight chronological source states including the target, earliest-state left padding for a shorter history.
- FEN-only: target state repeated eight times.
- Identical disabled clock inputs in both conditions. The sample includes 48 unknown, 28 rapid, 18 blitz and 2 classical source time controls; source/model mismatch is unresolved.
- Four identical-input control positions use the target alone in both code paths. Their maximum absolute move-probability difference must be at most `1e-6` before real pairs are accepted. Controls are bound to the first four frozen target identities and complete finite legal distributions; numeric pairs cannot be reported while controls are absent or invalid.

The legal-move engine evidence remains the original complete FEN-conditioned depth20/depth24 evidence. Giving history to Maia does not add actual history to the saved Stockfish search. Repetition/threefold sensitivity is flagged using the fully replayed game stack; none of these 96 targets triggered that flag. No new engine search or larger-model download is required.

## Outcomes

For each condition, rating and depth, the builder reports acceptable-set probability, capped expected regret (300cp cap), and the existing probability/regret/candidate gates. It uses the frozen summary's conservative probability upper bound and regret lower bound, including tiny numerical probability tails, rather than silently changing the rule.

The full candidate status requires engine stability and the gates at **both depths and both ratings**. A first-choice change and a full-criterion crossing are separate outcomes. The public report includes both, paired probability/regret changes, phase/side breakdowns, and a repetition-filtered sensitivity view. No individual board, answer, source ID or raw prediction is public. Human calibration and trainer-readiness remain false.

## Reproduction and power handling

`scripts/context_audit_20260916.py prepare` creates a new ignored private directory and refuses to overwrite a previous selection. The current 96-case selection manifest SHA-256 is `347565e5e4b946c77725c56c6e044a176e91503b326094a2a2c9a97114c3c277`; its input SHA-256 is `b0c54bf874bc2e50dfa3bbacf4526b3e02eae7d13812a2acf9a62d81f6e5720b`.

The current private directory is `data/mining_v3/context-audit-20260916-final`; the original uninferred preparation is preserved. The default `run` command points to the final directory.

`run` checks for confirmed AC power before model loading and before each eight-position paired batch. On battery or unknown power, it saves a paused status without model inference. Completed batches are atomic and resumable under a process lock. A changed script, adapter, imported metric/summary helper, Python-chess version, input or inference runtime is rejected rather than mixed into the run. `report` rebuilds only the public aggregate from the private paired evidence.

The local checkpoint is present, but a runtime estimate has not been measured while inference is paused. The bounded workload is 384 real predictions plus 16 identical-input control predictions. Nineteen focused tests pass, including legal replay, actual repetition, ambiguous-source rejection, bounded deterministic selection, source-alias separation, multi-answer mass, regret capping, top-choice versus criterion changes, paired identity, controls, pending counts and AC-only behavior.

This remains a selected-development model-sensitivity diagnostic. It cannot establish a person's puzzle difficulty, calibrated human choice probabilities, teaching benefit or novel chess knowledge.
