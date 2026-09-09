# Practice explanations

`webapp/practice_notes.json` covers eight of the 288 existing practice positions,
one in each group. It supplements the 32 explanations in `study_notes.json`.
The position IDs, FENs, answers, and trainer export are unchanged.

| Drill ID | Explanation | Saved evidence |
| --- | --- | --- |
| 0:0 | Clear f4 for the king | Research line and evaluated alternative |
| 1:0 | Turn the bishop toward c4 | Published six-ply preview |
| 2:0 | Line up the queen and rook | Published six-ply preview |
| 3:0 | Use both knights against f2 | Research line and evaluated alternative |
| 4:0 | Check before taking g6 | Published six-ply preview |
| 5:0 | Pin the pawn that attacks the queen | Research line and evaluated alternative |
| 6:0 | Back up the f7 rook | Published six-ply preview |
| 7:5 | Support the queen’s entry on g2 | Published six-ply preview |

The three research examples use the `related` entries already saved in
`webapp/research_examples.json`. Their generator,
`experiments/32_research_examples.py`, required an achieved depth of at least 20
for both the best line and the separately searched comparison. The cache stores
that minimum threshold, not the exact achieved depth. Scores are centipawns from
the root mover’s perspective. In drill 5:0, both scores favour White; the note
explains Black’s defensive resource without claiming a forced win.

The other five examples use the exact previews in `webapp/concepts.json`. That
export has no per-line engine version, achieved depth, or absolute score, so
those evidence fields are null. Its `gap_cp` and `cost_cp` fields are not treated
as absolute evaluations. These five notes have no evaluated comparison.

Each note has a concrete board constraint, the move’s purpose, an explanation
of the saved continuation, and a short prompt about what to watch. The main
line is `evidence.pv`; an optional `comparison` contains `uci`, `san`, `pv`,
`explanation`, and its evidence metadata. Comparisons describe the specific
cached alternative, not whichever move a learner happened to play.

The tests bind each note to the public source hashes and exact drill identity,
replay all saved UCI moves with matching SAN, and check the board claims attached
to the prose. These include captures, attacks, pins, castling rights, check, and
move legality. Legal replay does not establish optimal play, prove a line is
forced, or explain every part of an engine evaluation. No new engine searches
or private mining positions are used for this batch.

Run the focused checks with the project Python environment:

```sh
python -m unittest discover -s tests -p test_practice_notes.py -v
```
