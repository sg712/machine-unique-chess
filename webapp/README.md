# Machine Unique Chess — application

Flask, Jinja and JavaScript serve precomputed chess positions. The groups are exploratory practice material; learning effectiveness and rating-test validity have not been established.

```sh
python -m pip install -r requirements.txt
python webapp/app.py
```

## Pages

- `/`: playable research example with answer reveal, saved engine/Maia comparisons, and eight practice groups. The demo does not submit answers or create progress.
- `/learn`: suggested practice order; Continue prioritises groups already in progress, then studied groups.
- `/pattern/<id>`: four study examples with replay. Unfinished examples and choices resume in the same browser; saved account study progress avoids repeating the introduction on another device.
- `/pattern/<id>/drill`: five-position sessions drawn from 36 positions per group, followed by review or the next unfinished group. Twenty-four positions have authored explanations; the others retain their engine-line feedback.
- `/test`: resumable, signed placement attempts; estimates are exploratory.
- `/research`: methods, three worked examples, saved results, new robustness checks and study protocol.
- `/me`: distinct positions tried and engine moves found, with repeat-attempt totals labelled separately. Email/password sign-in and a recovery code preserve access across devices.

The research page reads `research_examples.json` and the committed audit JSONs in `results/`; it does not run an engine during a request. Its comparison viewer reuses the existing board and replay components. Static starting boards and text continuations remain readable without JavaScript.

The research overview separates the original trainer, expanded screening, initial depth checks,
and full candidate run. Its full-run status is a dated published snapshot, not a live feed.
The 24 practice explanations use existing public lines, with provenance and limitations in
[the practice-note documentation](../docs/PRACTICE_NOTES.md). New mining candidates are not added by this website update.

Practice keeps an account-bound draft in this browser until the user advances past feedback.
If a save is interrupted, `/api/answer/recover` reads the original receipt without recording
another attempt, including after the position has left the practice queue. A missing receipt
offers an explicit retry of the same move, request ID and elapsed time. Account changes and
changed positions reject stale saves. Reload recovery requires browser storage; progress
already saved on the server remains available without it. Earlier unowned browser drafts
are not imported. Session tallies restart on reload; distinct account progress does not.

Interactive boards support arrow keys, row Home/End, Ctrl+Home/End for board corners,
Enter/Space selection, Escape cancellation and keyboard promotion choices. Square labels
and live announcements identify movable pieces, selected pieces and legal destinations.

## Storage and deployment

Without `DATABASE_URL`, the application uses SQLite at `DB_PATH` (default `webapp/study.db`). Production uses Vercel and Neon Postgres, configured with `DATABASE_URL` and `SECRET_KEY`. Git pushes to main trigger deployment. The old PythonAnywhere host is no longer the deployment target described by these instructions.

Account data and answers must not be copied into research outputs without an explicitly consented study. The proposed learning pilot is not automatically enabled by ordinary website use.

## Verification

Use the disposable database and DOM checks in [tests/README.md](../tests/README.md). They do not contact production and do not verify physical browser layout or accessibility behavior. Move/capture sounds are Kenney's CC0 Impact Sounds.
