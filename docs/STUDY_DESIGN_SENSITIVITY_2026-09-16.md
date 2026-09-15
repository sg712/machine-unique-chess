# What a small learning pilot can tell us

16 September 2026. **These are hypothetical simulations, not participant data, observed learning gains, or a certified sample-size calculation.** The existing 24-person study remains a feasibility pilot. No participants were recruited and its protocol was not changed.

## Question

If grouped practice really increased the chance of an acceptable answer by **10 percentage points**, how often would a participant-level analysis detect that difference? How would uncertainty change with more people or assessment items?

This distinguishes a useful pilot from an efficacy claim. The [CONSORT pilot-trial extension](https://www.bmj.com/content/355/bmj.i5239) makes that distinction explicitly. Baseline-adjusted comparison follows the ANCOVA rationale described by [Vickers and Altman](https://www.bmj.com/content/323/7321/1123); neither source supplies the chess-specific assumptions below.

## Simulation, not fitted power

The reproducible [script](../scripts/study_design_sensitivity.py) generates 5,000 simulated trials for each of 72 settings: three participant-heterogeneity scenarios, four sample sizes, three assessment lengths, and a null or +10-point arm effect. All 360,000 trials are artificial.

- Total participants: 24, 48, 96, or 192, equally split across two rating strata and two arms. Assignment uses balanced permuted blocks of four within each stratum.
- Everyone answers eight baseline items. Immediate assessment has 8, 16, or 24 items. Only the eight-item case matches the current protocol; longer forms require more verified material and more session time.
- Baseline success probability averages 40%. Each person has a latent probability drawn from a declared scaled symmetric beta distribution, with three levels of heterogeneity; the rating strata shift that probability by −5/+5 points.
- Both arms receive a hypothetical common five-point practice gain. The treatment adds zero or ten points. The simulation does not estimate these quantities from the project.
- Responses are independent Bernoulli draws conditional on the person's probability. Shared participant ability makes their responses correlated marginally. Items and forms are otherwise equally difficult; effects are constant across people and families.
- Analysis is `immediate fraction ~ arm + baseline fraction + rating stratum`, using ordinary participant-level OLS and t-based intervals. The two-sided rejection threshold is .05. This is **not** the protocol's additional assignment-respecting randomization analysis.

The scenarios omit unequal item difficulty, item/family interactions, form imbalance, attrition, variable exposure, and delayed-test loss. They also assume equal stratum enrollment and complete allocation blocks; the actual protocol can end with uneven stratum enrollment and incomplete blocks. They do not establish generalization to a new item bank. These omissions limit the simulation; the values below must not be used as a recruitment guarantee.

## Results

Ranges span the three declared heterogeneity scenarios. “Detects” means the simulated two-sided test rejects under the assumed +10-point effect. The interval column is the mean **full** width of a nominal 95% confidence interval, in percentage points.

| Total participants | Immediate items | Detects assumed +10-point effect | Mean 95% interval width |
|---:|---:|---:|---:|
| 24 | 8 | 21.2–24.4% | 31.6–34.8 points |
| 24 | 16 | 27.2–39.6% | 23.4–29.1 points |
| 24 | 24 | 31.6–51.2% | 19.9–26.7 points |
| 48 | 8 | 37.3–44.8% | 21.4–23.6 points |
| 48 | 16 | 51.5–68.6% | 15.8–19.7 points |
| 96 | 8 | 66.5–74.2% | 14.9–16.4 points |
| 96 | 16 | 81.8–94.5% | 11.0–13.7 points |
| 192 | 8 | 92.3–95.8% | 10.4–11.5 points |

The complete [aggregate output](../results/study_design_sensitivity_20260916.json) contains all settings, seeds, runtime versions, source hashes, Monte Carlo standard errors, effect-estimate means, and interval coverage. Across null settings, rejection rates range from 4.12% to 5.68%, a useful implementation check. With 5,000 replicates, the maximum Monte Carlo standard error of a rejection rate is about 0.71 percentage points. That quantifies simulation noise, **not uncertainty about real learners**.

## Decision

Keep the 24-person pilot focused on whether the materials, timing, answer collection, and delayed follow-up work. A nonsignificant result would not rule out a useful effect; even under these simplified assumptions, a real ten-point benefit is usually missed. A positive result would also need a larger independent test and careful interpretation of its interval.

More assessment items can improve measurement, but they cannot replace additional independent people or independent position families. Increasing to 16 items also doubles the immediate assessment and needs a revised, frozen bank. We have not selected a confirmatory sample size. Use pilot information about response variation, missingness, item effects, and feasible recruitment to simulate that actual design later.

## Reproduction and checks

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python scripts/study_design_sensitivity.py \
  --replicates 5000 --output /tmp/chess-study-design-sensitivity.json
python -m unittest tests.test_study_design_sensitivity -v
```

The output path must not exist. Tests compare the batch fit against independent least-squares calculations, check a seeded null's error/coverage, verify effect recovery on the percentage-point scale, and reject invalid designs. No engine, neural model, private study bank, or human-response file is read.
