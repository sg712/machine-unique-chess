"""Independent synthetic evidence checks for the prospective continuing workflow."""
import copy
import math
from pathlib import Path
import random
import threading
import time
import unittest
from unittest.mock import patch

import chess
import chess.engine

from scripts import prospective_analysis_20260916 as audit


def fixture(role="calibration_development", key="sample", black=False):
    initial = "7k/5ppp/8/8/8/8/PPP5/K6R w - - 0 1"
    board = chess.Board(initial)
    history, states = [], [board.fen()]
    rng = random.Random(52)
    for _ in range(15 if black else 14):
        move = rng.choice(list(board.legal_moves))
        history.append(move.uci()); board.push(move); states.append(board.fen())
    row = {"id": key, "analysis_role": role, "game_id": key, "initial_fen": initial,
        "fen": board.fen(), "history_uci": history, "history_fens": states[-8:], "history_available": True,
        "ply": len(history) + 1, "played_move": sorted(m.uci() for m in board.legal_moves)[0],
        "side_to_move": "white" if board.turn else "black", "white_elo": 1600, "black_elo": 1900,
        "mover_elo": 1600 if board.turn else 1900, "phase": "endgame",
        "rating_group": "1400_1799" if board.turn else "1800_2399", "contains_bot": False,
        "known_project_public_exposure": False, "source_canonical_state_hashes": sorted({audit.string_hash(audit.canonical_fen(fen)) for fen in states}),
        "source_move_sequence_sha256": audit.string_hash(key), "player_hashes": {"white": "w", "black": "b"}}
    return row


def policy(row, p=.1):
    legal = sorted(m.uci() for m in chess.Board(row["fen"]).legal_moves)
    probs = {m: (p if m == legal[0] else (1 - p) / (len(legal) - 1)) for m in legal}
    return {"id": row["id"], "fen": row["fen"], "rating_pairs": {k: list(v) for k, v in audit.rating_pairs(row).items()},
            "policies": {c: {label: dict(probs) for label in audit.rating_pairs(row)} for c in ("history", "fen_only")}}


def root(row, depth, move, cp):
    board = chess.Board(row["fen"])
    return {"record_id": row["id"], "fen": row["fen"], "target_depth": depth, "requested_root": move,
        "board_context": "fen_only", "depth": depth, "reached_target": True, "cp": cp, "mate": None,
        "score_is_exact": True, "lowerbound": False, "upperbound": False, "nodes": 100,
        "pv": [{"uci": move, "san": board.san(chess.Move.from_uci(move))}], "status": "complete_numeric"}


def roots(row):
    legal = sorted(m.uci() for m in chess.Board(row["fen"]).legal_moves)
    return {str(d): {m: root(row, d, m, 100 if m == legal[0] else 0) for m in legal} for d in audit.depths_for(row)}


