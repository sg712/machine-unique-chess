# Machine Unique Chess

[Live trainer](https://www.machine-unique-chess.com/) · [Research](https://www.machine-unique-chess.com/research) · [Methods](docs/METHODS.md) · [Study protocol](docs/LEARNING_STUDY.md)

Practice engine moves that a model of human play assigns low probability. The project combines Stockfish, Maia and Leela to select positions, examine their structure, and organize examples into eight groups. Learning effectiveness and the discovery of new chess concepts have not been established.

## Current evidence

Across 123,405 sampled positions, 5,155 meet the operational filter: the Stockfish depth-16 move scores at least 100cp above Maia-2's favourite at 2000, and Maia-2 assigns that move at most 5% probability at each of 1100, 1400, 1700 and 2000. A separate Maia-3 ranking experiment covers 77 selected positions and 56 controls through 2600.

The actual player chose the exact engine move in 1,199 selected positions; the other 3,956 are nonmatches, not necessarily errors. In 2,034 positions, the saved runner-up is less than 20cp behind. The trainer has an additional curation filter: depth 18, retained top move, at least 70cp above the runner-up when built.

New checks, 7 September 2026:

- **Depth audit:** 48 sampled positions from different games, eight per rating band. Every search reached depth 20; 35 retained the original first move. In 44 cases without mate scores, 42 retained the 100cp gap against Maia's favourite. This is a small stratified audit, not a full remine.
- **Threshold sensitivity:** twelve probability/gap settings select 755–14,584 positions from the same saved corpus. The 4.18% headline describes one setting.
- **Predictive audit:** PCA now fits inside each training fold. On 1,745 positions, the full rating-aware baseline scores AUC 0.755; adding 40 Leela components gives 0.732. No tested width improves this baseline; this does not prove representational redundancy.
- **Worked examples:** three depth-20 illustrations with both engine and Maia-favourite continuations, each paired with a position from a different game.
- **Learning:** a controlled 24-person feasibility pilot is specified, but participant collection and verified private study materials are still pending.

The eight groups are an exploratory practice organization. The 12-motif reconstruction does not establish that residual variance represents unknown chess concepts. Sparse-direction extraction did not generalize in the earlier 30-fit experiment. See [grouping findings](docs/FINDINGS_validation.md), [feature associations](docs/FINDINGS_methods.md), and [difficulty evaluation](docs/FINDINGS_difficulty.md).

## Run the trainer

```sh
python -m pip install -r requirements.txt
python webapp/app.py
```

All 32 study examples have authored explanations, a replay of Maia’s preferred alternative, and checked tactical branches where needed. These notes live in `webapp/study_notes.json` with Stockfish search records; tests verify their position mapping and legal lines. The September 2026 review retired one unstable study answer and replaced it with an unused position from the same source group (see `results/34_study_corrections.json`). All 288 drill slots retain their original indices. These teaching checks are separate from the random research audit and are not evidence of learning gains.

The Flask application serves precomputed data, with no engine or neural inference per request. Without `DATABASE_URL` it uses local SQLite; production uses Neon Postgres and a configured `SECRET_KEY`. See [webapp/README.md](webapp/README.md).

## Reproduce the research

Experiments and inputs are documented in [docs/METHODS.md](docs/METHODS.md). Large source archives, `master_all.csv`, model weights and embedding caches are omitted from Git. A fresh clone can inspect the committed audit outputs and run the trainer; reproducing the analyses requires the exact omitted inputs or their reconstruction. Audit files record input hashes, random seeds, engine settings and per-position results.

```sh
python experiments/30_research_audit.py
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python experiments/31_embedding_audit.py
python experiments/32_research_examples.py
python scripts/render_research_notes.py
```

The research runtime needs additional packages and downloaded engines; the site requirements alone are insufficient. Summaries are generated from saved JSON to reduce stale numbers. Historical output files remain available and are explicitly distinguished from current reruns.

## Checks and deployment

See [tests/README.md](tests/README.md) for isolated Python and DOM checks. Production deploys through Vercel's Git integration on pushes to main. Automated route/DOM checks do not constitute live-browser visual verification.

## Foundations

[Schut et al.](https://arxiv.org/abs/2310.16410) report concept-prototype learning among four grandmasters using AlphaZero. This project adapts the motivation with open models; it has not replicated that human learning result. [Bibliography](BIBLIOGRAPHY.md).
