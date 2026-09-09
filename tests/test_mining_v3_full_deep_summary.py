import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import chess

from scripts import mining_v3_full_deep_summary as summary
from tests import test_mining_v3_deep_summary as prior_tests


class FullDeepSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_progress_reads_only_the_hash_bound_prefix(self):
        path = self.directory / "roots.jsonl"
        prefix = b'{"id":"private-observation-1"}\n'
        path.write_bytes(prefix + b'{"id":"writer-is-still-appending')
        actual = summary.read_prefix(path, len(prefix), hashlib.sha256(prefix).hexdigest())
        self.assertEqual(actual, [{"id": "private-observation-1"}])
        with self.assertRaisesRegex(ValueError, "hash changed"):
            summary.read_prefix(path, len(prefix), "0" * 64)

    def test_progress_checkpoint_cannot_end_inside_a_record(self):
        path = self.directory / "roots.jsonl"
        fragment = b'{"id":"not-terminated"}'
        path.write_bytes(fragment)
        with self.assertRaisesRegex(ValueError, "inside a record"):
            summary.read_prefix(path, len(fragment), hashlib.sha256(fragment).hexdigest())
        with self.assertRaisesRegex(ValueError, "hash changed"):
            summary.read_prefix(path, len(fragment) + 20, hashlib.sha256(fragment).hexdigest())

    def test_pending_positions_have_no_outcome_classification(self):
        result = summary.group_counts({"old", "new", "pending"}, {"old", "new"}, {"old"})
        self.assertEqual(result, {"planned_n": 3, "completed_n": 2, "pending_n": 1,
                                  "imported_completed_n": 1, "new_completed_n": 1, "outcomes": None})

    def test_attempt_clock_includes_suspension_without_inventing_compute(self):
        run = {"started_at": 100., "attempts": [
            {"started_at": 100., "finished_at": 200., "complete": False},
            {"started_at": 300.}]}
        value = summary.attempt_timing(run, 10300., False)
        self.assertEqual(value["closed_attempt_elapsed_wall_seconds"], 100.)
        self.assertEqual(value["open_attempt_elapsed_wall_seconds_to_checkpoint"], 10000.)
        self.assertEqual(value["attempt_elapsed_wall_seconds_to_checkpoint"], 10100.)
        self.assertEqual(value["run_elapsed_wall_seconds_to_checkpoint"], 10200.)
        self.assertIsNone(value["active_compute_seconds"])
        self.assertIsNone(value["host_suspension_seconds"])
        self.assertFalse(value["host_suspension_measured"])
        with self.assertRaisesRegex(ValueError, "open final attempt"):
            summary.attempt_timing(run, 10300., True)

    def test_missing_prior_finish_time_is_not_imputed(self):
        run = {"started_at": 100., "attempts": [
            {"started_at": 100.},
            {"started_at": 300., "finished_at": 400., "complete": True}]}
        value = summary.attempt_timing(run, 400., True)
        self.assertEqual(value["unfinished_prior_attempts_n"], 1)
        self.assertEqual(value["closed_attempt_elapsed_wall_seconds"], 100.)
        self.assertIsNone(value["attempt_elapsed_wall_seconds_to_checkpoint"])

    def test_progress_root_must_belong_to_exact_legal_plan(self):
        board = chess.Board()
        record = {"id": "private-position", "fen": board.fen()}
        move = "e2e4"
        legal = {action.uci() for action in board.legal_moves}
        root = {"id": summary.old_runner.task_id(record["id"], 20, move),
                "record_id": record["id"], "fen": record["fen"], "uci": move,
                "target_depth": 20, "depth": 20, "board_context": "fen_only",
                "reached_target": True, "score_is_exact": True,
                "cp": 5, "mate": None, "wall_seconds": 3., "nodes": 100}
        summary.check_root_fields(root, record, legal)
        for mutation, reason in (({"depth": 19}, "exact target-depth"),
                                 ({"upperbound": True}, "exact target-depth"),
                                 ({"uci": "e2e5"}, "legal-root plan"),
                                 ({"cp": None, "mate": "1"}, "typed mate"),
                                 ({"wall_seconds": float("nan")}, "timing or node")):
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, reason):
                    summary.check_root_fields({**root, **mutation}, record, legal)


