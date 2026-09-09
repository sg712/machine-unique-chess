# Version 3: adding the missing White positions

8 September 2026 UTC; completed 9 September in India. **The collection, source audits and full first-pass analysis are complete.** This expansion preserves the historical files and gives both actual sides to move the same fresh screening procedure. The [dataset audit](../results/mining_v3_dataset.json), [source audit](../results/mining_v3_provenance.json) and [screening results](../results/mining_v3_summary.json) identify the completed work. Candidate counts are separate from accepted puzzles and human learning results.

The run briefly paused when the host reached 2% battery, then resumed after AC power was connected. Completed outputs were checked and reused with the same inputs and settings. Both stages finished all 248,810 observations.

## What the counts mean

The collection adds **123,405 White observations**. Together with the original 123,405 Black observations and the earlier 1,000-per-colour pilot, this gives **124,405 White and 124,405 Black observations: 248,810 in total**. The audit confirms complete counts, legal observed moves and new White states distinct from one another and the existing White pilot. The new White sample comes from 10,749 games; the complete file has 18,339 recorded source-game identities.

Historical record identities are preserved. Canonical state comparison keeps piece placement, side to move, castling rights and legal en-passant rights, while ignoring the two FEN counters. The original corpus has 605 repeated canonical-state rows. A further 281 Black pilot states overlap historical states, so the combined Black side has 886 repeated rows. Equal row counts therefore do not imply equal unique-state counts or independent observations.

The existing files, 5,155 version-1 selections, 320 trainer positions and version-2 pilot results retain their original scope. No board was recoloured or mirrored to manufacture an additional observation.

## Recovering the original games

Recovery matches complete stored trajectories against the saved September–November 2025 elite archives and retained official June/July 2026 Lichess PGNs. It checks FEN, ply, played move and both ratings. A historical game with several stored rows must match the same actual source game throughout. Ambiguous matches remain unresolved.

The documented November `eN` aliases also identify games by original archive order. Exact club URL game IDs provide another authoritative identity route. Where every stored board and played move matches that exact game, the recovered PGN can correct ratings that were previously joined by FEN alone: 148 corrections use November aliases and 59 use club URL identities. Historical ratings remain in the record's audit metadata. The original master CSV is unchanged.

Recovered rows retain the actual source game ID, preceding moves, last eight positions, time control and available clock annotations. Missing clocks remain null. An absent clock on the most recent move does not reuse an older annotation. Recovery manifests identify complete local files and bounded downloaded prefixes separately.

The completed recovery verifies 124,351 Black histories. Only 54 historical elite orphan rows remain unresolved: 37 ambiguous and 17 unmatched. It corrects 207 historical rating joins. All new White histories replay correctly. Black has 62,054 recorded mover clocks; White has 61,911, including the pilot. Elite sources generally omit clock annotations.

Recovery also identifies BOT titles. These games remain in the historical accounting, but are excluded from the descriptive human-game subset. Games whose source has not been recovered are a separate unknown category. A missing BOT tag is not evidence that an account never used assistance; it is the available archive classification.

The source audit separates historical exact-engine agreement by BOT status. In particular, the old high-rating agreement rates mixed human and bot accounts. Those figures and the old AUC must not be described as human-only performance or independent puzzle calibration. The website identifies this limitation in the research results and test explanation.

Of the 123,405 historical observations, 17,931 came from BOT-tagged games, 105,420 from recovered games without BOT tags and 54 remain unknown. The 5,155 selected observations include 886 from BOT-tagged games. All 320 public trainer states now have recovered sources: 282 without BOT tags and 38 with them. All six worked research examples came from games without BOT tags. These source classifications do not by themselves determine whether a chess puzzle is useful.

## Sampling White

The new White sample follows the historical Black counts within source cohort, mover-rating band and game phase, using source-corrected ratings where available. The sampling bands are 1800–1999, 2000–2199, 2200–2399, 2400–2599, 2600–2799 and 2800+. Phases use the same declared material/ply rule as version 2. Small residual differences in the combined sample can come from the earlier pilot, which used broader rating bins.

The primary White cadence uses plies 15, 19, …, 71; historical Black observations occur at plies 16, 20, …, 68. The explicitly labelled additional-ply supplement uses other actual White turns. A source game contributes at most 15 new White observations. Every selected history is legally replayed to its FEN, and the subsequent observed move is checked.