class SourceAndSelectionTests(unittest.TestCase):
    def test_history_metadata_and_recorded_choice_verified(self):
        row = fixture()
        audit.validate_row(row)
        for key, value in (("mover_elo", 1900), ("white_elo", 2500), ("history_available", False),
                           ("history_uci", ["e2e5"]), ("played_move", "a1a8"), ("source_canonical_state_hashes", [])):
            changed = {**row, key: value}
            with self.subTest(key=key), self.assertRaises((ValueError, chess.IllegalMoveError)):
                audit.validate_row(changed)

    def test_cross_game_target_exposure_rejected(self):
        first, second = fixture(key="first"), fixture(key="second", black=True)
        first["source_canonical_state_hashes"].append(audit.string_hash(audit.canonical_fen(second["fen"])))
        with self.assertRaisesRegex(ValueError, "another source game"):
            audit.validate_cohort_rows([first, second])

    def test_tranche_is_bounded_balanced_and_order_independent(self):
        rows = []
        for role in audit.ROLES:
            for i in range(128):
                rows.append({"id": f"{role}-{i}", "analysis_role": role,
                             "side_to_move": "white" if i % 2 else "black",
                             "rating_group": "1400_1799" if (i // 2) % 2 else "1800_2399"})
        first, deficits = audit.tranche(rows)
        second, _ = audit.tranche(list(reversed(rows)))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertTrue(all(value == 0 for value in deficits.values()))
        self.assertEqual(sum(r["analysis_role"] == "targeted_endgame" for r in first), 32)
        _, missing = audit.tranche(rows[:1])
        self.assertGreater(sum(missing.values()), 0)

    def test_never_attempted_roots_precede_capped_retries(self):
        first, second = fixture(key="first"), fixture("calibration_evaluation", key="second", black=True)
        saved = {first["id"]: {}, second["id"]: {}}
        move = sorted(m.uci() for m in chess.Board(first["fen"]).legal_moves)[0]
        failed = root(first, 20, move, 100)
        failed.update(depth=10, reached_target=False, status="capped_or_interrupted", attempt_number=1)
        saved[first["id"]] = {"20": {move: failed}}
        tasks = audit.scheduled_tasks([first, second], saved)
        self.assertEqual(tasks[-1][0]["id"], first["id"])
        self.assertEqual(tasks[-1][2], move)
        self.assertEqual(tasks[-1][3], 1)
        self.assertTrue(all(t[3] == 0 for t in tasks[:-1]))

    def test_actual_rating_pair_tracks_mover_not_always_white(self):
        self.assertEqual(audit.rating_pairs(fixture())["actual"], (1600, 1900))
        self.assertEqual(audit.rating_pairs(fixture(black=True))["actual"], (1900, 1600))
        self.assertEqual(set(audit.rating_pairs(fixture("targeted_endgame"))), {"actual", "fixed1700", "fixed2000"})


class EvidenceTests(unittest.TestCase):
    def test_stable_complete_source_event_is_scored(self):
        row = fixture()
        value = audit.position_result(row, roots(row), policy(row))
        self.assertTrue(value["verified_for_calibration"])
        self.assertTrue(value["observed_move_acceptable"])
        self.assertAlmostEqual(value["metrics"]["history"]["actual"]["p_acceptable"], .1)

    def test_good_alternatives_included_in_event(self):
        row = fixture(); evidence = roots(row)
        second = sorted(evidence["24"])[1]
        row["played_move"] = second
        for depth in evidence: evidence[depth][second]["cp"] = 80
        value = audit.position_result(row, evidence, policy(row))
        self.assertTrue(value["observed_move_acceptable"])
        self.assertEqual(value["acceptable_n"], 2)
        self.assertGreater(value["metrics"]["history"]["actual"]["p_acceptable"], .1)

    def test_incomplete_bound_mate_and_unstable_not_scored_as_calibration(self):
        row = fixture()
        for change, expected in ((lambda e, m: e["24"].pop(m), "incomplete_roots"),
            (lambda e, m: e["24"][m].update(depth=23, reached_target=False), "incomplete_roots"),
            (lambda e, m: e["24"][m].update(lowerbound=True), "incomplete_roots"),
            (lambda e, m: e["24"][m].update(cp=None, mate=-2), "mate_in_legal_root"),
            (lambda e, m: e["24"][m].update(cp=200), "unstable_acceptable_set")):
            evidence = roots(row); move = sorted(evidence["24"])[1]
            change(evidence, move)
            value = audit.position_result(row, evidence, policy(row))
            self.assertFalse(value["verified_for_calibration"])
            self.assertEqual(value["state"], expected)

    def test_targeted_depth14_is_only_approximate(self):
        row = fixture("targeted_endgame")
        value = audit.position_result(row, roots(row), policy(row))
        self.assertFalse(value["verified_for_calibration"])
        self.assertEqual(value["state"], "approximate_targeted_screen")
        self.assertEqual(set(value["metrics"]["history"]), {"actual", "fixed1700", "fixed2000"})

    def test_policies_require_actual_ratings_and_all_legal_probabilities(self):
        row = fixture(); value = policy(row)
        audit.validate_policy_result(row, value)
        for change in (lambda p: p["rating_pairs"].update(actual=[1900, 1600]),
                       lambda p: p["policies"]["history"]["actual"].update(fake=.1),
                       lambda p: p.update(fen=chess.STARTING_FEN)):
            changed = copy.deepcopy(value); change(changed)
            with self.assertRaises(ValueError): audit.validate_policy_result(row, changed)

    def test_engine_exact_identity_and_pv_verified(self):
        row = fixture(); evidence = roots(row)
        move = sorted(evidence["20"])[0]; value = evidence["20"][move]
        self.assertEqual(audit.evidence_status(row, value, 20, move), "complete_numeric")
        for change in (lambda r: r.update(fen=chess.STARTING_FEN),
                       lambda r: r["pv"][0].update(uci="a1a8"), lambda r: r.update(cp=float("nan"))):
            bad = copy.deepcopy(value); change(bad)
            with self.assertRaises(ValueError): audit.evidence_status(row, bad, 20, move)

    def test_brier_logloss_bins_and_missingness(self):
        value = audit.calibration_metrics([(.1, False), (.9, True)])
        self.assertAlmostEqual(value["brier"], .01)
        self.assertAlmostEqual(value["log_loss"], -math.log(.9))
        self.assertEqual(sum(b["n"] for b in value["bins"]), 2)
        self.assertTrue(all(b["sparse"] for b in value["bins"]))
        self.assertEqual(audit.calibration_metrics([]), {"n": 0, "brier": None, "log_loss": None, "bins": []})
        self.assertTrue(math.isfinite(audit.calibration_metrics([(0., True), (1., False)])["log_loss"]))

    def test_same_input_controls_bound_to_expected_rows(self):
        expected = audit.model_control_rows([fixture(), fixture("targeted_endgame", key="target", black=True)])
        values = [policy(row) for row in expected]
        self.assertEqual(audit.verify_control_predictions(expected, values), 0)
        values[0]["id"] = "unrelated"
        with self.assertRaises(ValueError): audit.verify_control_predictions(expected, values)


class ResumeAndSnapshotTests(unittest.TestCase):
    def test_battery_preflight_returns_before_model_or_engine_work(self):
        from tempfile import TemporaryDirectory
        row = fixture()
        with TemporaryDirectory() as directory, patch.object(audit, "load_plan", return_value=({}, [row])), \
             patch.object(audit, "load_saved", return_value=({}, {row["id"]: {}}, {})), \
             patch.object(audit, "power_state", return_value="battery"), \
             patch.object(audit, "report", return_value={"status": "paused_power"}), \
             patch.object(audit.chess.engine.SimpleEngine, "popen_uci") as engine:
            self.assertEqual(audit.run_locked(Path(directory))["status"], "paused_power")
            engine.assert_not_called()

    def test_evidence_inventory_hashes_exact_files_read(self):
        from tempfile import TemporaryDirectory
        row = fixture(); move = row["played_move"]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "roots").mkdir()
            (output / "plan.json").write_text("{}")
            (output / "engine_runtime.json").write_text("{}")
            result = root(row, 20, move, 100)
            path = output / "roots/one.json"
            audit.atomic_json(path, {"plan_sha256": audit.digest(output / "plan.json"),
                "runtime_sha256": audit.digest(output / "engine_runtime.json"), "result": result})
            _, saved, inventory = audit.load_saved(output, {}, [row])
            self.assertEqual(inventory, {"roots/one.json": audit.digest(path)})
            self.assertEqual(saved[row["id"]]["20"][move]["cp"], 100)
            (output / "roots/later.json").write_text("{}")
            self.assertNotIn("roots/later.json", inventory)


class WatchdogTests(unittest.TestCase):
    def test_nonscored_depth_update_cannot_promote_older_scored_pv(self):
        row = fixture(); move = row["played_move"]
        class Analysis:
            def __iter__(self):
                yield {"score": chess.engine.PovScore(chess.engine.Cp(10), chess.Board(row["fen"]).turn),
                       "depth": 23, "pv": [chess.Move.from_uci(move)], "nodes": 100}
                yield {"depth": 24, "currmove": chess.Move.from_uci(move)}
            def stop(self): pass
        class Engine:
            def configure(self, options): pass
            def analysis(self, *args, **kwargs): return Analysis()
            def close(self): pass
        with patch.object(audit, "power_state", return_value="ac"):
            value = audit.bounded_search(Engine(), row, 24, move, time.monotonic() + 3)
        self.assertEqual(value["depth"], 23)
        self.assertFalse(value["reached_target"])
        self.assertEqual(value["status"], "capped_or_interrupted")

    def test_power_pause_interrupts_search_and_remains_incomplete(self):
        row = fixture(); move = row["played_move"]
        class Analysis:
            def __init__(self): self.stopped = threading.Event()
            def __iter__(self):
                yield {"score": chess.engine.PovScore(chess.engine.Cp(10), chess.Board(row["fen"]).turn),
                       "depth": 5, "pv": [chess.Move.from_uci(move)], "nodes": 100}
                self.stopped.wait(3)
            def stop(self): self.stopped.set()
        class Engine:
            def configure(self, options): pass
            def analysis(self, *args, **kwargs): self.active = Analysis(); return self.active
            def close(self): self.active.stop()
        with patch.object(audit, "power_state", return_value="battery"):
            result = audit.bounded_search(Engine(), row, 20, move, time.monotonic() + 5)
        self.assertEqual(result["status"], "capped_or_interrupted")
        self.assertEqual(result["stop_reason"], "power_pause")
        self.assertLess(result["wall_seconds"], 2)


class SeparateTensorTests(unittest.TestCase):
    def test_actual_forward_pass_uses_separate_mover_and_opponent_tensors(self):
        import torch
        row = fixture(black=True)
        board = chess.Board(row["fen"])
        def mirror(move):
            parsed = chess.Move.from_uci(move)
            return chess.Move(chess.square_mirror(parsed.from_square), chess.square_mirror(parsed.to_square), promotion=parsed.promotion).uci()
        class Adapter:
            device = "cpu"
            all_moves = [mirror(m.uci()) for m in board.legal_moves]
            move_index = {m: i for i, m in enumerate(all_moves)}
            mirror_move = staticmethod(mirror)
            def tokens(self, boards): return torch.zeros(2)
            def get_legal_moves_mask(self, b, index): return torch.ones(len(index), dtype=torch.bool)
            def model(self, tokens, movers, opponents):
                self.seen = (movers.tolist(), opponents.tolist())
                return torch.zeros((len(movers), len(self.all_moves))), None, None
        adapter = Adapter()
        value = audit.predict_actual(adapter, [row])[0]
        self.assertEqual(adapter.seen, ([1900, 1900], [1600, 1600]))
        audit.validate_policy_result(row, value)


if __name__ == "__main__":
    unittest.main()
