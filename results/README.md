# Results

Committed here are the outputs the project's claims rest on:

- `master_machine_unique.csv` — the 1,745 machine-unique positions
- `hard_core.csv` — the 1,499 also missed by the player at the board
- `16_families.json` / `16_mu_families.csv` — the eight concept clusters and their signatures
- `07_composition.json` — motif regression (R² = 0.46)
- `01_frontier.csv`, `06_frontier_2600.csv` — human-visibility curves
- `experiment/` — the transfer-experiment manifests

Bulky intermediates (raw per-batch mining output, Leela embedding caches) are not
committed; re-generate them with `experiments/03_disagreement_mining.py` and
`experiments/16_concept_families.py`.
