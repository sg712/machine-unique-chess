# Initial 200-position depth check

9 September 2026 in India. **All 200 positions have completed exhaustive depth-20/24 analysis: 116 meet the engine-stability contract, and 62 also retain the model-based candidate criterion.** The [validated results](../results/mining_v3_deep200.json) follow the completed first-pass screen of 248,810 observations. None of these 200 positions is marked ready for the trainer, and no human learning result is claimed.

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

## Completed results

All **14,208 legal-root searches** reached their requested depth with valid exact-score evidence. That establishes completion of the searches; engine stability additionally requires the no-mate and unchanged-acceptable-set checks above.

| Outcome | White | Black | Total |
|---|---:|---:|---:|
| Positions fully checked | 100 | 100 | 200 |
| Engine stability contract met | 60 | 56 | 116 |
| Stability and candidate criterion retained | 35 | 27 | 62 |
| Ready for the trainer | 0 | 0 | 0 |

Thus 58% of this batch met the engine-stability contract, and 31% met that contract plus the candidate criterion at both depths. Of the 116 engine-stable positions, 54 did not retain the full candidate criterion. These are descriptive results for this constrained batch, not a survival rate for all 4,345 distinct first-pass candidates or evidence of a colour difference.

The recorded failure reasons **overlap**:

| Failure reason | Positions |
|---|---:|
| Within-20-cp acceptable move set changed between depths | 56 |
| At least one legal root had a mate-valued score | 34 |
| Candidate criterion not retained at depth 20 | 117 |
| Candidate criterion not retained at depth 24 | 121 |

These counts must not be added. A position can have a mate-valued alternative, a changed acceptable set and a failed probability/regret gate. Among the 166 positions without any mate-valued root, the acceptable set changed in 50; the median absolute change in best numeric score from depth 20 to 24 was 8 cp, with a 90th percentile of 24 cp. Modest score changes can still change which moves fall inside the acceptance threshold.

The **62 retained positions need explanations, chess review and teaching-family assessment**. Engine evidence alone does not show that people will find them difficult, learn a useful pattern from them or improve after practice. No new trainer puzzle or private study item was approved by this run.

The completed aggregate checks the frozen selection, all input/output hashes and legal-root identities, then recomputes the outcomes from the saved roots and unchanged FEN-only policies. All saved position results match that recomputation. Raw inputs, moves, histories and possible future assessment material remain private.

## Runtime and remaining work

The run evaluated **70,328,375,217 nodes**. The one recorded execution attempt spans **43,093 seconds, about 12 hours of elapsed clock time**. The Mac actually entered system sleep during that attempt. This was not 12 hours of measured active computation: neither active-compute time nor the duration of host suspension was measured, and no estimated sleep duration is subtracted.

Recorded root-search durations sum to 77,815 seconds, averaging 389 seconds per position across its roots and both depths. These monotonic-clock durations overlap across workers; their sum is neither CPU time nor the job's elapsed clock time, and host suspension was not separately measured or corrected. The slowest single root took about 668 recorded seconds. Search costs have a long tail, so the earlier estimate based on small, time-capped batches was not a reliable forecast for this uncapped procedure.

There are **4,145 distinct first-pass candidates outside this batch**. Scaling the batch's mean recorded root duration to that count gives about 448 summed-search hours, or **56 hours with ideal eight-worker parallelism**. This is an illustrative planning scenario, not a completion forecast or a claim about active CPU time. The remaining pool differs from this recovered, non-BOT, game-capped sample and includes previously public and BOT-source material excluded here. Search complexity, scheduling, hardware contention, retries and pauses can all change the cost. Extrapolating the sleeping host's roughly 12-hour attempt directly would not estimate continuous execution reliably.

The next practical step is to review the 62 retained positions and their explanations before deciding how much of the remaining pool warrants the same expense. The remaining candidates have not undergone this deep check.

## Reproduce

```sh
python scripts/mining_v3_deep_selection.py
python scripts/mining_v3_deep.py --workers 8
python scripts/mining_v3_deep_summary.py
```

The selection command refuses to replace an existing frozen selection. The runner reuses its verified checkpoints; `--repair-partial` permits discarding only an incomplete final JSONL fragment after an interruption. Never edit frozen scoring inputs or dependencies during a run.
