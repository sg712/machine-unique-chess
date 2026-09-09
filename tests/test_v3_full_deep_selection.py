"""Full-census selection tests use synthetic games, never engines or deep outcomes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.mining_v3_deep_selection import checked_sources
from scripts.mining_v3_full_deep_selection import (ROOT, check_census_policy, checked_initial_selection,
    choose_census, classify_strata, origin_metadata, select_full_census, state_provenance)
from scripts.mining_v3_io import digest
from tests.test_v3_deep_selection import make_census, policy_for, synthetic_records


def refresh_stage_hashes(folder):
    """Re-freeze synthetic fixture hashes before testing the selector."""
    run_path = folder / 'run.json'
    run = json.loads(run_path.read_text())
    for stage in run['shards']:
        stage['output_sha256'] = digest(stage['output'])
        manifest_path = Path(stage['manifest'])
        manifest = json.loads(manifest_path.read_text())
        if stage['stage'] == 'engine':
            manifest['settings']['policy_sha256'] = digest(folder / 'policies.jsonl')
        manifest_path.write_text(json.dumps(manifest))
        stage['manifest_sha256'] = digest(manifest_path)
    run_path.write_text(json.dumps(run))


def make_initial(folder, source, identifiers):
    initial = folder / 'initial'
    initial.mkdir()
    position_lines = {json.loads(line)['id']: line for line in source.read_bytes().splitlines(keepends=True)}
    policy_lines = {json.loads(line)['id']: line for line in (folder/'policies.jsonl').read_bytes().splitlines(keepends=True)}
    (initial/'positions.jsonl').write_bytes(b''.join(position_lines[i] for i in identifiers))
    (initial/'policies.jsonl').write_bytes(b''.join(policy_lines[i] for i in identifiers))
    (initial/'selection_protocol.json').write_text('{"synthetic":true}\n')
    roots = {i: check_census_policy(json.loads(position_lines[i]), json.loads(policy_lines[i])) for i in identifiers}
    manifest = {'complete': True, 'selected_n': len(identifiers), 'selected_ids': identifiers,
        'input_hashes': checked_sources(source, folder)[4],
        'positions_sha256': digest(initial/'positions.jsonl'), 'policies_sha256': digest(initial/'policies.jsonl'),
        'selection_protocol_sha256': digest(initial/'selection_protocol.json'),
        'selection_script_sha256': digest(ROOT/'scripts/mining_v3_deep_selection.py'),
        'selected_legal_roots': roots, 'legal_roots': {'total': sum(roots.values())},
        'original_policy_line_sha256': {i: hashlib.sha256(policy_lines[i]).hexdigest() for i in identifiers}}
    manifest['outputs'] = {key: manifest[key] for key in ('positions_sha256', 'policies_sha256')}
    (initial/'selection_manifest.json').write_text(json.dumps(manifest))
    return initial


class FullDeepSelectionTests(unittest.TestCase):
    def test_census_has_no_game_cap_or_quota_and_preserves_initial_precedence(self):
        records = synthetic_records(8)
        for row in records:
            row['game_id'] = 'same-source-game'
        records[0]['contains_bot'] = True
        duplicate = copy.deepcopy(records[0])
        duplicate.update(id='clean-duplicate', contains_bot=False)
        selected, origins = choose_census(records + [duplicate], [records[0]])
        self.assertEqual(len(selected), 8)
        self.assertIn(records[0]['id'], {r['id'] for r in selected})
        self.assertNotIn(duplicate['id'], {r['id'] for r in selected})
        self.assertEqual(len(origins[records[0]['id']]), 2)
        self.assertEqual(len({r['game_id'] for r in selected}), 1)
        altered = copy.deepcopy(records + [duplicate])
        for i, row in enumerate(altered):
            row.update(depth=i, best_cp=i, legal_count=1000-i, elapsed_seconds=i)
        # Initial records need exact metadata equality, as the real export does.
        result, _ = choose_census(list(reversed(altered)), [altered[0]])
        self.assertEqual({r['id'] for r in selected}, {r['id'] for r in result})

    def test_preferred_representative_does_not_hide_any_origin_exposure(self):
        clean = synthetic_records(1)[0]
        bot, public, unknown = (copy.deepcopy(clean) for _ in range(3))
        bot.update(id='bot-origin', game_id='bot-game', contains_bot=True)
        public.update(id='public-origin', game_id='public-game', known_public_game=True)
        unknown.update(id='unknown-origin', game_id='unknown-game', contains_bot=None, history_available=None)
        selected, groups = choose_census([public, unknown, bot, clean], [])
        self.assertEqual(selected[0], clean)
        audit = state_provenance([origin_metadata(r, {'public-game'}) for r in groups[clean['id']]])
        self.assertTrue(audit['any_bot_tagged'])
        self.assertTrue(audit['any_known_public'])
        self.assertTrue(audit['any_unknown_bot_status'])
        self.assertTrue(audit['any_unknown_history'])
        self.assertFalse(audit['all_origins_recovered_no_bot_not_known_public'])
        self.assertEqual(audit['origin_observations_n'], 4)

    def test_unknown_sources_are_explicit_and_fen_policies_remain_strict(self):
        row = synthetic_records(1)[0]
        row.update(contains_bot=None, history_available=None, known_public_game=None, analysis_role=None)
        self.assertEqual(classify_strata(row), {'bot_status': 'unknown', 'history_status': 'unknown',
            'public_exposure': 'unknown', 'analysis_role': 'unknown'})
        policy = policy_for(row)
        policy['history_available'] = None
        self.assertGreater(check_census_policy(row, policy), 0)
        row['history_available'] = False
        policy['history_available'] = False
        self.assertGreater(check_census_policy(row, policy), 0)
        bad = copy.deepcopy(policy)
        bad['maia3']['fen_only']['1700'].pop(next(iter(bad['maia3']['fen_only']['1700'])))
        with self.assertRaisesRegex(ValueError, 'every legal move'):
            check_census_policy(row, bad)
        bad = copy.deepcopy(policy)
        bad['input_condition'] = 'history'
        with self.assertRaisesRegex(ValueError, 'FEN-only'):
            check_census_policy(row, bad)
        row['history_available'] = True
        row['history_uci'] = ['e2e5']
        policy['history_available'] = True
        with self.assertRaisesRegex(ValueError, 'illegal source history'):
            check_census_policy(row, policy)

    def test_export_is_complete_verbatim_and_private_with_propagated_public_game(self):
        records = synthetic_records(7)
        noncandidate = records.pop()
        records[2]['contains_bot'] = True
        records[3].update(contains_bot=None, history_available=None, known_public_game=None)
        records[4]['known_public_game'] = True
        records[5]['game_id'] = records[4]['game_id']
        initial_duplicate, other_duplicate = copy.deepcopy(records[0]), copy.deepcopy(records[2])
        initial_duplicate.update(id='first-state-duplicate', game_id='new-game-zero')
        other_duplicate.update(id='clean-state-duplicate', game_id='new-game-two', contains_bot=False)
        records.extend([initial_duplicate, other_duplicate, noncandidate])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, policies = make_census(folder, records)
            policy_rows = [json.loads(line) for line in policies.read_text().splitlines()]
            for row, policy in zip(records, policy_rows):
                policy['history_available'] = row['history_available']
            policies.write_text(''.join(json.dumps(p) + '\n' for p in policy_rows))
            engine_path = folder / 'engine.jsonl'
            engine_rows = [json.loads(line) for line in engine_path.read_text().splitlines()]
            for row in engine_rows:
                if row['id'] == noncandidate['id']:
                    row['best_cp'] = 500
            engine_path.write_text(''.join(json.dumps(r) + '\n' for r in engine_rows))
            refresh_stage_hashes(folder)
            initial = make_initial(folder, source, [records[0]['id'], records[1]['id']])
            with patch('scripts.mining_v3_full_deep_selection.public_exclusions', return_value=(set(), set(), {})):
                result = select_full_census(source, folder, initial, folder/'all', folder/'public.json', expected_n=6, initial_n=2)
            self.assertEqual((result['selected_n'], result['already_deep200_n'], result['new_n']), (6, 2, 4))
            self.assertEqual(result['counts']['screen_candidates_n'], 8)
            self.assertEqual(result['counts']['canonical_duplicate_rows_removed_n'], 2)
            expected = {r['id'] for r in records[:6]} - {records[2]['id']} | {other_duplicate['id']}
            self.assertEqual(set(result['selected_ids']), expected)
            self.assertEqual(result['selected_ids'], [r['id'] for r in records if r['id'] in expected])
            for name, original in (('positions.jsonl', source), ('policies.jsonl', policies)):
                expected_bytes = b''.join(line for line in original.read_bytes().splitlines(keepends=True)
                                           if json.loads(line)['id'] in expected)
                self.assertEqual((folder/'all'/name).read_bytes(), expected_bytes)
            self.assertTrue(result['state_provenance_by_id'][other_duplicate['id']]['any_bot_tagged'])
            self.assertTrue(result['state_provenance_by_id'][records[5]['id']]['any_known_public'])
            self.assertEqual(result['strata_by_id'][records[5]['id']]['public_exposure'], 'not_known_public')
            self.assertEqual(sum(len(v) for v in result['canonical_origins_by_id'].values()), 8)
            self.assertEqual(result['legal_roots']['total'], result['legal_roots']['remaining'] + result['legal_roots']['already_deep200'])
            public = (folder/'public.json').read_text()
            for forbidden in (str(folder), records[0]['id'], records[0]['fen'], 'selected_ids', 'by_id', 'canonical_origins'):
                self.assertNotIn(forbidden, public)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                select_full_census(source, folder, initial, folder/'all', folder/'public.json', expected_n=6, initial_n=2)

    def test_initial_hash_mismatch_and_non_candidate_reuse_fail(self):
        records = synthetic_records(3)
        with self.assertRaisesRegex(ValueError, 'screen candidate'):
            choose_census(records[:2], [records[2]])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, _ = make_census(folder, records)
            initial = make_initial(folder, source, [records[0]['id']])
            hashes = checked_sources(source, folder)[4]
            with (initial/'policies.jsonl').open('ab') as stream:
                stream.write(b'\n')
            with self.assertRaisesRegex(ValueError, 'export hash changed'):
                checked_initial_selection(initial, hashes, expected_n=1)


if __name__ == '__main__':
    unittest.main()
