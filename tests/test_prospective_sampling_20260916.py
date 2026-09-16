import copy
import random
import unittest

import chess
import chess.pgn

from scripts.prospective_sampling_20260916 import (
    candidate_from_game, canonical_fen, digest, header_eligibility, select,
)


def fixture_game(gid="fake0001"):
    game = chess.pgn.Game()
    game.setup(chess.Board("7k/5ppp/8/8/8/8/PPP5/K6R w - - 0 1"))
    game.headers.update({"Site": "https://lichess.org/" + gid, "Event": "Rated Rapid game",
                         "Date": "2026.08.01", "WhiteElo": "1600", "BlackElo": "1900",
                         "TimeControl": "600+5", "Result": "1-0"})
    board, node, rng = game.board(), game, random.Random(52)
    for _ in range(40):
        legal = list(board.legal_moves)
        if not legal:
            break
        move = rng.choice(legal)
        board.push(move)
        node = node.add_variation(move)
    return game


class ProspectiveSamplingTests(unittest.TestCase):
    def test_history_replays_and_observed_move_legal(self):
        game = fixture_game()
        row, problem = candidate_from_game(game)
        self.assertIsNone(problem)
        board = chess.Board(row["initial_fen"])
        for uci in row["history_uci"]:
            board.push_uci(uci)
        self.assertEqual(board.fen(), row["fen"])
        self.assertIn(chess.Move.from_uci(row["played_move"]), board.legal_moves)
        self.assertEqual(row["history_fens"][-1], row["fen"])

    def test_excludes_entire_game_for_late_public_state(self):
        game = fixture_game()
        end = game.end().board()
        row, problem = candidate_from_game(game, excluded_fens={canonical_fen(end.fen())})
        self.assertIsNone(row)
        self.assertEqual(problem, "previous_state_anywhere_in_game")

    def test_bots_unrated_wrong_month_and_missing_metadata_rejected(self):
        for changes in ({"WhiteTitle": "BOT"}, {"Event": "Unrated Rapid game"},
                        {"Date": "2026.07.31"}, {"Result": "*"},
                        {"WhiteElo": "?"}, {"TimeControl": "60+0"}):
            headers = dict(fixture_game().headers)
            headers.update(changes)
            self.assertIsNotNone(header_eligibility(headers), changes)

    def test_selection_is_independent_of_saved_eval_comments(self):
        game = fixture_game()
        original, _ = candidate_from_game(game)
        for node in game.mainline():
            node.comment = "[%eval 12.50] This is not used for selection"
        changed, _ = candidate_from_game(game)
        self.assertEqual(original, changed)

    def test_roles_assigned_by_game_before_position_choice(self):
        for i in range(12):
            gid = "fake" + str(i).zfill(4)
            row, problem = candidate_from_game(fixture_game(gid))
            self.assertIsNone(problem)
            bucket = int(digest(f"20260916:role:{gid}")[:16], 16) % 4
            self.assertEqual(row["analysis_role"], ("calibration_development", "calibration_evaluation", "targeted_endgame", "targeted_endgame")[bucket])
            if bucket >= 2:
                self.assertEqual(row["phase"], "endgame")

    def test_no_duplicate_state_or_copied_game_across_roles(self):
        original, _ = candidate_from_game(fixture_game())
        first = {**original, "analysis_role": "calibration_development"}
        copy_game = {**copy.deepcopy(original), "game_id": "fake9999", "analysis_role": "calibration_evaluation"}
        rows, stats = select([first, copy_game], calibration_n=1, targeted_cell_n=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(stats["shortfall_cells"]["calibration_evaluation"], 1)
        self.assertEqual(stats["selection_rejections"]["duplicate_game_state_or_sequence"], 1)

    def test_target_elsewhere_in_other_source_game_cannot_cross_roles(self):
        first, _ = candidate_from_game(fixture_game())
        first["analysis_role"] = "calibration_development"
        second, _ = candidate_from_game(fixture_game("fake9999"))
        second.update(game_id="fake9999", analysis_role="calibration_evaluation",
                      source_move_sequence_sha256="distinct-synthetic-sequence")
        board = chess.Board(second["fen"])
        board.push(next(iter(board.legal_moves)))
        second["fen"] = board.fen()
        # Different targets and sequences, but one target was exposed in the other source.
        second["source_canonical_state_hashes"] = [digest(canonical_fen(second["fen"])), digest(canonical_fen(first["fen"]))]
        rows, stats = select([first, second], calibration_n=1, targeted_cell_n=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(stats["selection_rejections"]["target_exposed_elsewhere_in_selected_source_game"], 1)

    def test_target_must_be_in_its_complete_source_state_set(self):
        row, _ = candidate_from_game(fixture_game())
        row["source_canonical_state_hashes"] = []
        with self.assertRaises(ValueError):
            select([row])


if __name__ == "__main__":
    unittest.main()
