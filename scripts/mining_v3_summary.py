"""Publish checked aggregates from complete v3 shards, never private positions."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import re
import statistics
import sys

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from mining_v2_sampling import canonical_fen
from mining_v2_summary import selected, competitive
from mining_v3_dataset import rating_band, read_rows, verify_record
from mining_v3_io import digest
from mining_v3_recover import time_class


def bot_status(row):
    value = row.get('contains_bot')
    return 'bot_tagged' if value is True else 'no_bot_tag' if value is False else 'unknown'


def matched_human_ids(records):
    """Match metadata before looking at outcomes; do not count repeat states twice.

    Use only recovered games without BOT tags, same cohort/rating/phase/time
    class/month cells on each side. Empty opposite-colour cells are discarded.
    The result is a descriptive subset, not a new held-out evaluation.
    """
    cells = defaultdict(lambda: defaultdict(list))
    seen = set()
    ranked = sorted(records.values(), key=lambda r: hashlib.sha256(('v3-human:'+r['id']).encode()).digest())
    for row in ranked:
        if (row['bot_status'] != 'no_bot_tag' or not row.get('source_recovered') or
                row['time_class'] == 'unknown' or not row['month'] or
                row['cohort'] == 'unknown' or row['phase'] not in ('opening', 'middlegame', 'endgame')):
            continue
        canon = canonical_fen(row['fen'])
        if canon in seen:
            continue
        seen.add(canon)
        cell = (row['cohort'], row['rating_band'], row['phase'], row['time_class'], row['month'])
        cells[cell][row['side']].append(row['id'])
    chosen, counts = set(), []
    for key, sides in sorted(cells.items()):
        n = min(len(sides['white']), len(sides['black']))
        if not n:
            continue
        chosen.update(sides['white'][:n])
        chosen.update(sides['black'][:n])
        counts.append(dict(zip(('cohort','rating_band','phase','time_class','month'), key), per_side=n))
    return chosen, counts


def quality(values):
    return {'n': len(values), 'min': min(values) if values else None,
            'median': statistics.median(values) if values else None,
            'max': max(values) if values else None,
            'mean': statistics.mean(values) if values else None}


def source_month(date):
    match = re.match(r'^(\d{4})[.-](0[1-9]|1[0-2])(?:[.-]|$)', str(date or ''))
    return f'{match[1]}-{match[2]}' if match else None


def used_previous_exact_iteration(search):
    final = search.get('last_reported', {})
    return (search.get('score_selection') == 'last_completed_exact_iteration' and
            (final.get('depth', 0) > search['depth'] or final.get('lowerbound') or final.get('upperbound') or
             final.get('uci') != search['uci'] or final.get('cp') != search.get('cp') or
             final.get('mate') != search.get('mate')))


def read_matching_metadata(input_path):
    records = {}
    for row in read_rows(input_path):
        if row['id'] in records:
            raise ValueError('Duplicate metadata record ID')
        verify_record(row)
        date = row.get('source', {}).get('date') or ''
        records[row['id']] = {
            'id': row['id'], 'fen': row['fen'], 'played_move': row['played_move'],
            'game_id': row['game_id'], 'side': row['side_to_move'],
            'cohort': row.get('cohort', row.get('source', {}).get('cohort', 'unknown')),
            'rating_band': rating_band(row['mover_elo']), 'phase': row['phase'],
            'time_class': time_class(row.get('time_control')),
            'month': source_month(date), 'source_recovered': row.get('history_available') is True,
            'bot_status': bot_status(row), 'analysis_role': row.get('analysis_role', 'unknown'),
        }
    return records


def matching_fingerprints():
    functions = (matched_human_ids, read_matching_metadata, source_month, bot_status,
                 canonical_fen, rating_band, verify_record, time_class, read_rows)
    return {'functions_sha256': {function.__name__: hashlib.sha256(inspect.getsource(function).encode()).hexdigest()
                                 for function in functions},
            'python_chess_version': chess.__version__}


def selected_ids_digest(identifiers):
    return hashlib.sha256(json.dumps(sorted(identifiers), separators=(',', ':')).encode()).hexdigest()


def verify_matching_manifest(path, input_path, records, identifiers, cells):
    manifest = json.loads(Path(path).read_text())
    if manifest.get('metadata_sha256') != digest(input_path) or manifest.get('metadata_n') != len(records):
        raise ValueError('Frozen matching metadata hash or count does not match the aggregate input')
    if manifest.get('implementation') != matching_fingerprints():
        raise ValueError('Frozen matching implementation fingerprints changed')
    expected_ids = sorted(identifiers)
    expected_sides = dict(Counter(records[identifier]['side'] for identifier in identifiers))
    if (manifest.get('selected_ids') != expected_ids or
            manifest.get('selected_ids_sha256') != selected_ids_digest(expected_ids) or
            manifest.get('selected_n') != len(expected_ids) or manifest.get('per_side') != expected_sides or
            manifest.get('cell_counts') != cells):
        raise ValueError('Frozen matching IDs, counts or cells differ from the predefined metadata-only selection')
    state = manifest.get('screening_state_at_freeze')
    public_state = ({key: state[key] for key in ('complete', 'input_n', 'engine_completed_n',
                                                'policy_completed_n', 'run_manifest_sha256') if key in state}
                    if isinstance(state, dict) else None)
    return {'status': 'verified_frozen_manifest', 'manifest_sha256': digest(path),
            'metadata_sha256': manifest['metadata_sha256'], 'created_at': manifest['created_at'],
            'selected_ids_sha256': manifest['selected_ids_sha256'],
            'implementation': manifest['implementation'],
            'timing_note': manifest.get('timing_note'),
            'screening_state_at_freeze': public_state}


def summarize(input_path, run_dir, output_path, matching_manifest=None):
    input_path, run_dir, output_path = map(Path, (input_path, run_dir, output_path))
    run = json.loads((run_dir/'run.json').read_text())
    shards = json.loads((run_dir/'shards.json').read_text())
    if not run.get('complete') or run.get('engine_completed_n') != run.get('input_n'):
        raise ValueError('Full engine run must be complete before publication')
    if run.get('policy_completed_n') != run.get('input_n'):
        raise ValueError('Full policy run must be complete before publication')
    if (not shards.get('complete') or shards.get('rows') != run.get('input_n') or
            run.get('shards_n') != len(shards.get('shards', [])) or not shards.get('shards')):
        raise ValueError('Shard plan must be complete and match the run counts')
    frozen_path = Path(shards['settings']['source'])
    frozen_hash = digest(frozen_path)
    if (frozen_hash != shards['settings']['source_sha256'] or
            frozen_hash != run['settings']['input_sha256']):
        raise ValueError('Frozen source, shard plan and run hashes do not match')
    indices = [shard['index'] for shard in shards['shards']]
    if indices != list(range(len(indices))):
        raise ValueError('Input shard indices must be unique and contiguous in source order')
    if sum(shard['rows'] for shard in shards['shards']) != run['input_n']:
        raise ValueError('Shard counts do not total the run input count')
    records = read_matching_metadata(input_path)
    if len(records) != run['input_n']:
        raise ValueError('Metadata count differs from the scoring snapshot')
    matched, matching_cells = matched_human_ids(records)
    adjacent_manifest = input_path.parent/'matched_human_selection.json'
    if matching_manifest is not None or adjacent_manifest.exists():
        matching_provenance = verify_matching_manifest(
            matching_manifest if matching_manifest is not None else adjacent_manifest,
            input_path, records, matched, matching_cells)
    else:
        matching_provenance = {'status': 'not_frozen',
                               'note': 'No selection manifest was supplied or found beside the metadata; IDs were computed by the deterministic metadata-only rule during aggregation.'}
    stages = {}
    for entry in run['shards']:
        key = (entry['index'], entry['stage'])
        if key in stages:
            raise ValueError('Duplicate completed stage entry')
        stages[key] = entry
    if set(stages) != {(index, stage) for index in indices for stage in ('policy', 'engine')}:
        raise ValueError('Run must contain exactly one policy and engine stage per input shard')
    seen, screened, chosen_ids = set(), Counter(), set()
    groups = defaultdict(Counter)
    top_depths, root_depths, tail_mass = [], [], []
    search_nodes, fallback_n, searches_n = 0, 0, 0
    fingerprints = []
    common_settings, common_model = {}, None
    frozen_rows = iter(read_rows(frozen_path))
    for shard in shards['shards']:
        source_path = Path(shard['input'])
        if digest(source_path) != shard['input_sha256']:
            raise ValueError('Frozen scoring input was modified')
        source = {}
        for row in read_rows(source_path):
            if row['id'] in source:
                raise ValueError('Duplicate source ID within a shard')
            if row != next(frozen_rows, None):
                raise ValueError('Input shards differ from the frozen source sequence')
            source[row['id']] = row
        if len(source) != shard['rows']:
            raise ValueError('Invalid input shard count')
        for identifier, row in source.items():
            metadata = records.get(identifier)
            if not metadata or row['fen'] != metadata['fen'] or row['played_move'] != metadata['played_move']:
                raise ValueError('Enriched metadata changed a scored board or observed move')
        for stage in ('policy', 'engine'):
            entry = stages[(shard['index'], stage)]
            if entry['rows'] != len(source):
                raise ValueError('Completed stage count differs from its shard')
            path, manifest_path = Path(entry['output']), Path(entry['manifest'])
            if digest(path) != entry['output_sha256'] or digest(manifest_path) != entry['manifest_sha256']:
                raise ValueError('Stage output or manifest hash mismatch')
            manifest = json.loads(manifest_path.read_text())
            if (not manifest.get('complete') or manifest.get('completed_n') != len(source) or
                    manifest.get('input_n') != len(source)):
                raise ValueError('A shard is incomplete')
            if manifest['settings']['input_sha256'] != shard['input_sha256']:
                raise ValueError('Stage input hash mismatch')
            if stage == 'engine':
                if manifest['settings']['policy_sha256'] != stages[(shard['index'], 'policy')]['output_sha256']:
                    raise ValueError('Engine policies differ from the completed policy shard')
            shared = {key: value for key, value in manifest['settings'].items()
                      if key not in ('input', 'policies', 'input_sha256', 'policy_sha256')}
            if stage in common_settings and shared != common_settings[stage]:
                raise ValueError('Scoring settings differ across shards')
            common_settings[stage] = shared
            expected = ({'top_nodes': 'top_nodes', 'root_nodes': 'root_nodes', 'max_human': 'max_human',
                         'coverage': 'coverage'} if stage == 'engine' else
                        {'threads': 'policy_threads', 'batch_size': 'batch_size', 'chunk_size': 'chunk_size'})
            if any(shared.get(key) != run['settings'].get(run_key) for key, run_key in expected.items()):
                raise ValueError('Stage settings differ from the declared run')
            if stage == 'engine' and shared.get('board_context') != 'fen_only':
                raise ValueError('Primary engine condition must be FEN-only')
            if stage == 'policy':
                if shared.get('context') != 'fen_only' or shared.get('ratings') != [1400, 1700, 2000, 2300]:
                    raise ValueError('Primary policy condition must contain the four FEN-only ratings')
                if common_model is not None and manifest.get('model') != common_model:
                    raise ValueError('Policy checkpoint or model settings differ across shards')
                common_model = manifest['model']
            code = run['settings'].get('code_sha256', {})
            expected_code = {'scorer_sha256': f'mining_v3_{stage}.py', 'io_sha256': 'mining_v3_io.py',
                             'adapter_sha256' if stage == 'policy' else 'v2_helpers_sha256': f'mining_v2_{stage}.py'}
            if any(shared.get(key) != code.get(name) for key, name in expected_code.items()):
                raise ValueError('Stage implementation hashes differ from the declared run')
            identities = set()
            for result in read_rows(path):
                identifier = result['id']
                if identifier in identities or identifier not in source or result['fen'] != source[identifier]['fen']:
                    raise ValueError('Stage identities do not match input')
                identities.add(identifier)
                if stage == 'policy':
                    continue
                if identifier in seen:
                    raise ValueError('Duplicate engine row across shards')
                seen.add(identifier)
                if result.get('verified') or result.get('mode') != 'fixed_node_screen':
                    raise ValueError('Screen summary must not mix deep verification or other regimes')
                row = records[identifier]
                if result.get('side_to_move') != row['side'] or result.get('board_context') != 'fen_only':
                    raise ValueError('Engine side or board context does not match the primary comparison')
                chosen = selected(result, 'fen_only')
                if chosen:
                    chosen_ids.add(identifier)
                group_keys = [('all', row['side']), (row['bot_status'], row['side']),
                              ('cohort/'+row['cohort'], row['side'])]
                if identifier in matched:
                    group_keys.append(('matched_human', row['side']))
                for key in group_keys:
                    counter = groups[key]
                    counter['n'] += 1
                    counter['screen_candidates_n'] += chosen
                    counter['competitive_numeric_n'] += competitive(result)
                    counter['source_move_matches_engine_leader_n'] += bool(result['observed_played_is_top_engine_move'])
                screened['exhaustive_roots_n'] += result['exhaustive']
                screened['mate_in_scored_roots_n'] += result['has_mate']
                screened['candidates_n'] += chosen
                top_depths.extend(r['depth'] for r in result['top'])
                root_depths.extend(r['depth'] for r in result['scores'].values())
                for search in [*result['top'], *result['scores'].values()]:
                    searches_n += 1
                    fallback_n += bool(used_previous_exact_iteration(search))
                search_nodes += result['search_nodes_total']
                value = result['metrics']['maia3/fen_only/2000']['20']
                if value.get('unscored_mass') is not None:
                    tail_mass.append(value['unscored_mass'])
            if identities != set(source):
                raise ValueError('Stage has missing rows')
            fingerprints.append({'shard': shard['index'], 'stage': stage,
                                 'output_sha256': entry['output_sha256'],
                                 'manifest_sha256': entry['manifest_sha256']})
    if seen != set(records):
        raise ValueError('Full scoring coverage does not match metadata')
    if next(frozen_rows, None) is not None:
        raise ValueError('Frozen source contains rows missing from the shard plan')
    engine_entry = stages[(0, 'engine')]
    policy_entry = stages[(0, 'policy')]
    engine_settings = json.loads(Path(engine_entry['manifest']).read_text())['settings']
    policy_manifest = json.loads(Path(policy_entry['manifest']).read_text())
    public_engine_keys = ('engine_sha256', 'scorer_sha256', 'v2_helpers_sha256', 'io_sha256',
                          'top_nodes', 'root_nodes', 'max_human', 'coverage', 'board_context',
                          'engine_threads', 'hash_mb', 'clear_hash_each_search', 'node_budget_interpretation')
    public_settings = {key: engine_settings[key] for key in public_engine_keys if key in engine_settings}
    public_model_keys = ('model', 'source_url', 'source_commit', 'source_files_sha256', 'weights_repo',
                         'weights_revision', 'weights_filename', 'weights_sha256', 'device', 'threads',
                         'batch_size', 'torch_version', 'precision', 'amp', 'history_length_including_current',
                         'history_order', 'short_history_padding', 'fen_only_padding', 'include_time_info',
                         'clk_ponder', 'rating_conditioning', 'policy', 'top_k', 'top_p')
    result = {
        'schema_version': 3, 'complete': True, 'created_at': datetime.now(timezone.utc).isoformat(),
        'screened_n': len(seen), 'deeply_verified_n': 0,
        'status': 'Completed first-pass screen; candidates are not validated puzzles or human learning results.',
        'counts': dict(screened),
        'candidate_unique_canonical_states': len({canonical_fen(records[k]['fen']) for k in chosen_ids}),
        'groups': [{'group': g, 'side': s, **dict(c)} for (g, s), c in sorted(groups.items())],
        'matched_human': {'n': len(matched), 'per_side': len(matched)//2,
                          'cells': matching_cells,
                          'selection_provenance': matching_provenance,
                          'selection': 'Deterministic metadata-only selection; unique canonical states; equal colours within cohort, rating band, phase, time class and source month; only recovered games without BOT tags. Freeze timing and screening progress are recorded in selection_provenance.',
                          'rating_bands': ['under_1800', '1800_1999', '2000_2199', '2200_2399',
                                           '2400_2599', '2600_2799', '2800_plus'],
                          'note': 'Descriptive archive comparison, not a fresh held-out or population-representative sample.'},
        'quality': {'top_search_depth': quality(top_depths), 'root_search_depth': quality(root_depths),
                    'unscored_mass_at_2000': quality(tail_mass), 'search_nodes_total': search_nodes,
                    'search_records_n': searches_n, 'previous_exact_iteration_used_n': fallback_n},
        'engine_settings': public_settings,
        'policy_model': {key: policy_manifest['model'][key] for key in public_model_keys if key in policy_manifest['model']},
        'definition': {'ratings': [1700, 2000], 'evaluation_range_cp': [-200, 200],
                       'acceptable_tolerance_cp': 20, 'max_good_mass_upper_each': .1,
                       'min_capped_regret_lower_each_cp': 50, 'regret_cap_cp': 300},
        'input_sha256': {'metadata': digest(input_path), 'frozen_scoring_snapshot': frozen_hash,
                         'run': digest(run_dir/'run.json'),
                         'shards': digest(run_dir/'shards.json')}, 'output_hashes': fingerprints,
        'limitations': [
            'Fixed-node searches are shallow and uneven in achieved depth; finite-search bounds are not proofs of chess values.',
            'Historical and bot-tagged observations remain in the complete accounting; human-game comparisons exclude bot-tagged and unknown-source games.',
            'Existing observations have informed development. Reassigned source-game hashes do not create fresh test data.',
            'No history or clock inputs enter the common primary policy/engine condition.',
            'Maia probabilities are model predictions, not calibrated independent puzzle responses.',
            'Acceptable-move and regret gates define a provisional shortlist. Stable exhaustive analysis and chess review are still required.',
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=ROOT/'data/mining_v3/positions.jsonl')
    ap.add_argument('--run-dir', type=Path, default=ROOT/'results/mining_v3/full')
    ap.add_argument('--output', type=Path, default=ROOT/'results/mining_v3_summary.json')
    ap.add_argument('--matching-manifest', type=Path,
                    help='Verify this frozen selection; by default use matched_human_selection.json beside the input if present')
    args = ap.parse_args()
    result = summarize(args.input, args.run_dir, args.output, args.matching_manifest)
    print(json.dumps({k: result[k] for k in ('screened_n','counts','matched_human')}, indent=2))


if __name__ == '__main__':
    main()
