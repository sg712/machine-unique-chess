"""Historical audit selection and matched-control integrity."""
import copy
import random
import unittest

import chess

from scripts.mining_v2_historical import (STRATA, distance, eligible, output_record,
                                         sample_matched, selected, stratum)
from scripts.mining_v2_sampling import canonical_fen


def fixtures():
    rng, rows = random.Random(81), []
    for elo in (1950, 2100, 2300, 2600):
        for i in range(6):
            board = chess.Board()
            for _ in range(15):
                board.push(rng.choice(list(board.legal_moves)))
            move = next(iter(board.legal_moves)).uci()
            rows.append({"fen": board.fen(), "game_id": f"fixture-{elo}-{i}",
                         "machine_unique": str(i < 2), "best_cp": str(i * 10),
                         "engine_margin": str(100 + i * 5), "mover_elo": str(elo),
                         "white_elo": str(elo + 50), "black_elo": str(elo),
                         "ply": "16", "batch": "batch-a", "played_move": move,
                         "engine_best": move, "p_max": "0.01" if i < 2 else "0.3"})
    return rows


class HistoricalSamplingTests(unittest.TestCase):
    def test_rating_boundaries_and_screen(self):
        self.assertEqual([stratum(x) for x in (2000, 2001, 2200, 2201, 2400, 2401)],
                         [STRATA[0], STRATA[1], STRATA[1], STRATA[2], STRATA[2], STRATA[3]])
        row = fixtures()[0]
        for cp in (-200, 200):
            self.assertTrue(eligible({**row, "best_cp": str(cp), "engine_margin": "70"}))
        for updates in ({"best_cp": "200.1"}, {"engine_margin": "69.9"}, {"best_cp": "nan"}):
            self.assertFalse(eligible({**row, **updates}))

    def test_matching_balance_uniqueness_and_reproducibility(self):
        rows = fixtures()
        # Duplicate canonical boards with different IDs and duplicate recorded
        # games with different boards must never yield repeat observations.
        rows.extend([{**rows[-1], "game_id": "duplicate-board"},
                     {**rows[-2], "game_id": rows[-1]["game_id"]}])
        pairs, stats = sample_matched(rows, per_stratum=2)
        again, _ = sample_matched(list(reversed(rows)), per_stratum=2)
        self.assertEqual([(p["case"]["fen"], p["control"]["fen"]) for p in pairs],
                         [(p["case"]["fen"], p["control"]["fen"]) for p in again])
        self.assertEqual(len(pairs), 8)
        records = [r for p in pairs for r in (p["case"], p["control"])]
        self.assertEqual(len({r["game_id"] for r in records}), 16)
        self.assertEqual(len({canonical_fen(r["fen"]) for r in records}), 16)
        for band in STRATA:
            self.assertEqual(sum(p["stratum"] == band for p in pairs), 2)
        self.assertTrue(all(selected(p["case"]) and not selected(p["control"]) for p in pairs))
        self.assertTrue(all(stratum(float(p["control"]["mover_elo"])) == p["stratum"] for p in pairs))
        self.assertEqual(stats["batch_fallback_pairs"], 0)

    def test_exact_batch_preference_and_reported_fallback(self):
        rows = fixtures()
        for r in rows:
            if not selected(r):
                r["batch"] = "other-batch"
        _, stats = sample_matched(rows, per_stratum=1)
        self.assertEqual(stats["batch_fallback_pairs"], 4)
        for elo in (1950, 2100, 2300, 2600):
            control = next(r for r in rows if not selected(r) and r["mover_elo"] == str(elo))
            control["batch"] = "batch-a"
            control["engine_margin"] = "900"
        pairs, stats = sample_matched(rows, per_stratum=1)
        self.assertTrue(all(p["control"]["batch"] == "batch-a" for p in pairs))
        self.assertEqual(stats["batch_fallback_pairs"], 0)

    def test_distance_uses_declared_scales(self):
        a = {"best_cp": "0", "engine_margin": "100", "mover_elo": "2100", "ply": "20"}
        b = {"best_cp": "50", "engine_margin": "150", "mover_elo": "2200", "ply": "26"}
        self.assertEqual(distance(a, b), 1.0)

    def test_fen_only_metadata_does_not_claim_real_history(self):
        row = output_record(fixtures()[0], "candidate", "fixture-hash")
        self.assertFalse(row["history_available"])
        self.assertFalse(row["initial_fen_is_game_start"])
        self.assertEqual(row["history_uci"], [])
        self.assertEqual(row["history_fens"], [row["fen"]])
        self.assertIsNone(row["clock_seconds_before"])
        self.assertIsNone(row["opponent_clock_seconds"])
        self.assertIsNone(row["time_control"])


if __name__ == "__main__":
    unittest.main()
