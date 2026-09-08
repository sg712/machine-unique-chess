"""Sampling regressions: side parity, replayable metadata and split isolation."""
import copy
import importlib.util
import io
from pathlib import Path
import random
import unittest

import chess
import chess.pgn

from scripts.mining_v2_sampling import (canonical_fen, game_candidates, legacy_sampled_plies,
                                       select_balanced, split_for_game, validate_rows)

ROOT = Path(__file__).resolve().parents[1]
PGN = '''[Event "Rated rapid game"]
[Site "https://lichess.org/Abcd1234"]
[Date "2026.06.01"]
[WhiteElo "2000"]
[BlackElo "2200"]
[TimeControl "600+5"]
[Result "*"]

1. e4 {[%clk 0:10:00]} e5 {[%clk 0:09:59]}
2. Nf3 {[%clk 0:09:57]} Nc6 {[%clk 0:09:56]}
3. Bb5 {[%clk 0:09:54]} a6 {[%clk 0:09:52]}
4. Ba4 Nf6 {[%clk 0:09:48]} 5. O-O Be7 6. Re1 b5
7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7
11. c4 c6 12. cxb5 axb5 13. Nc3 Bb7 14. Bg5 b4
15. Nb1 h6 16. Bxf6 Bxf6 17. a3 bxa3 18. Nxa3 Re8
19. Nc4 Rxa1 20. Qxa1 Qc7 *
'''


def source():
    return {"archive": "synthetic.pgn", "member": "test", "game_index": 1,
            "sha256": "test-only", "cohort": "club"}


class SamplingV2Tests(unittest.TestCase):
    def test_legacy_stride_does_not_alias_to_black(self):
        game = chess.pgn.read_game(io.StringIO(PGN))
        chosen = legacy_sampled_plies(game, 4, 14, 40)
        self.assertTrue(any(p % 2 for p in chosen))
        self.assertTrue(any(p % 2 == 0 for p in chosen))
        self.assertEqual(chosen, legacy_sampled_plies(game, 4, 14, 40))
        for side in (True, False):
            side_plies = legacy_sampled_plies(game, 4, 14, 40, white_side=side)
            self.assertTrue(side_plies)
            self.assertTrue(all(bool(p % 2) == side for p in side_plies))

    def test_top_band_sampler_actually_returns_white_positions(self):
        spec = importlib.util.spec_from_file_location("top_sampler", ROOT / "experiments/25_top_band_sampler.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for side in (True, False):
            rows = module.sample_side(PGN, side)
            self.assertGreater(len(rows), 0)
            self.assertTrue(all(chess.Board(row[1]).turn == side for row in rows))
            self.assertTrue(all(chess.Move.from_uci(row[2]) in chess.Board(row[1]).legal_moves for row in rows))

    def test_history_and_clocks_align_with_position_before_played_move(self):
        game = chess.pgn.read_game(io.StringIO(PGN))
        rows, reason = game_candidates(game, source(), min_ply=1, max_ply=8)
        self.assertIsNone(reason)
        self.assertEqual(2, len(rows))
        nodes = list(game.mainline())
        for row in rows:
            prior = nodes[:row["ply"] - 1]
            self.assertEqual(row["history_uci"], [n.move.uci() for n in prior])
            self.assertEqual(row["played_move"], nodes[row["ply"] - 1].move.uci())
            board, clocks = game.board(), {True: None, False: None}
            for node in prior:
                clocks[board.turn] = node.clock()
                board.push(node.move)
            self.assertEqual(row["clock_seconds_before"], clocks[board.turn])
            self.assertEqual(row["opponent_clock_seconds"], clocks[not board.turn])
            self.assertEqual(row["time_control"], "600+5")
            self.assertEqual(row["source"]["date"], "2026.06.01")
        self.assertTrue(validate_rows(rows)["history_replay_valid"])

    def test_missing_clock_is_null_instead_of_base_time(self):
        game = chess.pgn.read_game(io.StringIO(PGN))
        for node in game.mainline():
            node.comment = ""
        rows, _ = game_candidates(game, source(), min_ply=14, max_ply=35)
        self.assertTrue(rows)
        self.assertTrue(all(r["clock_seconds_before"] is None and r["opponent_clock_seconds"] is None for r in rows))

    def test_public_position_excludes_whole_game_even_outside_window(self):
        game = chess.pgn.read_game(io.StringIO(PGN))
        late_fen = canonical_fen(list(game.mainline())[-1].board().fen())
        rows, reason = game_candidates(game, source(), min_ply=1, max_ply=8,
                                      excluded_fens={late_fen})
        self.assertEqual(rows, [])
        self.assertEqual(reason, "public_position_in_game")
        rows, reason = game_candidates(game, source(), excluded_games={"Abcd1234"})
        self.assertEqual(reason, "public_game_id")

    def test_bot_games_are_not_human_training_observations(self):
        game = chess.pgn.read_game(io.StringIO(PGN))
        game.headers["BlackTitle"] = "BOT"
        self.assertEqual(game_candidates(game, source())[1], "bot")

    def test_selection_exact_balance_reproducibility_game_cap_and_replay(self):
        rng = random.Random(31)
        candidates = []
        for i in range(150):
            game = chess.pgn.Game()
            game.headers.update({"Site": f"https://lichess.org/{i:08d}",
                                 "WhiteElo": str(2200 + i % 4 * 200),
                                 "BlackElo": str(2300 + i % 4 * 200)})
            node, board = game, game.board()
            for _ in range(42):
                if board.is_game_over():
                    break
                move = rng.choice(list(board.legal_moves))
                node = node.add_variation(move)
                board.push(move)
            rows, _ = game_candidates(game, source(), min_ply=14, max_ply=42)
            candidates.extend(rows)
        selected, _ = select_balanced(candidates, 60)
        selected_again, _ = select_balanced(list(reversed(candidates)), 60)
        self.assertEqual([r["id"] for r in selected], [r["id"] for r in selected_again])
        for split, each_side in (("train", 18), ("validation", 6), ("test", 6)):
            for side in ("white", "black"):
                self.assertEqual(each_side, sum(r["split"] == split and r["side_to_move"] == side for r in selected))
        from collections import Counter
        self.assertLessEqual(max(Counter(r["game_id"] for r in selected).values()), 2)
        self.assertTrue(all(split_for_game(r["game_id"]) == r["split"] for r in selected))
        self.assertTrue(validate_rows(selected)["game_disjoint_splits"])
        damaged = copy.deepcopy(selected)
        damaged[0]["history_fens"][-1] = chess.STARTING_FEN
        with self.assertRaisesRegex(ValueError, "history/FEN mismatch"):
            validate_rows(damaged)

    def test_canonicalization_retains_side_and_legal_rights(self):
        board = chess.Board()
        board.push_uci("e2e4")
        self.assertEqual(canonical_fen(board.fen(en_passant="fen")), canonical_fen(board.fen()))
        black = board.fen()
        changed = black.replace(" b ", " w ")
        self.assertNotEqual(canonical_fen(black), canonical_fen(changed))


if __name__ == "__main__":
    unittest.main()
