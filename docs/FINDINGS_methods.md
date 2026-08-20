# Exps 26–27 — other methods for finding the pattern, and what they converge on

Everything before this asked "where do engines and humans part company" through one
lens: cluster the engine's internal representations. These two experiments ask the
same question through four more methods with different assumptions. They converge
on a single reframing.

## Exp 26 — the contrast study, in plain chess language

Two groups with **identical stakes** — in both, the engine's move is ≥100cp better
than the human favourite. They differ only in visibility: *invisible* = Maia gives
the move ≤5% at every rating (n=4,257; real players found 18%); *visible* = Maia
gives it ≥30% (n=2,287; real players found 60%). 8,674 in-betweens serve as a
dose-response check. Every position gets 30 boolean, human-readable features of
the engine's move.

**Invisibility is predictable from plain chess descriptors alone: AUC 0.852**
(grouped 5-fold). No neural network needed — surface "looks-wrongness" carries
most of the signal.

What makes a decisive move invisible (share of group, invisible / mid / visible —
nearly all trends monotone across the spectrum):

| Feature | Invisible | Mid | Visible | Ratio |
|---|---|---|---|---|
| offers material for nothing visible | 20.7% | 9.5% | 5.4% | **3.9×** |
| quiet (no capture, no check) | 86.6% | 79.6% | 49.1% | 1.8× |
| deep retreat (≥2 ranks) | 7.8% | 6.0% | 4.7% | 1.7× |
| sideways move | 21.4% | 17.5% | 13.5% | 1.6× |
| toward the board edge | 39.2% | 30.9% | 26.1% | 1.5× |

And the mirror — what makes it visible:

| Feature | Invisible | Mid | Visible | Ratio |
|---|---|---|---|---|
| is a capture | 11.3% | 16.4% | 43.6% | **0.26** |
| gives check | 4.2% | 5.6% | 11.1% | 0.38 |
| escapes an attacked square | 10.5% | 17.7% | 26.5% | 0.40 |
| creates an immediate threat | 24.7% | 34.7% | 38.8% | 0.64 |
| moves toward the enemy king | 52.7% | 59.0% | 64.6% | 0.81 |

The depth-3 decision tree says it in three rules: a quiet move that neither
escapes anything nor threatens anything is invisible (86% of that leaf); a
non-quiet move that offers material without giving check is invisible (90%); a
king escaping an attack is visible.

Within the invisible group, the moves real players *still* find most often are —
again — the forcing ones: checks 32%, captures 26%, versus deep retreats 13% and
quiet moves 17%.

**Reading:** the machine-unique set is, to first order, the set of moves that
violate the heuristics humans use to order their search — look at forcing moves
first, don't hang material, answer threats, activity toward the king. The engine
has no search-order prior to violate.

## Exp 27 — the same embeddings under four other unsupervised lenses

On the cached Leela layer-10 embeddings of the 1,745 machine-unique positions:

- **HDBSCAN** (density-based, allowed to answer "no cluster"): labels **74–83% of
  positions as noise**. The 2–3 dense cores it does find agree with k-means
  (ARI 0.75 on the non-noise subset) — the k-means clusters have small dense
  cores surrounded by diffuse mass.
- **Gaussian mixture BIC**: improves monotonically to k=12 with no minimum — a
  second, independent "k is underdetermined".
- **Agglomerative at k=8**: same silhouette as k-means (0.065) but only ARI 0.36
  agreement with it — two reasonable methods at the same k carve the space
  differently, which natural kinds would not allow.
- **Sparse dictionary learning** (32 atoms over MU + control positions): the
  MU-enriched atoms fire 2–6× more often on machine-unique positions and lean
  sacrifice/clearance — consistent with the motif regression (R² = 0.46), and
  again: interpretable ingredients, no sharp categories.

## The synthesis

Four methods, one picture:

1. "Machine-unique" is mostly **anti-heuristic move choice**, predictable from
   plain chess features (0.852 AUC) — it lives at the level of *how humans order
   their search*, not hidden positional archetypes.
2. The embedding space is a **continuum with small dense cores** — every lens
   that could say "soft" said soft; the parts that are nameable are the
   sacrifice/clearance flavours we already knew about.
3. This explains two earlier results at once: why clustering was weak
   (exp 18 — the phenomenon isn't clustered), and why the embedding added
   nothing over Maia + engine features for difficulty (exp 20 — the signal is
   surface-visible).
