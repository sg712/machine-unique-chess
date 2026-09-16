import copy
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import chess

SPEC = importlib.util.spec_from_file_location("lesson_family_research", Path(__file__).resolve().parents[1] / "scripts/lesson_family_research.py")
lessons = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lessons)


def selection_fixture():
    """Public initial-board variations; no private candidates or source games."""
    records, origins, provenance, cases = {}, {}, {}, []
    for index, move in enumerate(("e4", "d4", "c4")):
        board = chess.Board()
        board.push_san(move)
        key = f"synthetic-{index}"
        records[key] = {"id": key, "fen": board.fen()}
        origins[key] = [{"game_id": f"fictional-game-{index}", "strata": {"analysis_role": "new_train"}}]
        provenance[key] = {"all_origins_recovered_no_bot_not_known_public": True}
        cases.append({"id": key, "role": "positive" if index < 2 else "boundary"})
    notes = {"authorship": lessons.AUTHORSHIP, "readiness": {g: False for g in lessons.review.MANUAL_GATES},
             "families": [{"cases": cases}]}
    manifest = {"canonical_origins_by_id": origins, "state_provenance_by_id": provenance}
    return notes, records, manifest


def question_fixture():
    board = chess.Board()
    pv = []
    for san in ("e4", "e5", "Nf3"):
        move = board.parse_san(san)
        pv.append({"uci": move.uci(), "san": san})
        board.push(move)
    item = {"fen": chess.STARTING_FEN, "branches": [{"depth": 24, "uci": "e2e4", "pv": pv}]}
    question = {"scope": "saved_pv", "root_uci": "e2e4", "after": ["e4"], "answer_san": "e5"}
    return item, question


