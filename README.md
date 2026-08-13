# unnamed-concepts

**Can machine-exclusive chess knowledge be extracted from open engines and taught to strong human players?**

AlphaZero-class engines hold concepts that exist beyond the human chess vocabulary — Schut et al. (PNAS 2025) proved they can be mined and taught to 2700-rated grandmasters using nothing but prototype positions. This project reproduces and extends that line of work on *open* models (Leela Chess Zero, Maia-2/3), aiming at three outputs:

1. **Research** — reproduce concept probing/discovery on open weights; measure the *legibility frontier* (at what human skill level does machine knowledge become invisible?)
2. **Practice material** — turn discovered concepts into prototype-position curricula for strong players (IM-level+), the way the paper taught its GMs
3. **A site** — publish discoveries + interactive practice sets (prototype exists: chess-book-style artifact page with steppable boards)

This is a research project, not a startup. The relevant precedent for *why* practice material: Southwick et al. 2026 (N=44k) — structured study beats raw play 3.6×/hour.

## Layout

```
papers/         6 core PDFs (Schut, McGrath, Jenner ×3, Maia-2)
models/
  maia2-repo/          CSSLab Maia-2 (skill-aware human move model, Elo 1100–2000)
  leela-interp/        Jenner NeurIPS 2024 code — Leela policy net in PyTorch
  stockfish-build/     Stockfish 17.1 built from source (src/stockfish works)
experiments/
  01_rating_frontier.py   Maia-2 sweep over the 4 Schut prototype positions
results/        experiment outputs (CSV)
site/           (later) the public face
notes/          working notes
BIBLIOGRAPHY.md annotated reading list
```

## Environment

```bash
conda activate unnamed-concepts   # python 3.12: maia2, torch, python-chess, pandas
python experiments/01_rating_frontier.py
```

## Roadmap & results so far

- [x] Papers, reference repos, engine build, envs (`unnamed-concepts` py3.12 for Maia; `leela` py3.11 for leela-interp)
- [x] **Exp 01 — legibility frontier v0** (4 Schut positions × Maia-2 1100–2000): AZ concept moves ≤7% at every level; 2/4 *decline* with skill. `results/01_frontier.csv`
- [x] **Exp 02/03 — scale** (final: **43,603 positions** — all 33.8k club + 10k elite × SF depth 16 × Maia): **1,745 machine-unique (4.0%** — rate identical across every batch and both rating populations). `results/master_all.csv`
- [x] **Exp 09 — hard core**: 1,499 of the 1,745 also defeated the *real* player at the board (318 from elite games; 247 failed by 2500+ movers) — `results/hard_core.csv`. Real 2600+ players find MU moves 47.3% (n=148) vs 59.5% on normal positions: the wall is real at every level, permeable at the top.
- [x] **Exp 05 — Schut LP on Leela latents** (30 positions, layer 10, pooled residuals): every LP solves sparse (6–16/768 nonzeros) but **0/30 generalize** (held-out separation ≈0.5). Consistent with the paper's 97.6% attrition — mining is easy, transfer is the bottleneck.
- [x] **Exp 05b — group mining**: one vector per group of 5 stacks constraints and separates its own group perfectly (in-group 1.00) but held-out ≈ 0.515 — still chance. Conclusion: the failure is the *representation* (mean-pooled residuals), not LP underdetermination.
- [x] **Exp 06 — frontier to 2600** (Maia-3, 77 MU + 60 control): control converges 46→68% top-1; machine-unique **0→2.6%** — invisibility holds at 2600. But top-5 rises 29→57%: strong players increasingly *consider* the move and still reject it. Blindness at low Elo becomes disbelief at high Elo. `results/06_frontier_2600.csv`
- [ ] Square-aware pooling (pool over the plan's from/to squares, not all 64) — the Leela-SAEs result says features are square-localized; mean-pooling likely destroys them
- [ ] Use pretrained Leela-SAEs transcoders (HF: JacklE0niden/lc0-BT4-tc) to describe machine-unique positions in *feature* space
- [ ] Teachability filter proper (student net on prototypes vs random-position control)
- [ ] **Site**: publish frontier + positions + concept galleries (formats prototyped: two artifact pages live)
- [ ] Maia-3 swap · sub-elite transfer study (the n=4-no-control gap)

## People / orbit

Lisa Schut (lead author: Oxford OATML PhD → DeepMind, ex-Dutch Olympiad player) · Been Kim (DeepMind) · CSSLab Toronto (Maia, Ashton Anderson) · Erik Jenner (Berkeley CHAI → ?, leela-interp). Contact with a concrete reproduction in hand, not before.
