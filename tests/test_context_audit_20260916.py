"""Guard paired inference design, provenance, legality, and threshold comparisons."""
import copy
import subprocess
import unittest
from unittest.mock import patch

import chess
from scripts import context_audit_20260916 as audit


def fixture(key="fixture", moves=("e2e4", "e7e5"), phase="middlegame", side=None):
    board = chess.Board()
    states = [board.fen()]
    for move in moves:
        board.push_uci(move)
        states.append(board.fen())
    record = {"id": key, "fen": board.fen(), "initial_fen": chess.STARTING_FEN,
        "history_available": True, "history_uci": list(moves), "history_fens": states[-8:],
        "ply": len(moves) + 1, "source": {"pgn_sha256": "a" * 64}, "phase": phase,
        "side_to_move": side or ("white" if board.turn else "black")}
    legal = sorted(move.uci() for move in board.legal_moves)
    scores = {d: {m: 100 if m == legal[0] else -100 for m in legal} for d in audit.DEPTHS}
    outcome = {"accepted": {d: [legal[0]] for d in audit.DEPTHS},
        "best_cp": {d: 100 for d in audit.DEPTHS}, "engine_verified": True,
        "metrics": {d: {f"maia3/fen_only/{r}": {"20": {"p_good_upper": .05, "capped_regret_lower_cp": 100}}
                            for r in audit.RATINGS} for d in audit.DEPTHS}}
    origins = [{"id": key, "game_id": key, "legacy_game_id": None}]
    return {"record": record, "outcome": outcome, "scores": scores, "origins": origins}


def distribution(item, good=.05, reverse=False):
    moves = sorted(item["scores"]["24"])
    value = {m: 0. for m in moves}
    value[moves[0]], value[moves[-1 if reverse else 1]] = good, 1 - good
    return value


def prediction(item, f=.05, h=.05, reverse=False):
    return {"id": item["record"]["id"], "fen": item["record"]["fen"], "history_available": True,
            "maia3": {c: {str(r): distribution(item, f if c == "fen_only" else h, reverse and c == "history")
                           for r in audit.RATINGS} for c in audit.CONDITIONS}}


