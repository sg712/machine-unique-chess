"""Natural boundary retrieval requires legal captures and real entry geometry."""
from contextlib import redirect_stderr
import io
import unittest
from unittest.mock import patch

import chess

from scripts.mining_v2_boundaries import PROTECTED, capture_geometry, exclusion_sets, main, scan_rows
from scripts.mining_v2_sampling import canonical_fen

# Synthetic geometry fixtures, not unpublished study positions.
POSITIVE = '4k3/1Nr1p3/8/8/4n3/2N5/8/6K1 b - - 0 1'
BOUNDARY = '2r3k1/4p3/8/8/4n3/2N5/8/6K1 b - - 0 1'
OTHER = '2r3k1/4b3/8/8/4n3/2N2N2/8/6K1 b - - 0 1'


def row(fen, gid):
    return {'fen': fen, 'game_id': gid, 'engine_best': 'e4c3', 'best_cp': '0'}


class BoundaryRetrievalTests(unittest.TestCase):
    def test_active_boundary_file_cannot_be_overwritten_even_with_force(self):
        errors = io.StringIO()
        with patch('sys.argv', ['boundaries', '--output', str(PROTECTED), '--force']), redirect_stderr(errors):
            with self.assertRaises(SystemExit) as caught:
                main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('cannot be overwritten', errors.getvalue())

    def test_checking_entry_and_natural_boundary_have_different_geometry(self):
        positive = capture_geometry(chess.Board(POSITIVE))[0]
        self.assertEqual(positive['knight_move'], 'e4c3')
        self.assertEqual(positive['rook_moves'], ['c7c3'])
        self.assertIn({'uci': 'b7d6', 'san': 'Nd6+', 'is_check': True}, positive['opponent_knight_entries'])
        boundary = capture_geometry(chess.Board(BOUNDARY))[0]
        self.assertEqual(boundary['knight_move'], 'e4c3')
        self.assertEqual(boundary['rook_moves'], ['c8c3'])
        self.assertEqual(boundary['opponent_knight_entries'], [])
        self.assertEqual(boundary['remaining_opponent_knights'], [])
        self.assertIn({'square': 'e7', 'piece': 'p'}, boundary['entry_defenders_after_knight_capture'])
        self.assertTrue(boundary['knight_was_entry_defender'])

    def test_pinned_rook_or_empty_target_is_not_a_capture_choice(self):
        board = chess.Board('6k1/8/8/8/4n3/2N3r1/8/K5R1 b - - 0 1')
        move = chess.Move.from_uci('g3c3')
        self.assertTrue(board.is_pseudo_legal(move))
        self.assertFalse(board.is_legal(move))
        self.assertEqual(capture_geometry(board), [])
        board = chess.Board(BOUNDARY)
        board.remove_piece_at(chess.C3)
        self.assertEqual(capture_geometry(board), [])

    def test_pinned_opponent_knight_is_not_an_available_entry(self):
        board = chess.Board('2r3k1/8/8/r4N1K/4n3/2N5/8/8 b - - 0 1')
        geometry = capture_geometry(board)[0]
        board.push_uci('e4c3')
        move = chess.Move.from_uci('f5d6')
        self.assertTrue(board.is_pseudo_legal(move))
        self.assertFalse(board.is_legal(move))
        self.assertEqual(geometry['opponent_knight_entries'], [])

    def test_public_and_heldout_games_are_excluded_by_recoverable_ids(self):
        master = [row(BOUNDARY, 'legacy-public'), row(OTHER, 'legacy-public'),
                  row(OTHER, 'legacy-heldout'), row(POSITIVE, 'training-game')]
        pilot = [{'fen': OTHER, 'game_id': 'real-heldout', 'split': 'validation'},
                 {'fen': POSITIVE, 'game_id': 'training-game', 'split': 'train'}]
        fens, games, _ = exclusion_sets(master, [BOUNDARY], (), pilot, additional_games=())
        self.assertIn('legacy-public', games)
        self.assertIn('legacy-heldout', games)
        self.assertIn('real-heldout', games)
        self.assertNotIn('training-game', games)
        records, counts = scan_rows(master, fens, games)
        self.assertEqual([r['row']['game_id'] for r in records], ['training-game'])
        self.assertEqual(counts['excluded_recorded_game_rows'], 3)
        self.assertNotIn(canonical_fen(POSITIVE), fens)


if __name__ == '__main__':
    unittest.main()
