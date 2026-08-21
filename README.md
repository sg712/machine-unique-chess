# machine-unique chess

**Finding chess positions where a strong engine is decisively right and essentially no
human plays the move — then testing how much structure those positions actually have.**

All ratings are **Lichess ratings** (the scale runs ~200–400 above FIDE and past 3000
at the top). Across 123,405 positions from real games — deliberately balanced, 19–21k
in each rating band from 1800 to 2800+ — about 4% contain a move that Stockfish rates
clearly best and that a neural model of human play gives under 5% probability at
*every* rating from 1100 to 2600. The rate has held across nine separate batches
and every band. In 3,956 of those, the player actually at the board missed it too;
in 1,532, that player was rated 2500 or above.

With ~850 machine-unique positions per band, the find-rate by strength is cleanly
measured:

| Mover (Lichess) | Finds the machine-unique move |
|---|---|
| 1800–2000 | 6.6% |
| 2000–2200 | 13.0% |
| 2200–2400 | 15.9% |
| 2400–2600 | 17.0% |
| 2600–2800 | 27.4% |
| **2800+** | **56.9%** |

Nearly flat through 2600, then a steep climb — at the top of the pool a *majority* of
these moves are found. "Machine-unique" is a statement about everyone below ~2800.

**Why the moves are invisible.** Comparing equal-stakes positions that differ only in
visibility (both ≥100cp better than the human favourite): thirty plain yes/no features
of the move predict invisibility at **AUC 0.851** — no neural network needed. The
invisible signature is *anti-heuristic* moves: offering material with no visible payoff
(3.8× enriched), quiet moves (1.8×), deep retreats, moves to the rim. The visible
signature is forcing moves: captures (4× depleted), checks, escapes, immediate threats.
All trends monotone across the visibility spectrum. The machine-unique set is, to first
order, the set of moves that violate the heuristics humans use to order their search.

Clustering those positions by how an engine represents them internally produces groups
that are real but soft — nine times better separated than a shuffled null, yet with no
natural number of groups and no sharp boundaries. They are **deliberately unnamed**: a
name would assert that human chess vocabulary already covers the group, and the
measurements say it mostly does not.

The trainer teaches eight of these regions, by example.

---

## What's here

```
experiments/     the pipeline, numbered in the order it was built
webapp/          the trainer (Flask + SQLite)
docs/            findings, including the validation write-up
scripts/setup.sh fetches engines and networks (nothing large is committed)
notes/           working notes and the research landscape
BIBLIOGRAPHY.md  annotated reading list
```

### The pipeline

| Step | What it does |
|---|---|
| `02_build_dataset.py` | Streams the Lichess open database, samples mid-game positions from rated games |
| `03_disagreement_mining.py` | Stockfish at depth 16 vs Maia at four rating levels; flags machine-unique positions |
| `06_frontier_2600.py` | Extends the human-visibility curve to 2600 with Maia-3 |
| `09_consolidate.py` | Merges batches, defines the "hard core" (also missed by the real player) |
| `16_concept_families.py` | Embeds positions with Leela Chess Zero, clusters into groups |
| `17_build_concepts.py` | Engine lines + human move distributions for each group |
| `18_cluster_validation.py` | Tests the clustering against a null: is it real, and at what k? |
| `19_does_embedding_matter.py` | Does the embedding beat surface chess features — and does clustering keep that? |
| `20_difficulty_model.py` | The Maia control that overturns 19; a calibrated human-difficulty model |
| `21_learning_curve.py` | Is the model data-hungry or saturated? (saturated past ~20k) |
| `22_repair_elite_game_ids.py` | Rebuilds elite game ids — the grouped-CV bug fix |
| `23_band_value.py` | What each new batch bought, per rating band |
| `24_band_sampler.py` | Band-targeted sampling — evens the dataset to ~20k per band |
| `25_top_band_sampler.py` | Extends the ladder to Lichess 2800+ (mover-side sampling) |
| `26_why_invisible.py` | Equal-stakes contrast: which plain features make a move invisible |
| `27_other_lenses.py` | HDBSCAN, GMM-BIC, hierarchy, dictionary atoms — all say "continuum" |
| `28_assign_new_mu.py` | Embeds the later machine-unique positions, assigns each to its nearest group |
| `29_extend_trainer.py` | Triples the drill pool: 24 new engine-verified positions per concept |

Everything ran on one laptop.

### The trainer

```bash
bash scripts/setup.sh          # only needed to re-run the pipeline
pip install flask python-chess
python webapp/app.py           # http://127.0.0.1:5055
```

Eight groups. Each opens with four study positions showing the engine's move and
what follows — deliberately without commentary, since the patterns are easier absorbed
than described — then thirty-six unseen positions to drill. Feedback names your move, tells
you what share of 1900-rated humans play it, and steps through the engine's line.

The app serves precomputed positions from `webapp/concepts.json`; no engine runs per
request, which keeps it fast and deterministic. Feedback also quotes a difficulty model's
estimate of how often a 1900-rated player finds the move (exp 20).

To deploy: the repo carries a `render.yaml`, so connecting it to Render picks up the
build and start commands automatically. Runtime dependencies are Flask and python-chess
only — no engine, no neural network. Set `DB_PATH` to a mounted disk if progress should
survive redeploys.

---

## The eight groups

Characterised only by measurement. No names, no interpretation. Counts cover all 5,155
machine-unique positions — the 3,410 found after the clustering were embedded the same
way and assigned to the nearest group centre (exp 28).

