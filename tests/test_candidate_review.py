"""Private editorial selection must preserve evidence and untouched source roles."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import chess

from scripts import candidate_review as review


def fixture_item():
    board = chess.Board()
    record = {"id": "fixture", "fen": board.fen(), "game_id": "fixture-game", "side_to_move": "white",
              "history_available": False, "phase": "opening", "analysis_role": "new_train", "split": "train"}
    legal = sorted(move.uci() for move in board.legal_moves)
    probabilities = {move: .04 if move == "e2e4" else .96 / (len(legal) - 1) for move in legal}
    policy = {"id": record["id"], "fen": record["fen"], "history_available": False,
              "maia3": {"history": {}, "fen_only": {str(rating): probabilities for rating in (1400, 1700, 2000, 2300)}}}
    roots = [{"id": review.scorer.original.task_id(record["id"], depth, move), "record_id": record["id"],
              "fen": record["fen"], "uci": move, "target_depth": depth, "depth": depth,
              "board_context": "fen_only", "reached_target": True, "score_is_exact": True,
              "cp": 0 if move == "e2e4" else -100, "mate": None, "nodes": 100, "wall_seconds": 1.,
              "pv": [{"uci": move, "san": board.san(chess.Move.from_uci(move))}]} for depth in (20, 24) for move in legal]
    origins = [{"game_id": record["game_id"], "public_game_detected": False,
                "strata": {"bot_status": "no_bot", "history_status": "recovered",
                           "public_exposure": "not_known_public", "analysis_role": "new_train"}}]
    manifest = {"already_deep200_ids": [], "strata_by_id": {"fixture": origins[0]["strata"]},
                "canonical_origins_by_id": {"fixture": origins},
                "state_provenance_by_id": {"fixture": review.selection.state_provenance(origins)}}
    outcome = review.scorer.summarize_record(record, policy, roots, origins[0]["strata"], False)
    return record, policy, outcome, roots, manifest


def html_fixture():
    record, policy, outcome, roots, manifest = fixture_item()
    item = review.make_item(record, policy, outcome, roots, manifest)
    second = copy.deepcopy(item)
    second.update(id="fixture-two", evidence_sha256="b" * 64)
    return {"items": [item, second], "selected_n": 2, "selected_by_side": {"white": 2},
            "selected_by_phase": {"opening": 2}, "pool_counts": {"editorial_eligible": 2},
            "method": review.METHOD}


class CandidateReviewTests(unittest.TestCase):
    def test_any_origin_exclusion_and_heldout_roles_are_not_erased_by_representative(self):
        record, _, outcome, _, manifest = fixture_item()
        safe = review.editorial_pool({"fixture": record}, {"fixture": outcome}, manifest)
        self.assertEqual(safe[0], ["fixture"])
        alternate = copy.deepcopy(manifest["canonical_origins_by_id"]["fixture"][0])
        alternate["game_id"] = "other-source"
        alternate["strata"]["analysis_role"] = "new_test"
        manifest["canonical_origins_by_id"]["fixture"].append(alternate)
        manifest["state_provenance_by_id"]["fixture"] = review.selection.state_provenance(manifest["canonical_origins_by_id"]["fixture"])
        eligible, counts = review.editorial_pool({"fixture": record}, {"fixture": outcome}, manifest)
        self.assertEqual(eligible, [])
        self.assertEqual(counts["noneditorial_role_excluded"], 1)
        alternate["strata"]["analysis_role"] = "new_train"
        alternate["public_game_detected"] = True
        manifest["state_provenance_by_id"]["fixture"] = review.selection.state_provenance(manifest["canonical_origins_by_id"]["fixture"])
        self.assertEqual(review.editorial_pool({"fixture": record}, {"fixture": outcome}, manifest)[1]["source_excluded"], 1)

    def test_stale_origin_flags_are_rejected(self):
        record, _, outcome, _, manifest = fixture_item()
        manifest["canonical_origins_by_id"]["fixture"][0]["public_game_detected"] = True
        with self.assertRaisesRegex(ValueError, "provenance"):
            review.editorial_pool({"fixture": record}, {"fixture": outcome}, manifest)

    def test_balanced_selection_is_order_invariant_and_uses_all_origin_aliases(self):
        records, outcomes, origins = {}, {}, {}
        for side in ("white", "black"):
            for i in range(12):
                key = f"{side}-{i}"
                records[key] = {"side_to_move": side, "phase": ("opening", "middlegame", "endgame")[i % 3]}
                outcomes[key] = {"accepted": {"24": ["a"] if i % 2 else ["a", "b"]}}
                origins[key] = [{"game_id": f"unique-{key}", "legacy_game_id": f"shared-{i}"}]
        manifest = {"canonical_origins_by_id": origins}
        selected = review.choose_batch(list(records), records, outcomes, manifest, count=8)
        self.assertEqual(selected, review.choose_batch(list(reversed(records)), records, outcomes, manifest, count=8))
        self.assertEqual([records[key]["side_to_move"] for key in selected], ["white", "black"] * 4)
        self.assertEqual(len({origins[key][0]["legacy_game_id"] for key in selected}), 8)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            review.choose_batch(list(records), records, outcomes, manifest, count=24)

    def test_missing_or_modified_root_is_rejected_and_frames_are_legal(self):
        record, policy, outcome, roots, manifest = fixture_item()
        item = review.make_item(record, policy, outcome, roots, manifest)
        self.assertEqual(item["accepted_san"], ["e4"])
        self.assertTrue(all(value is False for value in item["readiness"].values()))
        for branch in item["branches"]:
            board = chess.Board(record["fen"])
            board.push_uci(branch["uci"])
            self.assertEqual(branch["frames"], [record["fen"], board.fen()])
        with self.assertRaisesRegex(ValueError, "Every legal root"):
            review.make_item(record, policy, outcome, roots[:-1], manifest)
        broken = copy.deepcopy(roots)
        broken[0]["cp"] += 1
        with self.assertRaisesRegex(ValueError, "recomputation"):
            review.make_item(record, policy, outcome, broken, manifest)

    def test_review_notes_are_hash_bound_and_cannot_grant_readiness(self):
        packet = html_fixture()
        fingerprint = hashlib.sha256(review.encoded(packet)).hexdigest()
        notes = review.blank_reviews(packet, fingerprint)
        notes["items"][0].update(status="promising", explanation="A teaching hypothesis.")
        self.assertEqual(review.validate_reviews(notes, packet, fingerprint), notes)
        for mutate in (lambda v: v.update(packet_sha256="wrong"),
                       lambda v: v.update(schema_version=True),
                       lambda v: v["items"][0].update(trainer_ready=True),
                       lambda v: v["items"][0].update(evidence_sha256="wrong"),
                       lambda v: v["items"].__setitem__(1, copy.deepcopy(v["items"][0]))):
            bad = copy.deepcopy(notes)
            mutate(bad)
            with self.assertRaises(ValueError):
                review.validate_reviews(bad, packet, fingerprint)

    def test_script_payload_escapes_embedded_html_and_keeps_no_network_dependencies(self):
        packet = html_fixture()
        packet["method"] = "</script><script>alert('injected')</script>"
        output = review.review_html(packet, "a" * 64)
        self.assertEqual(output.count("<script>"), 1)
        self.assertEqual(output.count("</script>"), 1)
        self.assertNotIn("<script src=", output)
        self.assertNotIn("fetch(", output)

    def test_private_output_rejects_public_paths_and_existing_packets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "ignored"):
                review.require_private_output(root / "site/review", root)
            output = root / "data/mining_v3/review"
            with mock.patch.object(review.subprocess, "run") as run:
                run.side_effect = [mock.Mock(returncode=0), mock.Mock(stdout="")]
                self.assertEqual(review.require_private_output(output, root), output.resolve())
                output.mkdir(parents=True)
                run.side_effect = [mock.Mock(returncode=0), mock.Mock(stdout="")]
                with self.assertRaises(FileExistsError):
                    review.require_private_output(output, root)
                run.side_effect = [mock.Mock(returncode=0), mock.Mock(stdout="data/mining_v3/review/packet.json")]
                with self.assertRaisesRegex(ValueError, "tracked"):
                    review.require_private_output(output, root)

    def test_fingerprint_checks_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence"
            path.write_bytes(b"frozen evidence\n")
            fingerprint = review.digest(path)
            review.check_hash(path, fingerprint)
            path.write_bytes(b"modified evidence\n")
            with self.assertRaisesRegex(ValueError, "hash changed"):
                review.check_hash(path, fingerprint)


if __name__ == "__main__":
    unittest.main()