class FullCensusBuildTests(unittest.TestCase):
    """Three-state fixture: two imported, one new, and one duplicate origin."""
    def setUp(self):
        self.prior = prior_tests.DeepSummaryTests()
        self.prior.setUp()
        self.addCleanup(self.prior.doCleanups)
        patcher = mock.patch.multiple(summary, TOTAL_N=3, IMPORTED_N=2, OBSERVATIONS_N=4)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.directory = self.prior.root / "census"
        self.directory.mkdir()
        self.run_dir = self.directory / "run"
        self.run_dir.mkdir()
        self.input = self.directory / "positions.jsonl"
        self.policy = self.directory / "policies.jsonl"
        self.selection = self.directory / "selection_manifest.json"
        self.protocol = self.directory / "selection_protocol.json"
        self.public_prior = self.directory / "prior-public.json"
        previous = self.prior.build()
        self.public_prior.write_text(json.dumps(previous))
        board = chess.Board()
        history = ["d2d4", "g8f6"]
        states = [board.fen()]
        for move in history:
            board.push_uci(move)
            states.append(board.fen())
        moves = sorted(move.uci() for move in board.legal_moves)
        record = {**self.prior.records[0], "id": "PRIVATE-NEW", "fen": board.fen(),
                  "history_uci": history, "history_fens": states, "played_move": moves[0]}
        probabilities = {move: .04 if move == moves[0] else .96 / (len(moves) - 1) for move in moves}
        policy = {"id": record["id"], "fen": record["fen"], "history_available": True,
                  "input_condition": "fen_only", "maia3": {"history": {}, "fen_only": {
                      str(rating): probabilities for rating in (1400, 1700, 2000, 2300)}}}
        self.records = self.prior.records + [record]
        self.policies = self.prior.policies + [policy]
        self.new_roots = []
        for depth in (20, 24):
            for move in moves:
                self.new_roots.append({"id": summary.old_runner.task_id(record["id"], depth, move),
                    "record_id": record["id"], "fen": record["fen"], "uci": move,
                    "target_depth": depth, "depth": depth, "board_context": "fen_only",
                    "reached_target": True, "score_is_exact": True, "lowerbound": False, "upperbound": False,
                    "cp": 0 if move == moves[0] else -100, "mate": None, "wall_seconds": 3., "nodes": 1000,
                    "pv": [{"uci": move, "san": board.san(chess.Move.from_uci(move))}],
                    "evidence_origin": "new_full_census", "attempt_index": 1})
        self.write_lines(self.input, self.records)
        self.write_lines(self.policy, self.policies)
        initial_hashes = {"positions.jsonl": previous["fingerprints"]["input_sha256"],
                          "policies.jsonl": previous["fingerprints"]["policy_sha256"]}
        protocol = {"created_at": "1970-01-01T00:03:30Z", "expected_n": 3, "initial_n": 2, "seed": 9,
                    "input_hashes": {}, "initial_selection_hashes": initial_hashes,
                    "selection_script_sha256": summary.digest(summary.selector.__file__),
                    "selection_function_sha256": hashlib.sha256(inspect.getsource(summary.selector.choose_census).encode()).hexdigest(),
                    "screen_gate_function_sha256": hashlib.sha256(inspect.getsource(summary.selector.is_screen_candidate).encode()).hexdigest()}
        self.protocol.write_text(json.dumps(protocol))
        origins = {row["id"]: [summary.selector.origin_metadata(row, set())] for row in self.records}
        alias = {**record, "id": "PRIVATE-ALIAS", "game_id": "PRIVATE-OTHER-GAME",
                 "contains_bot": True, "known_public_game": True, "analysis_role": "public_exposed"}
        origins[record["id"]].append(summary.selector.origin_metadata(alias, {alias["game_id"]}))
        self.manifest = {"complete": True, "created_at": "1970-01-01T00:03:31Z", "seed": 9,
            "selected_n": 3, "selected_ids": [row["id"] for row in self.records],
            "already_deep200_n": 2, "already_deep200_ids": [row["id"] for row in self.prior.records], "new_n": 1,
            "positions_sha256": summary.digest(self.input), "policies_sha256": summary.digest(self.policy),
            "selection_script_sha256": summary.digest(summary.selector.__file__),
            "selection_protocol_sha256": summary.digest(self.protocol),
            "input_hashes": {}, "initial_selection_hashes": initial_hashes,
            "old200_selection_manifest_sha256": previous["fingerprints"]["selection_manifest_sha256"],
            "strata_by_id": {row["id"]: summary.runner.classify_strata(row) for row in self.records},
            "canonical_origins_by_id": origins,
            "state_provenance_by_id": {key: summary.selector.state_provenance(group) for key, group in origins.items()},
            "counts": {"screen_candidates_n": 4},
            "original_position_line_sha256": {row["id"]: hashlib.sha256(line).hexdigest() for row, line in zip(self.records, self.input.read_bytes().splitlines(keepends=True))},
            "original_policy_line_sha256": {row["id"]: hashlib.sha256(line).hexdigest() for row, line in zip(self.policies, self.policy.read_bytes().splitlines(keepends=True))},
            "legal_roots": {"total": sum(chess.Board(row["fen"]).legal_moves.count() for row in self.records)}}
        self.selection.write_text(json.dumps(self.manifest))
        reuse = {**previous["fingerprints"], "prior_public_summary_sha256": summary.digest(self.public_prior)}
        settings = {**summary.runner.SCORE_SETTINGS, **summary.runner.scoring_fingerprints(self.prior.engine),
                    "python_chess_version": chess.__version__, "workers": 2,
                    "input_sha256": summary.digest(self.input), "policy_sha256": summary.digest(self.policy),
                    "selection_manifest_sha256": summary.digest(self.selection), "reuse": reuse}
        self.run = {"settings": settings, "reuse": {"fingerprints": reuse}, "complete": True,
                    "input_n": 3, "root_searches_n": len(self.prior.roots) + len(self.new_roots),
                    "imported_positions_n": 2, "imported_root_searches_n": len(self.prior.roots),
                    "planned_new_positions_n": 1, "planned_new_root_searches_n": len(self.new_roots),
                    "completed_positions_n": 3, "completed_new_positions_n": 1,
                    "completed_root_searches_n": len(self.prior.roots) + len(self.new_roots),
                    "completed_new_root_searches_n": len(self.new_roots),
                    "started_at": 220., "updated_at": 240., "finished_at": 240.,
                    "attempts": [{"started_at": 220., "finished_at": 240., "complete": True,
                                  "monotonic_elapsed_seconds": 19.}]}
        (self.run_dir / "imported_roots.jsonl").write_bytes((self.prior.run_dir / "roots.jsonl").read_bytes())
        self.run["imported_roots_sha256"] = summary.digest(self.run_dir / "imported_roots.jsonl")
        self.saved = [summary.runner.summarize_record(row, policy,
            [root for root in self.prior.roots + self.new_roots if root["record_id"] == row["id"]],
            self.manifest["strata_by_id"][row["id"]], row["id"] != record["id"])
            for row, policy in zip(self.records, self.policies)]
        self.write_lines(self.run_dir / "positions.jsonl", self.saved)
        self.write_evidence()

    @staticmethod
    def write_lines(path, values):
        path.write_text("".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values))

    def write_evidence(self):
        self.write_lines(self.run_dir / "roots.jsonl", self.new_roots)
        self.run["settings_sha256"] = hashlib.sha256(json.dumps(self.run["settings"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.run["roots_sha256"] = summary.digest(self.run_dir / "roots.jsonl")
        self.run["positions_sha256"] = summary.digest(self.run_dir / "positions.jsonl")
        self.checkpoint = {"settings_sha256": self.run["settings_sha256"],
            "bytes": (self.run_dir / "roots.jsonl").stat().st_size,
            "sha256": self.run["roots_sha256"], "root_searches_n": len(self.new_roots), "updated_at": 239.}
        (self.run_dir / "checkpoint.json").write_text(json.dumps(self.checkpoint))
        (self.run_dir / "run.json").write_text(json.dumps(self.run))

    def build(self, require_complete=False):
        return summary.build_summary(self.input, self.policy, self.selection, self.run_dir,
                                     self.prior.engine, require_complete, self.public_prior)

    def test_final_outcomes_recomputed_with_imported_and_new_work_separate(self):
        result = self.build(require_complete=True)
        self.assertTrue(result["complete"])
        self.assertEqual(result["counts"]["checked_n"], 3)
        self.assertEqual(result["counts"]["engine_verified_n"], 3)
        self.assertEqual(result["counts"]["survives_candidate_criterion_n"], 2)
        self.assertEqual(result["counts"]["trainer_ready_n"], 0)
        self.assertEqual(result["previously_completed_initial_batch"]["survives_candidate_criterion_n"], 1)
        self.assertEqual(result["runtime"]["new_run_attempts"]["attempt_elapsed_wall_seconds_to_checkpoint"], 20.)
        self.assertEqual(result["runtime"]["new_run_attempts"]["closed_attempt_recorded_monotonic_seconds"], 19.)
        self.assertEqual(result["runtime"]["new_root_search_seconds"]["sum"], 3. * len(self.new_roots))
        self.assertEqual(result["selection"]["maximum_selected_positions_per_source_game"], 2)

    def test_progress_uses_checkpoint_counts_and_withholds_new_outcomes(self):
        self.run["complete"] = False
        self.new_roots = self.new_roots[:1]
        self.write_evidence()
        with (self.run_dir / "roots.jsonl").open("ab") as stream:
            stream.write(b'{"unanchored":"partial')
        result = self.build()
        self.assertFalse(result["complete"])
        self.assertEqual(result["counts"]["completed_positions_n"], 2)
        self.assertEqual(result["counts"]["pending_positions_n"], 1)
        self.assertEqual(result["counts"]["new_completed_positions_n"], 0)
        self.assertEqual(result["counts"]["partially_searched_positions_n"], 1)
        self.assertIsNone(result["counts"]["engine_verified_n"])
        self.assertIsNone(result["groups"]["by_evidence_origin"]["new_full_census"]["outcomes"])
        self.assertFalse(result["validation"]["all_outcomes_recomputed"])
        with self.assertRaisesRegex(ValueError, "must finish"):
            self.build(require_complete=True)

    def test_any_origin_exposure_does_not_disappear_behind_clean_representative(self):
        result = self.build()
        self.assertEqual(result["groups"]["representative_strata"]["bot_status"]["no_bot"]["planned_n"], 3)
        flags = result["groups"]["any_origin_provenance"]
        self.assertEqual(flags["any_bot_tagged"]["planned_n"], 1)
        self.assertEqual(flags["any_known_public"]["planned_n"], 1)
        self.assertEqual(flags["all_origins_recovered_no_bot_not_known_public"]["planned_n"], 2)

    def test_missing_duplicate_and_inexact_roots_fail_even_with_new_hashes(self):
        original = list(self.new_roots)
        for replacement, error in ((original[:-1], "incomplete legal-root coverage"),
                                   (original + [original[0]], "Duplicate"),
                                   ([{**original[0], "depth": 19}] + original[1:], "exact target-depth")):
            with self.subTest(error=error):
                self.new_roots = replacement
                self.write_evidence()
                with self.assertRaisesRegex(ValueError, error):
                    self.build()

    def test_final_saved_outcomes_are_not_trusted(self):
        self.saved[-1]["survives"] = False
        self.write_lines(self.run_dir / "positions.jsonl", self.saved)
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, "exhaustive recomputation"):
            self.build()

    def test_changed_frozen_code_or_prior_report_hash_is_rejected(self):
        for key in ("runner_sha256", "original_runner_sha256", "engine_sha256", "canonicalization_sha256"):
            with self.subTest(key=key):
                original = self.run["settings"][key]
                self.run["settings"][key] = "0" * 64
                self.write_evidence()
                with self.assertRaisesRegex(ValueError, "hash changed"):
                    self.build()
                self.run["settings"][key] = original
        self.write_evidence()
        self.public_prior.write_text(self.public_prior.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "Prior public summary hash changed"):
            self.build()

    def test_public_aggregate_does_not_leak_positions_origins_moves_or_paths(self):
        result = self.build()
        text = json.dumps(result)
        for private in ("PRIVATE-", str(self.directory), str(summary.ROOT), *(row["fen"] for row in self.records)):
            self.assertNotIn(private, text)
        forbidden = {"id", "game_id", "record_id", "fen", "uci", "pv", "history_uci", "history_fens",
                     "selected_ids", "already_deep200_ids", "path", "source", "strata_by_id"}
        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & forbidden)
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(result)


if __name__ == "__main__":
    unittest.main()
