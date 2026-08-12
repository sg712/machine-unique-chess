"""Schut et al. (PNAS 2025) concept mining — reimplemented, §4.1–4.2.

The paper's core object is a *concept vector* v: a sparse direction in a network's
latent space that separates what the engine does from what it declines to do.

Static concepts (§4.1.1) come from single positions; dynamic concepts (§4.1.2, the
ones actually taught to the grandmasters) come from contrasting the chosen MCTS
rollout against subpar rollouts, so the vector describes a *plan*, not a snapshot.

    minimise   ||v||_1
    such that  v · z⁺_t  >=  v · z⁻_t,j     for all t <= T, j <= T̃          (eq. 5)

L1 keeps it sparse and therefore interpretable; the constraints say the concept
must score every step of the good line above every step of every bad line. This is
a linear program, solved here with scipy.optimize.linprog (HiGHS) — no dependency
on the closed AlphaZero stack.

Then §4.2's filters:
  * teachability — a student trained on the concept's prototypes must beat a student
    trained on random positions (the paper discarded 97.6% of candidates here)
  * novelty      — the vector must be better expressed in the engine's own latent
    basis than in one built from human games (a further 27.1% discarded)
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog


def mine_concept(z_pos: np.ndarray, z_neg: np.ndarray, margin: float = 1.0,
                 slack_penalty: float = 10.0) -> tuple[np.ndarray, float]:
    """Solve eq. 5 for one (positive rollout, negative rollouts) pair.

    z_pos: (T, d)      activations along the chosen rollout
    z_neg: (T', d)     activations along subpar rollouts (all j stacked)
    Returns (v, infeasibility) where v is the L1-minimal concept vector.

    Formulated with soft constraints (slack) so a single noisy step cannot make the
    program infeasible — the paper's constraints are hard, but real activations from
    an open engine are noisier than AZ's curated rollouts.

    Variables: [v_plus (d), v_minus (d), slack (n_constraints)], all >= 0,
    with v = v_plus - v_minus so that ||v||_1 = sum(v_plus + v_minus) stays linear.
    """
    z_pos = np.atleast_2d(z_pos).astype(np.float64)
    z_neg = np.atleast_2d(z_neg).astype(np.float64)
    d = z_pos.shape[1]
    if z_neg.shape[1] != d:
        raise ValueError(f"dim mismatch: positive {d}, negative {z_neg.shape[1]}")

    # one constraint per (positive step, negative step) pair
    diffs = (z_pos[:, None, :] - z_neg[None, :, :]).reshape(-1, d)  # (T*T', d)
    n = diffs.shape[0]

    # minimise ||v||_1 + penalty * sum(slack)
    c = np.concatenate([np.ones(2 * d), slack_penalty * np.ones(n)])

    # -(diff·v) - slack <= -margin   i.e.   diff·v + slack >= margin
    A_ub = np.hstack([-diffs, diffs, -np.eye(n)])
    b_ub = np.full(n, -margin)

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=[(0, None)] * (2 * d + n), method="highs")
    if not res.success:
        raise RuntimeError(f"LP failed: {res.message}")

    v = res.x[:d] - res.x[d:2 * d]
    infeasibility = float(res.x[2 * d:].sum())
    return v, infeasibility


def concept_score(v: np.ndarray, activations: np.ndarray) -> np.ndarray:
    """c(x) = v · f_l(x) — how strongly each position expresses the concept (§4.2.1)."""
    return np.atleast_2d(activations) @ v


def select_prototypes(v: np.ndarray, activations: np.ndarray, pct: float = 2.5) -> np.ndarray:
    """Return indices of the top `pct`% positions by concept score — the curriculum."""
    scores = concept_score(v, activations)
    cutoff = np.percentile(scores, 100 - pct)
    return np.flatnonzero(scores >= cutoff)


def novelty_score(v: np.ndarray, engine_basis: np.ndarray, human_basis: np.ndarray) -> float:
    """§4.2.2 — how much better the engine's own basis reconstructs v than a human one.

    Bases are (k, d) row-matrices, e.g. top principal components of activations over
    engine self-play positions vs over human-game positions. Positive => the concept
    lives more naturally in the engine's representation: the paper's novelty signal.
    """
    def residual(basis: np.ndarray) -> float:
        b = np.atleast_2d(basis)
        coef, *_ = np.linalg.lstsq(b.T, v, rcond=None)
        return float(np.linalg.norm(v - b.T @ coef) / (np.linalg.norm(v) + 1e-12))

    return residual(human_basis) - residual(engine_basis)


def sanity_check() -> None:
    """Recover a known planted direction — verifies the LP, no engine needed."""
    rng = np.random.default_rng(0)
    d = 64
    truth = np.zeros(d)
    truth[[3, 17, 42]] = [1.0, -0.8, 0.6]  # sparse ground-truth concept

    base = rng.normal(size=(40, d))
    z_pos = base[:20] + 2.5 * truth        # good line expresses the concept
    z_neg = base[20:] - 2.5 * truth        # bad line does the opposite

    v, infeas = mine_concept(z_pos, z_neg)
    support = np.argsort(-np.abs(v))[:3]
    cos = float(v @ truth / (np.linalg.norm(v) * np.linalg.norm(truth)))
    print(f"planted support {[3, 17, 42]} -> recovered {sorted(support.tolist())}")
    print(f"cosine similarity to truth: {cos:.3f}   nonzeros: {int((np.abs(v) > 1e-6).sum())}/{d}   slack: {infeas:.3f}")
    assert cos > 0.9, "LP failed to recover the planted concept"
    print("sanity check PASSED")


if __name__ == "__main__":
    sanity_check()
