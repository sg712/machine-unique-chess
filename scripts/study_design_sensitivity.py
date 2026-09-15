"""Hypothetical design sensitivity, never fitted to participant responses.

This is a planning illustration for the fixed-bank ANCOVA in LEARNING_STUDY_V2,
not a power certification or an implementation of its randomization analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {
    "low_heterogeneity": (5.0, 0.2, 0.4),
    "moderate_heterogeneity": (2.0, 0.1, 0.6),
    "high_heterogeneity": (0.8, 0.05, 0.7),
}


def ancova(arm, baseline, stratum, outcome):
    """Fit independent participant-level regressions in simulation batches."""
    arrays = [np.asarray(a, dtype=float) for a in (arm, baseline, stratum, outcome)]
    if arrays[0].ndim != 2 or any(a.shape != arrays[0].shape for a in arrays):
        raise ValueError("all inputs must have the same (replicates, people) shape")
    if arrays[0].shape[1] <= 4 or not all(np.isfinite(a).all() for a in arrays):
        raise ValueError("need finite observations and positive residual degrees of freedom")
    arm, baseline, stratum, outcome = arrays
    x = np.stack((np.ones_like(arm), arm, baseline, stratum), axis=-1)
    gram = np.einsum("rni,rnj->rij", x, x)
    if np.any(np.linalg.matrix_rank(gram) < 4):
        raise ValueError("rank-deficient ANCOVA design")
    inverse = np.linalg.inv(gram)
    beta = np.einsum("rij,rj->ri", inverse, np.einsum("rni,rn->ri", x, outcome))
    residual = outcome - np.einsum("rni,ri->rn", x, beta)
    df = arm.shape[1] - 4
    variance = (residual * residual).sum(axis=1) / df
    se = np.sqrt(variance * inverse[:, 1, 1])
    if np.any(se <= 0):
        raise ValueError("degenerate residual variance")
    return beta[:, 1], se, 2 * t.sf(np.abs(beta[:, 1] / se), df)


def simulate(*, participants, items, effect, scenario, replicates=5000, seed=20260916):
    if participants < 16 or participants % 8:
        raise ValueError("participants must be a multiple of 8, at least 16")
    if items < 4 or replicates < 100 or not 0 <= effect <= 0.15:
        raise ValueError("require >=4 items, >=100 replicates and effect in [0, .15]")
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario")
    rng = np.random.default_rng(seed)
    # Every stratum has complete blocks of four with two people per arm.
    order = rng.random((replicates, participants // 4, 4)).argsort(axis=-1)
    arm = (order < 2).astype(float).reshape(replicates, participants)
    stratum = np.broadcast_to(np.repeat([0.0, 1.0], participants // 2), arm.shape)
    shape, low, width = SCENARIOS[scenario]
    latent = low + width * rng.beta(shape, shape, size=arm.shape)
    baseline_p = latent + 0.1 * (stratum - 0.5)
    # A five-point common practice gain and an explicitly hypothetical arm effect.
    post_p = baseline_p + 0.05 + arm * effect
    if post_p.min() < 0 or post_p.max() > 1:
        raise ValueError("scenario would require clipping probabilities")
    baseline = rng.binomial(8, baseline_p) / 8
    outcome = rng.binomial(items, post_p) / items
    estimate, se, pvalue = ancova(arm, baseline, stratum, outcome)
    critical = t.ppf(0.975, participants - 4)
    rate = float(np.mean(pvalue < 0.05))
    return {
        "scenario": scenario, "participants_total": participants,
        "baseline_items": 8, "immediate_items": items,
        "assumed_effect_percentage_points": effect * 100,
        "replicates": replicates, "seed": seed,
        "rejection_rate": rate,
        "rejection_rate_monte_carlo_se": float(np.sqrt(rate * (1 - rate) / replicates)),
        "mean_estimated_effect_percentage_points": float(100 * estimate.mean()),
        "mean_95ci_full_width_percentage_points": float(200 * critical * se.mean()),
        "nominal_95ci_coverage": float(np.mean(np.abs(estimate - effect) <= critical * se)),
    }


def build(replicates=5000):
    settings = [(n, items, effect, scenario)
                for scenario in SCENARIOS
                for n in (24, 48, 96, 192)
                for items in (8, 16, 24)
                for effect in (0.0, 0.1)]
    return {
        "schema_version": 1,
        "status": "hypothetical_planning_scenarios_not_observed_learning",
        "inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (Path(__file__), ROOT / "docs/LEARNING_STUDY_V2.md")},
        "runtime": {"numpy": np.__version__, "scipy": __import__("scipy").__version__},
        "assumptions": {
            "baseline_population_mean": 0.4, "common_practice_gain": 0.05,
            "participant_probability": "low + width * Beta(shape, shape), plus stratum shift -/+ .05",
            "scenarios_shape_low_width": SCENARIOS,
            "allocation": "two rating strata; balanced permuted blocks of four",
            "response_model": "conditionally independent Bernoulli items given participant probability",
            "analysis": "participant-level OLS ANCOVA: post ~ arm + baseline + rating stratum; t intervals",
            "not_modeled": ["item difficulty differences", "family-specific effects", "participant-by-item interactions",
                            "form imbalance", "unequal stratum enrollment", "incomplete final allocation blocks",
                            "attrition", "practice dose variation", "delayed outcomes",
                            "the protocol's assignment-respecting randomization analysis"],
            "interpretation": "Illustrates sensitivity to assumptions; cannot establish a required sample size or learning effect.",
        },
        "results": [simulate(participants=n, items=items, effect=effect, scenario=scenario,
                             replicates=replicates, seed=20260916 + i)
                    for i, (n, items, effect, scenario) in enumerate(settings)],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite an existing planning result")
    result = build(args.replicates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        out.write(json.dumps(result, indent=2) + "\n")
