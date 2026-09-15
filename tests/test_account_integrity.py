"""Account transitions, browser request boundaries and test ownership, offline only."""
import os
import re
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_app import site
from flask import template_rendered


class AccountIntegrityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="muc-account-integrity-")
        self.addCleanup(directory.cleanup)
        self.addCleanup(setattr, site, "DB", site.DB)
        site.DB = Path(directory.name) / "test.db"
        site.app.config.update(TESTING=True)
        site.init_db()
        self.client = site.app.test_client()

    def owner(self, client=None):
        with (client or self.client).session_transaction() as session:
            return session.get("code")

    def snapshot(self):
        with site.app.app_context():
            return {table: [dict(row) for row in site.db().execute(f"SELECT * FROM {table} ORDER BY rowid")]
                    for table in ("player", "attempt", "studied", "account", "blindspot", "submission")}

    def answer(self, client=None, index=0):
        client = client or self.client
        position = site.BY_ID[0]["drill"][index]
        payload = {"concept": 0, "idx": index, "fen": position["fen"],
                   "picked": position["best"], "seconds": 10, "request_id": str(uuid.uuid4())}
        response = client.post("/api/answer", json=payload)
        self.assertEqual(response.status_code, 200)
        return {**payload, "owner": self.owner(client)}, response.json

    def account(self, email="destination@example.invalid"):
        client = site.app.test_client()
        self.assertEqual(client.post("/register", data={"email": email, "password": "local-test-password"}).status_code, 302)
        return client, self.owner(client)

    def make_test(self, client=None):
        client = client or self.client
        response = client.get("/test?new=1")
        token = parse_qs(urlparse(response.location).query)["attempt"][0]
        attempt = site.read_test(token)
        picks = [site.BY_ID[int(key.split(":")[0])]["drill"][int(key.split(":")[1])]["best"]
                 for key in attempt["items"]]
        return response.location, {"attempt": token, "picks": picks}

    def login(self, client=None, merge=None, password="local-test-password", email="destination@example.invalid"):
        data = {"email": email, "password": password}
        if merge is not None:
            data["merge_progress"] = merge
        return (client or self.client).post("/login", data=data)

    def test_new_test_is_bound_to_issuing_player_and_retries_remain_exact(self):
        url, payload = self.make_test()
        attempt = site.read_test(payload["attempt"])
        self.assertEqual(attempt["owner"], self.owner())
        self.assertEqual(self.client.get(url).status_code, 200)
        first = self.client.post("/api/blindspot", json=payload)
        second = self.client.post("/api/blindspot", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json, second.json)
        self.assertEqual(len(self.snapshot()["blindspot"]), 1)

    def test_stale_or_copied_test_never_renders_or_saves_under_another_player(self):
        url, payload = self.make_test()
        owner = self.owner()
        other, _ = self.account()
        for client in (site.app.test_client(), other):
            with self.subTest(owner=self.owner(client)):
                before = self.snapshot()
                with patch.object(site, "ensure_player", side_effect=AssertionError("Do not create an owner for a stale test")):
                    page = client.get(url)
                    self.assertEqual(page.status_code, 403)
                    self.assertNotIn(b"const ITEMS =", page.data)
                    self.assertEqual(client.post("/api/blindspot", json=payload).status_code, 403)
                self.assertEqual(self.snapshot(), before)
        self.client.get("/logout")
        self.assertEqual(self.login().status_code, 302)
        before = self.snapshot()
        self.assertNotEqual(self.owner(), owner)
        self.assertEqual(self.client.post("/api/blindspot", json=payload).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_account_owner_can_resume_test_after_signing_back_in(self):
        client, owner = self.account()
        url, payload = self.make_test(client)
        client.get("/logout")
        self.assertEqual(client.get(url).status_code, 403)
        self.assertEqual(self.login(client).status_code, 302)
        self.assertEqual(self.owner(client), owner)
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post("/api/blindspot", json=payload).status_code, 200)

    def test_legacy_ownerless_and_malformed_signed_tests_fail_without_writes(self):
        _, payload = self.make_test()
        attempt = site.read_test(payload["attempt"])
        before = self.snapshot()
        legacy = {key: value for key, value in attempt.items() if key != "owner"}
        for invalid in (legacy, {**attempt, "owner": None}, {**attempt, "owner": []},
                        {**attempt, "id": ""}, {**attempt, "items": [[]] * 12}):
            token = site.test_signer().dumps(invalid)
            self.assertEqual(self.client.get("/test", query_string={"attempt": token}).status_code, 400)
            self.assertEqual(self.client.post("/api/blindspot", json={**payload, "attempt": token}).status_code, 400)
            self.assertEqual(self.snapshot(), before)

    def test_placement_review_uses_existing_authored_practice_explanations(self):
        _, payload = self.make_test()
        attempt = site.read_test(payload["attempt"])
        explained = next(iter(site.PRACTICE_NOTES))
        attempt["items"] = [explained] + [key for key in site.TEST_DATA["items"] if key != explained][:11]
        payload["attempt"] = site.test_signer().dumps(attempt)
        payload["picks"] = [site.BY_ID[int(key.split(":")[0])]["drill"][int(key.split(":")[1])]["best"]
                            for key in attempt["items"]]
        response = self.client.post("/api/blindspot", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["reveal"][0]["line"]["note"]["title"], site.PRACTICE_NOTES[explained]["title"])

    def test_login_offers_guest_counts_without_creating_or_altering_progress(self):
        self.answer(); self.answer()
        self.client.post("/pattern/1/studied")
        _, payload = self.make_test()
        self.client.post("/api/blindspot", json=payload)
        before = self.snapshot()
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, site.app):
            page = self.client.get("/login")
            self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        checkbox = re.search(r'<input[^>]*name="merge_progress"[^>]*>', html).group()
        self.assertIn('type="checkbox"', checkbox)
        self.assertIn('value="on"', checkbox)
        self.assertNotIn('checked', checkbox)
        self.assertIn("Leave this unchecked if someone else used this browser.", html)
        self.assertTrue(contexts[-1]["guest_progress_available"])
        self.assertEqual(contexts[-1]["guest_progress_count"], 1)
        self.assertEqual(contexts[-1]["guest_progress"], {"positions": 1, "studied": 1, "tests": 1})
        self.assertEqual(self.snapshot(), before)

    def test_login_without_explicit_opt_in_preserves_both_histories(self):
        destination_client, destination = self.account()
        self.answer(destination_client, index=1)
        self.answer()
        source = self.owner()
        before = self.snapshot()
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.owner(), destination)
        self.assertEqual(self.snapshot(), before)
        other = site.app.test_client()
        self.assertEqual(other.post("/claim", data={"resume": source}).status_code, 302)
        self.assertEqual(self.owner(other), source)

    def test_opt_in_merges_histories_atomically_and_keeps_receipt_retries_safe(self):
        destination_client, destination = self.account()
        self.answer(destination_client)
        destination_client.post("/pattern/0/studied")
        draft, result = self.answer()
        self.answer(index=1)
        source = self.owner()
        self.client.post("/pattern/0/studied")
        self.client.post("/pattern/1/studied")
        _, test_payload = self.make_test()
        self.client.post("/api/blindspot", json=test_payload)
        before = self.snapshot()
        self.assertEqual(self.login(merge="on").status_code, 302)
        self.assertEqual(self.owner(), destination)
        after = self.snapshot()
        for table in ("attempt", "blindspot", "submission"):
            self.assertEqual(len(after[table]), len(before[table]))
            self.assertTrue(all(row["code"] == destination for row in after[table]))
        self.assertEqual({row["concept"] for row in after["studied"]}, {0, 1})
        self.assertEqual(len(after["studied"]), 2)
        self.assertFalse(any(row["code"] == source for row in after["player"]))
        with site.app.app_context():
            progress = site.concept_progress(destination)[0]
        self.assertEqual((progress["n"], progress["correct"]), (2, 2))
        transferred = {**draft, "owner": destination}
        recovered = self.client.post("/api/answer/recover", json=transferred)
        self.assertEqual(recovered.json, {"status": "saved", "result": result})
        self.assertEqual(self.client.post("/api/answer", json=transferred).json, result)
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(site.app.test_client().post("/claim", data={"resume": source}).status_code, 200)
        self.assertEqual(self.login(merge="on").status_code, 302)
        self.assertEqual(self.snapshot(), after)

    def test_wrong_password_or_non_opt_in_values_never_transfer_guest_data(self):
        self.account(); self.answer()
        source = self.owner()
        before = self.snapshot()
        self.assertEqual(self.login(merge="on", password="wrong").status_code, 200)
        self.assertEqual(self.owner(), source)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.login(merge="true").status_code, 302)
        self.assertEqual(self.snapshot(), before)

    def test_opt_in_cannot_transfer_another_registered_accounts_history(self):
        self.account()
        source_client, source = self.account("source@example.invalid")
        self.answer(source_client)
        before = self.snapshot()
        self.assertEqual(self.login(source_client, merge="on").status_code, 302)
        self.assertNotEqual(self.owner(source_client), source)
        self.assertEqual(self.snapshot(), before)

    def test_transfer_rechecks_registration_after_acquiring_its_lock(self):
        self.account(); self.answer()
        source = self.owner()
        original_lock = site._lock_player_for_account_change
        def register_while_waiting(code):
            row = original_lock(code)
            site.db().execute("INSERT INTO account(email, pw_hash, code, created_at) VALUES(?,?,?,?)",
                              ("new-account@example.invalid", "not-a-login-hash", code, 1))
            return row
        with patch.object(site, "_lock_player_for_account_change", side_effect=register_while_waiting):
            self.assertEqual(self.login(merge="on").status_code, 302)
        after = self.snapshot()
        self.assertEqual(after["attempt"][0]["code"], source)
        self.assertTrue(any(row["code"] == source for row in after["account"]))

    def test_failed_transfer_rolls_back_progress_and_leaves_session_unchanged(self):
        self.account(); self.answer()
        _, payload = self.make_test()
        self.client.post("/api/blindspot", json=payload)
        source = self.owner()
        with site.app.app_context():
            site.db().execute("""CREATE TRIGGER fail_transfer BEFORE UPDATE ON blindspot
                BEGIN SELECT RAISE(ABORT, 'simulated transfer failure'); END""")
            site.db().commit()
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.login(merge="on")
        self.assertEqual(self.owner(), source)
        self.assertEqual(self.snapshot(), before)

    def test_answer_started_before_guest_transfer_cannot_write_to_retired_player(self):
        for kind in ("drill", "test"):
            client = site.app.test_client()
            client.get("/pattern/0/drill")
            owner = self.owner(client)
            position = site.BY_ID[0]["drill"][0]
            payload = {"owner": owner, "concept": 0, "idx": 0, "fen": position["fen"],
                       "picked": position["best"], "request_id": str(uuid.uuid4())}
            if kind == "test":
                _, payload = self.make_test(client)
            original_lock = site._lock_player_for_account_change
            def transfer_before_lock_returns(code):
                original_lock(code)
                site.db().execute("DELETE FROM player WHERE code=?", (code,))
                site.db().commit()
                return None
            with self.subTest(kind=kind), patch.object(site, "_lock_player_for_account_change", side_effect=transfer_before_lock_returns):
                response = client.post("/api/answer" if kind == "drill" else "/api/blindspot", json=payload)
                self.assertEqual(response.status_code, 403)
            after = self.snapshot()
            for table in ("attempt", "blindspot", "submission"):
                self.assertEqual(after[table], [])
            self.assertFalse(any(row["code"] == owner for row in after["player"]))

    def test_cross_origin_browser_requests_cannot_change_progress_or_sessions(self):
        self.answer()
        owner = self.owner()
        _, payload = self.make_test()
        before = self.snapshot()
        requests = [("post", "/register", {"data": {"email": "cross@example.invalid", "password": "long-password"}}),
                    ("post", "/login", {"data": {"email": "cross@example.invalid", "password": "long-password"}}),
                    ("post", "/claim", {"data": {"resume": owner}}),
                    ("post", "/pattern/1/studied", {}),
                    ("post", "/api/blindspot", {"json": payload}),
                    ("post", "/api/answer", {"json": {}}), ("get", "/logout", {})]
        for method, path, options in requests:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, headers={"Origin": "https://outside.example", "Sec-Fetch-Site": "cross-site"}, **options)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(self.owner(), owner)
                self.assertEqual(self.snapshot(), before)

    def test_origin_referer_and_fetch_metadata_independently_reject_unsafe_origins(self):
        before = self.snapshot()
        for headers in ({"Origin": "https://outside.example"}, {"Origin": "null"},
                        {"Referer": "https://outside.example/form"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Sec-Fetch-Site": "same-site", "Origin": "http://localhost"},
                        {"Origin": "http://localhost:9999"}, {"Origin": "http://outside.example@localhost"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post("/pattern/0/studied", headers=headers).status_code, 403)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.get("/research", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 200)

    def test_same_origin_forms_fetches_and_direct_logout_keep_working(self):
        for headers in ({"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"},
                        {"Referer": "http://localhost/pattern/0"}, {}, {"Sec-Fetch-Site": "none"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post("/pattern/0/studied", headers=headers).status_code, 302)
        self.assertEqual(self.client.get("/logout", headers={"Sec-Fetch-Site": "same-origin"}).status_code, 302)
        self.assertIsNone(self.owner())

    def test_vercel_https_termination_accepts_actual_host_but_never_forwarded_host(self):
        with patch.dict(os.environ, {"VERCEL": "1"}):
            response = self.client.post("/pattern/0/studied", base_url="http://www.machine-unique-chess.com",
                headers={"Origin": "https://www.machine-unique-chess.com", "Sec-Fetch-Site": "same-origin"})
            self.assertEqual(response.status_code, 302)
            before = self.snapshot()
            response = self.client.post("/pattern/1/studied", base_url="http://www.machine-unique-chess.com",
                headers={"Origin": "https://outside.example", "X-Forwarded-Host": "outside.example",
                         "X-Forwarded-Proto": "https", "Forwarded": "host=outside.example;proto=https"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
