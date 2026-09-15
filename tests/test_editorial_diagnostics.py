"""Prevent diagnostic drift, source leakage, and misleading single-move probabilities."""
import copy
from pathlib import Path
import tempfile
import unittest

from scripts import editorial_diagnostics as diagnostics


def fixture(key="editorial", role="new_train"):
    # Abstract legal-root labels keep these arithmetic tests independent of chess search.
    record = {"id": key, "fen": "private-board", "side_to_move": "white", "phase": "middlegame",
              "analysis_role": role, "mover_elo": 2000}
    maps = {rating: {"a": .01, "b": .03, "c": .03, "d": .93} for rating in diagnostics.RATINGS}
    policy = {"id": key, "fen": record["fen"], "input_condition": "fen_only",
              "maia3": {"history": {}, "fen_only": maps}}
    scores = {"20": {"a": 0, "b": -15, "c": -25, "d": -100},
              "24": {"a": 0, "b": -15, "c": -35, "d": -100}}
    outcome = {"fen": record["fen"], "survives": True, "engine_verified": True, "trainer_ready": False,
        "legal_count": 4, "accepted": {depth: ["a", "b"] for depth in diagnostics.DEPTHS},
        "best_moves": {depth: ["a"] for depth in diagnostics.DEPTHS},
        "best_cp": {depth: 0 for depth in diagnostics.DEPTHS}, "metrics": {}}
    for depth in diagnostics.DEPTHS:
        outcome["metrics"][depth] = {f"maia3/fen_only/{rating}": {"20": diagnostics.review.scorer.original.base.probability_summary(
            {move: {"cp": cp, "mate": None} for move, cp in scores[depth].items()}, maps[rating], 20)}
            for rating in diagnostics.RATINGS}
    origins = [{"game_id": "private-source-" + key, "public_game_detected": False,
        "strata": {"bot_status": "no_bot", "history_status": "recovered",
                   "public_exposure": "not_known_public", "analysis_role": role}}]
    manifest = {"canonical_origins_by_id": {key: origins},
                "state_provenance_by_id": {key: diagnostics.review.selection.state_provenance(origins)}}
    return record, outcome, policy, scores, manifest