class HistoryAuditTests(unittest.TestCase):
    def test_real_history_replay_and_eight_state_limit(self):
        item = fixture(moves="e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1".split())
        value = audit.history_check(item["record"], item["origins"])
        self.assertEqual(value["history_plies"], 9)
        self.assertEqual(value["history_tokens_including_current"], 8)
        self.assertFalse(value["repetition_sensitive"])

    def test_actual_repetition_flag_uses_full_stack(self):
        item = fixture(moves="g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8".split())
        flags = audit.history_check(item["record"], item["origins"])
        self.assertTrue(flags["target_previously_seen"])
        self.assertTrue(flags["threefold_claim_available"])
        self.assertFalse(chess.Board(item["record"]["fen"]).can_claim_threefold_repetition())

    def test_ambiguous_missing_fake_and_illegal_history_rejected(self):
        item = fixture()
        mutations = [("history_available", False), ("history_uci", []), ("source_match_count", 2),
                     ("history_fens", list(reversed(item["record"]["history_fens"]))),
                     ("history_uci", ["e2e5", "e7e5"]), ("ply", 4), ("source", {})]
        for field, value in mutations:
            changed = copy.deepcopy(item)
            changed["record"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit.history_check(changed["record"], changed["origins"])
        with self.assertRaises(ValueError):
            audit.history_check(item["record"], item["origins"] * 2)

    def test_deterministic_phase_side_quota_and_game_alias_exclusion(self):
        fixtures = [fixture(f"{phase}-{side}-{i}", phase=phase, side=side)
                    for phase in ("opening", "middlegame", "endgame") for side in ("white", "black") for i in range(4)]
        records = {i["record"]["id"]: i["record"] for i in fixtures}
        outcomes = {i["record"]["id"]: i["outcome"] for i in fixtures}
        origins = {i["record"]["id"]: i["origins"] for i in fixtures}
        first = audit.choose(records, outcomes, origins, 12)
        second = audit.choose(dict(reversed(list(records.items()))), outcomes, origins, 12)
        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), 12)
        self.assertTrue(all(v == 0 for v in first[-1]["phase_side_deficits"].values()))
        for origin in origins.values():
            origin[0]["legacy_game_id"] = "shared"
        constrained = audit.choose(records, outcomes, origins, 12)
        self.assertEqual(len(constrained[0]), 1)
        self.assertGreater(constrained[-1]["source_collision_skipped_n"], 0)
        self.assertEqual(sum(constrained[-1]["phase_side_deficits"].values()), 11)

    def test_sample_cannot_exceed_bounded_plan(self):
        for count in (0, 5, 7, 97, 102, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                audit.choose({}, {}, {}, count)

    def test_both_old_probability_and_regret_margins_stratify(self):
        item = fixture()
        self.assertEqual(audit.selection_bucket(item["record"], item["outcome"])[-1], "interior")
        item["outcome"]["metrics"]["20"]["maia3/fen_only/1700"]["20"]["p_good_upper"] = .075
        self.assertEqual(audit.selection_bucket(item["record"], item["outcome"])[-1], "near_gate")
        item["outcome"]["metrics"]["20"]["maia3/fen_only/1700"]["20"]["p_good_upper"] = .05
        item["outcome"]["metrics"]["24"]["maia3/fen_only/2000"]["20"]["capped_regret_lower_cp"] = 75
        self.assertEqual(audit.selection_bucket(item["record"], item["outcome"])[-1], "near_gate")


class PairedMetricTests(unittest.TestCase):
    def test_identical_policies_have_zero_paired_changes(self):
        item = fixture()
        result = audit.paired_metrics(item, prediction(item))
        self.assertEqual(result["condition_pass"], {"fen_only": True, "history": True})
        self.assertEqual(result["changes"]["1700"]["total_variation"], 0)
        self.assertEqual(result["changes"]["2000"]["by_depth"]["24"]["delta_p_acceptable"], 0)

    def test_exact_first_choice_change_is_not_criterion_change(self):
        item = fixture()
        result = audit.paired_metrics(item, prediction(item, reverse=True))
        self.assertTrue(result["changes"]["2000"]["top_choice_changed"])
        self.assertTrue(all(result["condition_pass"].values()))
        self.assertEqual(result["changes"]["2000"]["by_depth"]["24"]["delta_p_acceptable"], 0)

    def test_threshold_crossing_can_happen_without_top_choice_change(self):
        item = fixture()
        result = audit.paired_metrics(item, prediction(item, .09, .11))
        self.assertFalse(result["changes"]["2000"]["top_choice_changed"])
        self.assertEqual(result["condition_pass"], {"fen_only": True, "history": False})
        self.assertAlmostEqual(result["changes"]["2000"]["by_depth"]["24"]["delta_p_acceptable"], .02)

    def test_acceptable_set_mass_includes_good_alternatives(self):
        item = fixture()
        moves = sorted(item["scores"]["24"])
        for d in audit.DEPTHS:
            item["scores"][d][moves[1]] = 80
            item["outcome"]["accepted"][d].append(moves[1])
        p = {move: 0. for move in moves}
        p[moves[0]], p[moves[1]], p[moves[2]] = .05, .08, .87
        metric = audit.evidence_metrics(item["record"], item["outcome"], item["scores"], p)
        self.assertAlmostEqual(metric["24"]["p_acceptable"], .13)
        self.assertFalse(metric["24"]["candidate_gate"])

    def test_capped_regret_and_complete_support_required(self):
        item = fixture()
        good = item["outcome"]["accepted"]["24"][0]
        for d in audit.DEPTHS:
            item["scores"][d] = {m: 100 if m == good else -500 for m in item["scores"][d]}
        p = distribution(item)
        metric = audit.evidence_metrics(item["record"], item["outcome"], item["scores"], p)
        self.assertAlmostEqual(metric["24"]["capped_regret_cp"], .95 * 300)
        for bad in ({**p, good: float("nan")}, {m: v for m, v in p.items() if m != good}, {**p, good: .5}):
            with self.assertRaises(ValueError):
                audit.evidence_metrics(item["record"], item["outcome"], item["scores"], bad)

    def test_pair_identity_rating_and_condition_must_match(self):
        item = fixture()
        for mutation in (lambda r: r.update(id="other"), lambda r: r.update(history_available=False),
                         lambda r: r["maia3"].pop("history"), lambda r: r["maia3"]["history"].pop("1700")):
            p = prediction(item)
            mutation(p)
            with self.assertRaises(ValueError):
                audit.paired_metrics(item, p)

    def test_controls_reject_nonidentical_tokens_results(self):
        item = fixture()
        self.assertTrue(audit.check_controls([prediction(item)], [item["record"]])["passed"])
        with self.assertRaises(ValueError):
            audit.check_controls([prediction(item, .05, .05001)], [item["record"]])

    def test_controls_reject_wrong_identity_support_and_missing_rows(self):
        item = fixture()
        for change in (lambda p: p.update(id="unrelated"), lambda p: p.update(fen=chess.STARTING_FEN),
                       lambda p: p.update(history_available=False), lambda p: p["maia3"]["history"].pop("1700"),
                       lambda p: p["maia3"]["history"]["1700"].update(a1a8=.5),
                       lambda p: p["maia3"]["fen_only"].update({"1700": {"invalid": 1}})):
            value = prediction(item)
            change(value)
            with self.assertRaises(ValueError):
                audit.check_controls([value], [item["record"]])
        with self.assertRaises(ValueError):
            audit.check_controls([], [item["record"]])

    def test_numeric_batches_require_controls_before_reporting(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        item = fixture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "batches").mkdir()
            (root / "selection_manifest.json").write_text("{}")
            (root / "runtime.json").write_text("{}")
            audit.atomic_json(root / "batches/batch.json", {
                "selection_manifest_sha256": audit.digest(root / "selection_manifest.json"),
                "runtime_sha256": audit.digest(root / "runtime.json"), "predictions": [prediction(item)]})
            with self.assertRaisesRegex(ValueError, "require successful"):
                audit.read_batches(root, {}, [item])

    def test_existing_invalid_controls_stop_before_first_numeric_batch(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "controls.json").write_text("{}")
            with self.assertRaises((KeyError, ValueError)):
                audit.read_batches(root, {}, [fixture()])

    def test_resume_rejects_changed_imported_metric_and_summary_helpers(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            output = root / "data/mining_v3/context-test"
            output.mkdir(parents=True)
            adapter = root / "scripts/mining_v2_policy.py"
            adapter.write_text("adapter")
            for name in ("mining_v2_engine.py", "editorial_diagnostics.py"):
                (root / "scripts" / name).write_text("changed")
                audit.atomic_json(output / "selection_manifest.json", {
                    "audit_script_sha256": audit.digest(audit.__file__), "adapter_sha256": audit.digest(adapter),
                    "python_chess_version": chess.__version__, "dependency_sha256": {name: "old-hash"}})
                with patch.object(audit, "ROOT", root), self.assertRaisesRegex(ValueError, "dependency changed"):
                    audit.read_inputs(output)

    def test_empty_pending_report_has_no_numeric_observations(self):
        result = audit.group_report([fixture()], {})
        self.assertEqual(result["n"], 0)
        self.assertIsNone(result["by_rating"]["1700"]["total_variation"])


class PowerTests(unittest.TestCase):
    def test_only_confirmed_ac_allows_run(self):
        for text, expected in (("Now drawing from 'AC Power'", "ac"),
                               ("Now drawing from 'Battery Power'", "battery"), ("", "unknown")):
            with patch.object(audit.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, text)):
                self.assertEqual(audit.power_state(), expected)
        with patch.object(audit.subprocess, "run", side_effect=OSError()):
            self.assertEqual(audit.power_state(), "unknown")


if __name__ == "__main__":
    unittest.main()
