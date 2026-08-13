# Methods & Data Provenance — unnamed-concepts

*Everything we did, where every byte came from, and what was done to it. As of 2026-08-13.*

## The question

Superhuman chess engines hold knowledge that human players don't. Schut et al. (PNAS 2025) proved some of it can be extracted from AlphaZero and taught to grandmasters. AlphaZero is closed. **Can the same phenomena be found, measured, and eventually taught using only open models — on a laptop?**

---

## Data sources (external, all public)

| Source | What | URL | Used in |
|---|---|---|---|
| Lichess open database | Full monthly PGN archives of rated games (~30 GB/mo compressed) | database.lichess.org/standard/ | Exp 02 |
| Lichess Elite database (nikonoel) | Monthly PGNs filtered to 2500+ vs 2300+ rated players | database.nikonoel.fr | Exp 02b |
| Lichess puzzle database | 4M+ puzzles, each tagged with motif themes (pin, fork, …) | database.lichess.org/lichess_db_puzzle.csv.zst | Exp 07 |
| Schut et al. paper | 4 concept-prototype positions, transcribed by hand from Figs 8/10/14 (verified: FEN → legal-move check against the paper's lines) | arXiv:2310.16410 | Exp 01, 06 |
| Stockfish 17.1 | Compiled from the source tree already on this machine (`make ARCH=apple-silicon`) — no quarantined binaries | github.com/official-stockfish | Exp 03+ |
| Maia-2 | Skill-conditioned human-move model, Elo 1100–2000, rapid weights | pip `maia2`, weights auto-fetched (CSSLab) | Exp 01, 03 |
| Maia-3 (Chessformer) | Successor; skill conditioning is continuous, trained through 2600+ | github.com/CSSLab/maia3 + HF `UofTCSSLab` | Exp 06 |
| Leela Chess Zero "LD2" | Open AZ-style network converted to PyTorch by the leela-interp authors (~361 MB, `lc0.onnx`; manual browser download — figshare blocks CLI) | github.com/HumanCompatibleAI/leela-interp | Exp 05, 07, 08 |
| BT4 network + transcoders | Bigger Leela + pretrained sparse-feature dictionaries (layers 9–11) | storage.lczero.org + HF `JacklE0niden/lc0-BT4-tc` | downloaded, not yet used |

Everything generated from these lives in `data/` (position samples) and `results/` (experiment outputs). Nothing external was modified; nothing private was used.

## Environments

- `unnamed-concepts` (conda, py3.12): maia2, torch 2.8, python-chess, pandas — Maia + Stockfish experiments
- `leela` (conda, py3.11): leela-interp editable install (zarr<3 pinned; two upstream import bugs patched in our clone), scipy, scikit-learn — Leela latent experiments
- Stockfish runs as a subprocess (UCI) from either env

---

## Pipeline, experiment by experiment

### Exp 01 — Do simulated humans find AlphaZero's concept moves? (`01_rating_frontier.py`)
**In:** 4 hand-transcribed Schut positions. **Do:** Maia-2 `inference_each(fen, elo, elo)` for Elo 1100→2000 in steps of 100; record probability of the AZ move and the GM's move. **Out:** `results/01_frontier.csv`. **Result:** AZ moves ≤7% at every level; 2 of 4 *fall* as skill rises. **Caveat:** playing-probability ≠ understanding; 4 positions.

### Exp 02/02b — Position corpora from real games (`02_build_dataset.py`, `02b_elite_dataset.py`)
**In:** lichess monthly archive (streamed+decompressed on the fly, never fully downloaded); elite monthly zip. **Do:** keep rapid/classical games, both players ≥1800 (club) / elite file as-is (2500+); sample every 4th ply between plies 14–70. **Out:** `data/positions.csv` (33,808 rows from 3,000 club games), `data/positions_elite.csv` (31,065 rows from 2,500 elite games). Each row: FEN, the move the human actually played, both Elos.

### Exp 03 — Machine-unique mining (`03_disagreement_mining.py`)
**In:** the corpora above. **Do:** per position — Stockfish depth 16 multipv 2 (best move, margin); Maia-2 P(best move) at Elo {1100,1400,1700,2000}; Stockfish eval of the human-favourite move (`root_moves` restricted search) → `human_cost_cp`. **Definition:** position is **machine-unique** iff `human_cost_cp ≥ 100` *and* `max_elo P(engine move) ≤ 0.05`. **Out:** `results/03_disagreements.csv` (+`_b2`, `_elite`), merged into `results/master_all.csv` (16,474 analysed) and `results/master_machine_unique.csv` (**646 positions, 3.9% — rate identical in club and elite games**). **Caveats:** depth-16 truth; the 5%/100cp thresholds are choices (sensitivity unchecked); Maia-2 caps at 2000.

### Real-player check (inline analysis, no script file)
**Do:** join mined positions back to the games they came from; did the actual human play the engine move? **Result:** club players 7.8% on machine-unique vs ~45% baseline; elite 2500+ players **29.5%** (2600+: 16/34 = 47%) vs 51% baseline. **Finding:** real masters recover roughly a third to half of "machine-only" moves that simulated masters (Maia-3 2600: 2.6%) do not — the simulation-reality gap we call the *calculation gap*; the ~70% they still miss is the hard core.

### Exp 06 — Frontier to 2600 (`06_frontier_2600.py`)
**In:** 77 club machine-unique + 60 control positions. **Do:** Maia-3 (79M, CPU) top-1/top-5 at Elo {1100,1500,2000,2300,2600}. **Out:** `results/06_frontier_2600.csv`. **Result:** control top-1 rises 46→68%; machine-unique 0→2.6%. Top-5 rises 29→57% — *strong simulated players increasingly consider the move and still reject it.* **Caveat:** simulated; selection used Maia-2 (bands >2000 are out-of-sample though).

### Exp 05/05b — Schut's convex optimization on Leela (`05_leela_concepts.py`, `05b_group_mining.py`, `src/concept_mining.py`)
**In:** 30 highest-cost machine-unique positions. **Do:** for each — Leela policy rollouts (top move line = chosen, 2nd/3rd move lines = subpar, 6 plies); embed every state (layer-10 residual stream, mean-pooled over 64 squares → 768-d); solve the paper's LP `min ‖v‖₁ s.t. v·z⁺ₜ ≥ v·z⁻ₜ + 1` (scipy linprog, split-variable L1; **verified by planting a synthetic concept and recovering it**). Filter: does v separate chosen/subpar on *held-out* positions? **Result:** every LP solves sparse (6–16 active dims); **0/30 generalize** (≈0.5 = chance); grouping 5 positions per LP → in-group 1.00, held-out 0.515. **Reading:** consistent with the paper's 97.6% attrition; with our substitutions the bottleneck is the pooled representation, not the optimizer. **Deviations from the paper:** Leela policy rollouts instead of AZ MCTS; pooled residuals instead of AZ's internal planes; our generalization proxy instead of their student-network teachability filter.

### Exp 07 — Composition test (`07_composition.py`)
**In:** 12 motif direction-vectors (each = mean Leela embedding of ~150 lichess-puzzle positions tagged with that theme, minus puzzle baseline mean); the 646 machine-unique + 400 control embeddings. **Do:** least-squares reconstruction of the machine-unique mean direction from the motif basis; per-position R² for calibration. **Out:** `results/07_composition.json`. **Result:** global **R² = 0.46**, signature ≈ *+sacrifice +pin +exposedKing −clearance −fork −deflection*; per-position R² ≈ control (0.20 vs 0.18) — the instrument resolves populations, not individual positions. **Reading:** machine-unique play is roughly half-composable from named human motifs ("unnamed chunks"), half off-vocabulary.

### Exp 08 — Pattern families (`08_cluster_families.py`)
**In:** the 646 embeddings + motif basis + game metadata. **Do:** k-means (k=8, cosine-normalized); per family: quiet-move share, piece/phase mix, nearest motifs, real-found rate; render board gallery. **Out:** `results/08_families.json`, `families.html` (published artifact). **Headlines:** 72–92% of machine-unique moves are **quiet** (no capture, no check); family 5 (endgame king-safety, 20.5% real-found) is the most teachable candidate; family 7 (n=46) is near-orthogonal to *every* named motif — the concentrated alien residue.

---

## Known limitations (the honest list)

1. Stockfish depth 16 as ground truth (not exhaustive); thresholds 100cp/5% untested for sensitivity.
2. Maia models blitz/rapid *recognition*, not calculation — hence the simulation-reality gap at 2600.
3. Mean-pooled residuals lose square-local structure (probable cause of Exp 05's transfer failure).
4. Position-level composition claims are beyond this instrument; only population-level claims made.
5. No causal evidence yet — everything so far is correlational. (Next: activation patching, transcoder features.)
6. Elite band n is small (34 positions for 2600+ movers).

## Reproduce

```
conda activate unnamed-concepts
python experiments/02_build_dataset.py --games 3000 --min-elo 1800
python experiments/03_disagreement_mining.py --limit 2000
conda activate leela
python experiments/07_composition.py && python experiments/08_cluster_families.py
```

Repo: `~/Desktop/Projects/unnamed-concepts` (git, 12 commits). Artifacts: Schut positions (steppable), machine-unique gallery, pattern families.
