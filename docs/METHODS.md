# Methods and data provenance

Updated 7 September 2026. This document describes the current saved corpus and separates historical experiments from new audits. Quantities are not interchangeable across experiments. Earlier versions are retained in Git history.

## Research question and operational definition

Can disagreements between a strong chess engine and a model of human move choice provide useful practice material? Learning effectiveness, the discovery of new human-unknown concepts, and a causal explanation of human search have not been established.

For each sampled position, experiment 03 runs Stockfish 17.1 at depth 16 with MultiPV=2. Maia-2 rapid predicts move probabilities at **1100, 1400, 1700 and 2000**, with both player-rating inputs set to the tested level. The most probable Maia move at 2000 is separately evaluated with a root-restricted Stockfish search.

A selected position satisfies both:

- `human_cost_cp >= 100`: engine-choice evaluation minus the evaluation of Maia-2's 2000 favourite.
- `p_max <= 0.05`: maximum probability assigned to the engine move at those four Maia settings.

“Machine unique” names this filter. It does not mean no human can find the move, every alternative is bad, or the engine move is uniquely optimal. `engine_margin` records the first-versus-second engine evaluation gap, but is not part of this mining filter. Historical scores convert mate scores to a numeric sentinel, so centipawn analyses require special care around mates. Saved probabilities are rounded; reapplying thresholds to saved CSVs can be affected by rounding at the boundary.

## Sources and sampling

