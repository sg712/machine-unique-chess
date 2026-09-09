import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import chess

from scripts import mining_v3_deep_summary as summary


class DeepSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = mock.patch.multiple(summary, SAMPLE_N=2, PER_SIDE=1,
                                        DISTINCT_CANDIDATES=12, REMAINING_CANDIDATES=10)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.inputs = self.root / "inputs.jsonl"
        self.policies_path = self.root / "policies.jsonl"
        self.selection_path = self.root / "selection_manifest.json"
        self.protocol_path = self.root / "selection_protocol.json"
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.engine = self.root / "test-engine"
        self.engine.write_bytes(b"Synthetic fixture; never executed")
        self.records, self.policies, self.roots = [], [], []
        for i, history in enumerate((["e2e4", "e7e5"], ["d2d4"])):
            board = chess.Board()
            states = [board.fen()]
            for move in history:
                board.push_uci(move)
                states.append(board.fen())
            moves = sorted(move.uci() for move in board.legal_moves)
            record = {"id": f"PRIVATE-OBSERVATION-{i}", "game_id": f"PRIVATE-GAME-{i}",
                      "fen": board.fen(), "initial_fen": chess.STARTING_FEN,
                      "history_uci": history, "history_fens": states,
                      "history_available": True, "contains_bot": False,
                      "known_public_game": False, "played_move": moves[0],
                      "side_to_move": "white" if board.turn else "black", "cohort": "club",
                      "phase": "opening", "mover_elo": 1900, "rating_bin": "1800_1999",
                      "analysis_role": "prior_development", "split": "train"}
            self.records.append(record)
            probabilities = {move: .04 if move == moves[0] else .96 / (len(moves) - 1) for move in moves}
            self.policies.append({"id": record["id"], "fen": board.fen(), "history_available": True,
                                  "input_condition": "fen_only", "maia3": {"history": {},
                                  "fen_only": {str(r): probabilities for r in (1400, 1700, 2000, 2300)}}})
            for depth in (20, 24):
                for move in moves:
                    # Both positions have stable accepted sets. The Black
                    # fixture fails the competitive-position condition only.
                    best = 0 if i == 0 else 500
                    root = {"id": summary.runner.task_id(record["id"], depth, move),
                            "record_id": record["id"], "fen": board.fen(), "uci": move,
                            "target_depth": depth, "depth": depth, "reached_target": True,
                            "score_is_exact": True, "lowerbound": False, "upperbound": False,
                            "cp": best if move == moves[0] else best - 100, "mate": None,
                            "board_context": "fen_only", "nodes": 1000, "wall_seconds": float(i + 1),
                            "seconds": float(i + 1), "pv": [{"uci": move, "san": board.san(chess.Move.from_uci(move))}]}
                    self.roots.append(root)
        self.write_lines(self.inputs, self.records)
        self.write_lines(self.policies_path, self.policies)
        protocol = {"created_at": "1970-01-01T00:01:00+00:00", "seed": 20260909, "per_side_target": 1, "input_hashes": {"metadata_sha256": "fixture"},
                    "selection_script_sha256": summary.digest(summary.selector.__file__),
                    "selection_function_sha256": hashlib.sha256(inspect.getsource(summary.selector.choose_candidates).encode()).hexdigest(),
                    "screen_gate_function_sha256": hashlib.sha256(inspect.getsource(summary.selector.is_screen_candidate).encode()).hexdigest()}
        self.protocol_path.write_text(json.dumps(protocol))
        self.selection = {"complete": True, "created_at": "1970-01-01T00:01:30+00:00", "selected_n": 2, "selected_ids": [r["id"] for r in self.records],
                          "positions_sha256": summary.digest(self.inputs), "policies_sha256": summary.digest(self.policies_path),
                          "selection_script_sha256": summary.digest(summary.selector.__file__),
                          "selection_protocol_sha256": summary.digest(self.protocol_path),
                          "seed": 20260909, "per_side_target": 1, "input_hashes": protocol["input_hashes"],
                          "original_policy_line_sha256": {r["id"]: hashlib.sha256(line).hexdigest()
                              for r, line in zip(self.records, self.policies_path.read_bytes().splitlines(keepends=True))}}
        self.selection_path.write_text(json.dumps(self.selection))
        self.run = {"complete": True, "input_n": 2, "completed_positions_n": 2,
                    "root_searches_n": len(self.roots), "completed_root_searches_n": len(self.roots),
                    "started_at": 98., "finished_at": 201.,
                    "attempts": [{"started_at": 100., "finished_at": 120., "complete": False},
                                 {"started_at": 160., "finished_at": 200., "complete": True}],
                    "settings": {"depths": [20, 24], "board_context": "fen_only", "engine_threads": 1,
                                 "hash_mb": 64, "clear_hash_each_search": True, "time_limit": None, "node_limit": None,
                                 "python_chess_version": chess.__version__,
                                 "workers": 2, "input_sha256": summary.digest(self.inputs),
                                 "policy_sha256": summary.digest(self.policies_path),
                                 "selection_manifest_sha256": summary.digest(self.selection_path),
                                 "engine_sha256": summary.digest(self.engine),
                                 "runner_sha256": summary.digest(summary.runner.__file__),
                                 "search_and_metrics_sha256": summary.digest(summary.runner.base.__file__),
                                 "canonicalization_sha256": summary.digest(summary.ROOT / "scripts/mining_v2_sampling.py"),
                                 "io_sha256": summary.digest(summary.ROOT / "scripts/mining_v3_io.py")}}
        self.write_evidence()

    @staticmethod
    def write_lines(path, values):
        path.write_text("".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values))

    def write_evidence(self, recompute=True):
        self.write_lines(self.run_dir / "roots.jsonl", self.roots)
        if recompute:
            self.position_results = [summary.runner.summarize_position(r, p, [x for x in self.roots if x["record_id"] == r["id"]])
                                     for r, p in zip(self.records, self.policies)]
            self.write_lines(self.run_dir / "positions.jsonl", self.position_results)
        self.run.update(roots_sha256=summary.digest(self.run_dir / "roots.jsonl"),
                        positions_sha256=summary.digest(self.run_dir / "positions.jsonl"),
                        roots_checkpoint_bytes=(self.run_dir / "roots.jsonl").stat().st_size,
                        roots_checkpoint_sha256=summary.digest(self.run_dir / "roots.jsonl"))
        self.save_run()

    def save_run(self):
        (self.run_dir / "run.json").write_text(json.dumps(self.run))

    def build(self):
        return summary.build_summary(self.inputs, self.policies_path, self.selection_path, self.run_dir, self.engine)

    def test_recomputation_separates_engine_criterion_and_trainer_readiness(self):
        result = self.build()
        self.assertEqual(result["counts"]["engine_verified_n"], 2)
        self.assertEqual(result["counts"]["survives_candidate_criterion_n"], 1)
        self.assertEqual(result["counts"]["trainer_ready_n"], 0)
        self.assertEqual(result["failure_reasons_overlapping"]["candidate_criterion_not_retained_at_20"], 1)
        self.assertEqual(result["failure_reasons_overlapping"]["candidate_criterion_not_retained_at_24"], 1)

    def test_attempt_elapsed_time_excludes_explicit_gaps_without_claiming_compute_time(self):
        result = self.build()
        self.assertEqual(result["runtime"]["attempt_elapsed_wall_seconds"], 60)
        self.assertIsNone(result["runtime"]["active_attempt_wall_seconds"])
        self.assertFalse(result["runtime"]["host_suspension_measured"])
        self.assertIsNone(result["runtime"]["host_suspension_seconds"])
        self.assertEqual(result["runtime"]["elapsed_wall_seconds_including_pauses"], 103)
        self.assertEqual(result["runtime"]["outside_attempt_seconds"], 43)
        costs = [sum(x["wall_seconds"] for x in self.roots if x["record_id"] == r["id"]) for r in self.records]
        self.assertEqual(result["runtime"]["per_position_root_search_seconds"], summary.distribution(costs))
        self.assertEqual(result["remaining_work_planning_estimate"]["attempt_elapsed_hours_from_observed_throughput"], 30 * 10 / 3600)
        self.assertIsNone(result["remaining_work_planning_estimate"]["active_attempt_hours_from_observed_throughput"])

    def test_long_attempt_does_not_infer_sleep_duration_or_active_compute(self):
        baseline = self.build()
        self.run["attempts"][-1]["finished_at"] += 3600
        self.run["finished_at"] += 3600
        self.save_run()
        result = self.build()
        self.assertEqual(result["runtime"]["attempt_elapsed_wall_seconds"], 3660)
        self.assertEqual(result["runtime"]["outside_attempt_seconds"], 43)
        self.assertEqual(result["runtime"]["per_position_root_search_seconds"],
                         baseline["runtime"]["per_position_root_search_seconds"])
        self.assertIsNone(result["runtime"]["active_attempt_wall_seconds"])
        self.assertIsNone(result["runtime"]["host_suspension_seconds"])
        estimate = result["remaining_work_planning_estimate"]
        self.assertIsNone(estimate["active_attempt_hours_from_observed_throughput"])
        self.assertEqual(estimate["attempt_elapsed_hours_from_observed_throughput"], 1830 * 10 / 3600)
        self.assertIn("not active computation or a reliable no-sleep forecast", estimate["interpretation"])

    def test_recorded_python_chess_version_must_match_runtime(self):
        self.run["settings"]["python_chess_version"] = "different-version"
        self.save_run()
        with self.assertRaisesRegex(ValueError, "python-chess version differs"):
            self.build()

    def test_selection_freeze_and_protocol_must_precede_run(self):
        result = self.build()
        self.assertEqual(result["selection"]["frozen_at"], self.selection["created_at"])
        self.assertTrue(result["selection"]["freeze_precedes_run_checked"])
        self.assertTrue(result["selection"]["protocol_precedes_run_checked"])
        for path in (self.selection_path, self.protocol_path):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                document = json.loads(original)
                document["created_at"] = "1970-01-01T00:01:39+00:00"
                path.write_text(json.dumps(document))
                if path == self.protocol_path:
                    self.selection["selection_protocol_sha256"] = summary.digest(path)
                    self.selection_path.write_text(json.dumps(self.selection))
                self.run["settings"]["selection_manifest_sha256"] = summary.digest(self.selection_path)
                self.save_run()
                with self.assertRaisesRegex(ValueError, "must precede the run start"):
                    self.build()
                path.write_bytes(original)

    def test_missing_selection_timestamps_are_not_invented(self):
        result = summary.selection_timing({}, {}, 100.)
        self.assertIsNone(result["frozen_at"])
        self.assertFalse(result["freeze_precedes_run_checked"])
        self.assertIsNone(result["protocol_declared_at"])
        self.assertFalse(result["protocol_precedes_run_checked"])

    def test_selection_timestamp_requires_timezone_and_ordered_protocol(self):
        with self.assertRaisesRegex(ValueError, "no timezone"):
            summary.selection_timing({"created_at": "1970-01-01T00:01:30"}, {}, 100.)
        with self.assertRaisesRegex(ValueError, "after the selection freeze"):
            summary.selection_timing({"created_at": "1970-01-01T00:01:30Z"},
                                     {"created_at": "1970-01-01T00:01:31Z"}, 100.)

    def test_missing_legal_root_rejected_even_with_updated_output_hash(self):
        self.roots.pop()
        self.write_evidence(recompute=False)
        with self.assertRaisesRegex(ValueError, "complete plan"):
            self.build()

    def test_inexact_or_shallow_root_rejected_even_with_updated_output_hash(self):
        for mutation in ({"score_is_exact": False, "lowerbound": True}, {"depth": 19}, {"upperbound": True}):
            original = dict(self.roots[0])
            self.roots[0].update(mutation)
            self.write_evidence(recompute=False)
            with self.assertRaisesRegex(ValueError, "exact target-depth"):
                self.build()
            self.roots[0] = original

    def test_changed_input_policy_selection_engine_and_source_hashes_rejected(self):
        for key in ("input_sha256", "policy_sha256", "selection_manifest_sha256", "engine_sha256",
                    "runner_sha256", "search_and_metrics_sha256", "canonicalization_sha256", "io_sha256"):
            original = self.run["settings"][key]
            self.run["settings"][key] = "0" * 64
            self.save_run()
            with self.assertRaisesRegex(ValueError, "hash changed"):
                self.build()
            self.run["settings"][key] = original

    def test_saved_success_flags_are_not_trusted(self):
        self.position_results[1]["survives"] = True
        self.position_results[1]["trainer_ready"] = True
        self.write_lines(self.run_dir / "positions.jsonl", self.position_results)
        self.write_evidence(recompute=False)
        with self.assertRaisesRegex(ValueError, "recomputation"):
            self.build()

    def test_public_result_contains_no_private_records_moves_or_paths(self):
        result = self.build()
        text = json.dumps(result)
        for private in ("PRIVATE-OBSERVATION", "PRIVATE-GAME", str(self.root), str(summary.ROOT), *[r["fen"] for r in self.records]):
            self.assertNotIn(private, text)
        forbidden_keys = {"id", "record_id", "game_id", "fen", "uci", "pv", "history_uci", "history_fens", "selected_ids", "played_move", "path"}
        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & forbidden_keys)
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(result)
        self.assertEqual(summary.safe_categories([{**self.records[0], "cohort": "PRIVATE-GAME-0"}])["cohort"], {"unknown": 1})

    def test_incomplete_run_and_unfinished_final_attempt_rejected(self):
        self.run["complete"] = False
        self.save_run()
        with self.assertRaisesRegex(ValueError, "entire deep run"):
            self.build()
        self.run["complete"] = True
        self.run["attempts"][-1].pop("finished_at")
        self.save_run()
        with self.assertRaisesRegex(ValueError, "final attempt"):
            self.build()

    def test_unclosed_prior_attempt_does_not_fabricate_active_duration(self):
        self.run["attempts"][0].pop("finished_at")
        self.save_run()
        result = self.build()
        self.assertFalse(result["runtime"]["attempt_timing_complete"])
        self.assertIsNone(result["runtime"]["attempt_elapsed_wall_seconds"])
        self.assertIsNone(result["runtime"]["active_attempt_wall_seconds"])
        self.assertIsNone(result["remaining_work_planning_estimate"]["attempt_elapsed_hours_from_observed_throughput"])
        self.assertIsNone(result["remaining_work_planning_estimate"]["active_attempt_hours_from_observed_throughput"])
        self.assertGreater(result["remaining_work_planning_estimate"]["serial_root_search_hours_from_sample_mean"], 0)

    def test_repeated_game_rejected_before_results_are_used(self):
        self.records[1]["game_id"] = self.records[0]["game_id"]
        self.write_lines(self.inputs, self.records)
        self.selection["positions_sha256"] = summary.digest(self.inputs)
        self.selection_path.write_text(json.dumps(self.selection))
        with self.assertRaisesRegex(ValueError, "repeats a source game"):
            self.build()

    def test_changed_policy_bytes_rejected_even_when_input_manifest_updated(self):
        self.policies[0]["maia3"]["fen_only"]["1400"] = dict(reversed(list(self.policies[0]["maia3"]["fen_only"]["1400"].items())))
        self.write_lines(self.policies_path, self.policies)
        self.selection["policies_sha256"] = summary.digest(self.policies_path)
        self.selection_path.write_text(json.dumps(self.selection))
        with self.assertRaisesRegex(ValueError, "original policy bytes"):
            self.build()

    def test_depth_score_and_move_set_changes_are_recomputed(self):
        identifier = self.records[0]["id"]
        changed = [root for root in self.roots if root["record_id"] == identifier and root["target_depth"] == 24]
        changed[0]["cp"] = -100
        changed[1]["cp"] = 30
        self.write_evidence()
        result = self.build()
        changes = result["depth_changes"]
        self.assertEqual(changes["best_move_set_changed_n"], 1)
        self.assertEqual(changes["acceptable_move_set_changed_n"], 1)
        self.assertEqual(changes["best_score_change_cp"]["median"], 15)
        self.assertEqual(changes["best_score_change_cp"]["p90"], 27)
        self.assertEqual(result["counts"]["engine_verified_n"], 1)
        self.assertEqual(result["failure_reasons_overlapping"]["acceptable_set_changed"], 1)

    def test_mate_values_are_not_used_as_centipawn_changes(self):
        changed = next(root for root in self.roots if root["target_depth"] == 24)
        changed.update(cp=None, mate=-1)
        self.write_evidence()
        result = self.build()
        self.assertEqual(result["depth_changes"]["numeric_positions_n"], 1)
        self.assertEqual(result["counts"]["engine_verified_n"], 1)
        self.assertEqual(result["failure_reasons_overlapping"]["mate_in_any_legal_root"], 1)


if __name__ == "__main__":
    unittest.main()
