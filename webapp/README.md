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
- `/review`: five-position sessions across all groups, ordered by oldest latest attempt. A latest miss enters the queue even after an earlier success; a correct answer clears it. Review is a single pass, with remaining misses available on the next visit.
- `/test`: resumable, owner-bound signed attempts. Results lead with actual answers and missed/all review filters, including authored explanations when available. Rating comparisons are secondary and exploratory.
- `/research`: methods, three worked examples, saved results, new robustness checks and study protocol.
- `/me`: next-practice and review actions, distinct first-try/latest-try/ever-found totals, and per-group review counts. Repeated attempts and test results are separate. Email/password sign-in and legacy recovery codes preserve access across devices.
- `/privacy`: visit-history preferences and browser exclusion. `/owner/login` provides separate private access to usage counts and opted-in browser histories; see [analytics documentation](../docs/ANALYTICS.md).

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
Mixed review drafts also preserve the remaining cross-group order and use the actual group
and index in every save. Restoring an old receipt does not overwrite the fresh server-derived
review count. Practice and study feedback hide the original attempt board after replay is
ready; the replay's “Your move” control remains available for comparison.

Sign-in offers an unchecked, explicit option to add this browser's guest history to an
existing account. Registered-account history cannot be transferred this way. Guest attempts,
study progress, test results and submission receipts move in one transaction. Account
transitions and answer writes lock the affected player to avoid stranding an in-flight answer.
Test links belong to their original player; links created before owner binding require a fresh
test. Browser-origin checks reject cross-site account/progress changes, including logout.

Interactive boards support arrow keys, row Home/End, Ctrl+Home/End for board corners,
Enter/Space selection, Escape cancellation and keyboard promotion choices. Square labels
and live announcements identify movable pieces, selected pieces and legal destinations.

## Storage and deployment

Without `DATABASE_URL`, the application uses SQLite at `DB_PATH` (default `webapp/study.db`). Production uses Vercel and Neon Postgres, configured with `DATABASE_URL` and `SECRET_KEY`. Git pushes to main trigger deployment. The old PythonAnywhere host is no longer the deployment target described by these instructions.

Account data and answers must not be copied into research outputs without an explicitly consented study. The proposed learning pilot is not automatically enabled by ordinary website use.

## Verification

Use the disposable database and DOM checks in [tests/README.md](../tests/README.md). They do not contact production and do not verify physical browser layout or accessibility behavior. Move/capture sounds are Kenney's CC0 Impact Sounds.
