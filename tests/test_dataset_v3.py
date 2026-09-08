"""The expansion preserves old observations without padding new observations."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chess

from scripts.mining_v3_dataset import assemble


def record(identifier, game, moves, played):
    board = chess.Board()
    for move in moves:
        board.push_uci(move)
    return dict(id=identifier, game_id=game, fen=board.fen(), played_move=played,
                side_to_move='white' if board.turn else 'black', mover_elo=2100,
                cohort='club', phase='opening', split='train', source={},
                history_available=False, contains_bot=None)


class DatasetV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.black = [record('b1', 'legacy-game', ['e2e4'], 'e7e5'),
                      record('b2', 'legacy-game', ['e2e4'], 'e7e5')]
        for row in self.black:
            row['legacy_game_id'] = 'old-id'
        self.pilot = [record('pw1', 'pilot-game', [], 'd2d4')]
        self.white = [record('nw1', 'legacy-game', ['e2e4', 'e7e5'], 'g1f3')]

    def run_assembly(self):
        paths = [self.root/name for name in ('black.jsonl', 'pilot.jsonl', 'white.jsonl')]
        for path, rows in zip(paths, (self.black, self.pilot, self.white)):
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        with patch('scripts.mining_v3_dataset.public_exclusions', return_value=(set(), set(), {})):
            return assemble(*paths, self.root/'out.jsonl', self.root/'summary.json',
                            expected_black=2, expected_new_white=1, expected_pilot_white=1)

    def test_keep_historical_duplicates_and_propagate_prior_exposure(self):
        result = self.run_assembly()
        self.assertEqual(result['sides'], {'black': 2, 'white': 2})
        self.assertEqual(result['canonical_duplicate_rows'], {'black': 1, 'white': 0})
        rows = [json.loads(s) for s in (self.root/'out.jsonl').read_text().splitlines()]
        self.assertEqual([r['side_to_move'] for r in rows], ['black', 'white', 'black', 'white'])
        paired_white = next(r for r in rows if r['id'] == 'nw1')
        self.assertTrue(paired_white['prior_development_game'])
        self.assertEqual(paired_white['analysis_role'], 'prior_development')
        related = [r['split'] for r in rows if r['game_id'] == 'legacy-game']
        self.assertEqual(len(set(related)), 1)

    def test_reject_new_white_reusing_existing_white_board(self):
        self.white[0] = record('nw1', 'other-game', [], 'e2e4')
        with self.assertRaisesRegex(ValueError, 'repeated canonical'):
            self.run_assembly()

    def test_reject_count_shortfall_before_final_artifact(self):
        self.white = []
        with self.assertRaisesRegex(ValueError, 'Incomplete or unbalanced'):
            self.run_assembly()
        self.assertFalse((self.root/'out.jsonl').exists())

    def test_reject_incorrect_side_and_observed_move(self):
        self.white[0]['side_to_move'] = 'black'
        with self.assertRaisesRegex(ValueError, 'side metadata'):
            self.run_assembly()
        self.white[0]['side_to_move'] = 'white'
        self.white[0]['played_move'] = 'e2e4'
        with self.assertRaisesRegex(ValueError, 'observed move is illegal'):
            self.run_assembly()


if __name__ == '__main__':
    unittest.main()
