"""Exercise first-party analytics and private owner access offline."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import uuid

from test_app import site
import site_analytics as store


class AnalyticsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="muc-analytics-test-")
        self.addCleanup(self.folder.cleanup)
        site.DB = Path(self.folder.name) / "site.db"
        site.init_db()
        site.app.config.update(TESTING=True, ANALYTICS_SECURE_COOKIE=False)
        self.old_key = site.app.config["ANALYTICS_OWNER_KEY_SHA256"]
        self.key = "offline-owner-key-" + uuid.uuid4().hex
        site.app.config["ANALYTICS_OWNER_KEY_SHA256"] = hashlib.sha256(self.key.encode()).hexdigest()
        self.addCleanup(site.app.config.__setitem__, "ANALYTICS_OWNER_KEY_SHA256", self.old_key)
        self.client = self.browser()

    def browser(self):
        client = site.app.test_client()
        client.environ_base["HTTP_USER_AGENT"] = "Mozilla/5.0 Desktop Chrome/140"
        return client

    def rows(self, table="analytics_event"):
        with site.app.app_context():
            return [dict(r) for r in site.db().execute(f"SELECT * FROM {table}").fetchall()]

    def context(self, path="/", client=None, headers=None):
        response = (client or self.client).get(path, headers=headers or {})
        self.assertEqual(response.status_code, 200)
        match = re.search(r'<script type="application/json" id="analytics-context">(.*?)</script>', response.text, re.S)
        self.assertIsNotNone(match)
        return json.loads(match[1])

    def preference(self, choice, client=None, headers=None):
        client = client or self.client
        context = self.context("/privacy", client)
        return client.post("/api/analytics/preference", json={"choice": choice, "page_token": context["page_token"]},
                           headers={"Origin": "http://localhost", **(headers or {})})

    def page(self, context=None, *, consent=False, client=None):
        client = client or self.client
        context = context or self.context(client=client)
        return client.post("/api/analytics/page", json={"page_token": context["page_token"],
                           "event_id": str(uuid.uuid4()), "visitor_consent": consent}, headers={"Origin": "http://localhost"})

    def answer(self, key=None, client=None):
        return (client or self.client).post("/api/answer", json={"concept": 0, "idx": 0,
            "picked": site.BY_ID[0]["drill"][0]["best"], "seconds": 1,
            "request_id": key or str(uuid.uuid4())})

    def owner_login(self, client=None):
        response = (client or self.client).post("/owner/login", data={"access_key": self.key}, headers={"Origin":"http://localhost"})
        self.assertEqual(response.status_code, 302)
        return response

    def owner_csrf(self, client=None):
        response = (client or self.client).get("/owner/analytics")
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="csrf_token" value="([a-f0-9]+)"', response.text)[1]

    def test_anonymous_page_counts_once_without_cookies_or_identity(self):
        context = self.context(headers={"Referer":"https://example.org/article?email=private%40example.com"})
        for _ in range(2):
            response = self.page(context)
            self.assertEqual(response.status_code, 204)
            self.assertNotIn("Set-Cookie", response.headers)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_host"], "example.org")
        self.assertIsNone(rows[0]["visitor_id"])
        self.assertIsNone(rows[0]["visit_id"])
        self.assertIsNone(rows[0]["account_code"])
        self.assertNotIn("private", json.dumps(rows))
        self.assertEqual(self.rows("analytics_visitor"), [])

    def test_optin_allocates_one_identity_and_does_not_relabel_old_page(self):
        original = self.context()
        self.page(original)
        response = self.preference("yes")
        self.assertEqual(response.json, {"consent":"yes", "excluded":False})
        cookie = self.client.get_cookie("muc_usage")
        self.assertTrue(cookie.http_only)
        a = self.context("/learn")
        b = self.context("/research")
        self.page(a, consent=True)
        self.page(b, consent=True)
        self.page(original, consent=True)
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertIsNone(next(r for r in rows if r["path"] == "/")["visitor_id"])
        linked = [r for r in rows if r["visitor_id"]]
        self.assertEqual(len({r["visitor_id"] for r in linked}), 1)
        self.assertEqual(len({r["visit_id"] for r in linked}), 1)

    def test_cannot_force_optin_with_page_payload_or_external_preference(self):
        context = self.context()
        self.page(context, consent=True)
        self.assertIsNone(self.rows()[0]["visitor_id"])
        response = self.client.post("/analytics/preference", data={"choice":"yes", "page_token":context["page_token"]},
                                    headers={"Origin":"https://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/api/analytics/preference", json={"choice":"yes", "page_token":context["page_token"]}).status_code, 400)

    def test_privacy_signals_revoke_old_linking(self):
        self.preference("yes")
        self.page(consent=True)
        context = self.context("/learn", headers={"Sec-GPC":"1"})
        self.assertEqual(context["consent"], "no")
        self.page(context, consent=True)
        self.assertIsNone(next(r for r in self.rows() if r["path"] == "/learn")["visitor_id"])
        self.assertEqual(self.preference("yes", headers={"DNT":"1"}).json["consent"], "no")

    def test_only_real_new_answers_count_and_analytics_failure_does_not_undo_them(self):
        key = str(uuid.uuid4())
        self.assertEqual(self.answer(key).status_code, 200)
        self.assertEqual(self.answer(key).status_code, 200)
        events = self.rows()
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["name"], events[0]["correct"], events[0]["n"]), ("practice_answer",1,1))
        with patch.object(store, "insert_event", side_effect=RuntimeError("synthetic telemetry failure")):
            self.assertEqual(self.answer().status_code, 200)
        self.assertEqual(len(self.rows("attempt")), 2)
        self.assertEqual(len(self.rows()), 1)

    def test_test_receipt_replay_and_invalid_inputs_do_not_inflate_completion(self):
        response = self.client.get("/test?new=1")
        from urllib.parse import parse_qs, urlparse
        token = parse_qs(urlparse(response.location).query)["attempt"][0]
        item = site.read_test(token)
        picks = [site.BY_ID[int(k.split(":")[0])]["drill"][int(k.split(":")[1])]["best"] for k in item["items"]]
        self.assertEqual(self.client.post("/api/blindspot", json={"attempt":token,"picks":[]}).status_code,400)
        for _ in range(2):
            self.assertEqual(self.client.post("/api/blindspot", json={"attempt":token,"picks":picks}).status_code,200)
        events=self.rows()
        self.assertEqual(len(events),1)
        self.assertEqual((events[0]["name"],events[0]["n"],events[0]["correct"]),("test_completed",12,12))
        self.assertEqual(len(self.rows("blindspot")),1)

    def test_registered_account_link_requires_optin(self):
        self.answer()
        self.client.post("/register", data={"email":"private@example.invalid","password":"not-a-real-password"})
        self.assertTrue(all(r["account_code"] is None for r in self.rows()))
        self.preference("yes")
        self.answer()
        with self.client.session_transaction() as state:
            account = state["authenticated_code"]
        self.assertEqual(self.rows()[-1]["account_code"],account)
        self.assertNotIn("private@example.invalid",json.dumps(self.rows()))

    def test_optout_and_normal_logout_preserve_preference(self):
        self.preference("yes")
        self.answer()
        self.preference("no")
        self.client.get("/logout")
        self.assertEqual(self.context()["consent"],"no")
        self.answer()
        self.assertIsNone(self.rows()[-1]["visitor_id"])

    def test_exclusion_removes_prior_browser_counts_and_stops_future_events(self):
        self.preference("yes")
        self.page(consent=True)
        self.preference("exclude")
        self.page()
        self.answer()
        self.assertEqual(len(self.rows()),1)
        with site.app.app_context():
            self.assertEqual(store.dashboard_summary(site.db())["totals"]["events"],0)
        self.preference("include")
        self.page()
        self.assertEqual(len(self.rows()),2)
        self.assertIsNone(self.rows()[-1]["visitor_id"])

    def test_owner_access_is_independent_of_user_sessions_and_key_rotation(self):
        self.assertEqual(self.client.get("/owner/analytics").status_code,302)
        with self.client.session_transaction() as state:
            state["analytics_owner"] = True
        self.assertEqual(self.client.get("/owner/analytics").status_code,302)
        self.assertEqual(self.client.post("/owner/login",data={"access_key":"wrong"}).status_code,403)
        self.owner_login()
        response=self.client.get("/owner/analytics?days=7")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers["Cache-Control"],"private, no-store")
        self.assertIn("noindex",response.headers["X-Robots-Tag"])
        self.assertNotIn(self.key,response.text)
        site.app.config["ANALYTICS_OWNER_KEY_SHA256"] = "a"*64
        self.assertEqual(self.client.get("/owner/analytics").status_code,302)

    def test_owner_login_excludes_current_browser_and_logout_revokes_cookie(self):
        self.preference("yes")
        self.page(consent=True)
        self.owner_login()
        self.assertTrue(self.context()["excluded"])
        self.assertTrue(self.preference("yes").json["excluded"])
        self.answer()
        with site.app.app_context():
            self.assertEqual(store.dashboard_summary(site.db())["totals"]["events"],0)
        csrf=self.owner_csrf()
        self.assertEqual(self.client.post("/owner/logout",data={"csrf_token":"wrong"}).status_code,403)
        self.assertEqual(self.client.post("/owner/logout",data={"csrf_token":csrf}).status_code,302)
        self.assertEqual(self.client.get("/owner/analytics").status_code,302)

    def test_owner_exclusion_requires_csrf_and_browser_details_stay_private(self):
        visitor=self.browser()
        self.preference("yes",client=visitor)
        self.page(consent=True,client=visitor)
        vid=self.rows()[0]["visitor_id"]
        self.owner_login()
        csrf=self.owner_csrf()
        data={"visitor_id":vid,"excluded":"1","csrf_token":csrf,"days":"7"}
        self.assertEqual(visitor.post("/owner/analytics/exclude",data=data).status_code,403)
        self.assertEqual(self.client.post("/owner/analytics/exclude",data={**data,"csrf_token":"wrong"}).status_code,403)
        self.assertEqual(self.client.post("/owner/analytics/exclude",data=data,headers={"Origin":"https://evil.example"}).status_code,403)
        self.assertEqual(self.client.post("/owner/analytics/exclude",data=data).status_code,302)
        self.assertEqual(self.rows("analytics_visitor")[0]["excluded"],1)
        response=self.client.get("/owner/analytics?visitor="+vid)
        self.assertEqual(response.status_code,200)
        self.assertNotIn(vid,visitor.get("/").text)

    def test_signed_page_validation_known_bots_and_canonical_integer_routes(self):
        context=self.context("/pattern/0001")
        self.assertEqual(context["path"],"/pattern/1")
        self.assertEqual(self.client.post("/api/analytics/page",json={"page_token":"forged"}).status_code,400)
        bot=self.browser();bot.environ_base["HTTP_USER_AGENT"]="Googlebot"
        self.page(client=bot)
        self.assertEqual(self.rows(),[])
        self.page(context)
        self.assertEqual({r["name"] for r in self.rows()},{"page_view","study_opened"})

    def test_preference_html_fallback_and_routine_retention(self):
        context=self.context("/privacy")
        response=self.client.post("/analytics/preference",data={"page_token":context["page_token"],"choice":"no"},
                                  headers={"Referer":"http://localhost/privacy"})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.context()["consent"],"no")
        with site.app.app_context():
            store.insert_event(site.db(),event_id="e"*64,name="page_view",path="/",at=1)
            site.db().commit()
        self.page()
        self.assertEqual(len(self.rows()),1)
        self.assertNotEqual(self.rows()[0]["id"],"e"*64)


if __name__ == "__main__":
    unittest.main()
