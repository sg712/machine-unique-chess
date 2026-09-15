# From completed searches to teaching material

The full census checked 4,345 positions; 1,398 retained the engine-and-model criterion. That establishes a pool for review, not a finished set of lessons. The private review desk makes the next step concrete: inspect every acceptable answer, compare plausible alternatives against the saved branches, and write a claim that another chess reviewer can check.

## First editorial batch

The default export contains 24 positions, 12 White and 12 Black. It draws from 1,032 retained positions whose **every originating observation** has recovered history, no BOT tag, no known public exposure, and an editorial role (`prior_development`, `pilot_train` or `new_train`). Another 199 of the 1,231 source-eligible retained positions have validation/test roles and are excluded from editorial inspection. Their existing role labels are preserved; this does not establish that they form an independent future test set.

Selection alternates sides and cycles through game-phase and single/multiple-acceptable-answer buckets, using a fixed SHA-256 ordering within each bucket. Every originating source-game identity and recorded legacy alias is checked to avoid sharing a game between selected cases. This is a reproducible, deliberately varied editorial batch chosen after examining engine outcomes. Its composition and pass rates must not be presented as population estimates or new experimental results. Phase and acceptable-set size are selection features, not verified teaching families.

The source rule means **not known public**, not guaranteed private or unassisted human play. Unknown exposure outside the recovered source records remains possible. Existing development use is explicit. Notes must not convert these examples into held-out assessment items.

## Use the private desk

```sh
python scripts/candidate_review.py build
```

The default output is `data/mining_v3/editorial-review-20260916/`. Open its `review.html` directly on the computer. It has no external dependencies, does not start a server or engine, and sends no data over the network.

For each case, the desk shows the complete acceptable-move set at both depths, every legal root at depth 20 or 24, and the exact saved continuation. Step through the continuation on a board; change the root to compare alternatives. Scores stay in the original mover's perspective. Maia probabilities are model predictions at the labelled rating settings, not observed human solving rates. Saved continuations may be short and do not by themselves explain why a move works.

The rubric asks for a teaching idea, explanation, failures of plausible alternatives, a limiting case, related-position checks and source concerns. A decision of **promising**, **needs more work** or **do not use** is only an editorial note. Chess review, independent chess review, family validation, near-duplicate review, exposure review and trainer readiness remain false. No automatic promotion or trainer import exists.

Edits stay in the open tab's memory. Use **Export review notes** before closing; use **Import saved notes** to continue. The import requires the same complete packet and exact evidence identities, rejects missing/duplicate cases or extra fields, and cannot change the evidence or readiness flags. An unsaved-edit prompt appears before an import replaces notes. The exported notes can also be checked offline:

```sh
python scripts/candidate_review.py validate-reviews \
  --output data/mining_v3/editorial-review-20260916 \
  --reviews /path/to/chess-review-notes.json
```

The validator reports note structure and editorial decisions only. It does not judge chess correctness or certify that a person reviewed the material.

## Evidence and privacy

Before selecting cases, the builder checks the completed census and hashes for the exact source positions, policies, selection, outcomes, imported/new root archives, checkpoint, run manifest and frozen scoring implementations. For every exported case it recomputes the outcome with the unchanged scoring function, replays every saved legal continuation, and requires exact equality with the saved outcome. It never calls the engine. Packet and per-case hashes bind review notes to this evidence.

`packet.json` contains the immutable evidence, including private source information and solutions. `reviews.json` is an empty separate notes template; downloaded review notes are separate files. `manifest.json` records export hashes. Keep all of these local. The exporter accepts only an untracked, Git-ignored directory under `data/mining_v3/`, refuses existing output directories, and does not write a public aggregate. Choose a new `--output` directory when deliberately creating a different packet; old notes remain bound to their original packet.

After editorial inspection, the useful next work is to substantiate explanations and teaching families with distinct source games, genuine boundary examples and independent chess review. A complete family bank, human learning evidence and approved new puzzles are still future work.
