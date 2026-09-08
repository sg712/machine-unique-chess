# Local regression checks

These checks use disposable SQLite databases and DOM fixtures. They do not contact production or start a browser.

With the Python runtime dependencies installed:

```sh
python -m unittest discover -s tests -v
npm --prefix tests ci
TEST_PYTHON=python npm --prefix tests test
```

The Python tests cover account recovery, legacy sessions, invalid inputs, repeated requests, progress counts, practice modes, independent test attempts, and position legality. The DOM tests cover keyboard move selection, promotion and special moves, study replay, retry handling, five-position sessions, saved test drafts, and duplicate submission.

Research checks also verify saved audit denominators, legal engine continuations, distinct source games for paired examples, rejection of study-bank leakage, and the research page's reveal/compare/replay controls. With the research dependencies installed, an additional synthetic test verifies that PCA sees only training-fold positions; the web-only environment skips that test. No synthetic test values are published as research findings.

DOM tests do not verify actual layout, screen-reader behavior, pointer dragging, audio output, or browser compatibility. Check the home, Learn, practice, test, account, and research pages in a real browser at 320px, 390px, and desktop widths before calling visual verification complete.

Study-note checks cover all 32 examples, source hashes, unique training positions, legal comparison and side-variation lines, and retirement of the invalid example. DOM checks play all four examples in every group, verify explanations appear only after checking, switch replay lines, and return to the unanswered state.
