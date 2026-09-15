# Checking the full candidate pool

Completed 15 September 2026; selection and protocol frozen on 9 September. This follow-up extends the [200-position batch](MINING_V3_DEEP200.md) to every distinct candidate from the same first-pass screen. **All 4,345 positions and 304,068 legal-move searches are complete.** The [validated aggregate](../results/mining_v3_full_deep.json), saved at 17:13 UTC on 15 September, has `complete: true`, no pending or partial positions, and all validation checks passed.

## Results

**2,379 positions met the engine-stability rule; 1,398 also retained the full candidate criterion.** Engine stability means the complete within-20-centipawn acceptable-move set stayed the same at depths 20 and 24, with no mate-valued score for any legal root. The additional criterion measures engine evaluation and Maia probabilities under the unchanged thresholds below. None of these positions is yet approved for the trainer.

| Side to move | Checked | Engine-stable | Stable + full candidate criterion |
|---|---:|---:|---:|
| White | 2,106 | 1,177 | 680 |
| Black | 2,239 | 1,202 | 718 |
| Total | 4,345 | 2,379 | 1,398 |

The initial 200 contribute 116 engine-stable positions and 62 retaining the full criterion. The other 4,145 contribute 2,263 and 1,336 respectively. These are parts of the same census; the initial batch is not an additional sample or an independent replication. White and Black positions were not matched on every feature, and several states can share a source game. These counts do not establish a colour effect, human solving rate or learning benefit.

### Source groups

These rows use provenance from **any originating candidate observation**, not only the chosen representative. Flags overlap and must not be added as disjoint groups.

| Source condition | Checked | Engine-stable | Stable + full candidate criterion |
|---|---:|---:|---:|
| All origins recovered, without BOT tags or known public exposure | 3,830 | 2,096 | 1,231 |
| Any BOT-tagged origin | 410 | 210 | 120 |
| Any known public origin | 128 | 88 | 56 |
| Any origin with unresolved BOT status | 1 | 0 | 0 |
| Any origin with unavailable history | 1 | 0 | 0 |

The 1,231 retained positions in the first row provide a narrower pool for explanation and chess review. That source label does not prove unassisted human play or fresh held-out data. Trainer readiness remains zero in every group.

### What changed at greater depth

Among the 3,726 positions with only numeric centipawn scores, the median absolute change in the best evaluation was 7 cp, and the 90th percentile was 25 cp. Yet 1,347 changed their complete acceptable-move set between depths 20 and 24. A small evaluation change does not guarantee the same set of acceptable answers.

Another 619 positions had a mate-valued score for at least one legal root and were excluded by the frozen stability rule. This flag concerns any tested move, including alternatives to the best move. Failure flags in the aggregate can overlap.

## Scope

The unchanged screen selected 4,353 observations representing **4,345 distinct canonical board states**. The initial 200 are included in that total. The additional **4,145 states** received the same exhaustive depth-20/24 procedure: 2,006 White and 2,139 Black. The [frozen selection audit](../results/mining_v3_full_deep_selection.json) records the complete plan. This stage did not repeat the screen across all 248,810 observations or add a new mining source.

The census spans 3,726 source games, with at most five selected states from one game. It contains 152,034 legal moves and therefore 304,068 two-depth searches in total. Of these, **14,208 searches are reused and 289,860 are new**. There are 410 states with BOT-tagged candidate origins, 128 with known public exposure and one with unresolved BOT status and unavailable history; these categories overlap. All candidate origins are recovered, without BOT tags and without known public exposure for 3,830 states.

Unlike the initial sample, the full census has no colour quota, one-position-per-game cap or source-stratum exclusion. Several positions can therefore come from one game. Equal source weights, independent observations and a fresh held-out test set are not claimed.

The census retains the exact representative used for each initial-200 state. Other repeated canonical states use a deterministic representative preference for recovered games without BOT tags or known public exposure, then a declared hash ranking. All originating candidate observations and their source labels remain in a private mapping. Preferring one representative does not erase alternate BOT or public provenance.

The original position records and Maia policy lines remain unchanged. Canonical comparison ignores the two FEN counters when identifying duplicate states, but evidence reuse requires the exact previously analyzed FEN and source/policy bytes, including those counters. A merely similar board is insufficient.

## Same search and acceptance rules