class LessonFamilyTests(unittest.TestCase):
    def test_relative_pin_is_not_confused_with_king_pin(self):
        board = chess.Board("q6k/8/8/8/1b6/P7/8/R5K1 w - - 0 1")
        self.assertFalse(board.is_pinned(chess.WHITE, chess.A3))
        self.assertIn(chess.Move.from_uci("a3b4"), board.legal_moves)
        pins = lessons.relative_pins(board)
        self.assertEqual(pins, [{"target": chess.A1, "blocker": chess.A3, "attacker": chess.A8}])
        shifted = lessons.pin_target_shift(board, chess.Move.from_uci("a1b1"))
        self.assertEqual(shifted[0]["blocker_captures_available"], ["axb4"])

    def test_two_blockers_do_not_match_relative_pin(self):
        board = chess.Board("q6k/8/P7/8/1b6/P7/8/R5K1 w - - 0 1")
        self.assertEqual(lessons.relative_pins(board), [])

    def test_queen_counterattack_is_only_a_geometry_screen(self):
        board = chess.Board("7k/8/8/3q4/4Q3/8/2B5/K7 w - - 0 1")
        move = board.parse_san("Bb3")
        feature = lessons.queen_counterattack(board, move)
        self.assertTrue(feature["own_queen_still_attacked"])
        # The opponent can capture and leave the square attacked by the bishop.
        board.push(move)
        board.push_san("Qxe4")
        self.assertNotIn(chess.E4, board.attacks(chess.B3))
        self.assertIsNone(lessons.queen_counterattack(chess.Board(), chess.Move.from_uci("b1c3")))

    def test_fork_requires_check_and_nonpawn_target_and_legal_saved_line(self):
        board = chess.Board("k7/8/8/8/6n1/8/P7/3Q3K w - - 0 1")
        pv = [{"uci": "a2a3", "san": "a3"}, {"uci": "g4f2", "san": "Nf2+"}]
        forks = lessons.knight_forks(board, pv)
        self.assertEqual(forks[0]["targets"], ["d1"])
        self.assertEqual(forks[0]["ply"], 2)
        pv[-1]["san"] = "Nf2"
        with self.assertRaisesRegex(ValueError, "Invalid saved continuation"):
            lessons.knight_forks(board, pv)

    def test_selection_uses_two_positives_and_one_boundary(self):
        notes, records, manifest = selection_fixture()
        self.assertEqual(len(lessons.validate_selection(notes, records, manifest)), 3)
        notes["families"][0]["cases"][-1]["role"] = "positive"
        with self.assertRaisesRegex(ValueError, "two positives"):
            lessons.validate_selection(notes, records, manifest)

    def test_unadmitted_identity_is_rejected_before_any_board_access(self):
        notes, records, manifest = selection_fixture()
        notes["families"][0]["cases"][0]["id"] = "sealed-evaluation-item"
        with self.assertRaisesRegex(ValueError, "admitted editorial pool"):
            lessons.validate_selection(notes, records, manifest)

    def test_every_origin_role_and_public_provenance_must_pass(self):
        notes, records, manifest = selection_fixture()
        manifest["canonical_origins_by_id"]["synthetic-0"].append(
            {"game_id": "second-origin", "strata": {"analysis_role": "new_test"}})
        with self.assertRaisesRegex(ValueError, "Every origin"):
            lessons.validate_selection(notes, records, manifest)
        notes, records, manifest = selection_fixture()
        manifest["state_provenance_by_id"]["synthetic-0"]["all_origins_recovered_no_bot_not_known_public"] = False
        with self.assertRaisesRegex(ValueError, "provenance"):
            lessons.validate_selection(notes, records, manifest)

    def test_source_alias_overlap_across_roles_is_rejected(self):
        notes, records, manifest = selection_fixture()
        manifest["canonical_origins_by_id"]["synthetic-2"][0]["legacy_game_id"] = "fictional-game-0"
        with self.assertRaisesRegex(ValueError, "legacy aliases"):
            lessons.validate_selection(notes, records, manifest)

    def test_duplicate_canonical_state_ignores_move_counters(self):
        notes, records, manifest = selection_fixture()
        records["synthetic-2"]["fen"] = records["synthetic-0"]["fen"].rsplit(" ", 2)[0] + " 8 19"
        with self.assertRaisesRegex(ValueError, "Canonical states"):
            lessons.validate_selection(notes, records, manifest)

    def test_readiness_and_authorship_cannot_be_promoted(self):
        notes, records, manifest = selection_fixture()
        notes["readiness"]["independent_chess_review"] = True
        with self.assertRaisesRegex(ValueError, "remain false"):
            lessons.validate_selection(notes, records, manifest)
        notes, records, manifest = selection_fixture()
        notes["authorship"] = "Human approved"
        with self.assertRaisesRegex(ValueError, "AI authorship"):
            lessons.validate_selection(notes, records, manifest)

    def test_question_must_match_the_exact_saved_root_and_prefix(self):
        item, question = question_fixture()
        lessons.verify_question(item, question)
        altered = copy.deepcopy(question)
        altered["answer_san"] = "c5"
        with self.assertRaisesRegex(ValueError, "exact saved"):
            lessons.verify_question(item, altered)
        altered = copy.deepcopy(question)
        altered["after"] = ["d4"]
        with self.assertRaisesRegex(ValueError, "exact saved"):
            lessons.verify_question(item, altered)

    def test_legality_only_question_cannot_claim_saved_evidence(self):
        item, _ = question_fixture()
        question = {"scope": "legality_only", "after": ["e4"], "answer_san": "e5", "answer_is_legal": True}
        lessons.verify_question(item, question)
        question["answer_is_legal"] = False
        with self.assertRaisesRegex(ValueError, "legality answer"):
            lessons.verify_question(item, question)

    def test_every_accepted_alternative_needs_its_own_authored_discussion(self):
        item = {"accepted": {"24": ["e2e4", "d2d4"]}}
        note = {"accepted_move_discussions": {"e2e4": "An illustrative first answer."}}
        with self.assertRaisesRegex(ValueError, "every accepted move"):
            lessons.verify_accepted_coverage(item, note)
        note["accepted_move_discussions"]["d2d4"] = "An illustrative equally accepted answer."
        lessons.verify_accepted_coverage(item, note)
        note["accepted_move_discussions"]["g1f3"] = "An unaccepted answer."
        with self.assertRaisesRegex(ValueError, "every accepted move"):
            lessons.verify_accepted_coverage(item, note)

    def test_private_export_cannot_overwrite_or_leave_ignored_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_text("data/mining_v3/\n")
            with self.assertRaisesRegex(ValueError, "ignored"):
                lessons.review.require_private_output(root / "docs/private-bank", root)
            output = root / "data/mining_v3/bank"
            output.mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                lessons.review.require_private_output(output, root)

    def test_seed_source_bindings_reject_changes_and_paths_outside_private_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "data/mining_v3/seed.json"
            seed.parent.mkdir(parents=True)
            seed.write_text("{}")
            source = {"path": "data/mining_v3/seed.json", "sha256": lessons.review.digest(seed)}
            notes = {"source_bindings": [source]}
            lessons.verify_note_sources(notes, root)
            seed.write_text('{"changed": true}')
            with self.assertRaisesRegex(ValueError, "hash changed"):
                lessons.verify_note_sources(notes, root)
            source["path"] = "../outside.json"
            with self.assertRaisesRegex(ValueError, "private research"):
                lessons.verify_note_sources(notes, root)


if __name__ == "__main__":
    unittest.main()
