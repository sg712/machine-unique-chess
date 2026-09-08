"""Discovery isolation, complete move mass, and honest unknown-root accounting."""
from types import SimpleNamespace
import json
import unittest

import chess

from scripts.mining_v2_diagnostics import (
    canonical, compare_model_sizes, complete_depth, conditional_mass,
    heldout_exact_choice, public_aggregate, train_rankings,
)


FEN = "7k/8/8/8/8/8/8/K7 w - - 0 1"
MOVES = sorted(move.uci() for move in chess.Board(FEN).legal_moves)


def scores(values=(0, -10, -100)):
    return {move: {"uci": move, "cp": cp, "mate": None, "score_is_exact": True,
                   "lowerbound": False, "upperbound": False, "reached_target": True,
                   "depth": 24, "target_depth": 24}
            for move, cp in zip(MOVES, values)}


def fixture(ident="train-secret", split="train", distribution=(.2, .3, .5)):
    record = {"id": ident, "fen": FEN, "game_id": ident + "-game", "split": split,
              "cohort": "club", "mover_elo": 1900, "played_move": MOVES[0]}
    policy = {"id": ident, "fen": FEN, "history_available": True,
              "maia3": {"history": {"1400": dict(zip(MOVES, (.02, .08, .90))),
                                    "1700": dict(zip(MOVES, (.05, .15, .80))),
                                    "2000": dict(zip(MOVES, distribution)),
                                    "2300": dict(zip(MOVES, (.4, .5, .1)))},
                        "fen_only": {"1700": dict(zip(MOVES, (.7, .2, .1))),
                                     "2000": dict(zip(MOVES, (.8, .1, .1)))}}}
    result = {"id": ident, "fen": FEN, "split": split, "scores": scores(), "best": MOVES[0]}
    return record, policy, result


class DiagnosticsTests(unittest.TestCase):
    def test_partial_mass_retains_unknown_tail_and_no_unconditional_lower_claim(self):
        metric = conditional_mass({MOVES[0]: scores()[MOVES[0]]}, dict(zip(MOVES, (.2, .3, .5))))
        self.assertAlmostEqual(metric["observed_acceptable_mass"], .2)
        self.assertAlmostEqual(metric["unscored_mass"], .8)
        self.assertEqual(metric["acceptable_mass_interval_allowing_unobserved_better_move"], [0., 1.])
        self.assertEqual(metric["conditional_acceptable_mass_interval"], [.2, 1.])
        self.assertEqual(metric["conditional_capped_regret_interval_cp"], [0., 240.])
        self.assertFalse(metric["verified_human_solve_probability"])

    def test_bound_scores_are_unmeasured_even_when_exact_flag_is_inconsistent(self):
        values = scores()
        values[MOVES[1]]["lowerbound"] = True
        metric = conditional_mass(values, dict(zip(MOVES, (.2, .3, .5))))
        self.assertAlmostEqual(metric["unscored_mass"], .3)
        self.assertFalse(metric["all_legal_moves_have_point_scores"])
        self.assertFalse(complete_depth(values, set(MOVES)))

    def test_missing_or_unreached_depth_is_excluded_from_size_comparison(self):
        self.assertTrue(complete_depth(scores(), set(MOVES)))
        partial = scores()
        partial.pop(MOVES[2])
        self.assertFalse(complete_depth(partial, set(MOVES)))
        failed = scores()
        failed[MOVES[2]]["reached_target"] = False
        self.assertFalse(complete_depth(failed, set(MOVES)))

    def test_full_mass_adds_all_acceptable_moves_not_only_engine_target(self):
        record, small, _ = fixture(distribution=(.1, .5, .4))
        _, large, _ = fixture(distribution=(.4, .4, .2))
        deep = {canonical(FEN): {"fen": FEN, "split": "train", "verified": True,
                                "searches": {"24": scores()}}}
        items, excluded = compare_model_sizes({record["id"]: record}, {record["id"]: small},
                                              {record["id"]: large}, deep)
        metric = items[0]["depths"]["24"]["maia3/history/2000"]["20"]
        self.assertEqual(metric["acceptable_moves"], MOVES[:2])
        self.assertAlmostEqual(metric["maia3_5m"]["p_any_acceptable"], .6)
        self.assertAlmostEqual(metric["maia3_79m"]["p_any_acceptable"], .8)
        self.assertAlmostEqual(metric["maia3_5m"]["capped_regret_cp"], 45.)
        self.assertAlmostEqual(metric["maia3_79m"]["capped_regret_cp"], 24.)
        self.assertEqual(excluded, {})

    def test_training_rankings_never_use_validation_or_test_items(self):
        records, policies, results = {}, {}, {}
        for split in ("train", "validation", "test"):
            r, p, s = fixture("secret-" + split, split)
            records[r["id"]], policies[r["id"]], results[r["id"]] = r, p, s
        transitions, sensitivity, counts = train_rankings(records, policies, results)
        self.assertTrue(transitions)
        self.assertTrue(sensitivity)
        self.assertEqual({r["split"] for r in transitions + sensitivity}, {"train"})
        self.assertEqual({r["id"] for r in transitions + sensitivity}, {"secret-train"})
        self.assertEqual(counts["source_training_n"], 1)
        # Poisoning held-out values cannot change the discovery rankings.
        results["secret-test"]["scores"] = scores((9999, 9999, 9999))
        changed = train_rankings(records, policies, results)
        self.assertEqual(changed, (transitions, sensitivity, counts))

    def test_unknown_tail_prevents_a_false_rating_transition(self):
        record, policy, result = fixture(distribution=(.2, .3, .5))
        result["scores"] = {MOVES[0]: scores()[MOVES[0]]}
        transitions, _, _ = train_rankings({record["id"]: record}, {record["id"]: policy},
                                            {record["id"]: result})
        self.assertEqual(transitions, [])

    def test_heldout_bins_are_fixed_descriptive_and_exclude_training(self):
        records, policies, results = {}, {}, {}
        for index, probability in enumerate((.049, .05, .20, .50, 1.)):
            r, p, s = fixture("private-test-" + str(index), "test",
                              (probability, (1 - probability) / 2, (1 - probability) / 2))
            records[r["id"]], policies[r["id"]], results[r["id"]] = r, p, s
        r, p, s = fixture("private-train", "train")
        records[r["id"]], policies[r["id"]], results[r["id"]] = r, p, s
        diagnostic = heldout_exact_choice(records, policies, results)
        group = diagnostic["groups"]["all_test"]
        self.assertEqual(group["positions_n"], 5)
        self.assertEqual([b["positions_n"] for b in group["bins"]], [1, 1, 1, 2])
        self.assertTrue(all(b["sparse_fewer_than_30_games"] for b in group["bins"]))
        self.assertFalse(diagnostic["fit_performed"])
        self.assertEqual(diagnostic["groups"]["club_movers_1800_to_2000_test"]["positions_n"], 5)
        self.assertNotIn("private-test", json.dumps(diagnostic))

    def test_public_output_contains_no_item_identifiers_fens_or_moves(self):
        record, policy, result = fixture()
        transitions, sensitivity, counts = train_rankings({record["id"]: record},
                                                          {record["id"]: policy}, {record["id"]: result})
        public = public_aggregate(transitions, sensitivity, counts, [], {}, {"input": "a" * 64}, 0,
                                  SimpleNamespace(top_n=50, min_gain=.05, min_tv=.10))
        encoded = json.dumps(public)
        for private in (FEN, record["id"], record["game_id"], *MOVES):
            self.assertNotIn(private, encoded)


if __name__ == "__main__":
    unittest.main()
