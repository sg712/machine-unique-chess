"""Mixed review uses each player's latest practice outcome, never test answers."""
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from flask import template_rendered
from test_app import site


class MixedReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="muc-mixed-review-")
        self.previous_db = site.DB
        site.DB = Path(self.tmp.name) / "test.db"
        site.app.config.update(TESTING=True)
        site.init_db()
        self.client = site.app.test_client()

    def tearDown(self):
        site.DB = self.previous_db
        self.tmp.cleanup()

    def page(self, route="/review", client=None):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, site.app):
            response = (client or self.client).get(route)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True), contexts[-1]

    def answer(self, cid=0, idx=0, correct=False, client=None):
        client = client or self.client
        client.get("/review")
        with client.session_transaction() as session:
            owner = session["code"]
        position = site.BY_ID[cid]["drill"][idx]
        picked = position["best"] if correct else next(
            move for move in site.board_of(position["fen"])["legal"] if move != position["best"])
        payload = {"owner": owner, "concept": cid, "idx": idx,
                   "fen": position["fen"], "picked": picked, "seconds": 9,
                   "request_id": str(uuid.uuid4())}
        result = client.post("/api/answer", json=payload)
        self.assertEqual(result.status_code, 200)
        return payload, result.json

    def test_latest_miss_reenters_after_a_success_and_metrics_keep_their_meanings(self):
        # Every row has the same wall-clock timestamp; insertion order breaks ties.
        with patch.object(site.time, "time", return_value=int(site.time.time())):
            self.answer(0, 0)
            self.answer(1, 0, correct=True)
            self.answer(0, 1)
            self.answer(0, 0, correct=True)
            self.answer(1, 0)
            self.answer(0, 1, correct=True)
            self.answer(0, 0)
            self.answer(2, 0)
        _, review = self.page()
        self.assertEqual([p["idx"] for p in review["positions"]], ["1:0", "0:0", "2:0"])
        self.assertEqual([(p["concept"], p["source_idx"]) for p in review["positions"]],
                         [(1, 0), (0, 0), (2, 0)])
        _, profile = self.page("/me")
        self.assertEqual(profile["practice"], {"tried": 4, "first": 1, "latest": 1, "review": 3})
        self.assertEqual(profile["tot"], {"n": 4, "c": 3})
        self.assertEqual(profile["attempts"], {"n": 8, "c": 3})
        self.assertEqual(profile["prog"][0]["correct"], 2)
        self.assertEqual(profile["prog"][0]["first"], 0)
        self.assertEqual(profile["prog"][0]["review"], 1)
        _, local_review = self.page("/pattern/0/drill?mode=missed")
        self.assertEqual([p["idx"] for p in local_review["positions"]], [0])

    def test_receipt_retries_do_not_add_attempts_or_change_review_priority(self):
        first_payload, first_result = self.answer(0, 0)
        self.answer(1, 0)
        retry = self.client.post("/api/answer", json=first_payload)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json, first_result)
        _, context = self.page()
        self.assertEqual([p["idx"] for p in context["positions"]], ["0:0", "1:0"])
        self.assertEqual(self.page("/me")[1]["attempts"]["n"], 2)
        saved_payload, saved_result = self.answer(0, 0, correct=True)
        self.assertEqual([p["idx"] for p in self.page()[1]["positions"]], ["1:0"])
        recovered = self.client.post("/api/answer/recover", json=saved_payload)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json, {"status": "saved", "result": saved_result})
        self.assertEqual(self.page("/me")[1]["attempts"]["n"], 3)

    def test_test_results_never_enter_the_practice_review_queue(self):
        self.answer(0, 0)
        before = self.page("/me")[1]
        target = self.client.get("/test?new=1").location
        token = parse_qs(urlparse(target).query)["attempt"][0]
        attempt = site.read_test(token)
        picks = []
        for key in attempt["items"]:
            cid, idx = map(int, key.split(":"))
            position = site.BY_ID[cid]["drill"][idx]
            picks.append(next(move for move in site.board_of(position["fen"])["legal"]
                              if move != position["best"]))
        response = self.client.post("/api/blindspot", json={"attempt": token, "picks": picks})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["correct"], 0)
        after = self.page("/me")[1]
        self.assertEqual(after["practice"], before["practice"])
        self.assertEqual(after["attempts"], before["attempts"])
        self.assertEqual(after["bs"]["n"], 12)
        self.assertEqual([p["idx"] for p in self.page()[1]["positions"]], ["0:0"])

    def test_player_queues_receipts_and_cleared_empty_state_stay_separate(self):
        other = site.app.test_client()
        first_payload, _ = self.answer(0, 0)
        self.answer(1, 0, client=other)
        self.assertEqual([p["idx"] for p in self.page()[1]["positions"]], ["0:0"])
        self.assertEqual([p["idx"] for p in self.page(client=other)[1]["positions"]], ["1:0"])
        self.assertEqual(other.post("/api/answer", json=first_payload).status_code, 403)
        self.assertEqual(other.post("/api/answer/recover", json=first_payload).status_code, 403)
        self.answer(0, 0, correct=True)
        html, cleared = self.page()
        self.assertEqual(cleared["positions"], [])
        self.assertEqual(cleared["group"]["tried"], ["0:0"])
        self.assertIn("Nothing waiting for review", html)
        fresh_html, fresh = self.page(client=site.app.test_client())
        self.assertEqual(fresh["group"]["tried"], [])
        self.assertIn("Try a practice session first", fresh_html)
        self.assertEqual(len(fresh["all_positions"]), 288)
        self.assertEqual(len({p["idx"] for p in fresh["all_positions"]}), 288)
        self.assertTrue(all("best" not in p for p in fresh["all_positions"]))

    def test_obsolete_position_rows_cannot_change_current_first_latest_or_ever_results(self):
        self.page()
        with self.client.session_transaction() as session:
            owner = session["code"]
        obsolete_fen = site.chess.STARTING_FEN
        self.assertNotEqual(obsolete_fen, site.BY_ID[0]["drill"][0]["fen"])
        def obsolete_success():
            with site.app.app_context():
                site.db().execute("""INSERT INTO attempt
                    (code,concept,idx,fen,correct,created_at) VALUES(?,?,?,?,?,?)""",
                    (owner, 0, 0, obsolete_fen, 1, site.time.time()))
                site.db().commit()
        obsolete_success()
        self.answer(0, 0)
        obsolete_success()
        _, profile = self.page("/me")
        self.assertEqual(profile["practice"], {"tried": 1, "first": 0, "latest": 0, "review": 1})
        self.assertEqual(profile["tot"], {"n": 1, "c": 0})
        self.assertEqual(profile["prog"][0]["first"], 0)
        self.assertEqual(profile["prog"][0]["correct"], 0)
        self.assertEqual([p["idx"] for p in self.page()[1]["positions"]], ["0:0"])


if __name__ == "__main__":
    unittest.main()
