# Validation: are the concepts real?

Experiments 18 and 19 test the framing the rest of the project rests on. The
short answer: **the structure is real, the discrete "eight concepts" framing was
not justified, and the embedding carries information that surface chess features
do not.**

## 1. Is there cluster structure? (exp 18)

Silhouette across k = 2..16, against a null built by shuffling each embedding
dimension independently (destroys structure, preserves the marginal spectrum):

| | value |
|---|---|
| Silhouette at k=8, real | 0.0715 |
| Silhouette at k=8, null | 0.0078 |
| Ratio | **9.2×** |

Structure exists — real embeddings separate roughly nine times better than a
structureless cloud of the same shape. But **0.07 is a weak silhouette in
absolute terms.** These are diffuse regions in a continuous space, not
well-separated natural kinds.

**The number of groups is underdetermined.** The margin over null is essentially
flat from k=3 (+0.061) to k=12 (+0.063), peaking at k=9 (+0.065). No elbow. Any
k in that range is about equally defensible; k=8 was arbitrary and remains
arbitrary.

**Stability (bootstrap ARI over 80% resamples):** k=6 is the most reproducible
partition (0.904 ± 0.029), k=8 next (0.800 ± 0.147), k=4 unstable (0.510 ± 0.199).

**External validity:** at k=8, cluster membership predicts how often real players
found the move better than random groupings of the same sizes (permutation
p = 0.009). At k=9 it does not (p = 0.063). So k=8 survives on this criterion —
by luck rather than by design.

## 2. Does the embedding beat surface features? (exp 19)

Predicting whether the player at the board found the move (14.1% base rate),
5-fold cross-validated ROC AUC:

| Predictor | AUC |
|---|---|
| Random baseline | 0.500 |
| Surface chess features (piece, quiet, phase, capture, check, cost) | 0.561 |
| Cluster label alone (k=4) | 0.581 |
| Surface + cluster label | 0.572 (+0.011) |
| **Leela embedding, 40 PCs** | **0.590** |
| **Surface + embedding** | **0.622 (+0.062)** |

Two things follow.

**The embedding carries real signal beyond surface features.** Adding 40
principal components of the Leela representation lifts AUC by +0.062 over what
piece/quiet/phase/cost can do alone — roughly a fifth of the distance from the
surface baseline to perfect prediction. The engine's internal representation
knows something about human difficulty that the obvious features do not.

**Clustering throws most of that signal away.** Discretising into k groups
recovers at best +0.011 of the +0.062. The information is in the continuous
geometry, not in which bucket a position lands in.

## 3. What this means for the framing

- "Eight concepts" overstates the case. The honest description is *a continuous
  space of engine-human disagreement, with measurable but soft regions.*
- The clusters remain useful as a **teaching partition** — they group similar
  positions so a learner sees related examples together, and they do predict
  human failure better than chance. That is a pedagogical justification, not a
  claim about natural kinds.
- All absolute effects are modest. AUC 0.62 means the model is meaningfully but
  not dramatically better than guessing.

## Reproduce

```bash
python experiments/18_cluster_validation.py     # structure, k, stability
python experiments/19_does_embedding_matter.py  # embedding vs surface features
```
