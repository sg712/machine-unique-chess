"""Research integrity checks use committed artifacts and synthetic model fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import random
import unittest

import chess

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'experiments' / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ResearchTests(unittest.TestCase):
    def test_audit_denominators_and_engine_records(self):
        audit = json.loads((ROOT / 'results/30_research_audit.json').read_text())
        records = json.loads((ROOT / 'results/30_engine_audit.json').read_text())
        self.assertEqual(sum(b['n'] for b in audit['bands']), audit['mu_n'])
        self.assertEqual(sum(b['all_n'] for b in audit['bands']), audit['n'])
        self.assertEqual(sum(b['exact_n'] for b in audit['bands']), audit['exact_matches'])
        self.assertEqual(audit['engine']['n'], len(records['positions']))
        self.assertEqual(len({r['game_id'] for r in records['positions']}), len(records['positions']))
        self.assertEqual(sum(r['same_top_move'] for r in records['positions']), audit['engine']['same_top_n'])
        self.assertEqual(sum(not r['mate_in_search'] for r in records['positions']), audit['engine']['numeric_n'])
        for row in records['positions']:
            for info in row['top'] + list(row['restricted'].values()):
                board = chess.Board(row['fen'])
                for uci in info['pv']:
                    move = chess.Move.from_uci(uci)
                    self.assertIn(move, board.legal_moves)
                    board.push(move)
                self.assertGreaterEqual(info['depth'], records['settings']['depth_target'])

    def test_worked_examples_have_legal_lines_and_separate_games(self):
        examples = json.loads((ROOT / 'webapp/research_examples.json').read_text())['examples']
        self.assertEqual(len(examples), 3)
        for example in examples:
            self.assertNotEqual(example['primary']['game_id'], example['related']['game_id'])
            for key in ['primary', 'related']:
                pos = example[key]
                self.assertGreaterEqual(pos['best_cp'] - pos['runner_up_cp'], 70)
                self.assertEqual(pos['pv'][0]['uci'], pos['best'])
                for line in [pos['pv'], pos['human']['pv']]:
                    board = chess.Board(pos['fen'])
                    for step in line:
                        move = chess.Move.from_uci(step['uci'])
                        self.assertIn(move, board.legal_moves)
                        self.assertEqual(board.san(move), step['san'])
                        board.push(move)

    def test_study_validator_rejects_leakage_and_unverified_moves(self):
        validator = module('study_validator', '33_validate_study_manifest.py')
        # Synthetic chess positions and scores test structure only; never research results.
        rng = random.Random(19)
        items, states = [], set()
        for i in range(52):
            while True:
                board = chess.Board()
                for _ in range(20):
                    if board.is_game_over(): break
                    board.push(rng.choice(list(board.legal_moves)))
                state = validator.canonical(board.fen())
                if not board.is_game_over() and state not in states:
                    states.add(state); break
            legal = {m.uci(): 0 for m in board.legal_moves}
            role = 'test' if i < 36 else ('grouped_training' if i < 44 else 'ordinary_training')
            items.append({'id': str(i), 'role': role, 'form': 'ABC'[i // 12] if i < 36 else None,
                'family': (i % 12 if i % 12 < 8 else None) if i < 36 else (i - 36 if i < 44 else None),
                'fen': board.fen(), 'game_id': 'fixture-' + str(i), 'scores_20': legal,
                'scores_24': dict(legal), 'accepted': list(legal)})
        fixture = {'engine': {'name': 'Stockfish 17.1', 'binary_sha256': '0' * 64, 'threads': 1, 'hash_mb': 128}, 'items': items}
        self.assertEqual(validator.validate(fixture), [])
        bad = copy.deepcopy(fixture)
        bad['items'][1]['game_id'] = bad['items'][0]['game_id']
        bad['items'][2]['scores_24'].pop(next(iter(bad['items'][2]['scores_24'])))
        errors = validator.validate(bad, [items[0]['fen']])
        self.assertTrue(any('reused source game' in e for e in errors))
        self.assertTrue(any('every legal move' in e for e in errors))
        self.assertTrue(any('public trainer' in e for e in errors))

    @unittest.skipUnless(importlib.util.find_spec('sklearn'), 'Research dependencies are optional for the web app')
    def test_pca_is_fit_only_on_training_positions(self):
        from unittest.mock import patch
        import numpy as np
        from sklearn.model_selection import GroupKFold
        m = module('difficulty_test', '20_difficulty_model.py')
        rng = np.random.default_rng(1)
        X = rng.normal(size=(80, 2)); Z = rng.normal(size=(80, 6))
        y = np.tile([0, 1], 40); groups = np.repeat(np.arange(40), 2)
        fitted = []
        original = m.PCA
        class RecordingPCA(original):
            def fit_transform(self, values, y=None):
                fitted.append(values.copy())
                return super().fit_transform(values, y)
        with patch.object(m, 'PCA', RecordingPCA):
            _, _, predictions = m.cv_score(X, y, groups, embed=Z, n_pc=2)
        folds = list(GroupKFold(5).split(X, y, groups))
        self.assertEqual(len(fitted), len(folds))
        for seen, (train, test) in zip(fitted, folds):
            np.testing.assert_array_equal(seen, Z[train])
            self.assertTrue(set(groups[train]).isdisjoint(groups[test]))
        self.assertTrue(np.isfinite(predictions).all())
