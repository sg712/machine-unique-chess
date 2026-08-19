# Exp 20 — predicting human difficulty, and a correction to exp 19

## Summary

Exp 19 reported that Leela's internal representation predicts human difficulty
better than surface chess features (+0.062 AUC). That result is real but the
comparison was unfair: its baseline had no access to **Maia**, a neural network
trained specifically to predict human moves, and no access to the engine's own
evaluation.

Given a fair baseline, **the embedding adds nothing.** Not at 40 principal
components, not at 2. The information it carries about human difficulty is already
present in Maia's output plus the engine's evaluation.

The rest of the experiment is more useful than the correction: a calibrated model
that predicts how often a human of a given rating finds a given move, at
**AUC 0.849** over 43,603 positions.

---

## Part A — does the embedding survive a Maia control?

n = 1,745 machine-unique positions, 14.1% found by the player at the board.
5-fold cross-validation grouped by `game_id`, so positions from one game never
straddle the train/test split.

| What the model sees | AUC |
|---|---|
| Maia's probabilities alone | 0.581 ± 0.022 |
| Leela embedding alone (40 PCs) | 0.583 ± 0.052 |
| Surface chess features alone | 0.613 ± 0.047 |
| Engine evaluation alone | 0.636 ± 0.050 |
| Surface + engine | 0.633 ± 0.052 |
| Surface + engine + Maia | 0.648 ± 0.053 |
| Surface + engine + Maia + player rating | **0.724 ± 0.053** |
| ...+ Leela embedding | 0.683 ± 0.051 |

Adding the embedding to a proper baseline *costs* 0.041 AUC.

### Is that just overfitting?

40 extra features against 246 positive cases could lose on dimensionality alone,
which would be a fact about sample size rather than about the embedding. So the
width was swept:

| Principal components | Position-only baseline (0.648) | + player rating (0.724) |
|---|---|---|
| 2 | 0.642 (−0.005) | 0.722 (−0.001) |
| 5 | 0.637 (−0.011) | 0.714 (−0.010) |
| 10 | 0.631 (−0.017) | 0.707 (−0.017) |
| 20 | 0.622 (−0.025) | 0.699 (−0.025) |
| 40 | 0.608 (−0.040) | 0.683 (−0.041) |

Monotonic decline, and the best result at *any* width is −0.001 — indistinguishable
from adding nothing. This is not an overfitting artefact. The embedding is redundant
given Maia and the engine evaluation.

### Why exp 19 saw a gain

Exp 19's baseline was surface features only: piece, phase, quiet, capture, check,
cost. Against that weak baseline the embedding genuinely helped (+0.062). But
"beats a baseline that doesn't know what the engine thinks or what humans play" is a
much smaller claim than it appeared to be. Both facts are true; only the second one
is interesting, and it is negative.

**What this does not overturn:** exp 18 stands unchanged — the clusters still beat a
shuffled null by ~9×, k is still underdetermined, and the k=8 external-validity
result (p = 0.009) is untouched. What falls is exp 19's interpretation that the
embedding carries *unique* information about human difficulty.

---

## Part B — the difficulty model

n = 43,603 positions (every position mined, not only the machine-unique ones),
43.3% found by the player at the board. Gradient boosting, grouped 5-fold CV.

| What the model sees | AUC |
|---|---|
| Surface chess features | 0.688 ± 0.018 |
| Maia's probabilities | 0.835 ± 0.024 |
| Surface + engine evaluation | 0.806 ± 0.018 |
| **Everything cheap to compute** | **0.849 ± 0.018** |

Maia alone does most of the work, which is unsurprising — it is trained for exactly
this. Surface and engine features add 0.014 on top.

Brier score **0.158**, against 0.246 for always predicting the base rate. The model
is close to calibrated, drifting slightly overconfident in the middle deciles:

| Predicted | Actual |
|---|---|
| 4.3% | 4.1% |
| 10.9% | 9.8% |
| 17.9% | 17.5% |
| 26.6% | 24.3% |
| 36.3% | 33.8% |
| 46.7% | 44.3% |
| 58.7% | 54.4% |
| 72.4% | 67.6% |
| 84.6% | 80.5% |
| 96.5% | 96.7% |

On the machine-unique subset the model predicts a 17.7% find-rate where the true
rate is 14.1% — so even a model built to detect difficulty **underestimates how hard
these positions are.** That is a small independent corroboration that the
machine-unique set is genuinely unusual rather than just the tail of a smooth
distribution.

---

## Part C — what the trainer now shows

The CV model uses the original player's rating, which is meaningless for someone
using the trainer. So the model is refit on everything and asked a counterfactual
instead: *how often would a 1900-rated player find this move?* — matching the rating
band the trainer already quotes in its feedback.

All 128 trainer positions scored:

| Group | Predicted at 1900 | Observed over the board (all ratings) |
|---|---|---|
| Concept 1 | 10.9% | 16.7% |
| Concept 2 | 7.5% | 7.8% |
| Concept 3 | 9.2% | 15.0% |
| Concept 4 | 6.7% | 9.7% |
| Concept 5 | 14.6% | 19.0% |
| Concept 6 | 9.6% | 18.0% |
| Concept 7 | 10.0% | 10.2% |
| Concept 8 | 11.6% | 18.5% |

Predictions sit below the observed rates because the observed pool includes players
well above 1900, including the 247 positions where a 2500+ player was at the board.

---

## What this means for the project

The honest position after exps 18–20:

1. There is a real, reproducible set of positions where engines and humans part
   company, and it is not an artefact — 4.0% of mined positions, stable across
   batches and rating pools.
2. Those positions have measurable structure in Leela's representation space, about
   9× a shuffled null — but soft, with no natural number of groups.
3. That structure is a reasonable basis for **grouping positions to teach from**.
4. It is **not** a source of information about human difficulty beyond what Maia and
   the engine already give you.

Claim 4 is the one that changed. The trainer's justification rests on 1–3, which
survive. What does not survive is any suggestion that the embedding is a privileged
window into what humans cannot see.
