# Version 2: balanced sampling and acceptable moves

8 September 2026. This is an exploratory mining pilot, not a completed human learning experiment. [Aggregate results and input hashes](../results/mining_v2_summary.json) identify the completed run; historical version-1 outputs are preserved.

## Completed run

| Check | Result | Scope |
|---|---|---|
| New screening | 48/2,000 shortlisted; 28 in training | Fixed operational rule below; approximate searches |
| Historical recheck | 26/64 candidates; 1/64 matched controls | FEN-only, four rating strata, same-batch controls |
| Exhaustive verification | 13/19 positions retained | Latest completed check per position, stable full acceptance at depths 20/24 |
| History sensitivity | First choice changes in 322/2,000 | Maia3-5M, fixed 2000 inputs |
| Larger model | 11/12 retain the low-good-mass/high-regret criterion | Maia3-79M versus 5M, selected verified subset, full acceptable sets |
| Curriculum candidates | 37 training positions with conditional rating gains | Exploratory rankings; unexamined roots remain explicit |

The [diagnostic aggregates](../results/mining_v2_diagnostics.json) also report fixed-rating exact-choice bins on 400 held-out positions from 331 games, with a club 1800–2000 subgroup of 116 positions from 98 games. Sparse bins are flagged. This is descriptive source-game agreement, not calibrated puzzle-solving probability; no calibration transform was fitted.

The current private material draft contains six provisional families, eight positive anchors and two natural boundary candidates. Four positive anchors and one boundary meet the full engine gate. The other boundary's complete acceptance set changed between depths despite supporting the intended capture comparison. Assessment forms and independent review are still missing, so the draft is not ready for recruitment. The 8–12-family target has not been met and no complete family bank is claimed. Additional retrieved candidates remain separate from accepted materials.

## Sample and provenance

The new sample contains **2,000 positions from 1,662 games**: 1,000 White and 1,000 Black, with 1,000 club and 1,000 elite positions. Each cohort independently has equal sides and 60/20/20 train/validation/test quotas. No game contributes more than two positions. All selected canonical states are distinct, and every saved full move history legally replays to its supplied FEN. Phase counts are 670 opening, 669 middlegame and 661 endgame under the sampler's declared material/ply rule. Rating and phase targets are approximately equal where cells exist; shortfalls are redistributed and reported.

Club input is a bounded prefix of the official June 2026 Lichess archive, with both players at least 1800 and base time at least 600 seconds. The sampler stopped after 2,000 eligible games. Selected dates fall on June 1; this is not a random whole-month sample. All 1,000 selected club positions retain actual mover and opponent clocks. Elite input uses the saved September–November 2025 archives, excludes BOT-tag games, and retains missing clocks as null. Elite time controls remain mixed. These are constructed cohorts, not a representative or fully time-matched comparison.

Source manifests distinguish complete local archive hashes from hashes of a downloaded compressed prefix. Game assignment precedes selection. Public trainer/worked-example states and recovered source-game IDs are excluded; entire source games are also scanned for public states outside the sampled window. Selected states are unique across cohorts. This does not establish player, opening-family or all-transposition separation. Old unresolved provenance remains a limitation. The split supports later development; no new held-out predictive model evaluation is claimed.

## Human policies

The primary instrument is pinned **Maia3-5M**, with temperature-one softmax probabilities over every legal move at 1400/1700/2000/2300 and real move history. A separate FEN-only condition at 1700/2000 repeats the current board under the official supported convention. Maia-2 rapid at 1700/2000 provides a model-version comparison. Both rating inputs use the requested level. **Clocks are retained for future ablation but are not model inputs in this run.**

Manifests record source/checkpoint hashes, runtime, precision, history padding and rating settings. Tests cover full legal-action coverage, Black mapping, castling, en passant and underpromotion, and compare history tokens with official inference. An optional pinned Maia3-79M adapter supports a separately identified shortlist sensitivity check. Model agreement is robustness evidence, not independent observations from two human populations; fixed-rating probabilities have not been calibrated to independent puzzle responses.

## Engine scoring and selection

Stockfish 18 is pinned by binary SHA-256, using one thread and 64 MB hash per worker. Hash is cleared for each root search. Records retain typed cp/mate scores, UCI bounds and WDL, achieved depth, nodes and legal continuations. Screening targets depth 16 with a 0.5-second top-three search and 0.2-second separate searches of engine leaders, likely human candidates and the actual played move. Requested depth is not achieved depth; this screening is approximate.