- [Lichess rated-game archives](https://database.lichess.org/): experiment 02 samples games with both players at least 1800 and base time at least 600 seconds, excluding abandoned games. It samples every fourth ply between 14 and 70. The script tries June, May and April 2026 in order; that list is a fallback configuration, not proof all months were consumed.
- [Lichess Elite Database](https://database.nikonoel.fr/): experiment 02b and later samplers read filtered elite archives. Elite time controls are not necessarily the same as the slower club sample. Saved local archives include September–November 2025. Experiments 24/25 add band-targeted samples; their source-month options are recorded in those scripts.
- [Lichess puzzle database](https://database.lichess.org/#puzzles): supplies tagged positions for the 12-motif basis, about 150 examples per theme and a 400-position puzzle baseline.
- [Stockfish](https://github.com/official-stockfish/Stockfish), [Maia-2](https://github.com/CSSLab/maia2), [Maia-3](https://github.com/CSSLab/maia3), and [Leela interpretability tooling](https://github.com/HumanCompatibleAI/leela-interp) supply the engine and model components. Exact local engine hash is recorded for the new audit; historical neural checkpoints are not completely version-pinned in the old outputs.

The corpus contains **123,405 positions from nine mining batches**, including **5,155 selected positions** (4.1773%). Rating-band counts range from 20,074 to 21,359 in the consolidated data. The source distribution is constructed, not representative of all chess games. Ratings are the source Lichess ratings; no universal conversion to FIDE is assumed. Time control, date, phase and player differences can confound comparisons.

Experiment 09 deduplicates full FEN strings and repairs missing elite source-game IDs using experiment 22's reconstruction. Unresolved positions may remain singleton groups. Removing the two FEN move counters reveals **605 duplicate board-state rows** in the current full corpus. Game-level cross-validation does not guarantee separation by player, transposition or time. Exact sampled inputs are identified by SHA-256 in the new output; the historical pipeline lacks a complete immutable archive manifest, which remains a reproducibility limitation.

## Experiment inventory

| Experiment | Actual scope | Evaluation and result source |
|---|---|---|
| 01: paper prototypes | 4 transcribed positions | Maia-2 probabilities; `01_frontier.csv`; descriptive examples only |
| 03/09: mining and consolidation | 123,405 positions; 5,155 selected | Fixed depth-16/100cp/5% definition; `master_all.csv`, `master_machine_unique.csv` |
| Actual game moves | 5,155 selected; 1,199 exact matches | `played_move == engine_best`; 3,956 nonmatches, including 1,532 from movers rated at least 2500 |
| 06: Maia-3 ranking | 77 selected + **56 saved controls**, each at five ratings | Top-one/top-five rank at 1100,1500,2000,2300,2600; `06_frontier_2600.csv`. The requested control sample was 60; the saved output has 56. This is not a full-corpus probability filter through 2600. |
| 05/05b: sparse directions | 30 individual fits; grouped fits on five examples | Leela policy rollouts, pooled residuals, held-out separation; no individual fit generalized; grouped held-out score 0.515 |
| 07: motif reconstruction | Cached 646 selected / 400 controls, not all 5,155 | 12 directions; mean-direction R² 0.462; per-position means 0.202 / 0.184; `07_composition.json` |
| 16/18/27: grouping and validation | 1,745 cached selected embeddings | Layer-10, 768-dimensional mean-pooled Leela embeddings; k=8; resampling, shuffled null and alternative clustering methods |
| 28: assignment | 3,410 later positions | Nearest centre from the original fit; combined group signatures cover 5,155 |
| 17/29: trainer curation | 32 study + 288 drill positions | Additional depth-18 check, unchanged top move and at least 70cp runner-up gap when curated; this is a stricter subset than the mining corpus |
| 26: feature contrast | 18,296 rows with gap >=100cp; 7,853 extreme-group rows for classification | 5,155 low-probability, 10,443 intermediate, 2,698 high-probability; 30 binary features; five folds by game; AUC 0.851 |
| 20B: difficulty | 123,405 positions | Gradient boosting, five folds grouped by game; AUC 0.845, Brier 0.160; `20_difficulty.json` |
| 30: new descriptive audit | Full corpus threshold sweep; 48 different games for engine check | `30_research_audit.json`, `30_engine_audit.json` |
| 31: corrected embedding comparison | 1,745 positions / 1,341 games / 246 exact matches | PCA fitted within each training fold; `31_embedding_audit.json` |
| 32: worked examples | 3 primary + 3 related positions | Deliberately curated; depth 20; each pair from different games; `webapp/research_examples.json` |
| Proposed learning study | 24-person feasibility pilot | Protocol only in `LEARNING_STUDY.md`; no completed randomized learning result |

## Interpreting the observational results

Exact agreement is not move quality. In 2,034 of 5,155 selected positions (39.5%), the saved runner-up is **less than 20cp** behind. An alternative can be good even when the real player did not match the first engine move. Full-corpus actual-move losses have not been computed; the new 48-position audit provides a limited comparison only.

The feature contrast shares a minimum evaluation gap; it does not match position difficulty, exact gap, phase, rating, time control or batch. Its label comes from Maia, not a direct measurement of thought. “Offers material” is a static attack/value proxy, not an assessment of compensation. The historical feature extractor also uses destination occupancy for captures and can misclassify en passant; no new feature-model rerun is claimed here. Monotonic associations in selected rows do not rule out selection effects.

The motif result reconstructs a population mean direction in a particular embedding basis. Residual variance does not establish new concepts or missing chess vocabulary. In particular, the old `mu.npy` cache has 646 rows; the current larger CSV must not be silently treated as the source of those cached embeddings.

Clustering validation is exploratory. Independent-dimension shuffling destroys correlations and therefore is not a covariance-preserving null. Small absolute silhouettes and disagreement between methods limit claims of natural categories. The k=8 permutation p-value is not the probability that the result is due to luck; several values of k were examined without a multiple-comparison adjustment. A teaching partition can be useful without representing newly discovered concepts, but usefulness still needs a learning study.

## New engine and threshold audit (experiment 30)

Seed 20260907. Shuffle selected positions separately in each of the six rating bands and take eight per band, skipping previously selected source games. Bands have lower-exclusive, upper-inclusive bounds: <=2000, (2000,2200], …, >2800. This is a stratified descriptive sample, not 48 independent draws representative of every chess position.

Stockfish 17.1, one thread, 128 MB hash, cleared before every search. Each search targets depth 20 with a three-second time cap. Analyze the unrestricted top two moves, then separately the original engine move, Maia-2's 2000 favourite and the actual played move. Record actual depth, nodes, elapsed engine time, scores and principal variations. **All searches for all 48 positions reached depth 20.**

- Original top move retained: **35/48**.
- Four positions include a mate score and are excluded from cp comparisons, but retained in top-move stability counts.
- Original move still at least 100cp above Maia's favourite: **42/44** numeric cases.
- Actual played move exactly equals the original answer: **12/44** numeric cases.
- Actual played move within 20cp of the best score encountered: **14/44** numeric cases.

“Best encountered” is the maximum across these finite searches; separately restricted search scores can disagree and do not prove the global optimum. Maia probabilities are not recomputed for changed answers. The gap result and top-move stability answer different questions. No original labels, trainer answers or participant records were overwritten by this audit.

The threshold sweep combines cp gaps 50/100/200 with Maia ceilings 1/2.5/5/10%. Counts span 755–14,584. Exact-match rates span 16.1–29.3% in this grid. These are descriptive selection sensitivities; we have not refitted every cluster or feature association at each threshold.

Rating-band uncertainty uses 1,000 percentile bootstrap samples of source games within each band, retaining all sampled positions per game. It conditions on this corpus and does not cover player dependence, source bias or engine uncertainty. JSON includes numerator, denominator, number of games, intervals and per-batch counts.

## Predictive evaluation and corrections

Experiment 20B's saved metrics use game-grouped folds after the elite-ID repair. The target is the actual player's exact agreement with the saved engine choice. Five-fold standard deviations describe variation among folds, not confidence intervals for a population effect. The old result files are retained as historical outputs, not silently replaced.

Experiment 31 reruns 20A after moving PCA inside the training folds. Surface-category columns are now fixed to a declared chess vocabulary. Scaling and logistic fitting are inside each fold. Full baseline AUC is 0.755; adding 40 embedding components yields 0.732. Widths 2/5/10/20/40 do not improve the full rating-aware baseline. A position-only baseline gains approximately 0.007 at best; it is a different comparison. The width sweep is exploratory and uses the same folds, not nested model selection. These results neither demonstrate unique predictive value nor prove representational redundancy.

The current trainer's 1900 estimates and six-rating test curves are full-corpus refits that include the trainer positions. They are counterfactual model outputs, not independently calibrated human item-response curves or validated ratings. The new research audits do not retrain or replace those live curves. Independent held-out-game calibration and participant responses are still needed.

The sparse-direction experiment adapted [Schut et al.](https://arxiv.org/abs/2310.16410) using Leela policy rollouts instead of AlphaZero MCTS, pooled residuals instead of the same internal representation, and held-out separation instead of their teachability procedure. The failed transfer is reported; no claim of replicating their grandmaster learning result is made.

## Reproduction

The Flask site uses only committed precomputed data and `requirements.txt`. Research needs Python with numpy, pandas, scipy, scikit-learn, python-chess, the relevant neural runtimes, and downloaded model weights. Existing research environments are described by `scripts/setup.sh` and the experiment imports; these environments are not fully lockfile-reproducible.

From the repository root:

```sh
# Rebuild the master from preserved mining batches and rating sources first:
python experiments/09_consolidate.py

# Full audit; supports --skip-engine for descriptive tables only.
# Existing engine rows are cached against input hash, seed and engine settings.
python experiments/30_research_audit.py

# Rerun embedding comparison without changing trainer difficulty scores:
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python experiments/31_embedding_audit.py

# Curated examples; failure to verify stops the build:
python experiments/32_research_examples.py

# Regenerate current result summaries from JSON:
python scripts/render_research_notes.py
```

`master_all.csv`, raw source archives and embedding caches are omitted from Git because of size. A fresh clone can inspect the committed audit records and run the website, but cannot reproduce the full audit without reconstructing or obtaining those exact inputs. SHA-256 hashes identify the inputs used here; they do not make the omitted files downloadable. Cache row identity beyond the preserved historical ordering is an additional limitation of earlier embedding experiments.

Before a confirmatory study: freeze an archive/checkpoint manifest, separate by game and canonical position (and preferably player/time period), use stronger engine verification, calibrate item curves independently, register the study, then collect participant responses. See [the proposed learning protocol](LEARNING_STUDY.md).
