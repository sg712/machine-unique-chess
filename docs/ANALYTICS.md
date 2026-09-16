# Website analytics

The application records first-party usage events in the same SQLite/Postgres
database as the trainer, using separate tables and connections. It does not send
events to an external analytics service or copy usage into research datasets.

## Owner access

Open `/owner/login` and enter the owner access key saved in the private local
`Analytics owner access.txt` file. Never put the key in a URL or commit it.
`webapp/owner_analytics.json` contains only its SHA-256 verification hash.
The generated key has 256 bits of entropy; ordinary account sign-in does not
grant analytics access. Owner sessions expire after 12 hours. Replacing the
verification hash with a newly generated key's hash revokes existing sessions
after deployment. Preserve the application's `SECRET_KEY` between deployments.

Successful owner sign-in excludes that browser's future analytics and hides
earlier events linked to its current analytics visitor ID. Past anonymous views
cannot be identified and removed as the owner's. Owner pages are private,
uncacheable and excluded from search indexing; their forms require an owner
session and a matching CSRF token. Ordinary site logout leaves the browser's
analytics preference in place.

The dashboard at `/owner/analytics` has 7-day and 30-day UTC views of:

- Page views, referring hostnames and broad device categories.
- Opted-in browser IDs and visits, including returning browsers.
- Practice, review, study and test pages opened.
- Newly saved practice answers, test results and marked-studied actions.
- Registrations and successful sign-ins.
- Recent events and individual opted-in browser histories, with existing account
  codes when those events were recorded while signed in.

These are events and browser IDs, not verified people or an ordered conversion
funnel. A visit changes after 30 minutes of inactivity. Returning browsers have
an earlier first visit or multiple visits within the selected range. Opening
practice does not prove an answer was attempted; marking a study group complete
does not prove it was read. A browser history filter changes the activity list,
while dashboard totals remain for the full selected period.

## Visitor preferences and counting

Without optional visit history, page and action counts have no persistent
analytics ID or account association. Allowing history on the page prompt or
`/privacy` links future activity with a random browser ID. Existing anonymous
events stay anonymous. Signed-in activity links to the existing account only
when visit history is enabled. Analytics never queries or stores account emails.

Global Privacy Control and Do Not Track disable optional history. Anonymous
counts continue unless the visitor excludes the browser. Exclusion hides the
current visitor ID's earlier events from the dashboard and stops future events.
Including the browser again starts future anonymous counting; old excluded
history stays excluded unless the owner explicitly includes that ID again.
Preferences expire after 90 days. Functional account progress remains separate.

Browser views use signed, expiring page tokens and deduplicate a page's initial
event. New page loads are new views. Server completion events are written only
after a successful application commit; retrying or recovering an existing
receipt does not create a second completion. Marked-studied events deduplicate
by account, group and UTC day. Analytics failures do not roll back saved progress.

Known automated user agents and prefetch requests are ignored. This is not a
bot-proof measurement system, and blocked JavaScript or network failures can
cause missing page views. Counts begin with this feature's deployment; earlier
visits cannot be reconstructed from these tables.

## Storage and maintenance

Analytics records contain only allowlisted paths/events, timestamps, coarse
device classes, referring hostnames, exercise metadata and optional random
visitor/visit IDs and account codes. No IP addresses, full user-agent strings,
query strings, full referring URLs, form values or chess solutions are stored.
Host infrastructure logs are separate from these application analytics tables.

`analytics_event`, `analytics_visitor` and `analytics_meta` hold measurement
data. `analytics_owner_session` stores hashes of temporary owner tokens.
Startup creates these tables within the application's existing serialized
Postgres migration transaction. The dashboard uses database aggregates and
bounded result lists rather than loading every event.

Normal analytics traffic triggers cleanup at most once per day, removing events
older than 90 days and expired owner sessions. An inactive database may retain
older physical records until the next cleanup. Analytics write failures log
`analytics_write_failed:<exception class>` without request data or credentials.

## Verification

Disposable SQLite/Flask and offline DOM tests cover event deduplication, saved
action recording, consent, bot filtering, failure isolation, retention, owner
authentication, key rotation, CSRF, exclusion and dashboard rendering. The
Postgres startup tests preserve the requirement that the advisory migration
lock precedes every DDL statement. SQL compatibility has also been inspected
against the production adapter. These checks do not replace a live production
database test or a browser layout review.
