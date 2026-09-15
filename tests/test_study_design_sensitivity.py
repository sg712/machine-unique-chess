import importlib.util
import unittest

HAS_RESEARCH_DEPS = all(importlib.util.find_spec(name) is not None for name in ("numpy", "scipy"))
if HAS_RESEARCH_DEPS:
    import numpy as np
    from scipy.stats import t
    from scripts.study_design_sensitivity import ancova, simulate


@unittest.skipUnless(HAS_RESEARCH_DEPS, "NumPy/SciPy research dependencies are optional for the web app")
class DesignSensitivityTests(unittest.TestCase):
    def test_batch_fit_agrees_with_independent_lstsq(self):
        rng = np.random.default_rng(7)
        arm = np.tile([0, 1], (3, 12)).astype(float)
        baseline = rng.uniform(size=arm.shape)
        stratum = np.tile(np.repeat([0, 1], 12), (3, 1))
        outcome = 0.3 + 0.1 * arm + 0.4 * baseline + rng.normal(0, 0.1, arm.shape)
        estimate, se, p = ancova(arm, baseline, stratum, outcome)
        for i in range(3):
            x = np.column_stack([np.ones(24), arm[i], baseline[i], stratum[i]])
            beta, _, _, _ = np.linalg.lstsq(x, outcome[i], rcond=None)
            residual = outcome[i] - x @ beta
            expected_se = np.sqrt(np.dot(residual, residual) / 20 * np.linalg.inv(x.T @ x)[1, 1])
            self.assertAlmostEqual(estimate[i], beta[1], places=12)
            self.assertAlmostEqual(se[i], expected_se, places=12)
            self.assertAlmostEqual(p[i], 2 * t.sf(abs(beta[1] / expected_se), 20), places=12)

    def test_seeded_null_has_sensible_error_and_coverage(self):
        null = simulate(participants=48, items=8, effect=0,
                        scenario="moderate_heterogeneity", replicates=3000, seed=9)
        self.assertLess(abs(null["mean_estimated_effect_percentage_points"]), 1)
        self.assertTrue(0.025 < null["rejection_rate"] < 0.075)
        self.assertTrue(0.925 < null["nominal_95ci_coverage"] < 0.975)

    def test_effect_is_on_percentage_point_scale(self):
        result = simulate(participants=96, items=16, effect=0.1,
                          scenario="high_heterogeneity", replicates=1000, seed=10)
        self.assertLess(abs(result["mean_estimated_effect_percentage_points"] - 10), 1)

    def test_invalid_or_unidentifiable_design_fails(self):
        with self.assertRaises(ValueError):
            simulate(participants=25, items=8, effect=.1, scenario="low_heterogeneity")
        with self.assertRaises(ValueError):
            ancova(*[np.ones((2, 24))] * 4)


if __name__ == "__main__":
    unittest.main()
