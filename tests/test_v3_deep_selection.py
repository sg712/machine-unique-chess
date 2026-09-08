"""Deep-batch selection invariants without running engines or models."""
import copy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import chess

from scripts.mining_v3_deep_selection import (choose_candidates, check_selected_policy,
    checked_sources, select_batch)
from scripts.mining_v3_io import digest


def synthetic_records(n):
    rng, records, states = random.Random(408), [], set()
    while len(records) < n:
        board, history, fens = chess.Board(), [], [chess.STARTING_FEN]
        for _ in range(16 + len(records) % 2):
            if not list(board.legal_moves):
                break
            move = rng.choice(list(board.legal_moves))
            history.append(move.uci())
            board.push(move)
            fens.append(board.fen())
        if not board.is_valid() or board.is_game_over() or board.fen() in states:
            continue
        side = 'white' if board.turn else 'black'
        states.add(board.fen())
        index = len(records)
        records.append({'id': f'synthetic-{index:04d}', 'fen': board.fen(),
            'game_id': f'synthetic-game-{index:04d}', 'side_to_move': side,
            'played_move': list(board.legal_moves)[0].uci(), 'history_available': True,
            'initial_fen': chess.STARTING_FEN, 'history_uci': history, 'history_fens': fens[-8:],
            'contains_bot': False, 'known_public_game': False, 'analysis_role': 'prior_development',
            'split': 'test', 'cohort': 'club', 'phase': 'opening', 'rating_bin': '2000_2199',
            'source': {'archive': 'synthetic-only', 'date': '2026.06.01'}})
    return records


def policy_for(record):
    moves = [move.uci() for move in chess.Board(record['fen']).legal_moves]
    distribution = {move: 1 / len(moves) for move in moves}
    return {'id': record['id'], 'fen': record['fen'], 'history_available': True,
            'input_condition': 'fen_only', 'maia3': {'history': {}, 'fen_only':
             {str(r): dict(distribution) for r in (1400, 1700, 2000, 2300)}}}


def make_census(directory, records):
    directory = Path(directory)
    input_path = directory / 'frozen.jsonl'
    policy_path, engine_path = directory / 'policies.jsonl', directory / 'engine.jsonl'
    input_path.write_text(''.join(json.dumps(row) + '\n' for row in records))
    policy_path.write_text(''.join(json.dumps(policy_for(row)) + '\n' for row in records))
    engines = [{'id': row['id'], 'fen': row['fen'], 'side_to_move': row['side_to_move'],
                'board_context': 'fen_only', 'mode': 'fixed_node_screen', 'verified': False,
                'has_mate': False, 'best_cp': 0, 'metrics':
                {f'maia3/fen_only/{r}': {'20': {'available': True, 'p_good_upper': .03,
                                             'capped_regret_lower_cp': 80}} for r in (1700, 2000)}}
               for row in records]
    engine_path.write_text(''.join(json.dumps(row) + '\n' for row in reversed(engines)))
    stages = []
    for stage, path in (('policy', policy_path), ('engine', engine_path)):
        settings = {'input_sha256': digest(input_path)}
        settings.update({'context': 'fen_only', 'ratings': [1400, 1700, 2000, 2300]} if stage == 'policy'
                        else {'board_context': 'fen_only', 'policy_sha256': digest(policy_path)})
        manifest = path.with_suffix('.manifest.json')
        manifest.write_text(json.dumps({'complete': True, 'input_n': len(records),
            'completed_n': len(records), 'settings': settings}))
        stages.append({'index': 0, 'stage': stage, 'rows': len(records), 'output': str(path),
                       'output_sha256': digest(path), 'manifest': str(manifest), 'manifest_sha256': digest(manifest)})
    (directory / 'run.json').write_text(json.dumps({'complete': True, 'input_n': len(records),
        'engine_completed_n': len(records), 'policy_completed_n': len(records),
        'settings': {'input_sha256': digest(input_path)}, 'shards': stages}))
    (directory / 'shards.json').write_text(json.dumps({'complete': True, 'rows': len(records),
        'settings': {'source': str(input_path), 'source_sha256': digest(input_path)},
        'shards': [{'index': 0, 'input': str(input_path), 'input_sha256': digest(input_path), 'rows': len(records)}]}))
    return input_path, policy_path


