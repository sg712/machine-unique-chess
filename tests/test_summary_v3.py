"""Synthetic publication contracts; no private assessment positions are fixtures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from mining_v3_dataset import assemble
from mining_v3_io import digest
from mining_v3_summary import matched_human_ids, source_month, summarize
from mining_v2_sampling import canonical_fen


def write_json(path, value):
    Path(path).write_text(json.dumps(value)+'\n')


def write_rows(path, values):
    Path(path).write_text(''.join(json.dumps(value)+'\n' for value in values))


def fixture_rows():
    sequences = [[], ['e2e4'], ['e2e4', 'e7e5'], ['d2d4']]
    played = ['e2e4', 'e7e5', 'g1f3', 'd7d5']
    result = []
    for index, (moves, choice) in enumerate(zip(sequences, played)):
        board = chess.Board()
        for move in moves:
            board.push_uci(move)
        result.append({'id': f'PRIVATE-RECORD-{index}', 'fen': board.fen(),
                       'played_move': choice, 'game_id': f'PRIVATE-GAME-{index}',
                       'side_to_move': 'white' if board.turn else 'black',
                       'mover_elo': 2400, 'cohort': 'elite', 'phase': 'opening',
                       'source': {'date': '2026.06.01', 'private_note': 'PRIVATE-ANNOTATION'},
                       'contains_bot': False, 'history_available': True, 'time_control': '180+0',
                       'split': 'train'})
    return result


class SummaryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory/'source.jsonl'
        self.metadata = self.directory/'enriched.jsonl'
        self.output = self.directory/'public.json'
        self.rows = fixture_rows()
        write_rows(self.source, self.rows)
        write_rows(self.metadata, self.rows)
        code = {name: 'hash-'+name for name in ('mining_v3_policy.py', 'mining_v3_engine.py',
                                               'mining_v3_io.py', 'mining_v2_policy.py', 'mining_v2_engine.py')}
        self.run = {'complete': True, 'input_n': 4, 'policy_completed_n': 4, 'engine_completed_n': 4,
                    'shards_n': 2, 'shards': [],
                    'settings': {'input': str(self.source), 'input_sha256': digest(self.source),
                                 'top_nodes': 30000, 'root_nodes': 5000, 'max_human': 10, 'coverage': .85,
                                 'policy_threads': 2, 'batch_size': 128, 'chunk_size': 256, 'code_sha256': code}}
        self.plan = {'complete': True, 'rows': 4, 'settings': {
            'source': str(self.source), 'source_sha256': digest(self.source)}, 'shards': []}
        for index in range(2):
            inputs = self.rows[2*index:2*index+2]
            source = self.directory/f'input-{index}.jsonl'
            write_rows(source, inputs)
            self.plan['shards'].append({'index': index, 'input': str(source), 'input_sha256': digest(source), 'rows': 2})
            for stage in ('policy', 'engine'):
                path = self.directory/f'{stage}-{index}.jsonl'
                manifest_path = self.directory/f'{stage}-{index}.manifest.json'
                settings = {'input': str(source), 'input_sha256': digest(source),
                            'scorer_sha256': code[f'mining_v3_{stage}.py'], 'io_sha256': code['mining_v3_io.py']}
                if stage == 'policy':
                    results = [{'id': row['id'], 'fen': row['fen'], 'private_debug': 'PRIVATE-POLICY'} for row in inputs]
                    settings.update(adapter_sha256=code['mining_v2_policy.py'], context='fen_only',
                                    ratings=[1400, 1700, 2000, 2300], threads=2, batch_size=128, chunk_size=256)
                else:
                    results = [self.engine_result(row) for row in inputs]
                    settings.update(v2_helpers_sha256=code['mining_v2_engine.py'], board_context='fen_only',
                                    top_nodes=30000, root_nodes=5000, max_human=10, coverage=.85,
                                    policies=str(self.directory/f'policy-{index}.jsonl'),
                                    policy_sha256=digest(self.directory/f'policy-{index}.jsonl'),
                                    private_debug='PRIVATE-ENGINE')
                write_rows(path, results)
                manifest = {'complete': True, 'input_n': 2, 'completed_n': 2, 'settings': settings}
                if stage == 'policy':
                    manifest['model'] = {'model': 'Maia3-5M', 'weights_sha256': 'checkpoint-hash',
                                         'private_debug': 'PRIVATE-MODEL'}
                write_json(manifest_path, manifest)
                self.run['shards'].append({'index': index, 'stage': stage, 'rows': 2,
                                           'output': str(path), 'output_sha256': digest(path),
                                           'manifest': str(manifest_path), 'manifest_sha256': digest(manifest_path)})
        self.save()

    def save(self):
        write_json(self.directory/'run.json', self.run)
        write_json(self.directory/'shards.json', self.plan)

    def entry(self, index, stage):
        return next(item for item in self.run['shards'] if item['index'] == index and item['stage'] == stage)

    def change_manifest(self, index, stage, edit):
        entry = self.entry(index, stage)
        manifest = json.loads(Path(entry['manifest']).read_text())
        edit(manifest)
        write_json(entry['manifest'], manifest)
        entry['manifest_sha256'] = digest(entry['manifest'])
        self.save()

    def engine_result(self, row):
        search = {'uci': row['played_move'], 'depth': 8, 'cp': 30, 'mate': None,
                  'score_selection': 'last_completed_exact_iteration',
                  'last_reported': {'depth': 9, 'uci': row['played_move'], 'cp': 40,
                                    'mate': None, 'lowerbound': True, 'upperbound': False}}
        metric = {'available': True, 'p_good_upper': .05, 'capped_regret_lower_cp': 75,
                  'unscored_mass': .04}
        return {'id': row['id'], 'fen': row['fen'], 'mode': 'fixed_node_screen',
                'side_to_move': row['side_to_move'], 'board_context': 'fen_only',
                'verified': False, 'exhaustive': False, 'has_mate': False, 'best_cp': 30,
                'observed_played_is_top_engine_move': True, 'top': [copy.deepcopy(search)],
                'scores': {row['played_move']: copy.deepcopy(search)}, 'search_nodes_total': 35000,
                'metrics': {f'maia3/fen_only/{rating}': {'20': copy.deepcopy(metric)} for rating in (1700, 2000)}}

    def summarize(self):
        return summarize(self.metadata, self.directory, self.output)

    def test_complete_contract_and_public_aggregate_privacy(self):
        result = self.summarize()
        self.assertTrue(result['complete'])
        self.assertEqual(result['screened_n'], 4)
        self.assertEqual(result['matched_human']['per_side'], 2)
        self.assertEqual(result['quality']['previous_exact_iteration_used_n'], 8)
        self.assertEqual(result['quality']['unscored_mass_at_2000']['mean'], .04)
        self.assertEqual(result['input_sha256']['frozen_scoring_snapshot'], digest(self.source))
        text = self.output.read_text()
        self.assertNotIn('PRIVATE-', text)
        self.assertNotIn(str(self.directory), text)
        for row in self.rows:
            self.assertNotIn(row['fen'], text)
            self.assertNotIn('"'+row['played_move']+'"', text)

    def test_partial_run_cannot_publish(self):
        self.run['complete'] = False
        self.save()
        with self.assertRaisesRegex(ValueError, 'must be complete'):
            self.summarize()
        self.assertFalse(self.output.exists())

    def test_incomplete_shard_manifest_cannot_publish(self):
        self.change_manifest(0, 'engine', lambda manifest: manifest.update(complete=False))
        with self.assertRaisesRegex(ValueError, 'shard is incomplete'):
            self.summarize()

    def test_frozen_snapshot_change_is_detected(self):
        self.source.write_text(self.source.read_text()+'\n')
        with self.assertRaisesRegex(ValueError, 'hashes do not match'):
            self.summarize()

    def test_declared_run_source_hash_cannot_disagree(self):
        self.run['settings']['input_sha256'] = 'wrong'
        self.save()
        with self.assertRaisesRegex(ValueError, 'hashes do not match'):
            self.summarize()

    def test_duplicate_stage_entries_are_not_silently_overwritten(self):
        self.run['shards'].append(copy.deepcopy(self.run['shards'][0]))
        self.save()
        with self.assertRaisesRegex(ValueError, 'Duplicate completed stage'):
            self.summarize()

    def test_duplicate_metadata_ids_fail(self):
        write_rows(self.metadata, self.rows+[self.rows[0]])
        with self.assertRaisesRegex(ValueError, 'Duplicate metadata'):
            self.summarize()

    def test_duplicate_policy_ids_fail_even_with_matching_file_hash(self):
        entry = self.entry(0, 'policy')
        values = [json.loads(line) for line in Path(entry['output']).read_text().splitlines()]
        write_rows(entry['output'], [values[0], values[0]])
        entry['output_sha256'] = digest(entry['output'])
        self.save()
        with self.assertRaisesRegex(ValueError, 'Stage identities'):
            self.summarize()

    def test_metadata_must_preserve_scored_move(self):
        self.rows[0]['played_move'] = 'd2d4'
        write_rows(self.metadata, self.rows)
        with self.assertRaisesRegex(ValueError, 'changed a scored board or observed move'):
            self.summarize()

    def test_metadata_cannot_change_colour_without_changing_board(self):
        self.rows[0]['side_to_move'] = 'black'
        write_rows(self.metadata, self.rows)
        with self.assertRaisesRegex(ValueError, 'side metadata'):
            self.summarize()

    def test_changed_regime_cannot_mix_into_run(self):
        self.change_manifest(1, 'engine', lambda manifest: manifest['settings'].update(root_nodes=9999))
        with self.assertRaisesRegex(ValueError, 'settings differ'):
            self.summarize()

    def test_wrong_policy_hash_cannot_be_used_by_engine(self):
        self.change_manifest(0, 'engine', lambda manifest: manifest['settings'].update(policy_sha256='wrong'))
        with self.assertRaisesRegex(ValueError, 'policies differ'):
            self.summarize()

    def test_bot_unknown_and_unrecovered_metadata_leave_complete_counts_unchanged(self):
        for field, value in (('contains_bot', True), ('contains_bot', None), ('history_available', False)):
            rows = copy.deepcopy(self.rows)
            rows[1][field] = value
            write_rows(self.metadata, rows)
            result = self.summarize()
            self.assertEqual(result['screened_n'], 4)
            self.assertEqual(result['matched_human']['n'], 2)
            self.assertEqual(sum(group['n'] for group in result['groups'] if group['group'] == 'all'), 4)


class MatchingContracts(unittest.TestCase):
    def test_duplicate_canonical_states_are_not_independent_matches(self):
        base = fixture_rows()
        records = {row['id']: {'id': row['id'], 'fen': row['fen'], 'side': row['side_to_move'],
                               'bot_status': 'no_bot_tag', 'source_recovered': True,
                               'cohort': 'elite', 'rating_band': '2400_2599', 'phase': 'opening',
                               'time_class': 'blitz', 'month': '2026-06'} for row in base}
        records[base[2]['id']]['fen'] = base[0]['fen']
        chosen, cells = matched_human_ids(records)
        self.assertEqual(len(chosen), 2)
        self.assertEqual(cells[0]['per_side'], 1)
        self.assertEqual(sum(records[key]['side'] == 'white' for key in chosen), 1)

    def test_invalid_or_unknown_months_are_not_matching_cells(self):
        self.assertEqual(source_month('2026.06.01'), '2026-06')
        self.assertEqual(source_month('2026-06-01'), '2026-06')
        for value in ('2026.??.01', '2026.13.01', '', None):
            self.assertIsNone(source_month(value))


class DatasetExposureContracts(unittest.TestCase):
    def test_public_exposure_propagates_across_both_colours_of_a_game(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            white, black = fixture_rows()[:2]
            black['game_id'] = white['game_id']
            paths = [directory/name for name in ('black.jsonl', 'pilot.jsonl', 'white.jsonl')]
            write_rows(paths[0], [black]); write_rows(paths[1], []); write_rows(paths[2], [white])
            with patch('mining_v3_dataset.public_exclusions', return_value=({canonical_fen(black['fen'])}, set(), {})):
                with self.assertRaisesRegex(ValueError, 'shares a source game with a public position'):
                    assemble(*paths, directory/'out.jsonl', directory/'summary.json',
                             expected_black=1, expected_new_white=1, expected_pilot_white=0)

    def test_outputs_cannot_overwrite_source_data(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory)/name for name in ('black.jsonl', 'pilot.jsonl', 'white.jsonl')]
            for path in paths:
                path.write_text('')
            with self.assertRaisesRegex(ValueError, 'must not overwrite'):
                assemble(*paths, paths[0], Path(directory)/'summary.json')


if __name__ == '__main__':
    unittest.main()
