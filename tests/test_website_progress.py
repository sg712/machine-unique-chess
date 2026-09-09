"""Continuation and progress regressions using disposable local databases."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

os.environ.pop("DATABASE_URL", None)
_INITIAL = tempfile.TemporaryDirectory(prefix="muc-progress-import-")
os.environ["DB_PATH"] = str(Path(_INITIAL.name) / "initial.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))
import app as site
from flask import template_rendered


class WebsiteProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="muc-progress-")
        self.previous_db = site.DB
        site.DB = Path(self.tmp.name) / "test.db"
        site.app.config.update(TESTING=True)
        site.init_db()
        self.client = site.app.test_client()

    def tearDown(self):
        site.DB = self.previous_db
        self.tmp.cleanup()

    def page(self, route, client=None):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, site.app):
            response = (client or self.client).get(route)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True), contexts[-1]

    def answer(self, idx=0, correct=True):
        pos = site.BY_ID[0]["drill"][idx]
        picked = pos["best"] if correct else next(
            move for move in site.board_of(pos["fen"])["legal"] if move != pos["best"])
        response = self.client.post("/api/answer", json={"concept": 0, "idx": idx,
            "picked": picked, "seconds": 1, "request_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200)

    def row(self):
        return next(r for r in self.page("/learn")[1]["rows"] if r["c"]["id"] == 0)

    def test_continue_destination_changes_with_saved_progress(self):
        self.assertEqual((self.row()["state"], self.row()["next_url"]), ("new", "/pattern/0"))
        self.client.post("/pattern/0/studied")
        self.assertEqual((self.row()["state"], self.row()["next_url"]), ("studied", "/pattern/0/drill"))
        self.answer()
        self.assertEqual((self.row()["state"], self.row()["next_url"]), ("going", "/pattern/0/drill"))
        _, context = self.page("/pattern/0/drill")
        self.assertEqual(context["positions"][0]["idx"], 1)

    def test_signed_in_second_device_uses_server_study_state(self):
        self.client.post("/pattern/0/studied")
        self.client.post("/register", data={"email": "resume@example.invalid", "password": "local-test-password"})
        other = site.app.test_client()
        response = other.post("/login", data={"email": "resume@example.invalid", "password": "local-test-password"})
        self.assertEqual(response.status_code, 302)
        html, context = self.page("/pattern/0", other)
        self.assertTrue(context["prog"]["studied"])
        self.assertIn("const SERVER_STUDIED = true;", html)
        _, context = self.page("/learn", other)
        row = next(r for r in context["rows"] if r["c"]["id"] == 0)
        self.assertEqual(row["next_url"], "/pattern/0/drill")

    def test_repeat_attempts_do_not_change_unique_progress_or_rate(self):
        self.answer(correct=False)
        self.answer()
        self.answer()
        self.answer(idx=1, correct=False)
        html, context = self.page("/me")
        self.assertEqual(context["tot"], {"n": 2, "c": 1})
        self.assertEqual(context["attempts"], {"n": 4, "c": 2})
        self.assertIn("50%", html)
        self.assertIn("Including repeats: 4 attempts", html)
        _, drill = self.page("/pattern/0/drill")
        self.assertEqual(drill["group"], {"tried": [0, 1], "found": [0], "total": 36})

    def test_finished_group_offers_next_unfinished_group(self):
        for idx in range(36):
            self.answer(idx)
        self.assertEqual(self.row()["state"], "done")
        html, context = self.page("/pattern/0/drill")
        self.assertEqual(context["positions"], [])
        self.assertIsNotNone(context["next_group"])
        self.assertNotEqual(context["next_group"]["c"]["id"], 0)
        self.assertIn("Next group:", html)

    def test_next_group_skips_finished_and_wraps_to_earlier_groups(self):
        rows = [{"c": {"id": i}, "state": state} for i, state in enumerate(("new", "done", "going"))]
        self.assertIs(site.next_group(rows, 2), rows[0])
        self.assertIs(site.next_group(rows, 0), rows[2])
        rows[0]["state"] = "done"
        self.assertIsNone(site.next_group(rows, 2))

    def test_home_and_learn_resume_later_group_before_earlier_new_group(self):
        rows = self.page("/learn")[1]["rows"]
        cid = rows[-1]["c"]["id"]
        pos = site.BY_ID[cid]["drill"][0]
        self.client.post("/api/answer", json={"concept": cid, "idx": 0,
            "picked": pos["best"], "seconds": 1, "request_id": str(uuid.uuid4())})
        for route in ("/", "/learn"):
            _, context = self.page(route)
            self.assertEqual(context["nxt"]["c"]["id"], cid)
            self.assertEqual(context["nxt"]["next_url"], f"/pattern/{cid}/drill")
        priorities = [{"state": state} for state in ("new", "studied", "going", "done")]
        self.assertIs(site.recommended_group(priorities), priorities[2])
        self.assertIs(site.recommended_group(priorities[:2]), priorities[1])
        self.assertIsNone(site.recommended_group(priorities[-1:]))


if __name__ == "__main__":
    unittest.main()
