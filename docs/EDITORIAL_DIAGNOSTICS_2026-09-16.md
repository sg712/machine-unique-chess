# What the completed candidates can tell us before more mining

These are exploratory diagnostics of **1,032 already retained, editorial-eligible positions**, not estimates for chess as a whole and not a new held-out evaluation. The useful next step is to improve candidate selection and grading before spending more time on engine searches.

The reproducible aggregate is [editorial_diagnostics_20260916.json](../results/editorial_diagnostics_20260916.json). Its builder, [editorial_diagnostics.py](../scripts/editorial_diagnostics.py), verifies the completed census's frozen source hashes, then reconciles the selected positions' saved depth-20/24 root scores, acceptable sets, probabilities and regret. It runs no engine searches or model inference. No positions enter the trainer.

## Exactly what was analyzed

The completed census contains 4,345 states, of which 1,398 retain the full frozen criterion. Requiring **every originating observation** to have recovered source history, no BOT tag and no known public exposure leaves 1,231. Excluding all validation, test, unknown and other noneditorial analysis roles leaves **1,032: 481 White and 551 Black**. The other 199 source-eligible states remain outside these diagnostics.

Allowed analysis roles are `prior_development`, `pilot_train` and `new_train`. They contribute 737, 8 and 287 positions respectively. Analysis role takes precedence over an older source-split label: an already explored development item is not an untouched test item just because an earlier split called it one. Conversely, any untouched validation/test origin excludes the entire canonical state.

The source inputs, policies, outcomes, roots, run/checkpoint manifests, scoring dependencies and diagnostic builder are bound by SHA-256 in the aggregate. The public aggregate contains no boards, moves, source game identifiers or private paths. Every diagnostic below has **1,032 selected positions** as its denominator unless a different denominator is stated.

## Several good moves are a real part of this collection

An acceptable move is within 20 centipawns of the best saved numeric root score. The set must agree at both depth 20 and depth 24 under the frozen criterion.

| Number of acceptable moves | Positions |
|---|---:|
| 1 | 903 |
| 2 | 106 |
| 3 | 17 |
| 4 | 5 |
| 5 | 1 |

**129 positions (12.5%) have more than one acceptable move.** At depth 24, seven positions also have ties for the exact top score: six have two tied moves, and one has four. “The best move” needs to mean a set where appropriate.

For the Maia 2000 policy, acceptable-set probability is at least twice the probability of the exact-top-score tie set in **55 positions**. Including the other acceptable moves adds at least one percentage point in **66 positions**, and as much as 7.99 percentage points in one position. At Maia 1700 the corresponding counts are 58 and 71, with a maximum difference of 7.82 percentage points.

The exact-top calculation includes **every tied top score**, not an arbitrary engine ordering. These are model probabilities for a single supplied board, not measured human success rates.

**Practical change:** a future v3 drill must grade the frozen acceptable set, store its version and tolerance, and explain alternative good moves. An exact-one-move answer key would wrongly reject some acceptable responses. The original trainer bank is a separate dataset and is unchanged by this analysis.

## The collection is not mainly hanging on the 10% probability cutoff

For each position, the probability margin uses the largest `p_good_upper` across Maia 1700/2000 and both depths; the regret margin uses the smallest capped-regret lower bound over the same four conditions. Evaluation margin is the minimum distance from the ±200cp boundary across both depths.

| Diagnostic flag | Positions |
|---|---:|
| Within 1 percentage point of the 10% probability cutoff | 14 |
| Within 2 percentage points of the probability cutoff | 31 |
| Within 10cp of the 50cp regret minimum | 69 |
| Within 25cp of the ±200cp evaluation boundary | 70 |
| At least one of the 1pp / 10cp / 25cp flags | 147 |

The median worst-case acceptable-set probability is **2.29%**; the median minimum capped regret is **113.71cp**. These values are conditional on having been selected for low model probability and high regret. They do not independently validate difficulty.

For editorial planning only, changing one requirement while leaving the other frozen gates fixed would leave:

| Hypothetical stricter requirement | Remaining in this selected pool |
|---|---:|
| Probability ≤8% at both ratings and depths | 1,001 |
| Probability ≤5% at both ratings and depths | 871 |
| Capped regret ≥75cp at both ratings and depths | 830 |
| Absolute best evaluation ≤150cp at both depths | 871 |
| Probability ≤5%, regret ≥75cp, and absolute evaluation ≤150cp together | 598 |

**Practical change:** expose these margins to private reviewers and distinguish borderline cases from cases with more score margin. Do not silently replace the frozen criterion with the stricter requirements or advertise the resulting subset as a new validation result. The 598-position subset is an editorial sensitivity calculation, not a newly established “better” benchmark.

## The acceptable-move tolerance changes membership substantially

The following counterfactuals use the same saved exhaustive root scores and model distributions. They vary only the acceptable-set tolerance, keep the original probability cutoff, and retain the already satisfied regret/evaluation gates. Both depth agreement and the probability gate must hold.

