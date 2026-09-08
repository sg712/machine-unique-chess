"""Retry efficiency must not weaken the depth/bound/acceptance gates."""
import copy
from pathlib import Path
import importlib.util
import unittest
from unittest.mock import patch

import chess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mining_v2_deep_retry', ROOT / 'scripts/mining_v2_deep_retry.py')
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


def result_for(board, move, depth):
    return {'uci': move.uci(), 'cp': 0, 'mate': None, 'depth': depth, 'target_depth': depth,
            'reached_target': True, 'lowerbound': False, 'upperbound': False, 'score_is_exact': True,
            'nodes': 10, 'seconds': .01, 'pv': [{'uci': move.uci(), 'san': board.san(move)}], 'wdl': None}


class EngineRetryTests(unittest.TestCase):
    def setUp(self):
        self.board = chess.Board()
        self.row = {'id': 'test', 'fen': self.board.fen(), 'game_id': 'test-game'}
        self.prior = dict(self.row, mode='deep', stable_acceptance=True,
                          searches={str(depth): {move.uci(): result_for(self.board, move, depth)
                                                for move in self.board.legal_moves} for depth in (20, 24)})
        self.provenance = {'output_sha256': 'a'*64, 'scorer_sha256': 'b'*64}

    @staticmethod
    def search(_engine, board, depth, _seconds, roots):
        return [result_for(board, roots[0], depth)]

    def test_reuses_good_roots_and_only_retries_failed_root(self):
        move = next(iter(self.board.legal_moves)).uci()
        self.prior['searches']['24'][move]['score_is_exact'] = False
        with patch.object(retry.scoring, 'search', side_effect=self.search) as search:
            result = retry.inspect_retry(None, self.row, {}, 30, self.prior, self.provenance)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(result['fresh_root_searches'], 1)
        self.assertEqual(result['reused_root_searches'], 39)
        self.assertTrue(result['verified'])
        cached = result['searches']['20'][move]
        self.assertEqual(cached['reused_from'], self.provenance)

    def test_unstable_acceptance_forces_all_roots_fresh(self):
        self.prior['stable_acceptance'] = False
        with patch.object(retry.scoring, 'search', side_effect=self.search) as search:
            result = retry.inspect_retry(None, self.row, {}, 30, self.prior, self.provenance)
        self.assertEqual(search.call_count, 40)
        self.assertTrue(result['rerun_all_due_to_prior_instability'])
        self.assertEqual(result['reused_root_searches'], 0)

    def test_reuse_rejects_missing_evidence_bad_pv_and_wrong_target(self):
        action = next(iter(self.board.legal_moves))
        good = result_for(self.board, action, 24)
        self.assertTrue(retry.reusable_root(good, action.uci(), self.board, 24))
        variants = [{'lowerbound': True}, {'reached_target': False}, {'depth': 23},
                    {'target_depth': 20}, {'cp': float('nan')}, {'nodes': None},
                    {'pv': [{'uci': 'a1a8', 'san': 'Ra8'}]}]
        for changes in variants:
            with self.subTest(changes=changes):
                bad = copy.deepcopy(good)
                bad.update(changes)
                self.assertFalse(retry.reusable_root(bad, action.uci(), self.board, 24))
        del good['score_is_exact']
        self.assertFalse(retry.reusable_root(good, action.uci(), self.board, 24))


if __name__ == '__main__':
    unittest.main()
