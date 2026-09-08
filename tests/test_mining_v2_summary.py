"""Aggregate publication must use matching, completed data and keep items private."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.mining_v2_summary import (check_identity, check_policy_manifest,
                                       check_screen_manifest, deep_summary, describe,
                                       policy_comparison, sha)

FEN = '7k/8/8/8/8/8/8/K7 w - - 0 1'


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


class MiningSummaryTests(unittest.TestCase):
    def test_identity_rejects_duplicates_missing_rows_and_stale_fens(self):
        records = {'a': {'id': 'a', 'fen': FEN}}
        self.assertEqual(check_identity(list(records.values()), records, 'fixture'), records)
        for rows in ([], [records['a'], records['a']], [{'id': 'a', 'fen': FEN.replace(' w ', ' b ')}]):
            with self.assertRaises(ValueError):
                check_identity(rows, records, 'fixture')

    def test_manifest_hashes_reject_stale_or_incomplete_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            data, policy = base / 'input.jsonl', base / 'policy.jsonl'
            rows = [{'id': 'a', 'fen': FEN}]
            write_jsonl(data, rows)
            write_jsonl(policy, rows)
            records = {'a': rows[0]}
            pm = {'record_count': 1, 'input_sha256': sha(data), 'output_sha256': sha(policy)}
            check_policy_manifest(pm, data, policy, rows, records)
            sm = {'complete': True, 'input_n': 1, 'completed_n': 1,
                  'settings': {'input_sha256': sha(data), 'policy_sha256': sha(policy)}}
            check_screen_manifest(sm, data, policy, rows, records, 'fixture')
            with self.assertRaises(ValueError):
                check_screen_manifest({**sm, 'complete': False}, data, policy, rows, records, 'fixture')
            policy.write_text(policy.read_text() + '\n')
            with self.assertRaises(ValueError):
                check_screen_manifest(sm, data, policy, rows, records, 'fixture')
            with self.assertRaises(ValueError):
                check_policy_manifest(pm, data, policy, rows, records)

    def test_heldout_candidates_are_not_discovery_counts_or_published_items(self):
        records, rows = {}, []
        for split in ('train', 'validation', 'test'):
            records[split] = {'id': split, 'fen': FEN, 'split': split,
                              'source': {'cohort': 'club'}}
            rows.append({'id': split, 'has_mate': False, 'best_cp': 0,
                         'metrics': {f'maia3/history/{rating}':
                                     {'20': {'available': True, 'p_good_upper': .01,
                                             'capped_regret_lower_cp': 100}}
                                     for rating in (1700, 2000)}})
        result = describe(rows, records, 'history')
        self.assertEqual(result['screen_candidates_n'], 3)
        self.assertEqual(result['family_discovery_train_candidates_n'], 1)
        encoded = json.dumps(result)
        self.assertNotIn(FEN, encoded)
        self.assertNotIn('"id"', encoded)
        self.assertNotIn('"best"', encoded)

    def test_latest_completed_canonical_check_supersedes_stale_success(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            results = base / 'results'
            results.mkdir()
            for name, stamp, complete, verified, ident, fen in (
                    ('old_deep', 1, True, True, 'old-id', FEN),
                    ('new_deep', 2, True, False, 'new-id', FEN.replace('0 1', '2 4')),
                    ('running_deep', 3, False, True, 'future-id', FEN)):
                source, policies = base / f'{name}-input.jsonl', base / f'{name}-policy.jsonl'
                write_jsonl(source, [{'id': ident, 'fen': fen}])
                write_jsonl(policies, [{'id': ident, 'fen': fen}])
                output = results / f'{name}.jsonl'
                write_jsonl(output, [{'id': ident, 'fen': fen, 'mode': 'deep', 'split': 'train', 'verified': verified}])
                manifest = {'complete': complete, 'input_n': 1, 'completed_n': 1,
                            'finished_at': stamp, 'settings': {'input': str(source), 'policies': str(policies),
                                'input_sha256': sha(source), 'policy_sha256': sha(policies)}}
                output.with_suffix('.manifest.json').write_text(json.dumps(manifest))
            result = deep_summary(results)
            self.assertEqual(result['completed_batches_n'], 2)
            self.assertEqual(result['incomplete_batches_n'], 1)
            self.assertEqual(result['completed_position_checks_n'], 2)
            self.assertEqual(result['unique_positions_n'], 1)
            self.assertEqual(result['verified_unique_n'], 0)
            self.assertEqual(result['verified_training_positions_n'], 0)

    def test_optional_model_comparisons_report_correct_denominator(self):
        policies = [{'maia3': {'history': {'2000': {'a': .8, 'b': .2}},
                               'fen_only': {'2000': {'a': .3, 'b': .7}}},
                     'maia2': None},
                    {'maia3': {'history': {}, 'fen_only': {'2000': {'a': 1.0}}},
                     'maia2': {'fen_only': {'2000': {'a': 1.0}}}}]
        summary = policy_comparison(policies)
        self.assertEqual(summary['history_compared_n'], 1)
        self.assertEqual(summary['history_changes_top_move_n'], 1)
        self.assertEqual(summary['maia2_vs_maia3_compared_n'], 1)
        self.assertAlmostEqual(summary['history_mean_total_variation'], .5)


if __name__ == '__main__':
    unittest.main()