Games with explicit BOT titles, abandoned games, invalid games and known public trainer games are excluded from new sampling. The entire source game is scanned for public trainer states, including outside the sampling window. New White states are deduplicated against the White pilot. The source manifests document exact archive coverage, any supplements, retained eligible PGNs, quotas and file hashes.

The final quotas match the corrected historical cells exactly. Of the new White observations, 95 use additional actual White plies from cached June games. A further 143 meet the slower-game eligibility rule but come from elite archives: 27 from September 2025 and 116 from October 2025. These supplements are labelled in each record; they are not presented as 2026 standard-archive observations. The per-game cap and state deduplication still apply.

The slower-game cohort requires both players to be rated at least 1800 and base time of at least 600 seconds. Elite time controls are mixed. Chronological archive prefixes and targeted quotas make this a constructed sample; it is not a random sample of all chess. Full-corpus counts are not exactly matched by month or time control. Any slower-game supplement from an elite archive is explicitly labelled in the sampling audit.

## Exposure and dependence

Actual source-game identity determines a common split for both colours. Existing pilot assignments are retained where identities match. A separate exposure flag marks source games already used in historical development or public material. A new hash assignment does not turn an old development game into an unseen test game.

The audit reports canonical states crossing hash splits. Games, players, openings and transpositions can create dependence beyond the row count. This run does not fit a new predictive model or claim a fresh held-out performance score.

## Common engine and model inputs

The primary comparison is **FEN-only for every row**, using the current board without preceding moves or player clock inputs. FEN move counters remain part of the supplied board. This avoids the difference in recovered history availability between colours becoming a model-input difference. Later metadata recovery does not alter that frozen scoring input. The aggregate builder verifies every ID, FEN and observed move before joining enriched source metadata to the scores.

Pinned Maia3-5M supplies temperature-one softmax probabilities across every legal move at 1400, 1700, 2000 and 2300. Both player-rating inputs use the requested setting. The official repeated-current-board convention supplies the model's history tokens. The adapter matches the earlier pinned implementation numerically on checked inputs. Source and checkpoint hashes, PyTorch version and runtime settings are recorded. These probabilities are model predictions, not observations of how often people solve a puzzle.

Stockfish 18 uses one thread and 32 MB hash per worker, cleared before each search. Each board receives a top-three search with a 30,000-node stopping target, or fewer lines if fewer than three moves are legal. Its leaders, the observed move and up to ten likely model candidates receive separate 5,000-node root searches. Model candidates are drawn from the union of each rating's moves covering 85% policy mass, then capped at ten using their maximum probability across ratings. The same selection algorithm and per-search targets apply to both colours; the number of distinct roots, and therefore total nodes per board, can differ. Actual nodes may slightly exceed a stopping target, and solved or terminal searches can finish earlier.

A node-limited search may stop partway through an iteration with only a bound. The scorer retains the last completed exact score within the budget, when available, and records the later unfinished attempt separately. For MultiPV, the complete exact set comes from a common depth with distinct root moves. Here, “exact” means the engine reported neither an upper nor a lower bound; it does not mean the chess position was solved. If no complete exact iteration exists, the latest reported result remains in the audit, and bound-valued root results are excluded from the probability/regret calculations. Typed mate values, legal continuations and achieved depths remain recorded. This is a shallow first-pass screen, not depth-20/24 verification.

## Selection and reporting

The provisional rule requires the highest retained numeric score among the separately evaluated roots to fall within ±200 cp, excludes rows with a mate-valued retained search result, and requires at both 1700 and 2000:

- An upper bound of at most 10% on policy probability assigned to moves within 20 cp of the best root value.
- A lower bound of at least 50 cp on expected regret under that policy, capped at 300 cp.

For a mate-free row, let `b` be the highest retained exact root score. The good-move upper bound adds the policy mass of scored moves no more than 20 cp below `b` to all unscored mass. The regret lower bound sums `p(move) × min(300, max(0, b − score(move)))` over the scored moves; unscored moves contribute zero to this lower bound. An unscored move could improve the best reference, so a non-exhaustive row's unconditional good-move lower bound is zero and its capped-regret upper bound is 300 cp. Tighter quantities conditional on the observed reference are labelled separately in the raw output.

