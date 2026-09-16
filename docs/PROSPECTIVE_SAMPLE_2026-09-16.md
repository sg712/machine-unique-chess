# A separate calibration sample and targeted endgame queue

16 September 2026. **256 real positions have been acquired and frozen from 256 distinct games.** These are source observations, not newly verified puzzles, calibrated probabilities, or human-learning results. Model and engine analysis is a separate stage.

## Completed acquisition

The sampler downloaded only an **8 MiB prefix** of the official [August 2026 Lichess rated-game archive](https://database.lichess.org/), then considered its first 8,000 complete games. It retained completed standard rated games with both players rated 1400–2399 and base time of at least 180 seconds. BOT-tagged games, unresolved game identities, invalid games, and games containing already sampled/public project positions were excluded.

All selected games are from **1 August 2026**. This is a bounded chronological convenience sample; it must not be described as a random month or a population estimate for all chess players. Source ETag, archive byte range, prefix hash, selection protocol, exclusion identities and output hashes are recorded in the [aggregate](../results/prospective_sample_20260916.json).

The protocol was saved before reading the fresh source. A source-game hash assigned roles before looking at positions or outcomes. No engine evaluation, PGN evaluation comment, or model output influenced inclusion.

| Queue | Positions | Purpose |
|---|---:|---|
| Calibration development | 64 | Develop/check the planned behavioral evaluation |
| Calibration evaluation | 64 | Separate evaluation after analysis choices are frozen |
| Targeted endgames, White, mover 1400–1799 | 32 | Address both phase and lower-rating gaps |
| Targeted endgames, Black, mover 1400–1799 | 32 | Same targeted role with actual Black turns |
| Targeted endgames, White, mover 1800–2399 | 32 | Endgame comparisons in the prior audience range |
| Targeted endgames, Black, mover 1800–2399 | 32 | Same targeted role with actual Black turns |

Every requested cell was filled. The combined sample happens to contain **128 White / 128 Black** positions; calibration side counts were not forced. Calibration states were selected by a seeded hash over all eligible actual plies 14–140 in a source game. Targeted states were selected only among endgame plies on a hash-assigned side. Within each declared role/cell, games were ranked by a seeded hash.

“Endgame” uses the existing mechanical phase definition: total nonpawn material at most 20 points, with knights/bishops worth 3, rooks 5 and queens 9. It is not a human thematic annotation. The entire sample has 145 such endgames, 86 middlegames and 25 openings. There are 138 positions with mover rating 1400–1799 and 118 with mover rating 1800–2399.

## Separation and retained context

- Exclusions cover **247,924 prior canonical states** and **18,491 known prior/public game identifiers**. Reading previous state identities for exclusion did not inspect their outcomes or tune against held-out positions.
- Only one position is retained per source game. Full move-sequence hashes also reject copied games with different identities.
- Each selected target is absent from every other selected source game's complete state history. The check works in both directions: a new target cannot have appeared in an earlier selected game, and an earlier target cannot occur elsewhere in the new game.
- All 256 positions retain genuine replayable move histories, both source ratings, time control and mover/opponent clocks. There are zero missing mover clocks.
- Exact PGN-block hashes tie records to the preserved source prefix. Private source-state hashes support exposure checks without publishing boards.
- Private normalized username hashes permit later repeat-player sensitivity analysis. There are **510 distinct known players across 512 player appearances**. These identifiers are pseudonymous, not anonymous, and are not included in the public aggregate. No player-level separation is claimed.

The earlier local draft was preserved. The final cohort is `data/mining_v3/prospective-20260916-v2/`, which adds full-source target-exposure checks and provenance fields; it uses the same verified source bytes and selection protocol criteria. The version-1 cohort must not be used for downstream runs.

External puzzle exposure, near-duplicate teaching patterns and transpositions not equivalent under the canonical-state rule remain limitations. “Not known to be exposed in this project” is not “never seen by a human.”

## Model training dates checked separately

The pinned Maia3-5M [revision metadata](https://huggingface.co/api/models/UofTCSSLab/Maia3-5M/revision/b6559de2398d7140b985f28fd2c19fb5e47ddabe) dates the revision to **23 May 2026**. Its [published weight hash](https://huggingface.co/UofTCSSLab/Maia3-5M/blob/b6559de2398d7140b985f28fd2c19fb5e47ddabe/maia3-5m.pt) matches the locally pinned checkpoint. The [paper, §4.1](https://arxiv.org/html/2605.19091v1) describes January 2023–July 2025 training games.

Thus the selected August 2026 games postdate the published weights. The [separate provenance record](../results/prospective_model_provenance_20260916.json) documents that temporal separation. It does not prove the model has never encountered a similar position or the same players. No full training-corpus membership audit is claimed. This follow-up resolves the temporal-provenance question left pending in the original frozen source summary without rewriting that summary.

## Analysis boundary

Calibration must compare probability on an engine-acceptable **set** against the recorded source-game choice. Use actual mover/opponent rating pairs within the model's supported range and keep FEN/history predictions separate. Complete, stable, numeric depth-20/24 evidence is required by the planned primary scoring rule; capped, incomplete, mate-valued or unstable cases stay in the coverage denominator and are reported separately.

The selected endgame queue has different inclusion rules and cannot be pooled into the calibration denominator. Screening it can suggest candidates for further work, but screening cannot promote puzzles or certify explanations. The first executable analysis tranche is deliberately smaller than the acquired cohort; its membership and settings must be frozen before inference.

## Reproduction

[Sampler](../scripts/prospective_sampling_20260916.py), with the existing research dependencies and prior exclusion index:

```sh
python scripts/prospective_sampling_20260916.py \
  --output data/mining_v3/prospective-new-reproduction
python -m unittest tests.test_prospective_sampling_20260916 -v
```

The output directory must be new and ignored by Git. `--cached-source` can reuse a previous cohort's prefix only after its URL, byte count and hash match; it never overwrites that source. Eight tests verify history replay, legal observed choices, whole-game exclusions, role assignment before outcomes, ignored evaluation comments, duplicate/copy rejection and cross-source target exposure. The public aggregate contains no positions, solutions, game IDs or player hashes.
