# Research outputs

Current inventory, 7 September 2026. Different experiments use different subsets; do not infer sample sizes from the largest current CSV.

| Output | Scope |
|---|---|
| `master_machine_unique.csv` | 5,155 selected positions |
| `hard_core.csv` | 3,956 positions where the game move differs from the saved engine choice; not a move-quality label |
| `16_families.json`, `16_mu_families.csv` | Original 1,745-position grouping |
| `28_mu_assignments.csv` | 3,410 later assignments |
| `07_composition.json` | Historical 646-position motif reconstruction, 400 controls |
| `06_frontier_2600.csv` | 77 selected positions and 56 controls, each at five Maia-3 rating settings |
| `18_validation.json` | Exploratory grouping checks on the earlier embeddings |
| `19_embedding_value.json` | Historical weak-baseline comparison; superseded interpretation |
| `20_difficulty.json` | Historical embedding output plus current saved full-corpus difficulty metrics; see experiment 31 for corrected PCA evaluation |
| `26_why_invisible.json` | Feature associations, 18,296 positions; extreme-group classifier uses 7,853 |
| `30_research_audit.json` | Counts, game-bootstrap intervals, twelve threshold settings, depth-audit summary and input hashes |
| `30_engine_audit.json` | All 48 sampled positions, engine scores, searched lines, actual depths and settings |
| `31_embedding_audit.json` | PCA within training folds; no overwrite of existing trainer scores |
| `experiment/` | Older exploratory manifests and a single baseline response file, not a completed controlled learning study |

The full corpus, source archives and embedding caches are not committed. Their hashes in the new audit identify local inputs but do not make those inputs available from a fresh clone. See [methods](../docs/METHODS.md) for reconstruction steps and limitations.
