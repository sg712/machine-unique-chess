# machine-unique chess

**Finding chess positions where a strong engine is decisively right and essentially
no human plays the move — then turning them into something you can train on.**

Across 43,603 positions from real games, 4.0% contain a move that Stockfish rates
clearly best and that a neural model of human play gives under 5% probability at
*every* rating from 1100 to 2600. In 1,499 of those, the player actually at the board
missed it too; in 247, that player was rated 2500 or above.

Clustering those positions by how an engine represents them internally produces eight
groups. One of them has zero or negative similarity to every named chess motif — a
coherent pattern that human chess vocabulary has no word for.

The trainer teaches all eight, by example.

---

## What's here

```
experiments/     the pipeline, numbered in the order it was built
webapp/          the trainer (Flask + SQLite)
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
| `16_concept_families.py` | Embeds positions with Leela Chess Zero, clusters into concepts |
| `17_build_concepts.py` | Engine lines + human move distributions for each concept |

Everything ran on one laptop.

### The trainer

```bash
bash scripts/setup.sh          # only needed to re-run the pipeline
pip install flask python-chess
python webapp/app.py           # http://127.0.0.1:5055
```

Eight concepts. Each opens with four study positions showing the engine's move and
what follows — deliberately without commentary, since the patterns are easier absorbed
than described — then twelve unseen positions to drill. Feedback names your move, tells
you what share of 1900-rated humans play it, and steps through the engine's line.

The app serves precomputed positions from `webapp/concepts.json`; no engine runs per
request, which keeps it fast and deterministic.

---

## The eight concepts

| Concept | Positions | Found over the board | Character |
|---|---|---|---|
| The unpaid sacrifice | 204 | 7.8% | Material goes, no combination follows. Costs the average human 505cp |
| Against the book | 145 | 9.7% | Opening positions where the engine disagrees with theory |
| The long fuse | 295 | 10.2% | Middlegame setups whose payoff is too distant to connect |
| Order of operations | 339 | 15.0% | Right ideas, order nobody considers |
| The heavy-piece pause | 287 | 16.7% | Queens and rooks improving without threatening |
| Nothing happens | 278 | 18.0% | 94% quiet; positions that look settled and aren't |
| Walking into the fire | 92 | 18.5% | Opening lines toward a king, usually its own |
| **The one with no name** | 105 | 19.0% | **Matches no named motif — cosine ≤ 0 to all twelve** |

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

---

## Built on

Schut et al., *Bridging the human–AI knowledge gap through concept discovery and transfer
in AlphaZero*, PNAS 2025 — which mined concepts from AlphaZero absent from human play and
taught them to four grandmasters using only example positions. This project reproduces the
idea on open models and at scale.

Stockfish 17.1 · Maia-2 / Maia-3 (CSSLab, Toronto) · Leela Chess Zero · Lichess open
database. Full citations in [BIBLIOGRAPHY.md](BIBLIOGRAPHY.md).
