# Executing the research recommendations

16 September 2026. This follows the [research review](RESEARCH_NEXT_2026-09-16.md) and separates completed preparation from calculations that have not run.

## Completed

**Three contrasting lesson families, nine real cases.** Each family now has two positive examples and a different-game boundary. The private bank contains 41 checked board facts, ten continuation questions and complete discussions of all accepted moves, with 62 exact saved root citations. Its compiler replays 710 roots and 13,920 PV plies. The other three original hypotheses were deferred because the available comparisons did not justify stronger family claims. [Evidence and limitations](LESSON_FAMILIES_2026-09-16.md).

**Versioned acceptable-set grading.** Practice, mixed review and tests now support explicitly declared acceptable moves backed by complete depth-20/24 evidence. A correct alternative earns credit and replays its own line. Answer versions keep stale requests and older receipts from changing current progress; changed banks do not inherit incompatible historical rating estimates. The original bank remains unchanged. The legacy study/home demonstrations reject new set schemas until their feedback flow is adapted. [Contract and migration](ANSWER_SETS.md).

**256 fresh source positions.** A bounded August archive sample supplied 64 calibration-development positions, 64 separate calibration-evaluation positions, and 128 targeted endgames. The endgame queue has equal sides and equal mover-rating groups 1400–1799 / 1800–2399. All requested cells are full, all games and target states are distinct, and complete source histories are checked for cross-role target exposure. Model probabilities and engine evaluations did not select this sample. [Acquisition and model-date provenance](PROSPECTIVE_SAMPLE_2026-09-16.md).

**Frozen, executable context audit.** The 96-position comparison has 48 positions of each side and 32 of each phase, using only admitted development material and replayable histories. Its paired conditions use the same pinned Maia3-5M runtime and the same rating inputs. It will evaluate acceptable-set probability, capped regret and candidate status against unchanged saved engine scores. [Audit specification and current state](CONTEXT_AUDIT_2026-09-16.md).

## Compute status

The laptop was on battery during this work. The research run commands were invoked with power guards and paused before inference or new engine searches. **There are no new context-effect estimates, verified fresh puzzles, or calibration scores to report yet.** These prepared runs are not described as completed experiments.

The next prospective analysis uses a frozen first tranche of 16 calibration-development positions, 16 calibration-evaluation positions and 32 targeted endgames. All 2,875 planned legal-root searches are pending. Actual mover/opponent ratings are separate inputs. Calibration's full-root depth-20/24 checks and targeted approximate screening remain distinct; incomplete, capped, mate-valued and unstable evidence is counted explicitly. Runtime and per-search limits prevent an unbounded run, and checkpoints permit continuation without replacing completed evidence. [Analysis plan, limits and continuation](PROSPECTIVE_ANALYSIS_2026-09-16.md).

Both commands require AC power under their recorded run policies. No heartbeat automation, perpetual power watcher or long background mining process was created. Starting a guarded command while unplugged does not arrange automatic future execution.

## What still needs people

All independent chess-review, family-validation and trainer-release gates remain false. The nine lesson cases are development material and cannot become unseen assessments of the same definitions. They are a useful first subset, not the complete eight-family, 48-item formal study bank.

No participants were recruited and no messages were sent. Actual learning, calibrated puzzle difficulty and transfer still require independent review and human responses. The current progress records and simulations do not supply that evidence.

## Preservation

The historical mining definitions, full-census results, original editorial packet and existing trainer positions remain unchanged. New source games, case drafts and intermediate predictions stay in ignored private directories. Public documents and aggregates expose methods, counts and hashes, without publishing private boards, solutions or source-game/player identities.

## Verification

The final offline suites passed 407 Python tests and 59 interface tests, with no skips. Separate reviews checked answer recovery, history controls, rating inputs, search-depth reporting, retry ordering and saved-evidence bindings. Browser access is administratively restricted, so this does not include live visual or browser testing. The website deployment was confirmed through Vercel's production status, exact commit and custom-domain aliases; a live Postgres migration was not independently exercised.