At each rating, sum probability across moves within 20 cp of the best score encountered and calculate expected regret capped at 300 cp. Repeat with a 50 cp acceptance tolerance. Unscored policy mass is never renormalized away. The archive distinguishes conditional estimates using the observed reference from conservative bounds allowing an unexamined better move. If any legal root is unexamined, global acceptable-mass lower bound is zero and capped-regret upper bound is 300 cp. These bounds assume the recorded finite-search evaluations; they do not prove chess values. Winning mates do not receive invented centipawn summaries. WDL sensitivity uses engine self-play expected score, not human winning probability.

The initial operational shortlist requires:

- Numeric evaluation between −200 and +200 cp and no mate in scored roots.
- Acceptable-move probability **upper bound ≤10% at both 1700 and 2000**.
- Capped-regret **lower bound ≥50 cp at both settings**.

The aggregate table also sweeps 5/10/20% ceilings, 25/50/100 cp regret floors and 20/50 cp acceptance tolerances. These settings are exploratory, not participant-derived cutoffs. Screening candidates are not automatically teaching items.

Shortlisted positions and provisional teaching anchors undergo exhaustive legal-root searches at depths 20 and 24. A final item must actually reach both depths, retain exact rather than bound-only scores, and preserve its complete 20 cp acceptance set. The initial pilot-bank contract excludes any mate-valued root. Incomplete or unstable items remain visible in the local audit. A separate chess review must check the explanation and limiting cases; engine evidence alone does not establish a teaching family.

## Historical comparison

The historical audit selects 16 candidates in each of four mover-rating strata (≤2000, 2000–2200, 2200–2400, >2400), with 64 nonselected controls matched on evaluation, runner-up margin, rating and ply. Matching prefers the same mining batch. Public and pilot overlaps are excluded. Exact pools, strata, matching distances and fallback counts are recorded. The original 538 unused candidate rows narrow further when their public source games are excluded.

Saved historical rows do not reconstruct actual game history; this audit is explicitly FEN-only. Preliminary development screens are retained locally and distinguished from the final stratified audit. Matched comparisons describe this constructed sample and do not show why humans think as they do.

## Reproduce and review

Research needs python-chess, numpy/pandas, PyTorch, the pinned Maia source/weights and Stockfish 18; website-only requirements are insufficient. Large archives, complete policies, engine caches and prospective private assessment items stay local. Hashes identify these inputs but do not make them downloadable from a fresh clone.

```sh
python scripts/mining_v2_sampling.py --help
python scripts/mining_v2_historical.py --help
python scripts/mining_v2_policy.py --help
python scripts/mining_v2_engine.py --help
python scripts/mining_v2_boundaries.py --help

python scripts/mining_v2_engine.py --input data/mining_v2/positions.jsonl \
  --policies data/mining_v2/policies.jsonl \
  --output results/mining_v2/pilot_screen.jsonl --workers 4

python scripts/mining_v2_summary.py
python scripts/mining_v2_diagnostics.py
```

The boundary retriever defaults to a geometric scan with public/held-out exclusions; optional `--screen` runs a bounded engine comparison. Its initial query found 125 rows (124 canonical positions) where knight and rook captures compete. Two natural limiting cases were investigated. This query is a reusable retrieval hypothesis, not an automatic family-labeling algorithm.

The engine executable defaults to the official Apple Silicon Stockfish 18 release under `models/stockfish18/`; use `--engine` for another platform and record its hash. The engine cache rejects changed input, policy, scorer or settings; use a new output path after changes. Checkpoint adapters likewise verify their pinned sources rather than silently replacing versions.

`scripts/mining_v2_screen_20260908.py` preserves the exact scorer used for the 2,000-position screen, matching its manifest hash. The current engine script improves tracking of exact versus bound-only UCI scores: python-chess's merged output could retain an earlier bound flag after a later exact score. This made the original deep gate conservative, not permissive. Subsequent verification uses streamed updates and records its own scorer hash; audited retries retain provenance for any reused exact root. Use the archived source to reproduce that screen, and the current script for new work.

The [revised study protocol](LEARNING_STUDY_V2.md) compares identical positions and explanations in grouped or shuffled order. Its exporter produces local review materials and concealed allocation slots, not enrolled participants or a timed response collector. Eight to twelve teaching families are a planning target, not a promised yield. Each needs different source games, unseen positive cases and genuine boundary negatives. Independent chess review, completed private materials, consent and preregistration remain prerequisites to the actual study.
