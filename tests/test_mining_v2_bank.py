"""Draft assembly must preserve provenance and expose material shortages."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import chess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mining_v2_bank', ROOT / 'scripts/mining_v2_bank.py')
bank = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bank)


class MiningBankTests(unittest.TestCase):
    def fixture(self):
        start = chess.Board()
        following = start.copy(); following.push_uci('e2e4')
        rows = [{'id': key, 'fen': board.fen(), 'game_id': 'game-'+key} for key, board in [('a', start), ('b', following)]]
        policies = [{'id': row['id'], 'fen': row['fen'], 'maia3': {'fen_only': {}}} for row in rows]
        review = {'families': [{'id': 'draft-family', 'title': 'A readable family title', 'positive_ids': ['a'], 'related_unverified_ids': ['b'],
                                'verified_boundary_ids': [], 'notes_by_id': {'a': 'Provisional anchor explanation.',
                                                                          'b': 'Related, but not established.'}}]}
        return review, rows, policies

    def test_related_examples_are_unassigned_and_engine_does_not_imply_review(self):
        review, rows, policies = self.fixture()
        value = bank.build_bank(review, rows, policies, {}, {}, {'deep_runs': []})
        self.assertEqual(len(value['items']), 1)
        self.assertEqual(len(value['unassigned_candidates']), 1)
        self.assertEqual(value['unassigned_candidates'][0]['role'], 'unassigned')
        item = value['items'][0]
        self.assertEqual(item['source_row'], rows[0])
        self.assertEqual(item['family_title'], 'A readable family title')
        self.assertEqual(item['model_policy'], policies[0])
        self.assertFalse(item['review']['chess'])
        self.assertFalse(item['review']['near_duplicates'])
        self.assertEqual(value['candidate_summary']['assigned_boundary_anchors'], 0)
        self.assertEqual(value['candidate_summary']['test_items'], 0)

    def test_natural_boundary_is_training_but_remains_unverified_until_deep_review(self):
        review, rows, policies = self.fixture()
        review['families'][0]['related_unverified_ids'] = []
        boundary = {'id': 'b', 'family_link': 'draft-family', 'positive_anchor_id': 'a',
                    'fen': rows[1]['fen'], 'game_id': rows[1]['game_id'],
                    'explanation': 'Synthetic boundary fixture.',
                    'verification_status': 'provisional', 'comparison': {'knight_capture': {'root': 'g8f6'}}}
        value = bank.build_bank(review, rows, policies, {}, {}, {'deep_runs': []},
                                boundary_document={'candidates': [boundary]})
        item = next(item for item in value['items'] if item['id'] == 'b')
        self.assertEqual((item['role'], item['kind']), ('training', 'boundary'))
        self.assertEqual(item['family_title'], 'A readable family title')
        self.assertFalse(item['engine']['verified'])
        self.assertFalse(item['review']['chess'])
        self.assertEqual(value['candidate_summary']['test_items'], 0)
        self.assertEqual(value['candidate_summary']['assigned_boundary_anchors'], 1)
        boundary['positive_anchor_id'] = 'unassigned-anchor'
        with self.assertRaisesRegex(ValueError, 'not assigned'):
            bank.build_bank(review, rows, policies, {}, {}, {'deep_runs': []},
                            boundary_document={'candidates': [boundary]})

    def test_later_failed_deep_evidence_is_not_hidden_by_old_verified_result(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder)/name for name in ('old.jsonl', 'new.jsonl')]
            for path, verified in zip(paths, (True, False)):
                path.write_text(json.dumps({'id': 'a', 'mode': 'deep', 'verified': verified})+'\n')
            selected, history, metadata = bank.deep_snapshots(paths)
            self.assertFalse(selected['a'][0]['verified'])
            self.assertEqual([row['verified'] for row in history['a']], [True, False])
            self.assertEqual(len(metadata), 2)

    def test_partial_last_jsonl_line_is_explicitly_omitted_from_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'growing.jsonl'
            path.write_bytes(b'{"id":"done"}\n{"id":"unfinished')
            rows, metadata = bank.snapshot(path, jsonl=True)
            self.assertEqual(rows, [{'id': 'done'}])
            self.assertTrue(metadata['incomplete_last_line_omitted'])
            self.assertEqual(metadata['snapshot_sha256'], bank.sha(path.read_bytes()))

    def test_agent_review_is_tied_to_exact_explanation_and_deep_evidence(self):
        deep = {'verified': True, 'accepted': {'20': ['e2e4'], '24': ['e2e4']}}
        item = {'id': 'a', 'fen': chess.STARTING_FEN, 'game_id': 'game-a', 'explanation': 'Reviewed wording.',
                'raw_deep_evidence': deep, 'engine': {'verified': True},
                'accepted20': ['e2e4'], 'accepted24': ['e2e4'], 'review': {'chess': False}}
        record = {'id': 'a', 'fen': item['fen'], 'game_id': item['game_id'],
                  'status': 'agent_chess_review_passed', 'reviewer': 'test-fixture',
                  'explanation_sha256': bank.sha(item['explanation'].encode()),
                  'deep_row_sha256': bank.sha(json.dumps(deep, sort_keys=True, separators=(',', ':')).encode()),
                  'accepted20': ['e2e4'], 'accepted24': ['e2e4']}
        bank.apply_agent_review(item, record)
        self.assertTrue(item['review']['chess'])
        item['explanation'] = 'Different wording, not reviewed.'
        bank.apply_agent_review(item, record)
        self.assertFalse(item['review']['chess'])
        self.assertEqual(item['review']['agent_review_record_status'], 'stale_or_unmatched')

    def test_refresh_archives_a_draft_and_refuses_a_frozen_export(self):
        review, rows, policies = self.fixture()
        value = bank.build_bank(review, rows, policies, {}, {}, {'deep_runs': []})
        with tempfile.TemporaryDirectory() as folder:
            report = bank.export_draft(value, folder, seed=712)
            self.assertFalse(report['ready_for_recruitment'])
            value['items'][0]['explanation'] = 'A revised draft note.'
            bank.export_draft(value, folder, seed=712, refresh=True)
            self.assertEqual(len(list((Path(folder)/'archive').iterdir())), 1)
            allocation_path = Path(folder)/'private-allocation.json'
            allocation = json.loads(allocation_path.read_text())
            allocation['draft'] = False
            allocation_path.write_text(json.dumps(allocation))
            with self.assertRaisesRegex(ValueError, 'frozen'):
                bank.export_draft(value, folder, seed=712, refresh=True)


if __name__ == '__main__':
    unittest.main()
