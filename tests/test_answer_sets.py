"""Synthetic-only evidence fixtures; no private research boards are promoted."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from test_app import site
from answers import answer_spec, digest, grade


def synthetic_position(fen=site.chess.STARTING_FEN, accepted=("e2e4", "d2d4")):
    board = site.chess.Board(fen)
    best = accepted[0]
    roots = {}
    for move in board.legal_moves:
        uci = move.uci()
        score = 10 if uci == best else 0 if uci in accepted else -80
        roots[uci] = {str(depth): {"score_cp": score, "depth": depth,
                                   "bound": "exact", "pv": [uci]} for depth in (20, 24)}
    evidence = {"fen": fen, "roots": roots}
    return {"fen": fen, "best": best, "best_san": board.san(site.chess.Move.from_uci(best)),
            "answer": {"schema": "acceptable-moves/v1", "version": "synthetic-fixture-1",
                "accepted": list(accepted),
                "criterion": {"id": "stable-complete-root-cp/v1", "depths": [20, 24],
                              "tolerance_cp": 20, "score_perspective": "side_to_move"},
                "engine": {"name": "Stockfish", "version": "18-synthetic-not-a-search",
                           "binary_sha256": "a" * 64, "threads": 1, "hash_mb": 64,
                           "clear_hash_per_root": True, "context": "fen_only"},
                "evidence": evidence, "evidence_sha256": digest(evidence)}}


def rehash(position):
    position["answer"]["evidence_sha256"] = digest(position["answer"]["evidence"])


class AnswerSetContractTests(unittest.TestCase):
    def test_every_verified_alternative_is_accepted_and_others_rejected(self):
        position = synthetic_position()
        for move in site.chess.Board(position["fen"]).legal_moves:
            self.assertEqual(grade(position, move.uci()), move.uci() in ("e2e4", "d2d4"))
        self.assertFalse(grade(position, "e2e5"))

    def test_underpromotion_is_its_own_move(self):
        position = synthetic_position("7k/P7/8/8/8/8/8/7K w - - 0 1", ("a7a8q", "a7a8r"))
        self.assertTrue(grade(position, "a7a8r"))
        self.assertFalse(grade(position, "a7a8n"))
        self.assertFalse(grade(position, "a7a8"))

    def test_legacy_adapter_preserves_every_current_single_answer(self):
        for concept in site.CONCEPTS:
            for position in concept["drill"]:
                spec = answer_spec(position)
                self.assertEqual(spec["accepted"], (position["best"],))
                self.assertFalse(spec["explicit"])

    def test_rejects_malformed_or_incomplete_evidence(self):
        def accepted(position, value): position["answer"].__setitem__("accepted", value)
        changes = [
            lambda p: accepted(p, ["e2e4"]),  # omitted good alternative
            lambda p: accepted(p, ["e2e4", "d2d4", "g1f3"]),
            lambda p: accepted(p, ["e2e4", "d2d4", "d2d4"]),
            lambda p: accepted(p, ["e2e4", "d2d5"]),
            lambda p: p["answer"].__setitem__("schema", "acceptable-moves/v99"),
            lambda p: p["answer"].__setitem__("version", ""),
            lambda p: p["answer"]["criterion"].__setitem__("tolerance_cp", True),
            lambda p: p["answer"]["criterion"].__setitem__("score_perspective", "white"),
            lambda p: p["answer"]["engine"].__setitem__("binary_sha256", "unverified"),
            lambda p: p["answer"]["engine"].__setitem__("threads", True),
            lambda p: p["answer"]["engine"].__setitem__("context", "history"),
            lambda p: p["answer"]["evidence"]["roots"].pop("g1f3"),
            lambda p: p["answer"]["evidence"]["roots"]["d2d4"]["20"].__setitem__("score_cp", -80),
            lambda p: p["answer"]["evidence"]["roots"]["e2e4"]["20"].__setitem__("score_cp", "mate 3"),
            lambda p: p["answer"]["evidence"]["roots"]["e2e4"]["20"].__setitem__("score_cp", True),
            lambda p: p["answer"]["evidence"]["roots"]["e2e4"]["20"].__setitem__("depth", 19),
            lambda p: p["answer"]["evidence"]["roots"]["e2e4"]["20"].__setitem__("bound", "lower"),
            lambda p: p["answer"]["evidence"]["roots"]["e2e4"]["24"].__setitem__("pv", ["d2d4"]),
            lambda p: p["answer"]["evidence"]["roots"]["e2e4"]["24"].__setitem__("pv", ["e2e4", "e7e3"]),
            lambda p: p.__setitem__("best", "d2d4"),
            lambda p: p["answer"]["evidence"].__setitem__("fen", "different"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                position = synthetic_position(); change(position); rehash(position)
                with self.assertRaises(ValueError): answer_spec(position)
        position = synthetic_position(); position["answer"]["evidence_sha256"] = "b" * 64
        with self.assertRaises(ValueError): answer_spec(position)
        position["answer"] = None
        with self.assertRaises(ValueError): answer_spec(position)

    def test_identity_changes_with_evidence_version_and_tolerance_not_ui_copy(self):
        original = synthetic_position()
        base = answer_spec(original)["grading_id"]
        renamed = copy.deepcopy(original); renamed["best_san"] = "UI copy"
        self.assertEqual(answer_spec(renamed)["grading_id"], base)
        for key, value in (("version", "synthetic-fixture-2"),):
            changed = copy.deepcopy(original); changed["answer"][key] = value
            self.assertNotEqual(answer_spec(changed)["grading_id"], base)
        changed = copy.deepcopy(original); changed["answer"]["criterion"]["tolerance_cp"] = 15
        self.assertNotEqual(answer_spec(changed)["grading_id"], base)


class AnswerSetWebTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="muc-answer-sets-")
        self.addCleanup(directory.cleanup)
        self.addCleanup(setattr, site, "DB", site.DB)
        site.DB = Path(directory.name) / "test.db"
        site.init_db(); site.app.config.update(TESTING=True)
        self.client = site.app.test_client()
        concepts = copy.deepcopy(site.CONCEPTS)
        self.position = synthetic_position()
        concepts[0]["drill"][0] = self.position
        for name, value in (("CONCEPTS", concepts), ("BY_ID", {c["id"]: c for c in concepts})):
            patcher = patch.object(site, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        self.client.get("/pattern/0/drill")
        with self.client.session_transaction() as session: self.owner = session["code"]

    def payload(self, picked="d2d4"):
        return {"owner": self.owner, "concept": 0, "idx": 0, "fen": self.position["fen"],
                "grading_id": site.question_version(self.position), "picked": picked,
                "request_id": str(uuid.uuid4()), "seconds": 3}

    def history(self):
        with site.app.app_context(): return site.practice_history(self.owner)

    def test_alternative_is_saved_and_replayed_without_the_reference_explanation(self):
        payload = self.payload(); response = self.client.post("/api/answer", json=payload)
        self.assertEqual(response.status_code, 200)
        result = response.json
        self.assertTrue(result["correct"]); self.assertTrue(result["accepted_alternative"])
        self.assertEqual(result["line"]["frames"][1]["last"], "d2d4")
        self.assertEqual({line["move"] for line in result["line"]["accepted_lines"]}, {"e2e4", "d2d4"})
        self.assertNotIn("note", result["line"])
        self.assertIsNone(result["p_best"]); self.assertIsNone(result["predicted"])
        self.assertEqual(self.client.post("/api/answer", json=payload).json, result)
        self.assertEqual(self.history()[0]["attempts"], 1)
        recovered = self.client.post("/api/answer/recover", json=payload)
        self.assertEqual(recovered.json, {"status": "saved", "result": result})

    def test_questions_only_expose_opaque_identity_not_answer_evidence(self):
        page = self.client.get("/pattern/0/drill").get_data(as_text=True)
        self.assertIn(site.question_version(self.position), page)
        self.assertNotIn(answer_spec(self.position)["grading_id"], page)
        for value in ("accepted_lines", "acceptable_moves", "score_cp", "evidence_sha256", "synthetic-fixture-1"):
            self.assertNotIn(value, page)

    def test_changed_version_is_separate_history_and_stale_write_cannot_rescore(self):
        payload = self.payload(); old = self.client.post("/api/answer", json=payload).json
        self.position["answer"]["version"] = "synthetic-fixture-2"
        self.assertEqual(self.history(), [])
        self.assertEqual(self.client.post("/api/answer", json=payload).status_code, 409)
        recovered = self.client.post("/api/answer/recover", json=payload)
        self.assertEqual(recovered.json, {"status": "saved", "result": old})
        fresh = self.client.post("/api/answer", json=self.payload("g1f3"))
        self.assertFalse(fresh.json["correct"])
        self.assertEqual(self.history()[0]["attempts"], 1)
        self.assertFalse(self.history()[0]["ever_found"])

    def test_explicit_answers_require_version_without_creating_receipts(self):
        for key in (None, "0" * 64):
            payload = self.payload()
            if key is None: payload.pop("grading_id")
            else: payload["grading_id"] = key
            self.assertEqual(self.client.post("/api/answer", json=payload).status_code, 409)
        with site.app.app_context():
            self.assertEqual(site.db().execute("SELECT COUNT(*) FROM submission").fetchone()[0], 0)

    def test_old_unversioned_requests_fail_closed_after_a_bank_revision(self):
        keys = [f"0:{i}" for i in range(12)]
        token = site.test_signer().dumps({"id": uuid.uuid4().hex, "owner": self.owner, "items": keys})
        self.assertIsNone(site.read_test(token))
        picks = ["d2d4"] + [site.BY_ID[0]["drill"][i]["best"] for i in range(1, 12)]
        self.assertEqual(self.client.post("/api/blindspot", json={"attempt": token, "picks": picks}).status_code, 409)
        legacy = site.BY_ID[0]["drill"][1]
        old_practice = {"owner": self.owner, "concept": 0, "idx": 1, "fen": legacy["fen"],
                        "picked": legacy["best"], "request_id": str(uuid.uuid4())}
        self.assertEqual(self.client.post("/api/answer", json=old_practice).status_code, 409)
        with site.app.app_context():
            self.assertEqual(site.db().execute("SELECT COUNT(*) FROM submission").fetchone()[0], 0)

    def test_test_accepts_alternatives_but_does_not_reuse_exact_match_rating_model(self):
        keys = [f"0:{i}" for i in range(12)]
        token = site.test_signer().dumps({"id": uuid.uuid4().hex, "owner": self.owner,
                                         "items": keys, "bank_id": site.test_bank_id()})
        picks = ["d2d4"] + [site.BY_ID[0]["drill"][i]["best"] for i in range(1, 12)]
        result = self.client.post("/api/blindspot", json={"attempt": token, "picks": picks})
        self.assertEqual(result.status_code, 200); self.assertEqual(result.json["correct"], 12)
        self.assertFalse(result.json["rating_comparison_available"])
        self.assertIsNone(result.json["band"])
        self.assertEqual(result.json["reveal"][0]["line"]["frames"][1]["last"], "d2d4")
        before = self.client.get("/test?attempt=" + token).get_data(as_text=True)
        self.assertNotIn("accepted_lines", before)
        self.position["answer"]["version"] = "synthetic-fixture-2"
        self.assertIsNone(site.read_test(token))
        old = self.client.post("/api/blindspot", json={"attempt": token, "picks": picks})
        self.assertEqual(old.json, result.json)
        changed = picks.copy(); changed[0] = "g1f3"
        self.assertEqual(self.client.post("/api/blindspot", json={"attempt": token, "picks": changed}).status_code, 409)

    def test_unversioned_old_attempts_do_not_count_as_new_set_attempts(self):
        with site.app.app_context():
            site.db().execute("INSERT INTO attempt(code,concept,idx,fen,best,picked,correct) VALUES(?,?,?,?,?,?,?)",
                              (self.owner, 0, 0, self.position["fen"], self.position["best"], "e2e4", 1))
            site.db().commit()
        self.assertEqual(self.history(), [])

    def test_legacy_null_and_new_exact_rows_combine_without_losing_first_latest(self):
        legacy = site.BY_ID[0]["drill"][1]
        with site.app.app_context():
            site.db().execute("INSERT INTO attempt(code,concept,idx,fen,best,picked,correct) VALUES(?,?,?,?,?,?,?)",
                              (self.owner, 0, 1, legacy["fen"], legacy["best"], legacy["best"], 0))
            site.db().commit()
        response = self.client.post("/api/answer", json={"concept": 0, "idx": 1,
             "grading_id": site.question_version(legacy),
             "picked": legacy["best"], "request_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200)
        row = self.history()[0]
        self.assertEqual((row["first_correct"], row["correct"], row["ever_found"], row["attempts"]), (0, 1, 1, 2))
        legacy["best"] = next(m for m in site.board_of(legacy["fen"])["legal"] if m != legacy["best"])
        self.assertEqual(self.history(), [])

    def test_existing_sqlite_database_migrates_additively_and_idempotently(self):
        site.DB = site.DB.with_name("old.db")
        with sqlite3.connect(site.DB) as connection:
            connection.execute("CREATE TABLE attempt(id INTEGER PRIMARY KEY, code TEXT, concept INTEGER, idx INTEGER, fen TEXT, picked TEXT, best TEXT, correct INTEGER, human_p REAL, seconds REAL, created_at REAL)")
            connection.execute("INSERT INTO attempt(id,code,correct) VALUES(1,'ABCDEF',1)")
        site.init_db(); site.init_db()
        with sqlite3.connect(site.DB) as connection:
            row = connection.execute("SELECT id,code,correct,grading_id FROM attempt").fetchone()
        self.assertEqual(row, (1, "ABCDEF", 1, None))


if __name__ == "__main__": unittest.main()
