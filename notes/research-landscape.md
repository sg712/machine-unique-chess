# Where chess-engine interpretability actually stands (Aug 2026)

Written while building this project. The short version: **the field moved past the Schut method.**
Their convex-optimization concept mining (2023) predates the sparse-dictionary wave. For our
purposes the two approaches answer different questions and we should use both.

## Two families of method

### 1. Contrastive concept vectors — Schut et al. (PNAS 2025)
Find a sparse direction `v` separating the engine's chosen line from its rejected lines:

    min ||v||₁   s.t.   v·z⁺_t ≥ v·z⁻_t,j    ∀ t ≤ T, j ≤ T̃

Reimplemented in `src/concept_mining.py`, verified on planted ground truth (cos 0.907, 4/64 nonzeros).

- **Strength:** concepts are *dynamic* — defined over MCTS rollouts, so they describe plans, not
  snapshots. That is exactly why the taught concepts were things like "provoke h6 now, sacrifice
  the queen eight moves later." No dictionary method currently captures that.
- **Weakness:** needs MCTS rollout statistics (visit counts, value estimates) and the engine's
  latents. Leela + a search wrapper can provide both, but it's real engineering.
- **Their filters matter as much as the mining:** teachability (train a student net on prototypes,
  require it to beat a random-position control) killed 97.6% of candidates; novelty (concept better
  reconstructed in the engine's basis than a human-game basis) killed another 27%. **2.4% survived.**
  Any reproduction that skips the filters will produce mostly garbage vectors.

### 2. Sparse dictionaries — the 2024–26 wave
Train an overcomplete sparse decomposition of activations; each learned feature is a candidate concept.

- **Karvonen (2024)** — SAEs on a chess-playing LLM recover board state (piece locations) with high
  fidelity; also gave the field its board-game benchmark for dictionary quality (arXiv 2408.00113).
- **"Tracing the Thought of a Grandmaster-level Chess Transformer" (arXiv 2604.10158)** — the one to
  study. Applies **transcoders** (MLP) + **Lorsa** (low-rank sparse attention) to **Leela BT4**;
  claims the first sparse decomposition of a *full* transformer. Features are square-localized:
  "bishop-reach squares", "opponent rook rank-wise defensive coverage" (99.3% precision). Human raters
  scored feature consistency 4.15/5.
  **Pretrained weights are public** — HF `JacklE0niden/lc0-BT4-tc` and `lc0-BT4-lorsa`, code at
  `github.com/JacklE0niden/Leela-SAEs` (cloned to `models/leela-saes/`), plus a feature-browser UI.
  Their causal demo is the template for ours: ablating a pawn-detection feature on g2 moved LC0 from
  28.8% → 90.6% on a mate line — i.e. a *false defensive assessment* was suppressing the tactic.
- **Caveats from the same literature:** "Are Sparse Autoencoders Useful?" (2502.16681) finds SAEs
  often fail to beat plain sparse probing; "Transcoders Beat SAEs" (2501.18823) is why the above uses
  transcoders. Don't assume dictionary features are automatically the right unit.

### 3. Mechanism, not concepts — the look-ahead line
Jenner et al. (NeurIPS 2024) show Leela represents *future* moves that causally drive the current
one, concentrated in **L12H12**; follow-ups (2505.21552, 2508.21380) map when it calculates vs when
learned priors override. Relevant to us because a "concept" that is really just look-ahead is not a
teachable idea — it's search. Worth controlling for.

## What this means for our plan

1. **Don't start with the convex optimization.** Start with the *positions*: mine engine/human
   disagreements at scale (exp 03) to find where machine knowledge is invisible. That works with
   Stockfish + Maia alone, no latents needed, and produces the dataset every later method consumes.
2. **Then use the existing sparse dictionaries** (Leela-SAEs pretrained transcoders) to ask: *which
   features fire on machine-unique positions but not on human-legible ones?* That's a cheap, direct
   shot at "what is the engine seeing that we aren't," and it reuses someone else's expensive training.
3. **Keep the Schut LP for the dynamic case** — the plan-shaped concepts nobody else captures. Run it
   on Leela residuals along engine PVs vs rejected lines. This is where a genuinely novel result lives,
   because the 2604.10158 line is static/square-localized by construction.
4. **The teachability filter is the product.** It's also the bridge to the practice-material half:
   a concept that survives "train a student on prototypes, measure improvement on held-out positions"
   is, by definition, a concept that can be taught to a human the same way.

## Practical blockers found
- `leela-interp` weights are ONNX on **figshare behind AWS WAF** — scripted download 403s; needs a
  manual browser click (`lc0.onnx`, 361 MB). Leela-SAEs instead uses BT4 from lczero.org, no WAF.
- `leela-interp` pins **nnsight 0.2** and needs Python 3.10/3.11 (our env is 3.12) — separate venv.
- **MPS produces NaNs** in Leela per the repo's own README. CPU only for that stack.
- Probing all 15 layers wants ~70 GB RAM unless activations spill to zarr on disk.
