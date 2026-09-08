"""Policy correctness, including history, side-to-move, and special moves."""
import copy
import importlib.util
from pathlib import Path
import unittest

import chess
if importlib.util.find_spec("torch") is None:
    raise unittest.SkipTest("Policy tests require research dependencies (PyTorch)")
import torch

from scripts.mining_v2_policy import (
    Maia3Policy, Maia2Policy, MAIA3_REVISION, MAIA3_SOURCE, ROOT, history_boards, validate_policy,
)


def record(moves=(), initial_fen=chess.STARTING_FEN, ident="fixture"):
    board = chess.Board(initial_fen)
    history = [board.fen()]
    for move in moves:
        board.push_uci(move)
        history.append(board.fen())
    return {"id": ident, "fen": board.fen(), "initial_fen": initial_fen,
            "history_uci": list(moves), "history_fens": history[-8:]}


class HistoryTests(unittest.TestCase):
    def test_replays_full_game_but_keeps_eight_boards(self):
        moves = "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1".split()
        item = record(moves)
        boards = history_boards(item)
        self.assertEqual(len(boards), 8)
        self.assertEqual(boards[-1].fen(), item["fen"])
        self.assertEqual(boards[-1].piece_at(chess.G1).symbol(), "K")

    def test_rejects_wrong_history_and_illegal_moves(self):
        original = record(["e2e4", "c7c5"])
        for field, value in (("fen", chess.STARTING_FEN),
                             ("history_fens", list(reversed(original["history_fens"]))),
                             ("history_uci", ["e2e5"])):
            item = copy.deepcopy(original)
            item[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                history_boards(item)

    def test_probability_validation_rejects_truncation_and_nonfinite_values(self):
        board = chess.Board()
        policy = {move.uci(): 0.05 for move in board.legal_moves}
        validate_policy(board, policy)
        del policy["e2e4"]
        with self.assertRaises(ValueError):
            validate_policy(board, policy)
        policy["e2e4"] = float("nan")
        with self.assertRaises(ValueError):
            validate_policy(board, policy)


CHECKPOINT = (Path.home() / ".cache/huggingface/hub/models--UofTCSSLab--Maia3-5M"
              / "snapshots" / MAIA3_REVISION / "maia3-5m.pt")


@unittest.skipUnless(CHECKPOINT.exists() and MAIA3_SOURCE.exists(),
                     "Pinned Maia3 source/checkpoint not cached; no test downloads")
class RealMaia3PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = Maia3Policy(device="cpu", batch_size=16, checkpoint=CHECKPOINT)

    def test_full_legal_policy_both_colours_and_special_moves(self):
        fixtures = [record(["e2e4"]),
                    record(["e2e4", "e7e5"]),
                    record(initial_fen="r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"),
                    record(initial_fen="r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"),
                    record(initial_fen="8/P6k/8/8/8/8/7p/4K3 w - - 0 1"),
                    record(initial_fen="8/P6k/8/8/8/8/7p/4K3 b - - 0 1"),
                    record("e2e4 a7a6 e4e5 d7d5".split())]
        rows = self.adapter.predict(fixtures, history_ratings=(1700,), fen_ratings=(1700,))
        for item, row in zip(fixtures, rows):
            legal = {move.uci() for move in chess.Board(item["fen"]).legal_moves}
            for mode in ("history", "fen_only"):
                policy = row["maia3"][mode]["1700"]
                self.assertEqual(set(policy), legal)
                self.assertAlmostEqual(sum(policy.values()), 1, places=6)
        self.assertGreater(len(rows[2]["maia3"]["history"]["1700"]), 20)
        for uci in ("e1g1", "e1c1"):
            self.assertIn(uci, rows[2]["maia3"]["history"]["1700"])
        for uci in ("a7a8q", "a7a8r", "a7a8b", "a7a8n"):
            self.assertIn(uci, rows[4]["maia3"]["history"]["1700"])
        self.assertIn("h2h1n", rows[5]["maia3"]["history"]["1700"])
        self.assertIn("e5d6", rows[6]["maia3"]["history"]["1700"])

    def test_history_tokens_match_pinned_uci_replay(self):
        from maia3.uci import Maia3UCIEngine, parse_args
        cfg = parse_args(["--model", "maia3-5m", "--device", "cpu", "--use-uci-history"])
        engine = Maia3UCIEngine(cfg)
        for moves in ("e2e4", "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1"):
            item = record(moves.split())
            engine.cmd_position("position startpos moves " + moves)
            self.assertEqual(engine.board.fen(), item["fen"])
            self.assertTrue(torch.equal(
                self.adapter.tokens(history_boards(item)), engine._tokens_from_history(engine.history)))

    def test_actual_probabilities_match_uci_before_topk_and_value_reporting(self):
        from maia3.uci import Maia3UCIEngine, parse_args
        cfg = parse_args(["--model", "maia3-5m", "--device", "cpu", "--use-uci-history",
                          "--no-use-amp", "--elo", "1700", "--multipv", "20"])
        engine = Maia3UCIEngine(cfg)
        engine.model = self.adapter.model
        engine.cmd_position("position startpos moves e2e4")
        _, candidates = engine.score_moves()
        actual = self.adapter.predict([record(["e2e4"])], history_ratings=(1700,), fen_ratings=())
        policy = actual[0]["maia3"]["history"]["1700"]
        self.assertEqual(len(candidates), 20)
        for candidate in candidates:
            self.assertAlmostEqual(policy[candidate["move"].uci()], candidate["policy"], places=6)

    def test_missing_history_is_labelled_and_not_duplicated_as_real_history(self):
        item = record()
        item["history_available"] = False
        row = self.adapter.predict([item])[0]
        self.assertFalse(row["history_available"])
        self.assertEqual(row["maia3"]["history"], {})
        self.assertEqual(set(row["maia3"]["fen_only"]), {"1400", "1700", "2000", "2300"})

    def test_real_history_condition_changes_the_policy(self):
        row = self.adapter.predict([record(["e2e4"])], history_ratings=(1700,), fen_ratings=(1700,))[0]
        history, fen = (row["maia3"][mode]["1700"] for mode in ("history", "fen_only"))
        self.assertGreater(sum(abs(history[move] - fen[move]) for move in history), 0.01)


@unittest.skipUnless((ROOT / "maia2_models/rapid_model.pt").exists()
                     and importlib.util.find_spec("maia2") is not None,
                     "Maia2 package/checkpoint not cached")
class RealMaia2PolicyTests(unittest.TestCase):
    def test_full_precision_policy_both_turns(self):
        adapter = Maia2Policy(device="cpu", batch_size=8)
        items = [record(), record(["e2e4"])]
        rows = adapter.predict(items)
        for item, row in zip(items, rows):
            for policy in row.values():
                validate_policy(chess.Board(item["fen"]), policy)
                self.assertTrue(any(value != round(value, 4) for value in policy.values()))


if __name__ == "__main__":
    unittest.main()
