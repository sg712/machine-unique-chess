# Practice explanations

`webapp/practice_notes.json` covers 24 of the 288 existing practice positions,
three in each group. It supplements the 32 explanations in `study_notes.json`.
The position IDs, FENs, answers, and trainer export are unchanged.

| Drill ID | Explanation | Saved evidence |
| --- | --- | --- |
| 0:0 | Clear f4 for the king | Research line and evaluated alternative |
| 0:1 | Fork the queen and rook | Published six-ply preview |
| 0:9 | Put the bishop on the queen’s diagonal | Published six-ply preview |
| 1:0 | Turn the bishop toward c4 | Published six-ply preview |
| 1:3 | Remove the pawn blocking b4 | Published six-ply preview |
| 1:12 | Draw one rook away from the other | Published six-ply preview |
| 2:0 | Line up the queen and rook | Published six-ply preview |
| 2:2 | Draw the king onto a diagonal | Published six-ply preview |
| 2:11 | Fork two pieces and open the g-file | Published six-ply preview |
| 3:0 | Use both knights against f2 | Research line and evaluated alternative |
| 3:2 | Take the checking capture first | Published six-ply preview |
| 3:5 | Clear both blockers on the long diagonal | Published six-ply preview |
| 4:0 | Check before taking g6 | Published six-ply preview |
| 4:9 | Use the rook behind the queen | Published three-ply line ending in mate |
| 4:10 | Open the bishop’s diagonal with check | Published six-ply preview |
| 5:0 | Pin the pawn that attacks the queen | Research line and evaluated alternative |
| 5:6 | Clear the e-file for the rook | Published six-ply preview |
| 5:23 | Fork the queen and rook with a pawn | Published six-ply preview |
| 6:0 | Back up the f7 rook | Published six-ply preview |
| 6:2 | Attack the queen and clear the seventh rank | Published six-ply preview |
| 6:35 | Bring the queen onto the bishop’s diagonal | Published six-ply preview |
| 7:3 | Draw the rook off the back rank | Published six-ply preview |
| 7:5 | Support the queen’s entry on g2 | Published six-ply preview |
| 7:8 | Use two checks to take both bishops | Published six-ply preview |

The three research examples use the `related` entries already saved in
`webapp/research_examples.json`. Their generator,
`experiments/32_research_examples.py`, required an achieved depth of at least 20
for both the best line and the separately searched comparison. The cache stores
that minimum threshold, not the exact achieved depth. Scores are centipawns from
the root mover’s perspective. In drill 5:0, both scores favour White; the note
explains Black’s defensive resource without claiming a forced win.

The other 21 examples use the exact previews in `webapp/concepts.json`. That
export has no per-line engine version, achieved depth, or absolute score, so
those evidence fields are null. Its `gap_cp` and `cost_cp` fields are not treated
as absolute evaluations. These 21 notes have no evaluated comparison. The
expansion adds 16 notes while preserving the original eight explanations.

Each note has a concrete board constraint, the move’s purpose, an explanation
of the saved continuation, and a short prompt about what to watch. The main
line is `evidence.pv`; an optional `comparison` contains `uci`, `san`, `pv`,
`explanation`, and its evidence metadata. Comparisons describe the specific
cached alternative, not whichever move a learner happened to play.

The tests bind each note to the public source hashes and exact drill identity,
replay all saved UCI moves with matching SAN, and check the board claims attached
to the prose. These include captures, attacks, pins, castling rights, check, and
move legality. The terminal checkmate in drill 4:9 is checked directly; the tests
also verify that the initial queen check is not itself mate. For the queen pin
in 6:35, a focused check confirms that a capture along the pin line remains
legal, preventing the pin from being mistaken for a ban on every queen move.
Legal replay does not establish optimal play, prove a line is
forced, or explain every part of an engine evaluation. No new engine searches
or private mining positions are used for this batch.

Run the focused checks with the project Python environment:

```sh
python -m unittest discover -s tests -p test_practice_notes.py -v
```
