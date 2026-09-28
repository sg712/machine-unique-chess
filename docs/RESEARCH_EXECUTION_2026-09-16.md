# Executing the research recommendations

Prepared 16 September 2026; execution resumed 27 September; updated 29 September. This follows the [research review](RESEARCH_NEXT_2026-09-16.md) and separates completed measurements from remaining work.

## Completed

**Three contrasting lesson families, nine real cases.** Each family now has two positive examples and a different-game boundary. The private bank contains 41 checked board facts, ten continuation questions and complete discussions of all accepted moves, with 62 exact saved root citations. Its compiler replays 710 roots and 13,920 PV plies. The other three original hypotheses were deferred because the available comparisons did not justify stronger family claims. [Evidence and limitations](LESSON_FAMILIES_2026-09-16.md).

**Versioned acceptable-set grading.** Practice, mixed review and tests now support explicitly declared acceptable moves backed by complete depth-20/24 evidence. A correct alternative earns credit and replays its own line. Answer versions keep stale requests and older receipts from changing current progress; changed banks do not inherit incompatible historical rating estimates. The original bank remains unchanged. The legacy study/home demonstrations reject new set schemas until their feedback flow is adapted. [Contract and migration](ANSWER_SETS.md).

**256 fresh source positions.** A bounded August archive sample supplied 64 calibration-development positions, 64 separate calibration-evaluation positions, and 128 targeted endgames. The endgame queue has equal sides and equal mover-rating groups 1400–1799 / 1800–2399. All requested cells are full, all games and target states are distinct, and complete source histories are checked for cross-role target exposure. Model probabilities and engine evaluations did not select this sample. [Acquisition and model-date provenance](PROSPECTIVE_SAMPLE_2026-09-16.md).

**Completed context audit.** All 96 paired comparisons finished on 27 September: 48 positions of each side and 32 of each phase. Identical-input controls passed with zero probability difference. Using genuine game history, 83 positions retained the full candidate criterion and 13 lost it; all 96 passed the newly recomputed FEN-only baseline. The most likely move changed in 14 positions at model rating 1700 and 17 at 2000. This selected-development diagnostic keeps the saved engine scores unchanged and does not establish human puzzle difficulty or learning. [Audit specification and results](CONTEXT_AUDIT_2026-09-16.md).

## Compute status

The context audit is complete. The original prospective run stopped on 28 September after 2,873 of 2,875 legal-root searches reached their requested depths. Two development searches exhausted three full 30-second attempts each; their achieved depths were 21 and 23 against a target of 24. All 64 model policies are saved and both model-control checks passed. The final inventory contains 2,803 numeric roots, 70 mate-valued roots and two capped roots, with none pending or errored. This is the final bounded result, with two positions explicitly incomplete.

The prospective analysis uses a frozen first tranche of 16 calibration-development positions, 16 calibration-evaluation positions and 32 targeted endgames, with 2,875 planned legal-root searches. Actual mover/opponent ratings are separate inputs. Calibration's full-root depth-20/24 checks and targeted approximate screening remain distinct; incomplete, capped, mate-valued and unstable evidence is counted explicitly. Runtime and per-search limits prevent an unbounded invocation, and checkpoints permit continuation without replacing completed evidence. [Analysis plan, limits and current coverage](PROSPECTIVE_ANALYSIS_2026-09-16.md).

Development and held-out evaluation each contain nine stable numeric observations out of 16 selected. Development additionally has four unstable, one mate-valued and two incomplete positions; evaluation has three unstable and four mate-valued positions. The 32 targeted endgames yield 27 approximate depth-14 numeric cases and five mate exclusions. Separate history/FEN Brier and log-loss scores, actual denominators and limitations appear in the linked report. No excluded position was replaced.

The continuation supervisor stopped for review after 14 invocations and its follow-up was paused. On 29 September, the user authorized a separate 120-second supplement for only the two capped development roots. It preserves all original evidence and reports any supplemented results separately. The supplement is prepared and waiting for AC power; each root gets at most one full two-minute attempt, with a six-invocation limit for interruption recovery. AC checks, one engine thread, 64MB hash and the ten-minute invocation cap remain in force. Process-scoped sleep prevention is permitted during a run; persistent power settings remain unchanged.

## What still needs people

All independent chess-review, family-validation and trainer-release gates remain false. The nine lesson cases are development material and cannot become unseen assessments of the same definitions. They are a useful first subset, not the complete eight-family, 48-item formal study bank.

No participants were recruited and no messages were sent. Actual learning, calibrated puzzle difficulty and transfer still require independent review and human responses. The current progress records and simulations do not supply that evidence.

## Preservation

The historical mining definitions, full-census results, original editorial packet and existing trainer positions remain unchanged. New source games, case drafts and intermediate predictions stay in ignored private directories. Public documents and aggregates expose methods, counts and hashes, without publishing private boards, solutions or source-game/player identities.

## Verification

The original 16 September research release passed 407 Python tests and 59 interface tests, with no skips. On 27 September, all 441 backend tests passed, including 19 context tests, 18 prospective tests and 25 application/research-page tests. The context aggregate was independently reproduced byte for byte from its saved evidence. The stopped baseline's complete 2,953-file evidence inventory, hashes and controls were independently verified, and its coverage and separate calibration scores were reproduced. On 29 September, 63 relevant tests passed across the supplement, original prospective analysis, research page and application; the 17 supplement tests use mocked engines and power states. Independent reviews checked the new runner and public writeup. The actual prepared supplement and stopped baseline rendered successfully together in an offline `/research` check, with incomplete supplemental comparisons withheld. The supplement has zero executed invocations while waiting for AC power. Browser access is administratively restricted, so these checks do not include live visual or browser testing or a live Postgres migration.