Unexamined or inexact root scores remain explicit. Unscored policy mass is not renormalized away. These bounds account for missing root scores while treating the retained finite-search scores as given; they do not bound the engine's evaluation error or prove the true chess values. Results also retain a 50 cp acceptance sensitivity. No first-pass row is marked as a verified puzzle.

Aggregates separate all observations, recovered games without BOT tags, BOT-tagged games and unresolved sources. A descriptive matched subset selects equal colours using metadata alone, within cohort, rating band, phase, time-control class and source month. Its bands follow the six sampling bands above, with an additional under-1800 category for any earlier observations. It requires recovered source history, known time-control class and known source month, removes repeated canonical states and drops cells absent from either colour. This smaller subset is a closer archive comparison, not a population estimate or new test set.

The selected IDs are frozen in a private manifest: 45,326 observations per colour across 75 cells. The summary checks the input hash, selection implementation, IDs and cell counts against that manifest. It was saved at 17:57:24 UTC on 8 September 2026, while the run had recorded 24,576 engine results and 40,960 policy results in completed shards. Some early results had already been inspected. The selection rule does not use outcomes, but this is not a preregistration before any outcome access. The public aggregate retains the freeze timing and fingerprints without exposing position IDs.

New teaching items still require exhaustive legal-root evaluation, stable acceptable moves at higher depths, explanations and chess review. The version-2 learning protocol and its incomplete private material bank remain separate.

## Completed first-pass results

All 248,810 observations completed both stages. The provisional rule selected 4,353 observations, representing 4,345 distinct canonical board states. None is marked as a newly deep-verified puzzle.

| Sample | White observations | White candidates | Black observations | Black candidates |
|---|---:|---:|---:|---:|
| Complete accounting | 124,405 | 2,106 | 124,405 | 2,247 |
| Recovered games without BOT tags | 124,405 | 2,106 | 106,420 | 1,834 |
| Frozen matched subset | 45,326 | 736 | 45,326 | 734 |

In the matched subset, the candidate rate rounds to 1.62% for each colour. This is a descriptive result within the constructed archive sample; it does not establish population equivalence or a human learning effect. The complete Black accounting also includes 412 candidates from BOT-tagged games and one from the 54 unresolved-source observations. Candidate counts describe this screening rule, not the earlier version-1 selection rule, and should not be added to the old 5,155 as if every item were new.

The retained top and root searches both have median depth 10. Only 6,677 observations had every legal root examined in this first pass, and 8,642 contained a mate-valued retained score. Mean unscored Maia-2000 policy mass was 5.35% where reported. The summary verifies all 62 stage outputs and their identities, settings and hashes, along with the frozen matched-subset manifest. The engine evaluated 15,314,967,755 nodes in total; that amount of computation does not replace deeper candidate validation.

**Follow-up completed, 9 September:** a separately frozen batch of 200 candidates—100 per colour, from 200 recovered source games without BOT tags—now has exhaustive depth-20/24 checks. Of these, 116 met the engine-stability contract (60 White, 56 Black), and 62 also retained the candidate criterion at both depths (35 White, 27 Black). The first-pass counts above keep their original scope. This constrained batch does not establish a survival rate for the remaining candidates, and its 62 retained positions still require explanations and chess review; none was marked trainer-ready. See the [depth-check methods and limitations](MINING_V3_DEEP200.md) and [validated aggregate](../results/mining_v3_deep200.json).

## Reproduce

Use the existing research environment with python-chess, PyTorch, the pinned Maia sources/weights and Stockfish 18. Raw source games, full policies, engine outputs and potential assessment positions remain local under ignored version-3 directories. Public files contain aggregate counts and fingerprints.

```sh
python scripts/mining_v3_recover.py --help
python scripts/mining_v3_sampling.py --help
python scripts/mining_v3_dataset.py
python scripts/mining_v3_matching.py
python scripts/mining_v3_run.py --input data/mining_v3/positions.jsonl \
  --run-dir results/mining_v3/full --shard-size 8192 --engine-workers 8
python scripts/mining_v3_summary.py
```

The runner freezes 8,192-row input shards and overlaps model inference with engine scoring. Each stage has checked input/output hashes and completion counts. A resumed run rejects changed inputs or scorer settings. Public summaries require every shard to be complete and every record to match; a started job is not reported as a completed screen. The completed run contains 31 input shards and 62 completed analysis stages.