| Group | Positions | Found over the board | Quiet | Avg error | Closest named motifs |
|---|---|---|---|---|---|
| Concept 1 | 924 | 29.9% | 85% | −328cp | exposedKing 0.19 · defensiveMove 0.11 |
| Concept 2 | 444 | 9.5% | 88% | −533cp | sacrifice 0.41 · deflection 0.35 |
| Concept 3 | 1149 | 23.6% | 89% | −224cp | pin 0.27 · clearance 0.25 |
| Concept 4 | 431 | 22.3% | 89% | −219cp | intermezzo 0.20 · clearance 0.14 |
| **Concept 5** | 258 | 26.0% | 77% | −440cp | **exposedKing 0.00 · quietMove -0.05 — matches nothing** |
| Concept 6 | 829 | 24.1% | 93% | −300cp | skewer 0.29 · attraction 0.28 |
| Concept 7 | 861 | 20.3% | 85% | −434cp | sacrifice 0.42 · attraction 0.41 |
| Concept 8 | 259 | 27.8% | 82% | −313cp | exposedKing 0.53 · pin 0.30 |

Between 68% and 94% of these moves are quiet — neither capture nor check. The part of
chess humans can't see isn't tactics; tactics are what training drills.

---

## Findings

**Blindness becomes disbelief.** Simulated humans converge toward engine choices as
rating rises on ordinary positions. On machine-unique positions the rate at which they
*play* the engine's move stays near zero from 1100 to 2600 — but the rate at which it
appears in their top five climbs from 29% to 57%. Weak players never see the move;
strong players see it and reject it.

**Simulation underestimates real masters.** Maia-3 predicts 2.6% for simulated 2600s.
Real 2600+ players in the source games found these moves 37.7% of the time (n=901;
earlier estimates of 47% and 39.7% rested on 247 and 438 positions) — roughly 15×
higher. Behaviour models capture pattern recognition, not
calculation under a clock.

**Half-nameable.** Regressing the machine-unique direction onto twelve motif directions
built from tagged Lichess puzzles gives R² = 0.46 — a signature of sacrifice without a
combination to justify it. The other half is not expressible in known terms.

**The clusters are real but soft, and "eight" was a choice.** Silhouette beats a shuffled
null by ~9× at every k, but the margin is flat from k=3 to k=12 — no elbow, no natural
number of groups. k=6 is the most reproducible partition (bootstrap ARI 0.90 vs 0.80 at
k=8); k=8 is the arrangement whose groups predict human find-rate better than chance
(p = 0.009, where k=9 gives p = 0.063).

**Clustering discards most of the signal — and then the signal turned out not to be
there.** Predicting whether the player at the board found the move, the Leela embedding
beat surface chess features by +0.062 AUC. But that baseline had no access to **Maia**,
a network trained specifically to predict human moves, or to the engine's own evaluation.
Against a fair baseline (5-fold CV grouped by game, n=1,745, 14.1% base rate; game ids repaired by exp 22):

| What the model sees | AUC |
|---|---|
| Maia's probabilities alone | 0.581 |
| Leela embedding alone | 0.583 |
| Surface chess features alone | 0.613 |
| Engine evaluation alone | 0.636 |
| Surface + engine + Maia | 0.648 |
| **Surface + engine + Maia + player rating** | **0.724** |
| … and the Leela embedding on top | 0.683 |

Adding the embedding *costs* 0.041. Sweeping from 40 principal components down to 2 gives
a monotonic decline and a best-case gain of −0.001, so this is redundancy, not overfitting.
**The embedding tells you nothing about human difficulty that Maia and the engine did not
already say.** Exp 18 is untouched; what falls is exp 19's interpretation.

**A difficulty model that works.** Trained over all 123,405 mined positions rather than the
machine-unique subset, predicting whether a human plays the engine's best move:
**AUC 0.845 ± 0.003**, Brier 0.160 against 0.250 for guessing the base rate, calibrated to
within about half a point in every decile. (An earlier version claimed the model
underestimates machine-unique positions; that gap was an artefact of a broken evaluation —
see below — and is gone.) Every position in the trainer carries its prediction of how often
a 1900-rated player finds the move. Full write-up in
[docs/FINDINGS_difficulty.md](docs/FINDINGS_difficulty.md).

**The evaluation had a bug, found and fixed.** Every elite game carried the placeholder id
`"?"`, so "grouped by game" cross-validation was treating all 29,741 elite positions as one
game — one fold owned all of them. Exp 22 reconstructs real ids by replaying the source
archive; with sound folds, fold variance fell 4× and the reported calibration drift vanished.

**More data is done helping — except at the top.** The learning curve is flat past 20k
training positions (0.843 at 30k → 0.844 at 99k). Splitting the same held-out games by the
rating of the player at the board: each new elite batch has bought accuracy only in its own
top band (+0.0084 AUC at 2800+ for the latest; −0.0003 to +0.0007 everywhere else). And the
model's accuracy falls monotonically with player strength — 0.855 under 2000 down to 0.812
at 2800+. Strong players are genuinely harder to predict.

So: the groups are a defensible **teaching partition**, not a discovery of discrete kinds,
and not a privileged window into what humans cannot see.

---

## Built on

Schut et al., *Bridging the human–AI knowledge gap through concept discovery and transfer
in AlphaZero*, PNAS 2025 — which mined concepts from AlphaZero absent from human play and
taught them to four grandmasters using only example positions. This project reproduces the
idea on open models and at scale.

Stockfish 17.1 · Maia-2 / Maia-3 (CSSLab, Toronto) · Leela Chess Zero · Lichess open
database. Full citations in [BIBLIOGRAPHY.md](BIBLIOGRAPHY.md).