| Acceptable loss tolerance | Same set at both depths | Probability gate at both depths | Both conditions |
|---|---:|---:|---:|
| 10cp | 964 | 1,032 | 964 |
| 20cp — frozen rule | 1,032 | 1,032 | 1,032 |
| 30cp | 877 | 932 | 849 |
| 50cp | 708 | 708 | 598 |

For **149 positions**, at least one saved root is within 5cp of the 20cp acceptance boundary at either depth. A stable set at 20cp therefore does not imply stability under every reasonable tolerance.

**Practical change:** retain the exact 20cp label for the completed research, but add a tolerance-sensitivity field to editorial review. Before committing a future mining protocol, choose and justify its acceptable-move rule. Do not select the rule by optimizing performance on untouched evaluation positions.

## Source overlap is manageable; phase coverage needs more attention

After collapsing recorded game aliases, the 1,032 positions come from **969 source games**. There are 908 games contributing one position, 59 contributing two, and two contributing three. No eligible state has more than one distinct originating game after alias collapse. The top ten games account for 2.13% of the 1,032 position–game incidences.

A deterministic greedy pass that keeps only positions whose every originating game remains unused keeps **969** and removes **63**. Its result has 449 White and 520 Black positions. This algorithm is not presented as a general optimal selection algorithm; in this pool each position has one alias-collapsed game, so it achieves one retained position per game.

| Phase | White | Black | Total |
|---|---:|---:|---:|
| Opening | 70 | 81 | 151 |
| Middlegame | 389 | 452 | 841 |
| Endgame | 22 | 18 | 40 |

Middlegames make up **81.5%** of this editorial pool; endgames only **3.9%**. The greedy source-deduplicated pool contains 143 openings, 790 middlegames and 36 endgames.

**Practical change:** keep all-origin game separation for new review packets and future train/evaluation splits. Deliberately include the scarce endgame cases in editorial discovery, with explicit counts, instead of assuming a random packet will cover the game evenly. This is a case for targeted *future* sampling, not automatically adding another 123,000 White positions: the eligible side split is already reasonably close to balanced, while phase coverage is much less even.

## Player ratings and time controls limit audience claims

Representative mover ratings, recomputed from the saved numeric Elo rather than inconsistent legacy bin names, are:

| Mover rating | Positions |
|---|---:|
| 1800–1999 | 182 |
| 2000–2199 | 192 |
| 2200–2399 | 196 |
| 2400–2599 | 195 |
| 2600–2799 | 177 |
| 2800+ | 90 |

There are **no sub-1800 representative mover ratings** in this selected pool. Supplying a Maia 1400 policy does not turn it into evidence from 1400-rated players. The saved representative time-control class is rapid for 300 positions, blitz for 238 and classical for 13; it is **unknown for 481**. Missing fields remain unknown, rather than being inferred from a different cohort.

**Practical change:** describe the source population accurately. If the trainer targets intermediate players, include a prospective lower-rated human-source cohort with its own source and evaluation separation. Recover missing time-control metadata before claiming a blitz/rapid/classical comparison. Do not infer training benefit or true human difficulty from source ratings or policy labels.

## The history comparison cannot be done with these saved policies

Although recovered game histories exist, **all 1,032 eligible saved Maia history maps are empty**. Only FEN-conditioned distributions were saved. There are zero compatible four-rating paired policy comparisons in this v3 bundle. The separate [v2 pilot](MINING_V2.md) already compared history and FEN-only Maia3-5M predictions: first choices changed in 322/2,000 positions at fixed 2000 inputs. The proposed work extends that sensitivity check to this candidate pool and its acceptable-set criterion.

**Practical change:** make a separate, predeclared context audit before additional production mining. For the same editorial-only states, compare compatible FEN-only and history-conditioned model inputs while specifying move-history truncation, side conventions and legal-move handling. Keep engine scoring context explicit, including repetition-sensitive states. That is a proposed future experiment; this diagnostic did not run it and provides no estimate of its outcome.

## What to do next

1. Use the existing private 24-position review packet to write concrete chess explanations, and record acceptable alternatives and tolerance sensitivity. No new engine run is needed for this.
2. Implement set-aware answer schemas and feedback before promoting any v3 examples. Preserve evidence hashes and explicit review gates.
3. Design the next small editorial sample around phase, source-game separation, side and score margins, retaining both borderline and robust cases for comparison. Avoid declaring a motif simply because a cluster or piece label exists.
4. Predeclare a compatible history-context audit and a lower-rated source cohort. These address actual evidence gaps more directly than another undirected large mining run.
5. Keep future human learning evaluation separate: the current data supports candidate selection and software testing, not the claim that a pattern transfers to unseen positions or improves chess strength.

## Reproduce and verify

From the repository root, with the existing chess environment:

```sh
python scripts/editorial_diagnostics.py
python -m unittest tests.test_editorial_diagnostics -v
```

The builder is idempotent for identical bytes and refuses to overwrite a different existing aggregate or any frozen research output. Eight focused tests cover all-origin holdout exclusion before diagnostic access, alias-aware source deduplication, set versus exact-top probabilities, tolerance/depth disagreement, score/policy reconciliation, incomplete history evidence, public-output privacy and output protection. The complete real-data calculation reconciled all 1,032 eligible positions using only saved evidence.
