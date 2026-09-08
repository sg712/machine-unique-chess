"""Scoring invariants with synthetic engine responses; these are not mining evidence."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mining_v2_engine', ROOT / 'scripts/mining_v2_engine.py')
engine_v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine_v2)


class FakeEngine:
    def __init__(self, bound=False, achieved=None, wrong_root=False):
        self.bound, self.achieved, self.wrong_root = bound, achieved, wrong_root

    def analysis(self, board, limit, root_moves=None, multipv=None):
        from contextlib import nullcontext
        return nullcontext(iter([self.analyse(board, limit, root_moves=root_moves, multipv=multipv)]))

    def configure(self, options):
        pass

    def analyse(self, board, limit, root_moves=None, multipv=None):
        move = root_moves[0] if root_moves else next(iter(board.legal_moves))
        if self.wrong_root:
            move = next(m for m in board.legal_moves if m != move)
        # White POV is deliberately negative when Black is to move.
        score = chess.engine.PovScore(chess.engine.Cp(-75 if board.turn == chess.BLACK else 75), chess.WHITE)
        return {'score': score, 'depth': self.achieved if self.achieved is not None else limit.depth,
                'lowerbound': self.bound, 'nodes': 100, 'time': .01, 'pv': [move]}


class EngineV2Tests(unittest.TestCase):
    def setUp(self):
        self.board = chess.Board()
        self.board.push_uci('e2e4')
        self.row = {'id': 'fixture', 'fen': self.board.fen(), 'game_id': 'fixture-game',
                    'initial_fen': chess.STARTING_FEN, 'history_uci': ['e2e4'], 'history_available': True}
        legal = list(self.board.legal_moves)
        self.probs = {move.uci(): 1 / len(legal) for move in legal}
        self.policy = {'id': self.row['id'], 'fen': self.row['fen'], 'history_available': True,
                       'maia2': {'fen_only': {'1900': self.probs.copy()}}}
        self.args = SimpleNamespace(mode='deep', deep_seconds=1.)

    def test_root_perspective_and_bound_preservation(self):
        move = next(iter(self.board.legal_moves))
        result = engine_v2.search(FakeEngine(bound=True), self.board, 24, 1., roots=[move])[0]
        self.assertEqual(result['cp'], 75)
        self.assertEqual(result['uci'], move.uci())
        self.assertTrue(result['reached_target'])
        self.assertTrue(result['lowerbound'])
        self.assertFalse(result['score_is_exact'])
        with self.assertRaisesRegex(ValueError, 'unexpected root'):
            engine_v2.search(FakeEngine(wrong_root=True), self.board, 24, 1., roots=[move])

    def test_later_exact_score_clears_an_earlier_bound_flag(self):
        from contextlib import nullcontext
        class StreamingEngine(FakeEngine):
            def analysis(self, board, limit, root_moves=None, multipv=None):
                first = self.analyse(board, limit, root_moves=root_moves, multipv=multipv)
                first['lowerbound'] = True
                final = dict(first)
                final.pop('lowerbound')
                return nullcontext(iter([first, final, {'nodes': 120}]))
        result = engine_v2.search(StreamingEngine(), self.board, 24, 1.)[0]
        self.assertTrue(result['score_is_exact'])
        self.assertFalse(result['lowerbound'])
        self.assertEqual(result['nodes'], 120)

    def test_deep_gate_rejects_bound_only_and_early_stop(self):
        good = engine_v2.inspect(FakeEngine(), self.row, self.policy, self.args)
        self.assertTrue(good['verified'])
        self.assertEqual(len(good['searches']['24']), self.board.legal_moves.count())
        bounded = engine_v2.inspect(FakeEngine(bound=True), self.row, self.policy, self.args)
        self.assertTrue(bounded['stable_acceptance'])
        self.assertTrue(bounded['all_searches_reached_target'])
        self.assertFalse(bounded['verified'])
        early = engine_v2.inspect(FakeEngine(achieved=19), self.row, self.policy, self.args)
        self.assertFalse(early['verified'])

    def test_nested_and_legacy_maia2_maps_are_preserved(self):
        nested = engine_v2.policy_maps(self.policy)
        legacy = engine_v2.policy_maps({'maia2': {'1900': self.probs}})
        self.assertEqual(nested, legacy)
        self.assertEqual(set(nested), {'maia2/fen_only/1900'})

    def test_policy_validation_rejects_nonfinite_negative_boolean_and_mismatch(self):
        legal = set(self.probs)
        for invalid in (float('nan'), float('inf'), -.1, True):
            with self.subTest(value=invalid):
                policy = copy.deepcopy(self.policy)
                policy['maia2']['fen_only']['1900'][next(iter(legal))] = invalid
                with self.assertRaises(ValueError):
                    engine_v2.validated_policies(self.row, policy, legal)
        for key, value in [('fen', chess.STARTING_FEN), ('id', 'other'), ('history_available', False)]:
            policy = copy.deepcopy(self.policy)
            policy[key] = value
            with self.assertRaisesRegex(ValueError, 'does not match'):
                engine_v2.validated_policies(self.row, policy, legal)
        empty = {'id': self.row['id'], 'fen': self.row['fen'], 'maia3': {}}
        with self.assertRaisesRegex(ValueError, 'no usable distributions'):
            engine_v2.validated_policies(self.row, empty, legal)

    def test_history_must_reach_position(self):
        self.assertEqual(engine_v2.board_for(self.row).move_stack, self.board.move_stack)
        wrong = dict(self.row, history_uci=['d2d4'])
        with self.assertRaisesRegex(ValueError, 'does not reach'):
            engine_v2.board_for(wrong)

    def test_global_partial_score_bounds_include_unseen_better_move(self):
        scores = {'a': {'cp': 0, 'mate': None}, 'b': {'cp': -100, 'mate': None}}
        probs = {'a': .4, 'b': .5, 'c': .1}
        result = engine_v2.probability_summary(scores, probs)
        self.assertEqual(result['conditional_p_good_lower'], .4)
        self.assertAlmostEqual(result['conditional_capped_regret_upper_cp'], 80)
        # Unscored c=+500 would yield p_good=.1 and capped regret=270.
        self.assertLessEqual(result['p_good_lower'], .1)
        self.assertGreaterEqual(result['p_good_upper'], .1)
        self.assertLessEqual(result['capped_regret_lower_cp'], 270)
        self.assertGreaterEqual(result['capped_regret_upper_cp'], 270)
        zero_tail = engine_v2.probability_summary(scores, {'a': .5, 'b': .5, 'c': 0.})
        self.assertEqual(zero_tail['p_good_lower'], 0.)
        self.assertEqual(zero_tail['capped_regret_upper_cp'], 300)
        scores['c'] = {'cp': 500, 'mate': None}
        complete = engine_v2.probability_summary(scores, probs)
        self.assertAlmostEqual(complete['p_good_lower'], .1)
        self.assertAlmostEqual(complete['capped_regret_upper_cp'], 270)

    def test_wdl_tail_and_mate_handling_stay_explicit(self):
        scores = {'a': {'cp': 0, 'mate': None, 'wdl': {'wins': 200, 'draws': 400, 'losses': 400}}}
        result = engine_v2.wdl_summary(scores, {'a': .9, 'b': .1})
        self.assertEqual(result['loss_upper'], 1.)
        self.assertAlmostEqual(result['conditional_loss_upper'], .04)
        self.assertIn('not human win probability', result['interpretation'])
        scores['b'] = {'cp': None, 'mate': 3}
        self.assertFalse(engine_v2.probability_summary(scores, {'a': .9, 'b': .1})['available'])


if __name__ == '__main__':
    unittest.main()
