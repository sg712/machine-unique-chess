"""Contracts that protect the large-corpus primary comparison and resume path."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from mining_v3_engine import inspect, search_nodes
from mining_v3_io import check_manifest, completed_ids, paired_rows, write_manifest
from mining_v3_run import prepare_shards


class FakeAnalysis:
    def __init__(self, updates):
        self.updates = updates

    def __enter__(self):
        return iter(self.updates)

    def __exit__(self, *_):
        pass


class FakeEngine:
    def __init__(self, updates):
        self.updates = updates
        self.settings = []
        self.limit = None

    def configure(self, settings):
        self.settings.append(settings)

    def analysis(self, board, limit, **kwargs):
        self.limit = limit
        self.board = board
        return FakeAnalysis(self.updates)


class SearchContracts(unittest.TestCase):
    def test_new_exact_score_discards_stale_bound(self):
        board = chess.Board()
        engine = FakeEngine([
            {'score': chess.engine.PovScore(chess.engine.Cp(90), chess.WHITE),
             'pv': [chess.Move.from_uci('e2e4')], 'depth': 4, 'lowerbound': True},
            {'score': chess.engine.PovScore(chess.engine.Cp(32), chess.WHITE),
             'pv': [chess.Move.from_uci('e2e4')], 'depth': 9, 'nodes': 30024},
        ])
        result = search_nodes(engine, board, 30000)[0]
        self.assertTrue(result['score_is_exact'])
        self.assertFalse(result['lowerbound'])
        self.assertEqual(result['cp'], 32)
        self.assertEqual(result['nodes'], 30024)
        self.assertEqual(result['node_budget'], 30000)
        self.assertEqual(engine.limit.nodes, 30000)
        self.assertIsNone(engine.limit.depth)
        self.assertIsNone(engine.limit.time)
        self.assertEqual(engine.settings, [{'Clear Hash': None}])

    def test_latest_bound_is_retained(self):
        engine = FakeEngine([
            {'score': chess.engine.PovScore(chess.engine.Cp(32), chess.WHITE),
             'pv': [chess.Move.from_uci('e2e4')], 'upperbound': True},
        ])
        self.assertFalse(search_nodes(engine, chess.Board(), 50)[0]['score_is_exact'])

    def test_completed_exact_iteration_retained_before_final_bound(self):
        engine = FakeEngine([
            {'score': chess.engine.PovScore(chess.engine.Cp(32), chess.WHITE),
             'pv': [chess.Move.from_uci('e2e4')], 'depth': 8, 'nodes': 2000},
            {'score': chess.engine.PovScore(chess.engine.Cp(50), chess.WHITE),
             'pv': [chess.Move.from_uci('d2d4')], 'depth': 9, 'nodes': 5010, 'lowerbound': True},
        ])
        result = search_nodes(engine, chess.Board(), 5000)[0]
        self.assertEqual((result['uci'], result['cp'], result['depth']), ('e2e4', 32, 8))
        self.assertEqual(result['nodes'], 5010)
        self.assertEqual(result['score_nodes'], 2000)
        self.assertTrue(result['score_is_exact'])
        self.assertEqual(result['score_selection'], 'last_completed_exact_iteration')
        self.assertTrue(result['last_reported']['lowerbound'])
        self.assertEqual(result['last_reported']['depth'], 9)

    def test_multipv_does_not_mix_partial_depths_or_duplicate_roots(self):
        updates = []
        for index, move in enumerate(('e2e4', 'd2d4', 'g1f3'), 1):
            updates.append({'score': chess.engine.PovScore(chess.engine.Cp(30-index), chess.WHITE),
                            'pv': [chess.Move.from_uci(move)], 'depth': 8, 'multipv': index})
        updates.append({'score': chess.engine.PovScore(chess.engine.Cp(40), chess.WHITE),
                        'pv': [chess.Move.from_uci('d2d4')], 'depth': 9, 'multipv': 1})
        results = search_nodes(FakeEngine(updates), chess.Board(), 5000, multipv=3)
        self.assertEqual([result['depth'] for result in results], [8, 8, 8])
        self.assertEqual([result['uci'] for result in results], ['e2e4', 'd2d4', 'g1f3'])

    def test_mate_remains_typed_and_is_mover_relative(self):
        board = chess.Board()
        board.push_uci('e2e4')
        engine = FakeEngine([{'score': chess.engine.PovScore(chess.engine.Mate(-3), chess.WHITE),
                              'pv': [chess.Move.from_uci('e7e5')]}])
        result = search_nodes(engine, board, 50)[0]
        self.assertIsNone(result['cp'])
        self.assertEqual(result['mate'], 3)

    def test_illegal_continuation_fails(self):
        engine = FakeEngine([{'score': chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
                              'pv': [chess.Move.from_uci('e7e5')]}])
        with self.assertRaisesRegex(ValueError, 'illegal continuation'):
            search_nodes(engine, chess.Board(), 50)

    def test_wrong_requested_root_fails(self):
        engine = FakeEngine([{'score': chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
                              'pv': [chess.Move.from_uci('e2e4')]}])
        with self.assertRaisesRegex(ValueError, 'unexpected root'):
            search_nodes(engine, chess.Board(), 50, roots=[chess.Move.from_uci('d2d4')])

    def test_missing_score_fails(self):
        with self.assertRaisesRegex(ValueError, 'no scored continuation'):
            search_nodes(FakeEngine([{'depth': 0}]), chess.Board(), 50)


class ScreenContracts(unittest.TestCase):
    def fixture(self, colour):
        board = chess.Board()
        if colour == chess.BLACK:
            board.push_uci('e2e4')
        legal = sorted(move.uci() for move in board.legal_moves)
        row = {'id': 'synthetic', 'fen': board.fen(), 'game_id': 'synthetic-game',
               'history_available': False, 'played_move': legal[-1],
               'initial_fen': 'deliberately unused history', 'history_uci': ['invalid']}
        probs = {move: 1/len(legal) for move in legal}
        policy = {'id': row['id'], 'fen': row['fen'], 'history_available': False,
                  'maia3': {'fen_only': {str(r): probs for r in (1400, 1700, 2000, 2300)}}}
        args = SimpleNamespace(top_nodes=30000, root_nodes=5000, coverage=.85, max_human=2)
        return row, policy, args, legal

    def fake_search(self, engine, board, nodes, roots=None, multipv=None):
        self.assertFalse(board.move_stack)
        moves = [move.uci() for move in roots] if roots else sorted(move.uci() for move in board.legal_moves)[:multipv]
        return [{'uci': move, 'cp': 10, 'mate': None, 'score_is_exact': True,
                 'wdl': None, 'nodes': nodes, 'depth': 8} for move in moves]

    def test_both_colours_use_identical_budget_and_fen_only(self):
        for colour in (chess.WHITE, chess.BLACK):
            row, policy, args, _ = self.fixture(colour)
            with patch('mining_v3_engine.search_nodes', side_effect=self.fake_search) as search:
                result = inspect(None, row, policy, args)
            self.assertEqual(search.call_args_list[0].args[2], 30000)
            self.assertTrue(all(call.args[2] == 5000 for call in search.call_args_list[1:]))
            self.assertEqual(result['board_context'], 'fen_only')
            self.assertFalse(result['verified'])
            self.assertFalse(result['exhaustive'])
            self.assertEqual(result['side_to_move'], 'white' if colour else 'black')

    def test_bounds_not_used_as_exact_root_values(self):
        row, policy, args, legal = self.fixture(chess.WHITE)
        def search(*values, **kwargs):
            results = self.fake_search(*values, **kwargs)
            for result in results:
                if result['uci'] == legal[0]:
                    result.update(score_is_exact=False, cp=99999)
            return results
        with patch('mining_v3_engine.search_nodes', side_effect=search):
            result = inspect(None, row, policy, args)
        self.assertEqual(result['best_cp'], 10)
        metric = result['metrics']['maia3/fen_only/2000']['20']
        self.assertNotIn(legal[0], metric['acceptable'])
        self.assertEqual(metric['p_good_lower'], 0)
        self.assertEqual(metric['capped_regret_upper_cp'], 300)
        self.assertGreater(metric['unscored_mass'], 0)

    def test_missing_rating_cannot_silently_reduce_comparison(self):
        row, policy, args, _ = self.fixture(chess.WHITE)
        del policy['maia3']['fen_only']['2300']
        with self.assertRaisesRegex(ValueError, 'exactly the four'):
            inspect(None, row, policy, args)

    def test_wrong_policy_colour_fails(self):
        row, policy, args, _ = self.fixture(chess.WHITE)
        other = chess.Board(row['fen'])
        other.push_uci('e2e4')
        policy['fen'] = other.fen()
        with self.assertRaisesRegex(ValueError, 'FEN does not match'):
            inspect(None, row, policy, args)


class ResumeContracts(unittest.TestCase):
    def test_shards_are_reproducible_and_tampering_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source.jsonl'
            source.write_text(''.join(json.dumps({'id': str(i)})+'\n' for i in range(5)))
            run = Path(directory)/'run'
            plan = prepare_shards(source, run, 2)
            self.assertEqual([shard['rows'] for shard in plan['shards']], [2, 2, 1])
            self.assertEqual(plan['rows'], 5)
            self.assertEqual(prepare_shards(source, run, 2), plan)
            Path(plan['shards'][0]['input']).write_text('{"id":"changed"}\n')
            with self.assertRaisesRegex(ValueError, 'immutable input shard was changed'):
                prepare_shards(source, run, 2)

    def test_changed_source_cannot_reuse_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source.jsonl'
            source.write_text('{"id":"first"}\n')
            run = Path(directory)/'run'
            prepare_shards(source, run, 2)
            source.write_text('{"id":"second"}\n')
            with self.assertRaisesRegex(ValueError, 'source or size changed'):
                prepare_shards(source, run, 2)

    def test_duplicate_source_ids_cannot_be_sharded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source.jsonl'
            source.write_text('{"id":"same"}\n{"id":"same"}\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate source'):
                prepare_shards(source, Path(directory)/'run', 2)

    def test_only_unterminated_tail_can_be_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.jsonl'
            path.write_bytes(b'{"id":"first"}\n{"id":"unfinished')
            with self.assertRaisesRegex(ValueError, 'incomplete final line'):
                completed_ids(path)
            self.assertEqual(completed_ids(path, repair_partial=True), {'first'})
            self.assertEqual(path.read_bytes(), b'{"id":"first"}\n')
            path.write_bytes(b'{"id":"first"}\nnot valid\n')
            with self.assertRaisesRegex(ValueError, 'invalid completed'):
                completed_ids(path, repair_partial=True)

    def test_duplicate_completed_rows_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.jsonl'
            path.write_text('{"id":"same"}\n{"id":"same"}\n')
            with self.assertRaisesRegex(ValueError, 'duplicate completed'):
                completed_ids(path)

    def test_pairing_rejects_missing_extra_and_reordered_policies(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source.jsonl'
            policy = Path(directory)/'policy.jsonl'
            source.write_text('{"id":"a"}\n{"id":"b"}\n')
            for ids in (['a'], ['a', 'b', 'c'], ['b', 'a']):
                policy.write_text(''.join(json.dumps({'id': value})+'\n' for value in ids))
                with self.assertRaisesRegex(ValueError, 'order and length'):
                    list(paired_rows(source, policy))

    def test_changed_settings_cannot_reuse_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.jsonl'
            manifest_path, previous = check_manifest(path, {'nodes': 10})
            self.assertIsNone(previous)
            write_manifest(manifest_path, {'settings': {'nodes': 10}})
            self.assertEqual(check_manifest(path, {'nodes': 10})[1]['settings']['nodes'], 10)
            with self.assertRaisesRegex(ValueError, 'settings or input hashes changed'):
                check_manifest(path, {'nodes': 20})

    def test_untracked_output_cannot_be_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.jsonl'
            path.write_text('{"id":"a"}\n')
            with self.assertRaisesRegex(ValueError, 'without a matching manifest'):
                check_manifest(path, {})


if __name__ == '__main__':
    unittest.main()
