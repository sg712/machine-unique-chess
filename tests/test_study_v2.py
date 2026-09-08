"""Meaningful safeguards for an unpublished learning experiment, using synthetic scores."""
import copy
import importlib.util
import itertools
import json
from pathlib import Path
import tempfile
import unittest

import chess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mining_v2_study', ROOT / 'scripts/mining_v2_study.py')
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


def fixture_bank():
    """Synthetic structural fixture, never a scientifically verified item bank."""
    boards = []
    board = chess.Board()
    for first in list(board.legal_moves):
        after = board.copy()
        after.push(first)
        for second in list(after.legal_moves):
            child = after.copy()
            child.push(second)
            boards.append(child)
            if len(boards) == 48:
                break
        if len(boards) == 48:
            break
    items = []
    board_iter = iter(boards)
    for family in range(8):
        entries = [('training', None, kind) for kind in ('positive', 'positive', 'boundary')]
        entries += [('test', form, 'boundary' if (family + index) % 2 else 'positive')
                    for index, form in enumerate('ABC')]
        for role, form, kind in entries:
            position = next(board_iter)
            scores = {move.uci(): index * -50 for index, move in enumerate(position.legal_moves)}
            items.append({'id': f'item-{len(items)}', 'family': f'family-{family}', 'role': role,
                          'kind': kind, 'form': form, 'fen': position.fen(), 'game_id': f'game-{len(items)}',
                          'explanation': 'Synthetic fixture only; not research evidence.',
                          'scores_20': scores.copy(), 'scores_24': scores.copy(),
                          'accepted20': study.acceptance(scores), 'accepted24': study.acceptance(scores),
                          'engine': {'depth20': 20, 'depth24': 24, 'nodes20': 100, 'nodes24': 200,
                                     'all_scores_exact': True, 'verified': True},
                          'review': {'chess': True, 'near_duplicates': True, 'reviewer': 'test-fixture'}})
    return {'schema_version': 2,
            'engine': {'name': 'Stockfish 18', 'binary_sha256': 'a' * 64, 'threads': 1, 'hash_mb': 128},
            'readiness': {gate: True for gate in study.MANUAL_GATES}, 'items': items}


class StudyV2Tests(unittest.TestCase):
    def setUp(self):
        self.bank = fixture_bank()

    def test_complete_synthetic_structure_passes_but_open_gate_blocks_freeze(self):
        self.assertTrue(study.validate(self.bank)['ready_for_recruitment'])
        self.bank['readiness']['preregistered'] = False
        report = study.validate(self.bank)
        self.assertTrue(report['material_checks_passed'])
        self.assertFalse(report['ready_for_recruitment'])
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(ValueError, 'not ready'):
                study.export_bundle(self.bank, output, seed=15)
            study.export_bundle(self.bank, output, seed=15, draft=True)
            saved = json.loads((Path(output) / 'private-allocation.json').read_text())
            self.assertTrue(saved['draft'])
            self.assertTrue(saved['slots_are_not_participants'])

    def test_scoring_catches_unsearched_unstable_and_mate_moves(self):
        first = self.bank['items'][0]
        dropped = next(iter(first['scores_20']))
        del first['scores_20'][dropped]
        self.assertTrue(any('every legal move' in error for error in study.validate(self.bank)['errors']))
        self.bank = fixture_bank()
        first = self.bank['items'][0]
        moves = list(first['scores_24'])
        first['scores_24'][moves[1]] = 0
        first['accepted24'] = study.acceptance(first['scores_24'])
        self.assertTrue(any('changes between' in error for error in study.validate(self.bank)['errors']))
        first['scores_24'][moves[0]] = {'mate': 4}
        self.assertTrue(any('no mate scores' in error for error in study.validate(self.bank)['errors']))

    def test_duplicate_transposition_games_and_public_exposure_block_materials(self):
        original = self.bank['items'][0]
        duplicate = self.bank['items'][1]
        parts = original['fen'].split()
        parts[4:] = ['44', '72']
        duplicate['fen'] = ' '.join(parts)
        duplicate['game_id'] = original['game_id']
        errors = study.validate(self.bank)['errors']
        self.assertTrue(any('duplicate canonical' in error for error in errors))
        self.assertTrue(any('game is reused' in error for error in errors))
        test = next(item for item in self.bank['items'] if item['role'] == 'test')
        errors = study.validate(self.bank, [test['fen']], [test['game_id']])['errors']
        self.assertTrue(any('position is already public' in error for error in errors))
        self.assertTrue(any('source game already appears' in error for error in errors))

    def test_incomplete_boundaries_and_early_stop_are_not_silently_verified(self):
        self.bank['items'][2]['kind'] = 'positive'
        self.bank['items'][0]['engine']['depth24'] = 22
        self.bank['items'][1]['engine']['all_scores_exact'] = False
        errors = study.validate(self.bank)['errors']
        self.assertTrue(any('boundary example' in error for error in errors))
        self.assertTrue(any('actually reach' in error for error in errors))
        self.assertTrue(any('exact-score engine verification' in error for error in errors))

    def test_arms_only_change_order_and_seed_is_reproducible(self):
        before = copy.deepcopy(self.bank['items'])
        grouped = study.practice_order(self.bank['items'], 'grouped', 9)
        shuffled = study.practice_order(self.bank['items'], 'shuffled', 9)
        self.assertCountEqual(grouped, shuffled)
        self.assertNotEqual(grouped, shuffled)
        self.assertEqual(shuffled, study.practice_order(self.bank['items'], 'shuffled', 9))
        self.assertEqual(before, self.bank['items'])
        by_id = {item['id']: item for item in self.bank['items']}
        blocks = [list(values) for _, values in itertools.groupby(grouped, key=lambda key: by_id[key]['family'])]
        self.assertEqual(len(blocks), 8)
        self.assertTrue(all(len(block) == 3 for block in blocks))
        self.assertTrue(all(by_id[block[-1]]['kind'] == 'boundary' for block in blocks))

    def test_concealed_slots_balance_blocks_and_form_orders(self):
        plan = study.assignment_plan(self.bank['items'], 159)
        self.assertEqual(plan, study.assignment_plan(self.bank['items'], 159))
        for stratum in study.STRATA:
            slots = [slot for slot in plan['allocation'] if slot['stratum'] == stratum]
            for _, values in itertools.groupby(slots, key=lambda slot: slot['block']):
                self.assertCountEqual([slot['arm'] for slot in values], list(study.ARMS) * 2)
            for arm in study.ARMS:
                order = [tuple(slot['forms'].values()) for slot in slots if slot['arm'] == arm]
                self.assertEqual(len(set(order[:6])), 6)
        self.assertTrue(all(slot['assigned_participant_id'] is None for slot in plan['allocation']))

    def test_materials_conceal_test_answers_and_exports_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as output:
            study.export_bundle(self.bank, output, seed=159)
            bundle = json.loads((Path(output) / 'materials.json').read_text())
            self.assertEqual(len(bundle['training_items']), 24)
            for form in bundle['test_forms'].values():
                self.assertTrue(all(set(item) == {'id', 'fen'} for item in form))
            with self.assertRaises(FileExistsError):
                study.export_bundle(self.bank, output, seed=987)
            private = json.loads((Path(output) / 'private-allocation.json').read_text())
            self.assertEqual(private['seed'], 159)


if __name__ == '__main__':
    unittest.main()
