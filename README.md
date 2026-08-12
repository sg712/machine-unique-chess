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

## Roadmap

- [x] Papers, reference repos, engine build, env
- [ ] **Exp 01 — legibility frontier v0**: P(AZ concept move) vs P(GM move) across Maia-2 Elo 1100–2000 on the 4 paper positions. Prediction: AZ moves flat-low at every human level (that's what "machine-unique" means); GM moves rise with Elo.
- [ ] **Exp 02 — scale it**: same sweep over a large corpus of engine-vs-human disagreement positions (generate via Stockfish/Leela top moves that Maia never plays at any Elo) → the frontier *curve*, not 4 anecdotes. Candidate first real result.
- [ ] **Exp 03 — reproduce concept probing** on Leela latents using `leela-interp` machinery (McGrath-style human-concept probes first, then Schut's convex-optimization mining §4.1 — dynamic concepts over rollouts).
- [ ] **Exp 04 — curriculum generation**: for a discovered concept vector, retrieve maximally-expressing prototype positions (the paper's teachability filter, §4.2) → practice sets.
- [ ] **Site**: publish frontier curves + practice sets; steppable-board format already prototyped.
- [ ] Swap Maia-2 → Maia-3 (released 2026, CSSLab recommends; HF: UofTCSSLab/maia3).
- [ ] (Stretch) Sub-elite transfer study — the paper's n=4-no-control gap, run at club level online.

## People / orbit

Lisa Schut (lead author: Oxford OATML PhD → DeepMind, ex-Dutch Olympiad player) · Been Kim (DeepMind) · CSSLab Toronto (Maia, Ashton Anderson) · Erik Jenner (Berkeley CHAI → ?, leela-interp). Contact with a concrete reproduction in hand, not before.
