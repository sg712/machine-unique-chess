# Versioned acceptable moves in practice and tests

16 September 2026. Implemented support; no new positions published.

Practice, mixed review and the twelve-position test now share a server-side answer adapter. The existing public bank still accepts exactly its saved `best` move. Nothing in `webapp/concepts.json`, its historical answers or the completed mining census has changed. This is infrastructure for a later reviewed bank, not approval to release private candidates.

## Explicit answer contract

A new practice position retains `fen` and `best` (the reference move with the highest depth-24 score) and adds an `answer` object. The required fields are:

| Field | Meaning |
|---|---|
| `schema` | Exactly `acceptable-moves/v1` |
| `version` | A nonempty, explicit bank/item revision identifier |
| `accepted` | The complete, unique list of accepted UCI moves, including promotion suffixes |
| `criterion` | `id: stable-complete-root-cp/v1`, `depths: [20,24]`, an integer `tolerance_cp` from 0 through 100, and `score_perspective: side_to_move` |
| `engine` | Stockfish name, explicit version and binary SHA-256; one thread, 64 MB hash, clear hash for every root, `fen_only` context |
| `evidence` | The exact FEN and a `roots` mapping containing **every legal move** |
| `evidence_sha256` | SHA-256 of canonical evidence JSON: sorted keys, compact separators, UTF-8, no NaN |

Each legal root has `20` and `24` records, each with integer `score_cp`, integer reached `depth` at least the requested depth, `bound: exact`, and a nonempty legal `pv` of UCI moves beginning with that root. The engine object fields are `name`, `version`, `binary_sha256`, `threads`, `hash_mb`, `clear_hash_per_root` and `context`. The evidence fields are `fen` and `roots`; unknown fields in these versioned objects are rejected.

The validator recomputes the within-tolerance set from all legal roots at both depths. Both sets must equal the explicitly declared `accepted` list. It rejects missing or duplicate moves, omitted good alternatives, extra poor moves, unstable sets, illegal continuations, incomplete depth, bounds, mate/non-numeric values, an invalid board, inconsistent provenance and a mismatching evidence hash. The current frozen research tolerance remains 20 cp; supporting a different explicitly versioned tolerance does not silently change that criterion.

This is an integrity contract, **not independent evidence authentication**. A SHA-256 and a declared reached depth cannot prove that somebody actually ran the stated engine. Source archives, engine execution logs, the editorial process and independent chess review must establish authenticity and teaching readiness before a real bank is adopted. The validator does not impose Maia rarity, evaluation-window, source-exposure or research-split gates; those remain separate publication requirements.

See `webapp/answers.py` for the contract and `tests/test_answer_sets.py` for a complete, clearly synthetic fixture. Runtime validation performs no engine search or inference.

## Grading and feedback

- Every move in the verified set earns equal correctness credit. Legal moves outside it do not. No alternate answers are inferred from old score gaps, model probabilities or explanatory prose.
- Feedback for an accepted alternative starts with **that move's saved continuation**. Every accepted branch can be replayed. A miss starts with the reference accepted move, while the separate “Your move” control still shows the submitted move.
- Existing reference-specific practice notes are not attached to new set-based feedback. They require a separately reviewed explanation contract; a reference explanation must not be presented as evidence for another move.
- New questions contain the board, legal moves, schema name and an opaque keyed revision identifier, with no accepted moves, root scores or continuations. Those appear only after a legal submission. The keyed identifier avoids publishing a guessable hash of a legacy board and its single answer.
- Existing exact-match model probabilities and difficulty estimates are omitted for explicit sets. Rating comparisons are enabled only for the pinned original answer/calibration bank; any revised bank has no legacy rating-band comparison, even for a sample containing only legacy items. The original exact-match model does not calibrate a changed outcome. Scores and explanations remain available.

## History and migration

The migration adds a nullable `grading_id` column to `attempt`, idempotently, in SQLite and Postgres. It does not alter any saved `correct`, `best`, move, timestamp, receipt or test result. New attempts record the full answer identity, including its evidence and version. Changing UI text alone does not change that identity.

Old null-version attempts remain part of current practice history only while the current position is legacy exact-match and both its FEN and reference answer still match the stored row. Old and newly tagged legacy rows combine into one first/latest/ever-correct history. A new explicit set, new reference answer, new evidence or new version starts a separate current history; previous rows remain stored and contribute to the historical attempt totals.

New test tokens bind the owner and the entire answer/calibration bank identity. Unfinished tests cannot silently adopt new answers. Tokens and practice writes from before this change work only against the unchanged initial legacy bank, whose fingerprint is pinned in source rather than recomputed as a new baseline on deployment. After a revision, practice requires its opaque question identifier. Completed test receipts can still be retrieved through their original token and identical submitted picks after an answer revision; they are returned verbatim and never rescored. A stale question page requires a fresh test.

Practice drafts carry the opaque revision. Stale unsubmitted drafts are discarded. A previously submitted move can still recover its immutable receipt after the answer version changes, provided its FEN and legal move still match the current slot. The interface labels that feedback as belonging to the previous answer version, excludes it from the current session score, and offers the current question again when it is still outstanding. If no matching receipt exists for a stale draft, the interface discards that unusable draft, explains the reset and reopens the current queue; it never repeatedly retries the old version. Receipt lookup never performs new grading. If a position has been removed or its FEN changed, its stored history is preserved but recovery through that slot is rejected.

For deployment, allow the existing startup migration to run before new writes. The added nullable column remains compatible with older application code and rollback. No production database migration was executed during this development task. A Postgres instance was not available for live migration validation; the equivalent SQLite migration and behavior are covered offline.

## Current scope

The scored practice/review/test bank supports this schema. Legacy study and homepage demos still use their existing single-answer content and embedded explanations. Startup explicitly rejects the new schema in those surfaces. Publishing set-based lessons there requires a server-gated lesson-feedback flow and reviewed multi-branch explanations first. No v3 boards have been added to any public surface.

Verification uses synthetic positions (including underpromotion), disposable SQLite, Flask's in-process test client and JSDOM. It covers strict evidence rejection, exact legacy behavior, accepted-alternative replay, all-branch selection, owner/receipt semantics, opaque question identity, changed-bank separation, stale drafts, historical receipt recovery and omission of incompatible model claims. No browser or localhost access was used.
