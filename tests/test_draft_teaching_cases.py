import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import chess

SPEC = importlib.util.spec_from_file_location("draft_teaching_cases", Path(__file__).resolve().parents[1] / "scripts/draft_teaching_cases.py")
drafts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drafts)


def fixture():
    """Ordinary initial-board fixture; no private candidate identities or answers."""
    board = chess.Board()
    moves = sorted(board.legal_moves, key=lambda m: m.uci())
    accepted = {str(d): [m.uci() for m in moves] for d in (20, 24)}
    roots = []
    for depth in (20, 24):
        for move in moves:
            replay = board.copy()
            replay.push(move)
            roots.append({"depth": depth, "achieved_depth": depth, "uci": move.uci(),
                          "san": board.san(move), "pv": [{"uci": move.uci(), "san": board.san(move)}],
                          "frames": [board.fen(), replay.fen()], "cp": 0, "loss_cp": 0,
                          "acceptable": True, "maia": {"2000": 1 / len(moves)}, "root_sha256": "a" * 64})
    item = {"id": "synthetic-start", "fen": board.fen(), "side_to_move": "white",
            "readiness": {g: False for g in drafts.GATES}, "accepted": accepted,
            "accepted_san": [board.san(m) for m in moves], "branches": roots,
            "outcome": {"best_cp": {"20": 0, "24": 0}}, "evidence_sha256": "b" * 64,
            "origins": [{"strata": {"analysis_role": "new_train"}}],
            "provenance": {"all_origins_recovered_no_bot_not_known_public": True}}
    packet = {"items": [item], "readiness": {g: False for g in drafts.GATES}}
    payload = json.dumps(packet).encode()
    note = {"id": item["id"], "evidence_sha256": item["evidence_sha256"],
            "title": "Synthetic legality example", "hypothesis": "A test fixture, not a chess claim.",
            "plausible_alternatives": ["e2e4"],
            "board_facts": [{"text": "The pawn is on e4.", "after": ["e4"],
                             "assertions": [{"type": "piece", "square": "e4", "value": "P"}]}],
            "accepted_explanation": "Fixture.", "alternative_explanation": "Fixture.",
            "teaching_prompt": "Fixture.", "draft_feedback": "Fixture.", "requires_review": ["Independent review."]}
    notes = {"packet_sha256": drafts.sha256(payload), "authorship": drafts.AUTHORSHIP,
             "readiness": {g: False for g in drafts.GATES}, "cases": [note]}
    return packet, payload, notes


class TeachingDraftTests(unittest.TestCase):
    def test_saved_roots_replay_and_no_gate_is_promoted(self):
        _, payload, notes = fixture()
        result = drafts.compile_drafts(payload, notes)
        self.assertEqual(result["saved_roots_checked"], 40)
        self.assertEqual(result["saved_plies_checked"], 40)
        self.assertEqual(result["engine_searches_run"], 0)
        self.assertTrue(all(v is False for v in result["cases"][0]["readiness"].values()))

    def test_packet_bytes_are_bound_to_notes(self):
        _, payload, notes = fixture()
        with self.assertRaisesRegex(ValueError, "different packet"):
            drafts.compile_drafts(payload + b" ", notes)

    def test_case_evidence_fingerprint_is_bound(self):
        _, payload, notes = fixture()
        notes["cases"][0]["evidence_sha256"] = "bad"
        with self.assertRaisesRegex(ValueError, "fingerprint changed"):
            drafts.compile_drafts(payload, notes)

    def test_gate_promotion_is_rejected(self):
        _, payload, notes = fixture()
        notes["readiness"]["trainer_ready"] = True
        with self.assertRaisesRegex(ValueError, "remain false"):
            drafts.compile_drafts(payload, notes)

    def test_board_fact_must_match_real_position(self):
        _, payload, notes = fixture()
        notes["cases"][0]["board_facts"][0]["assertions"][0]["square"] = "e5"
        with self.assertRaisesRegex(ValueError, "assertion failed"):
            drafts.compile_drafts(payload, notes)

    def test_holdout_cannot_be_used_as_a_teaching_case(self):
        packet, _, _ = fixture()
        item = packet["items"][0]
        item["origins"].append({"strata": {"analysis_role": "new_test"}})
        with self.assertRaisesRegex(ValueError, "holdout"):
            drafts.verify_item(item)

    def test_corrupted_saved_san_or_frame_is_rejected(self):
        packet, _, _ = fixture()
        item = packet["items"][0]
        altered = copy.deepcopy(item)
        altered["branches"][0]["pv"][0]["san"] = "Qa8#"
        with self.assertRaisesRegex(ValueError, "mismatched SAN"):
            drafts.verify_item(altered)
        altered = copy.deepcopy(item)
        altered["branches"][0]["frames"][-1] = chess.Board().fen()
        with self.assertRaisesRegex(ValueError, "Saved frame"):
            drafts.verify_item(altered)

    def test_missing_root_and_changed_score_are_rejected(self):
        packet, _, _ = fixture()
        item = packet["items"][0]
        altered = copy.deepcopy(item)
        altered["branches"].pop()
        with self.assertRaisesRegex(ValueError, "not exhaustive"):
            drafts.verify_item(altered)
        altered = copy.deepcopy(item)
        altered["branches"][0]["loss_cp"] = 99
        with self.assertRaisesRegex(ValueError, "loss disagrees"):
            drafts.verify_item(altered)

    def test_no_unsaved_comparison_is_presented_as_a_saved_root(self):
        _, payload, notes = fixture()
        notes["cases"][0]["plausible_alternatives"] = ["e2e5"]
        with self.assertRaisesRegex(ValueError, "saved legal root"):
            drafts.compile_drafts(payload, notes)

    def test_board_only_line_checks_legality_and_labels_scope(self):
        board = chess.Board()
        fact = {"text": "An example pawn attack.", "after": ["e4", "d5"], "assertions": [
            {"type": "attacks", "from": "e4", "to": "d5", "value": True},
            {"type": "legal_san", "san": "exd5", "value": True},
            {"type": "legal_san", "san": "Ke3", "value": False}]}
        checked = drafts.verify_fact(board.fen(), fact)
        self.assertEqual(checked["assertions_verified"], 3)
        self.assertIn("no score or best-play proof", checked["verification_scope"])

    def test_markdown_cannot_misrepresent_verification_scope(self):
        _, payload, notes = fixture()
        text = drafts.markdown(drafts.compile_drafts(payload, notes))
        self.assertIn(drafts.AUTHORSHIP, text)
        self.assertIn("not measured human response rates", text)
        self.assertIn("not saved engine PVs", text)
        self.assertIn("All readiness gates remain false", text)

    def test_exports_require_private_ignored_location_and_refuse_overwrites(self):
        _, payload, notes = fixture()
        result = drafts.compile_drafts(payload, notes)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_text("data/mining_v3/\n")
            with self.assertRaisesRegex(ValueError, "remain inside"):
                drafts.export(result, root / "docs/leaked", root)
            output = root / "data/mining_v3/private-drafts"
            drafts.export(result, output, root)
            before = (output / "drafts.json").read_bytes()
            with self.assertRaises(FileExistsError):
                drafts.export(result, output, root)
            self.assertEqual((output / "drafts.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