Stockfish 18 searches every legal move independently at depths **20 and 24**, with one thread and 64 MB hash per worker. Hash is cleared before each search. Eight workers use the same procedure for both colours. Searches have no time or node stopping cap and must actually reach the requested depth with an exact, unbounded reported score and a legal continuation.

Inputs remain FEN-only, matching the frozen Maia3 policies at 1400, 1700, 2000 and 2300. Source histories are preserved as provenance; they are not newly supplied to either model or engine. Typed mate scores stay distinct from numeric centipawn scores.

The [initial batch's definitions](MINING_V3_DEEP200.md#three-separate-outcomes) remain unchanged: engine stability requires complete legal-root evidence, no mate-valued root, and the same nonempty within-20-centipawn move set at both depths. Retaining the candidate criterion additionally requires a best evaluation within ±200 cp and, at both depths and both Maia settings 1700/2000, at most 10% probability on acceptable moves and at least 50 cp capped expected regret. Regret is capped at 300 cp; the 50 cp acceptance-tolerance sensitivity remains available.

All positions keep `trainer_ready: false`. Source status does not alter these engine gates, but it matters to interpretation and later eligibility. BOT-tagged, public-exposed and unresolved-source positions are reported explicitly. A full-census engine count is not a human success rate, evidence of learning, or a bank of approved study items.

## Reuse and interruption handling

The 14,208 completed initial-batch root searches are copied into a separate, byte-identical imported-evidence file only after the original run, selected inputs, policies, scorer, engine and outputs pass hash and coverage checks. Their outcomes are recomputed before reuse. New searches have a separate checkpoint stream and timing accounting.

Each new checkpoint records a durable byte prefix, hash and root count. Resume validates the prefix and every reused root. Bytes written after the authenticated prefix are never silently accepted; explicit repair can discard that tail and repeat those searches. Process locks prevent two writers from owning the same run directory.

A finite local pipeline runs the search and then the complete aggregate validation. A low-battery pause closes owned engines and preserves evidence. The pipeline waits for AC power before resuming the same run. Other failures stop for review instead of being retried indefinitely. System sleep suspends computation; no results are lost simply because the laptop sleeps, but the run takes longer. The pipeline does not install an operating-system service or change power settings.

The original deep200 files are frozen. The new runner, selection code, summary builder, pipeline and their scoring dependencies are also fingerprinted before execution. Changing one during a run requires a reviewed recovery decision.

## Progress and completion

Progress reports distinguish the 200 imported positions, newly completed positions, pending positions, imported roots and new roots. Incomplete positions are never counted as failures. New pass/fail aggregates are withheld until the entire census finishes and every outcome is recomputed from its full legal-root evidence.

Final validation checked every selected identity, exact legal-root coverage at both depths, legal continuations, source strata, original policy probabilities, frozen hashes and saved outcomes. All outcomes were recomputed from the complete evidence and matched the saved results. Public outputs contain aggregate counts and fingerprints, without positions, solutions, source-game identities or private filesystem paths. The completed aggregate and a local readable report were saved by the pipeline; website publication is a separate deployment step.

## Interpreting runtime

Before the full run, the first batch's recorded root durations suggested about **56 hours under ideal eight-worker parallelism** for the additional 4,145 states. This was an illustrative planning calculation, not a promised finish time. The full pool differs from the constrained initial sample, and search costs have a long tail.

Imported root durations, new root durations, elapsed clock intervals and recorded monotonic attempt durations are kept separate. Parallel search durations overlap. They are not CPU-time measurements; elapsed clock intervals can include host sleep. The roughly 12-hour civil-clock duration of the first batch is not used as a no-sleep computation estimate.

Execution included manual pauses, system sleep and an automatic low-battery pause. Power settings also varied: late on 14 September, Low Power Mode was changed from Always to Only on Battery, allowing normal performance on AC. The search rules and frozen evidence were unchanged. These operational timings are not a controlled hardware benchmark, and no speed-up factor is inferred from the change in power setting.

## Run and inspect

```sh
python scripts/mining_v3_full_deep_selection.py
python scripts/mining_v3_full_deep_pipeline.py --workers 8
python scripts/mining_v3_full_deep_summary.py
```

The selector refuses to overwrite a frozen census. The pipeline resumes the verified run directory and automatically invokes the summary builder with `--require-complete` after all searches finish. A standalone summary call can save an explicitly incomplete progress snapshot during the run. Private evidence is stored under `data/mining_v3/deep_all/` and `results/mining_v3/deep_all/`; the completed public result is `results/mining_v3_full_deep.json`.
