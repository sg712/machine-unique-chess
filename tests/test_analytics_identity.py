"""Anonymous/account analytics boundaries and shared-browser labels, offline."""
import hashlib
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from flask import session
from test_app import site
import site_analytics as store


class AnalyticsIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="muc-analytics-identity-")
        self.addCleanup(directory.cleanup)
        self.addCleanup(setattr, site, "DB", site.DB)
        site.DB = Path(directory.name) / "test.db"
        site.init_db()
        with site.app.app_context():
            conn = site.db()
            for code in ("ABC123", "OTHER1", "GUEST1"):
                conn.execute("INSERT INTO player(code, created_at) VALUES (?, ?)", (code, time.time()))
            for code in ("ABC123", "OTHER1", "ORPHAN"):
                conn.execute("INSERT INTO account(email, pw_hash, code, created_at) VALUES (?, ?, ?, ?)",
                             (code.lower() + "@example.invalid", "unused-offline-fixture", code, time.time()))
            conn.commit()

    def test_account_link_requires_matching_authenticated_and_existing_account_and_player(self):
        cases = (
            ({}, None),
            ({"code": "ABC123"}, None),
            ({"authenticated_code": "ABC123"}, None),
            ({"code": "ABC123", "authenticated_code": "OTHER1"}, None),
            ({"code": "GUEST1", "authenticated_code": "GUEST1"}, None),
            ({"code": "ORPHAN", "authenticated_code": "ORPHAN"}, None),
            ({"code": "ABSENT", "authenticated_code": "ABSENT"}, None),
            ({"code": "ABC123", "authenticated_code": "ABC123"}, "ABC123"),
        )
        for state, expected in cases:
            with self.subTest(state=state), site.app.test_request_context("/"):
                session.update(state)
                self.assertEqual(site.analytics_account(), expected)

    def test_account_link_uses_one_existence_query_without_reading_email_column(self):
        with site.app.test_request_context("/"):
            session.update(code="ABC123", authenticated_code="ABC123")
            conn = site.db()
            statements = []
            conn.set_trace_callback(statements.append)

            def deny_email(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ and table == "account" and column == "email":
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            conn.set_authorizer(deny_email)
            with patch.object(site, "me", side_effect=AssertionError("No account email lookup")), \
                 patch.object(site, "current_email", side_effect=AssertionError("No account email lookup")):
                self.assertEqual(site.analytics_account(), "ABC123")
            self.assertEqual(len(statements), 1)

    def test_dashboard_labels_multiple_single_and_unlinked_accounts(self):
        with site.app.test_request_context("/owner/analytics"):
            conn = site.db()
            now = time.time()
            for label, visitor, account in (
                ("shared-first", "a" * 32, "FFFFFF"),
                ("shared-second", "a" * 32, "000000"),
                ("single", "b" * 32, "ABC123"),
                ("guest", "c" * 32, None),
            ):
                store.insert_event(conn, event_id=hashlib.sha256(label.encode()).hexdigest(),
                                   visitor_id=visitor, account_code=account, name="page_view", path="/", at=now)
            summary = store.dashboard_summary(conn, now=now)
            rendered = site.app.jinja_env.get_template("analytics.html").render(
                summary=summary, csrf_token="offline-fixture", selected_visitor=None)
            browser_table = rendered.split('<h2 id="browsers">', 1)[1].split('<h3 id="recent-activity">', 1)[0]
            labels = re.findall(r'<span class="analytics-account">(.*?)</span>', browser_table)
            self.assertCountEqual(labels, ["2 accounts", "ABC123", "No linked account"])
            self.assertNotIn("FFFFFF", browser_table)
            self.assertNotIn("000000", browser_table)
            self.assertEqual({event["account_code"] for event in summary["recent_activity"]},
                             {None, "FFFFFF", "000000", "ABC123"})


if __name__ == "__main__":
    unittest.main()
