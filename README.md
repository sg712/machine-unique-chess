# machine-unique chess

**Finding chess positions where a strong engine is decisively right and essentially no
human plays the move — then testing how much structure those positions actually have.**

Across 43,603 positions from real games, 4.0% contain a move that Stockfish rates
clearly best and that a neural model of human play gives under 5% probability at
*every* rating from 1100 to 2600. In 1,499 of those, the player actually at the board
missed it too; in 247, that player was rated 2500 or above.

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

Everything ran on one laptop.

### The trainer

```bash
bash scripts/setup.sh          # only needed to re-run the pipeline
pip install flask python-chess
python webapp/app.py           # http://127.0.0.1:5055
```

Eight groups. Each opens with four study positions showing the engine's move and
what follows — deliberately without commentary, since the patterns are easier absorbed
than described — then twelve unseen positions to drill. Feedback names your move, tells
you what share of 1900-rated humans play it, and steps through the engine's line.

The app serves precomputed positions from `webapp/concepts.json`; no engine runs per
request, which keeps it fast and deterministic.

---

## The eight groups

Characterised only by measurement. No names, no interpretation.

| Group | Positions | Found over the board | Quiet | Avg error | Closest named motifs |
|---|---|---|---|---|---|
| Concept 1 | 287 | 16.7% | 81% | −335cp | exposedKing 0.19 · defensiveMove 0.11 |
| Concept 2 | 204 | 7.8% | 89% | −505cp | sacrifice 0.41 · deflection 0.35 |
| Concept 3 | 339 | 15.0% | 88% | −212cp | pin 0.27 · clearance 0.25 |
| Concept 4 | 145 | 9.7% | 85% | −215cp | intermezzo 0.20 · clearance 0.14 |
| **Concept 5** | 105 | 19.0% | 68% | −507cp | **exposedKing 0.00 · quietMove −0.05 — matches nothing** |
| Concept 6 | 278 | 18.0% | 94% | −306cp | skewer 0.29 · attraction 0.28 |
| Concept 7 | 295 | 10.2% | 83% | −414cp | sacrifice 0.42 · attraction 0.41 |
| Concept 8 | 92 | 18.5% | 86% | −303cp | exposedKing 0.53 · pin 0.30 |

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
Real 2600+ players in the source games found these moves 47% of the time — roughly 18×
higher. Behaviour models capture pattern recognition, not calculation under a clock.

**Half-nameable.** Regressing the machine-unique direction onto twelve motif directions
built from tagged Lichess puzzles gives R² = 0.46 — a signature of sacrifice without a
combination to justify it. The other half is not expressible in known terms.

**The clusters are real but soft, and "eight" was a choice.** Silhouette beats a shuffled
null by ~9× at every k, but the margin is flat from k=3 to k=12 — no elbow, no natural
number of groups. k=6 is the most reproducible partition (bootstrap ARI 0.90 vs 0.80 at
k=8); k=8 is the arrangement whose groups predict human find-rate better than chance
(p = 0.009, where k=9 gives p = 0.063).

**Clustering discards most of the signal.** Predicting whether the player at the board
found the move (5-fold CV, 14.1% base rate):

| What the model sees | AUC |
|---|---|
| Random | 0.500 |
| Surface chess features (piece, phase, quiet, capture, check, cost) | 0.561 |
| Group label alone | 0.581 |
| Surface + group | 0.572 (**+0.011**) |
| Leela embedding, 40 PCs | 0.590 |
| **Surface + embedding** | **0.622 (+0.062)** |

The embedding carries real information about human difficulty that surface features do
not — and bucketing it into groups throws away about five-sixths of that. The structure
lives in continuous geometry, not in category membership. Full write-up in
[docs/FINDINGS_validation.md](docs/FINDINGS_validation.md).

So: the groups are a defensible **teaching partition**, not a discovery of discrete kinds.

---

## Built on

Schut et al., *Bridging the human–AI knowledge gap through concept discovery and transfer
in AlphaZero*, PNAS 2025 — which mined concepts from AlphaZero absent from human play and
taught them to four grandmasters using only example positions. This project reproduces the
idea on open models and at scale.

Stockfish 17.1 · Maia-2 / Maia-3 (CSSLab, Toronto) · Leela Chess Zero · Lichess open
database. Full citations in [BIBLIOGRAPHY.md](BIBLIOGRAPHY.md).
