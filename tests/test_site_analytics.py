"""Analytics counts, privacy boundaries and retention using disposable SQLite."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))
import site_analytics as analytics


NOW = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc).timestamp()
DAY = 86400


class SiteAnalyticsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="muc-analytics-")
        self.addCleanup(directory.cleanup)
        self.db = sqlite3.connect(str(Path(directory.name) / "analytics.db"))
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        for statement in analytics.SCHEMA_STATEMENTS:
            self.db.execute(statement)
        self.db.commit()

    def event(self, label, **kwargs):
        args = {"event_id": hashlib.sha256(label.encode()).hexdigest(),
                "name": "page_view", "path": "/", "at": NOW - 60, **kwargs}
        return analytics.insert_event(self.db, **args)

    def summary(self, **kwargs):
        return analytics.dashboard_summary(self.db, now=NOW, **kwargs)

    def test_deduplication_does_not_relink_or_update_browser(self):
        self.assertTrue(self.event("same", visitor_id="a" * 32, visit_id="b" * 32))
        self.assertFalse(self.event("same", visitor_id="c" * 32, visit_id="d" * 32, at=NOW))
        self.assertEqual(self.summary()["totals"]["page_views"], 1)
        self.assertEqual([dict(row) for row in self.db.execute("SELECT * FROM analytics_visitor")],
                         [{"id": "a" * 32, "first_at": NOW - 60, "last_at": NOW - 60, "excluded": 0}])

    def test_anonymous_counts_never_create_browser_or_account_links(self):
        self.event("anonymous", source_host="example.org", device="mobile")
        summary = self.summary()
        self.assertEqual(summary["totals"]["page_views"], 1)
        self.assertEqual(summary["totals"]["anonymous_page_views"], 1)
        self.assertEqual(summary["totals"]["browser_ids"], 0)
        self.assertEqual(summary["totals"]["visits"], 0)
        self.assertEqual(summary["visitors"], [])
        self.assertEqual(summary["sources"][0]["source_host"], "example.org")
        event = summary["recent_activity"][0]
        self.assertIsNone(event["visitor_id"])
        self.assertIsNone(event["visit_id"])
        self.assertIsNone(event["account_code"])
        for extra in ({"account_code": "ABC123"}, {"visit_id": "a" * 32}):
            with self.assertRaisesRegex(ValueError, "Anonymous"):
                self.event("forbidden", **extra)
        self.assertEqual(self.summary()["totals"]["events"], 1)

    def test_exclusions_apply_to_every_aggregate_and_history_and_can_be_reversed(self):
        self.event("owner", visitor_id="a" * 32, visit_id="b" * 32, source_host="owner.invalid")
        self.event("public", visitor_id="c" * 32, visit_id="d" * 32, source_host="public.invalid")
        self.assertTrue(analytics.set_visitor_excluded(self.db, "a" * 32, True))
        self.event("owner-again", visitor_id="a" * 32, visit_id="b" * 32, at=NOW)
        summary = self.summary()
        self.assertEqual(summary["totals"]["page_views"], 1)
        self.assertEqual(sum(row["page_views"] for row in summary["daily"]), 1)
        self.assertEqual(sum(row["page_views"] for row in summary["pages"]), 1)
        self.assertEqual(sum(row["page_views"] for row in summary["devices"]), 1)
        self.assertEqual(summary["sources"], [{"source_host": "public.invalid", "events": 1, "page_views": 1}])
        self.assertEqual(summary["events"], [{"name": "page_view", "events": 1, "browser_ids": 1}])
        self.assertEqual([row["id"] for row in summary["visitors"]], ["c" * 32])
        self.assertEqual(len(summary["recent_activity"]), 1)
        self.assertEqual(analytics.visitor_timeline(self.db, "a" * 32, now=NOW), [])
        self.assertEqual(summary["excluded_visitors"][0]["id"], "a" * 32)
        self.assertTrue(analytics.set_visitor_excluded(self.db, "a" * 32, False))
        self.assertEqual(self.summary()["totals"]["page_views"], 3)
        self.assertFalse(analytics.set_visitor_excluded(self.db, "e" * 32, True))

    def test_account_exclusion_and_guest_browser_remain_distinct(self):
        self.event("signed-in", visitor_id="a" * 32, account_code="OWNER1")
        self.event("guest", visitor_id="b" * 32)
        self.event("anonymous")
        summary = self.summary(exclude_accounts=("OWNER1",))
        self.assertEqual(summary["totals"]["page_views"], 2)
        self.assertEqual(summary["totals"]["anonymous_page_views"], 1)
        self.assertEqual(summary["totals"]["browser_ids"], 1)
        self.assertEqual([row["id"] for row in summary["visitors"]], ["b" * 32])
        self.assertIsNone(summary["visitors"][0]["account_code"])
        self.assertEqual(analytics.visitor_timeline(self.db, "a" * 32, now=NOW, exclude_accounts=("OWNER1",)), [])

    def test_saved_tests_and_practice_answers_have_different_denominators(self):
        self.event("test-start", name="test_started", path="/test")
        self.event("test-result", name="test_completed", path="/test", n=12, correct=8)
        for i in range(12):
            self.event(f"answer-{i}", name="practice_answer", path="/pattern/0/drill", n=1, correct=int(i < 9))
        self.event("study", name="study_completed", path="/pattern/0", concept=0)
        totals = self.summary()["totals"]
        self.assertEqual(totals["tests_started"], 1)
        self.assertEqual(totals["tests_completed"], 1)
        self.assertEqual(totals["practice_answers"], 12)
        self.assertEqual(totals["practice_correct"], 9)
        self.assertEqual(totals["studies_completed"], 1)
        self.assertEqual(totals["page_views"], 0)
        self.assertNotIn("learning", totals)
        self.assertNotIn("duration", totals)

    def test_utc_date_window_includes_boundary_and_excludes_future(self):
        start = datetime(2026, 9, 10, tzinfo=timezone.utc).timestamp()
        midnight = datetime(2026, 9, 16, tzinfo=timezone.utc).timestamp()
        self.event("too-old", at=start - 0.01)
        self.event("boundary", at=start)
        self.event("just-before-midnight", at=midnight - 0.01)
        self.event("midnight", at=midnight)
        self.event("now", at=NOW)
        self.event("future", at=NOW + 0.01)
        result = self.summary(days=7)
        self.assertEqual(result["start_at"], start)
        self.assertEqual(result["totals"]["page_views"], 4)
        self.assertEqual(len(result["daily"]), 7)
        self.assertEqual(result["daily"][0]["day"], "2026-09-10")
        self.assertEqual(result["daily"][0]["page_views"], 1)
        self.assertEqual(result["daily"][-2]["page_views"], 1)
        self.assertEqual(result["daily"][-1]["page_views"], 2)

    def test_returning_browser_means_prior_period_or_multiple_identified_visits(self):
        self.event("older", visitor_id="a" * 32, visit_id="a" * 32, at=NOW - 10 * DAY)
        self.event("old-returns", visitor_id="a" * 32, visit_id="b" * 32)
        self.event("first-this-period", visitor_id="c" * 32, visit_id="c" * 32)
        self.event("second-this-period", visitor_id="c" * 32, visit_id="d" * 32)
        self.event("new-one-visit", visitor_id="e" * 32, visit_id="e" * 32)
        self.event("new-repeat-page", visitor_id="e" * 32, visit_id="e" * 32)
        summary = self.summary(days=7)
        self.assertEqual(summary["totals"]["browser_ids"], 3)
        self.assertEqual(summary["totals"]["returning_browser_ids"], 2)
        self.assertEqual(summary["totals"]["visits"], 4)

    def test_rejects_unknown_private_fields_and_unsafe_dimensions_without_writes(self):
        invalid = [
            {"name": "email@example.invalid"}, {"path": "/test?attempt=private"},
            {"path": "/private/token"}, {"path": "https://site.invalid/"},
            {"source_host": "https://example.org/?email=a@example.org"},
            {"source_host": "192.0.2.1"}, {"device": "Full browser user agent"},
            {"event_id": "bad-id"}, {"visitor_id": "email@example.invalid"},
            {"visitor_id": "a" * 32, "account_code": "email@example.invalid"},
            {"visitor_id": "a" * 32, "visit_id": "unexpected-id"},
            {"at": float("nan")}, {"at": float("inf")}, {"at": -1},
            {"at": True}, {"correct": 2, "n": 1}, {"n": 0},
            {"concept": True}, {"concept": 100}, {"correct": "1"},
            {"name": "practice_answer", "correct": 2},
        ]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.event("invalid", **fields)
        with self.assertRaises(TypeError):
            self.event("private-field", email="no@example.invalid")
        self.assertEqual(self.summary()["totals"]["events"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM analytics_visitor").fetchone()[0], 0)

    def test_referrer_ingress_drops_everything_except_safe_hostname(self):
        self.assertEqual(analytics.source_host("https://NEWS.Example.Org/story?email=private#token"), "news.example.org")
        for raw in ("https://user:password@example.org/path", "https://192.0.2.1/",
                    "https://[2001:db8::1]/", "javascript:secret", "not a url", None):
            self.assertEqual(analytics.source_host(raw), "")
        self.assertEqual(analytics.canonical_path("/concept/01/drill"), "/pattern/1/drill")
        self.assertEqual(analytics.canonical_path("/privacy"), "/privacy")

    def test_retention_touches_only_analytics_and_keeps_first_recorded_date(self):
        cutoff = NOW - 90 * DAY
        self.db.execute("CREATE TABLE functional_progress (value TEXT)")
        self.db.execute("INSERT INTO functional_progress VALUES ('keep')")
        self.event("expired", at=cutoff - 1, visitor_id="a" * 32)
        self.event("boundary", at=cutoff, visitor_id="b" * 32)
        self.event("recent", visitor_id="c" * 32)
        result = analytics.prune_retention(self.db, now=NOW)
        self.assertEqual(result, {"events_deleted": 1, "visitors_deleted": 1, "cutoff": cutoff})
        self.assertEqual(self.db.execute("SELECT value FROM functional_progress").fetchone()[0], "keep")
        self.assertEqual(self.summary()["recorded_since_at"], cutoff - 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM analytics_event").fetchone()[0], 2)

    def test_cadence_is_atomic_and_transactions_belong_to_caller(self):
        self.assertTrue(analytics.claim_retention_due(self.db, now=NOW))
        self.assertFalse(analytics.claim_retention_due(self.db, now=NOW + DAY - 1))
        self.event("rollback", visitor_id="a" * 32)
        self.db.rollback()
        self.assertEqual(self.summary()["totals"]["events"], 0)
        self.assertIsNone(self.summary()["recorded_since_at"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM analytics_visitor").fetchone()[0], 0)
        self.assertTrue(analytics.claim_retention_due(self.db, now=NOW))
        self.db.commit()
        self.assertFalse(analytics.claim_retention_due(self.db, now=NOW))
        self.assertTrue(analytics.claim_retention_due(self.db, now=NOW + DAY))
        self.db.rollback()
        self.assertTrue(analytics.claim_retention_due(self.db, now=NOW + DAY))

    def test_lists_are_bounded_and_empty_ranges_are_zero_filled(self):
        empty = self.summary(days=7)
        self.assertEqual(len(empty["daily"]), 7)
        self.assertTrue(all(value == 0 for value in empty["totals"].values()))
        self.assertIsNone(empty["recorded_since_at"])
        for i in range(105):
            self.event(f"many-{i}", visitor_id=f"{i:032x}", at=NOW - i)
        summary = self.summary(recent_limit=3)
        self.assertEqual(len(summary["visitors"]), 100)
        self.assertEqual(len(summary["recent_activity"]), 3)
        self.assertEqual(summary["totals"]["browser_ids"], 105)
        self.assertEqual(len(analytics.visitor_timeline(self.db, "0" * 32, now=NOW, limit=1)), 1)
        for kwargs in ({"days": 0}, {"days": 91}, {"days": True},
                       {"recent_limit": 201}, {"exclude_accounts": ["email@example.invalid"]}):
            with self.assertRaises(ValueError):
                self.summary(**kwargs)


if __name__ == "__main__":
    unittest.main()
