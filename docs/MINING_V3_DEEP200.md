# Initial 200-position depth check

9 September 2026 in India. **The 200-position batch is selected and the deep analysis is running.** This follows the completed first-pass screen of 248,810 observations. No new trainer puzzles or human learning results are claimed.

## Frozen selection

The first-pass screen produced 4,353 candidate observations representing 4,345 distinct canonical states. Excluding known public-exposed source games, BOT-tagged or unresolved sources leaves 3,836 eligible observations and 3,830 distinct states. Exclusions use a declared precedence order, so their counts should not be read as independent categories.

The selected batch contains **100 White and 100 Black positions from 200 different source games**, with no repeated canonical states. It contains 104 slower-game and 96 elite-cohort positions: 28 openings, 159 middlegames and 13 endgames. It was not matched across colours by cohort, phase, rating or source month.

Selection uses the fixed seed `20260909`. Canonical duplicates receive one representative using a seeded ID hash; distinct states receive a separate hash rank. The ranking is traversed with the colour quotas and a global one-position-per-game cap. Neither legal-move count, shallow score magnitude nor any deep result determines the ranking. The selected IDs and source hashes were frozen before the deep run began. This constrained selection is not a uniform sample of every original candidate observation.

The original source histories, policy lines and exposure labels are preserved. There are 128 prior-development observations, 68 observations from new split assignments and four from pilot assignments. A split name does not make an observation independently unseen. Selected positions and solutions remain private.

The public [selection audit](../results/mining_v3_deep_selection.json) reports counts and the protocol without disclosing positions or game identities. Its `rating_bin` counts preserve the original source labels, including a broader pilot bin; they are not all uniform 200-point bands.

## Search procedure

The batch contains 7,104 legal moves: 3,561 on White turns and 3,543 on Black turns. Every legal move is evaluated separately at depths **20 and 24**, for **14,208 root searches** in total.

The primary board context remains **FEN-only**, matching the preceding screen and its frozen Maia3-5M policies at 1400, 1700, 2000 and 2300. Recovered preceding moves and clocks are retained as source metadata but are not supplied to Stockfish or the reused policy condition. Both player-rating inputs use the corresponding fixed model rating.

Stockfish 18 uses one thread and 64 MB hash per worker, clearing its hash before every root search. Eight independent workers execute the same procedure for both colours. Searches stop at their requested depth, with no time or node stopping limit. A fixed hash ordering interleaves White and Black positions for execution, independently of results.

Each saved root must actually reach the target depth, have an exact engine score (neither an upper nor a lower bound), and contain a legal principal variation starting with that root move. Mate scores retain their mate type. “Exact” describes the engine's reported score type, not a mathematical proof of chess value.

Every completed root is checkpointed. Resume verifies the frozen input, policy, selection, engine and code hashes, checks the saved output prefix, and validates each reused root. Only this run's complete exact root evidence can be reused. Shallow first-pass scores and history-conditioned version-2 searches cannot substitute for a depth check. A power safeguard pauses submission and closes owned engines if the Mac is discharging at 5% battery or below; completed roots remain saved.

## Three separate outcomes

1. **Engine stability:** every legal root has valid exact evidence at both depths; no root at either depth has a mate-valued score; the nonempty set of moves within 20 cp of the best score is identical at depths 20 and 24.
2. **Candidate criterion retained:** in addition to engine stability, the best numeric evaluation stays within −200 to +200 cp at both depths. At each depth, the full acceptable set has Maia probability at most 10% and capped expected regret at least 50 cp, at both the 1700 and 2000 model settings. Regret is capped at 300 cp. No missing policy mass is discarded. A 50 cp tolerance is retained as a sensitivity result.
3. **Trainer readiness:** explanation and chess review are still required. This engine run leaves every position's `trainer_ready` flag false.

A stable position can fail the model-based candidate criterion. A candidate can retain that criterion at depth 24 but fail stability or the depth-20 gate. Those outcomes are reported separately, with overlapping failure reasons. The no-mate rule is the existing conservative verification contract; a mate in a poor alternative does not itself make a chess position useless.

## Runtime and reporting

Earlier fresh depth checks averaged roughly 275 summed position-seconds across small batches, suggesting approximately two to three hours for 200 positions with six to eight workers. Those earlier runs used per-root time caps and some retries. This run has no time stop, so difficult roots may take longer. The completed report will use measured runtime and distinguish summed search time, actual run time and pauses.

A cost estimate for the remaining **4,145 distinct candidates** is a planning extrapolation from this restricted 200-position batch. It is not a representative survival estimate for all 4,345 states, which include bot-source and previously public material excluded from this selection.

Only a complete batch will be published as completed verification. The final aggregate must validate all file hashes and legal-root identities and recompute each position's outcomes from the saved roots and frozen policies. Raw inputs, moves, histories and possible future assessment material stay local.

## Reproduce

```sh
python scripts/mining_v3_deep_selection.py
python scripts/mining_v3_deep.py --workers 8
python scripts/mining_v3_deep_summary.py
```

The selection command refuses to replace an existing frozen selection. The runner reuses its verified checkpoints; `--repair-partial` permits discarding only an incomplete final JSONL fragment after an interruption. Never edit frozen scoring inputs or dependencies during a run.