class EditorialDiagnosticsTests(unittest.TestCase):
    def test_exact_top_set_and_acceptable_mass_are_not_confused(self):
        _, outcome, policy, scores, _ = fixture()
        result = diagnostics.position_diagnostics(outcome, policy, scores)
        metric = result["metrics"]["24"]["1700"]
        self.assertAlmostEqual(metric["exact_top_tie_set_mass"], .01)
        self.assertAlmostEqual(metric["acceptable_set_mass"], .04)
        self.assertAlmostEqual(metric["extra_acceptable_mass"], .03)
        self.assertEqual(result["multiplicity"], 2)

    def test_tolerance_joint_gate_detects_depth_disagreement(self):
        _, outcome, policy, scores, _ = fixture()
        result = diagnostics.position_diagnostics(outcome, policy, scores)
        self.assertTrue(result["tolerance_sensitivity"]["20"]["passes_jointly"])
        self.assertTrue(result["tolerance_sensitivity"]["30"]["passes_probability_both_depths"])
        self.assertFalse(result["tolerance_sensitivity"]["30"]["same_acceptable_set_both_depths"])
        self.assertFalse(result["tolerance_sensitivity"]["30"]["passes_jointly"])

    def test_reconciliation_rejects_missing_roots_changed_metrics_and_illegal_policy(self):
        _, outcome, policy, scores, _ = fixture()
        broken_scores = copy.deepcopy(scores)
        del broken_scores["24"]["c"]
        with self.assertRaisesRegex(ValueError, "coverage"):
            diagnostics.position_diagnostics(outcome, policy, broken_scores)
        bad_outcome = copy.deepcopy(outcome)
        bad_outcome["metrics"]["20"]["maia3/fen_only/1700"]["20"]["p_good_upper"] += .01
        with self.assertRaisesRegex(ValueError, "differs from frozen"):
            diagnostics.position_diagnostics(bad_outcome, policy, scores)
        bad_policy = copy.deepcopy(policy)
        bad_policy["maia3"]["fen_only"]["2000"]["unscored"] = 0
        with self.assertRaisesRegex(ValueError, "complete legal"):
            diagnostics.position_diagnostics(outcome, bad_policy, scores)

    def test_all_origin_holdout_is_excluded_before_diagnostic_access(self):
        record, outcome, policy, scores, manifest = fixture()
        held_record, held_outcome, _, _, held_manifest = fixture("held")
        alternate = copy.deepcopy(held_manifest["canonical_origins_by_id"]["held"][0])
        alternate["game_id"] = "private-heldout-source"
        alternate["strata"]["analysis_role"] = "new_test"
        held_manifest["canonical_origins_by_id"]["held"].append(alternate)
        held_manifest["state_provenance_by_id"]["held"] = diagnostics.review.selection.state_provenance(
            held_manifest["canonical_origins_by_id"]["held"])
        for field in manifest:
            manifest[field].update(held_manifest[field])
        report = diagnostics.build_report({"editorial": record, "held": held_record},
            {"editorial": outcome, "held": held_outcome}, manifest,
            {"editorial": policy, "held": "never inspect this policy"}, {"editorial": scores}, {})
        self.assertEqual(report["pool_counts"]["editorial_eligible"], 1)
        self.assertEqual(report["pool_counts"]["noneditorial_role_excluded"], 1)
        self.assertNotIn("private-source", diagnostics.review.encoded(report).decode())
        with self.assertRaisesRegex(ValueError, "exactly the editorial"):
            diagnostics.build_report({"editorial": record, "held": held_record},
                {"editorial": outcome, "held": held_outcome}, manifest,
                {"editorial": policy}, {"editorial": scores, "held": scores}, {})

    def test_aliases_and_multiple_origins_cannot_evade_source_dedup(self):
        origins = {"a": [{"game_id": "one", "legacy_game_id": "old-one"}],
            "b": [{"game_id": "old-one"}],
            "c": [{"game_id": "two"}, {"game_id": "one"}],
            "d": [{"game_id": "three"}]}
        report, selected = diagnostics.source_concentration(list(origins), origins)
        reversed_report, reversed_selected = diagnostics.source_concentration(list(reversed(origins)), origins)
        self.assertEqual((report, selected), (reversed_report, reversed_selected))
        self.assertEqual(report["unique_source_games_after_recorded_alias_collapse_n"], 3)
        self.assertEqual(report["position_game_incidences_n"], 5)
        self.assertEqual(report["max_positions_from_one_game_n"], 3)
        self.assertEqual(report["largest_overlap_component_positions_n"], 3)
        self.assertEqual(len(selected), 2)
        self.assertIn("d", selected)

    def test_partial_history_maps_do_not_produce_an_unsupported_comparison(self):
        record, outcome, policy, scores, manifest = fixture()
        policy["maia3"]["history"] = {"1700": policy["maia3"]["fen_only"]["1700"]}
        with self.assertRaisesRegex(ValueError, "compatible-context"):
            diagnostics.build_report({"editorial": record}, {"editorial": outcome}, manifest,
                                     {"editorial": policy}, {"editorial": scores}, {})

    def test_public_output_rejects_private_fields_paths_and_overwriting(self):
        for bad in ({"metadata": {"fen": "secret"}}, {"game_id": "secret"}, {"source": "/Users/name/private"}):
            with self.assertRaisesRegex(ValueError, "private"):
                diagnostics.assert_aggregate_only(bad)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "results").mkdir()
            output = root / "results/editorial_diagnostics_fixture.json"
            diagnostics.write_report(output, {"n": 1}, root)
            diagnostics.write_report(output, {"n": 1}, root)
            with self.assertRaises(FileExistsError):
                diagnostics.write_report(output, {"n": 2}, root)
            with self.assertRaisesRegex(ValueError, "Output must"):
                diagnostics.write_report(root / "results/mining_v3_full_deep.json", {"n": 1}, root)

    def test_rating_unknowns_and_quantiles_are_explicit(self):
        self.assertEqual(diagnostics.numeric_rating_bin(None), "unknown")
        self.assertEqual(diagnostics.numeric_rating_bin(2059), "2000_2199")
        self.assertEqual(diagnostics.summary([0, 10])["median"], 5)
        with self.assertRaises(ValueError):
            diagnostics.summary([float("nan")])


if __name__ == "__main__":
    unittest.main()
