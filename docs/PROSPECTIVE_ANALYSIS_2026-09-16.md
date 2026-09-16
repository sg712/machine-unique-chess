# The next analysis batch is frozen and resumable

16 September 2026. **Prepared and paused for battery power; no prospective model predictions or engine searches have run.** This is an executable continuation of the [fresh source sampling](PROSPECTIVE_SAMPLE_2026-09-16.md), not a calibration result.

The first tranche selects 64 of the 256 source games using metadata and seeded hashes before model or engine outcomes: 16 calibration-development positions, 16 calibration-evaluation positions and 32 targeted endgames. Endgames have eight positions in each side/rating-group cell. All requested counts were available. Selection preserves the cohort's source-game, move-sequence and bidirectional target-versus-other-source-state exclusions. Protected evaluation positions are consumed only by the fixed quantitative analysis, not by lesson drafting or model fitting.

The prepared engine workload is 1,090 legal-root searches for development, 1,142 for evaluation and 643 for the approximate endgame screen. All 2,875 remain pending. Every selected source row stays visible in coverage summaries; there are currently zero verified calibration events and the Brier/log-loss fields are null.

## What it will measure

The same locally pinned Maia3-5M model receives genuine chronological history and FEN-only input. Calibration uses the **actual mover and opponent ratings as separate inputs**, within the source cohort's 1400–2399 range. Targeted endgames also receive equal 1700 and equal 2000 settings. Both conditions use complete legal-move softmax probabilities at temperature one, float32, disabled clock inputs and no probability transform.

Four same-input control records check that the history and FEN code paths agree when given the same target state, including actual and fixed rating labels. A separate equal-1700 control checks that the new two-rating adapter agrees with the pinned original adapter. Controls require matching target identities, correct rating pairs and complete finite normalized legal policies; saved predictions cannot be reported until controls pass.

For calibration, every legal move is evaluated independently at depths 20 and 24, with one Stockfish18 thread, 64MB hash and cleared hash before every root. The event is whether the recorded online-game move belongs to the complete set within 20cp of the best numeric move. A position is eligible for that event only when all roots reach the requested depths with exact scores, none is mate-valued, and both depths yield the same nonempty acceptable set. **No low-Maia-probability, regret or evaluation-window filter is applied to calibration.**

The public aggregate reports Brier score, log loss and fixed reliability bins separately by source role and model condition only for eligible completed rows. Missing, capped, bound, mate-valued and unstable evidence remains in the original selected denominator. Small bins are explicitly marked sparse. These are source-game choice diagnostics on a filtered convenience sample; they are not human puzzle-success rates or evidence of learning.

Targeted endgames use complete legal-root searches at **depth14 only**. Their acceptable-set mass, capped regret and rise in probability from model rating1700 to2000 are exploratory screening quantities. A completed depth14 item is labelled approximate, never depth-stable, calibrated, trainer-ready or independently reviewed.

## Limits on the laptop work

The runner requires confirmed AC power before model loading, between model batches and during each engine search. It stops an individual search after 30 seconds and caps one invocation at ten minutes, with a short engine-stop grace period and bounded shutdown overhead. A watchdog interrupts an in-progress search on power loss. Capped evidence keeps its actually achieved scored depth: a later unscored engine update cannot promote an earlier score to depth24.

Each root attempt is saved separately. Completed exact searches are reused; incomplete searches are retained and eligible for retry. Never-attempted roots come first globally, so a few expensive early roots cannot consume every future invocation and starve later positions. After all new roots are attempted, retries are ordered by fewest prior attempts. The fixed caps and scoring rules remain unchanged.

An exclusive run lock prevents concurrent writers. Active, paused, interrupted and failed states are explicit; reporting recognizes a stale active state after a process exits. Every report binds its exact read policy/root/control files through a private inventory and a public inventory digest, as well as the frozen source, plan, input, checkpoint, runtime and helper hashes.

## Local continuation

The current ignored private output is `data/mining_v3/prospective-analysis-20260916`. The source cohort is `data/mining_v3/prospective-20260916-v2`.

With the research Python environment, `scripts/prospective_analysis_20260916.py run` resumes the bounded batch. It safely records another power pause while unplugged. `report` rebuilds the [public aggregate](../results/prospective_analysis_20260916.json) without inference or engine searches. `prepare` refuses to overwrite the frozen tranche.

The [pinned model provenance](../results/prospective_model_provenance_20260916.json) documents that the August2026 source games postdate the published May2026 checkpoint and the paper's declared January2023–July2025 training period. This is documentary temporal separation, not a full private training-corpus membership audit or proof of new players or board patterns. No probability transform is fitted, and no item is promoted to the trainer.

Eighteen focused prospective tests pass, including actual mover/opponent tensor order, complete accepted sets, capped/mate/unstable exclusions, separate targeted screening, source-state leakage, deterministic tranche selection, control identities, power interruption, scored-depth integrity, fair retry scheduling and exact evidence inventories. Nineteen separate context-audit tests also pass. The real prepared run remains paused before any model or engine work.