class DeepSelectionTests(unittest.TestCase):
    def test_ranking_is_order_and_complexity_independent_with_global_game_cap(self):
        candidates = synthetic_records(30)
        for i in range(0, 20, 2):
            candidates[i+1]['game_id'] = candidates[i]['game_id']
        expected, _ = choose_candidates(candidates, per_side=5)
        altered = copy.deepcopy(candidates)
        for i, row in enumerate(altered):
            row.update(best_cp=i, legal_count=100-i, depth=i, elapsed_seconds=i * 1000)
        actual, _ = choose_candidates(list(reversed(altered)), per_side=5)
        self.assertEqual([r['id'] for r in expected], [r['id'] for r in actual])
        self.assertEqual(len({r['game_id'] for r in actual}), 10)
        self.assertEqual(sum(r['side_to_move'] == 'white' for r in actual), 5)

    def test_canonical_duplicates_do_not_gain_multiple_selection_slots(self):
        candidates = synthetic_records(12)
        duplicate = copy.deepcopy(candidates[0])
        duplicate['id'] = 'duplicate-observation'
        duplicate['game_id'] = 'duplicate-source-game'
        duplicate['fen'] = ' '.join(duplicate['fen'].split()[:4]) + ' 42 99'
        selected, audit = choose_candidates(candidates + [duplicate], per_side=3)
        self.assertEqual(audit['canonical_duplicate_rows_removed_n'], 1)
        self.assertEqual(len({' '.join(r['fen'].split()[:4]) for r in selected}), 6)

    def test_insufficient_distinct_games_has_no_relaxed_fallback(self):
        rows = synthetic_records(10)
        for row in rows:
            row['game_id'] = 'one-game'
        with self.assertRaisesRegex(ValueError, 'no fallback'):
            choose_candidates(rows, per_side=2)

    def test_missing_policy_mass_wrong_context_and_bad_history_are_rejected(self):
        row = synthetic_records(1)[0]
        policy = policy_for(row)
        self.assertGreater(check_selected_policy(row, policy), 0)
        bad = copy.deepcopy(policy)
        bad['maia3']['fen_only']['2000'].pop(next(iter(bad['maia3']['fen_only']['2000'])))
        with self.assertRaisesRegex(ValueError, 'every legal move'):
            check_selected_policy(row, bad)
        bad = copy.deepcopy(policy)
        bad['input_condition'] = 'history'
        with self.assertRaisesRegex(ValueError, 'FEN-only'):
            check_selected_policy(row, bad)
        bad_row = copy.deepcopy(row)
        bad_row['history_uci'] = ['e2e5']
        with self.assertRaisesRegex(ValueError, 'illegal source history'):
            check_selected_policy(bad_row, policy)

    def test_export_preserves_source_order_policies_and_exposure_metadata(self):
        records = synthetic_records(230)
        records[0]['contains_bot'] = True
        records[1]['history_available'] = False
        records[2]['known_public_game'] = True
        records[3]['game_id'] = records[2]['game_id']
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, policies = make_census(folder, records)
            with patch('scripts.mining_v3_deep_selection.public_exclusions', return_value=(set(), set(), {})):
                result = select_batch(source, folder, folder/'deep', folder/'public.json')
            self.assertEqual(result['selected_n'], 200)
            self.assertEqual(result['counts']['selected_by_side'], {'white': 100, 'black': 100})
            self.assertEqual(result['counts']['selected_source_games_n'], 200)
            identifiers = set(result['selected_ids'])
            self.assertFalse(identifiers & {r['id'] for r in records[:4]})
            self.assertEqual(result['selected_ids'], [r['id'] for r in records if r['id'] in identifiers])
            original_lines = [line for line in policies.read_text().splitlines(keepends=True) if json.loads(line)['id'] in identifiers]
            self.assertEqual((folder/'deep/policies.jsonl').read_text(), ''.join(original_lines))
            exported = [json.loads(line) for line in (folder/'deep/positions.jsonl').read_text().splitlines()]
            self.assertTrue(all(row['analysis_role'] == 'prior_development' and row['split'] == 'test' for row in exported))
            self.assertEqual(result['positions_sha256'], digest(folder/'deep/positions.jsonl'))
            public = (folder/'public.json').read_text()
            for forbidden in (str(folder), records[8]['id'], records[8]['fen'], 'selected_ids', 'selected_legal_roots'):
                self.assertNotIn(forbidden, public)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                select_batch(source, folder, folder/'deep', folder/'public.json')

    def test_changed_completed_output_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, policies = make_census(directory, synthetic_records(4))
            with policies.open('a') as f:
                f.write('\n')
            with self.assertRaisesRegex(ValueError, 'hash or count'):
                checked_sources(source, Path(directory))


if __name__ == '__main__':
    unittest.main()
