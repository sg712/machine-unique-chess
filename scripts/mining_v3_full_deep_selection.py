"""Freeze every distinct v3 screen candidate, preserving the initial 200 inputs.

This census has no colour quota, game cap or provenance exclusion. Source strata
remain explicit, including all observations underlying duplicate board states.
Only first-pass screens and the frozen initial selection are read, never deep
outcomes. Original source records and four FEN-only policy lines stay unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import inspect
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mining_v2_engine import board_for, validated_policies
from scripts.mining_v2_sampling import canonical_fen, public_exclusions
from scripts.mining_v2_summary import selected as is_screen_candidate
from scripts.mining_v3_dataset import verify_record
from scripts.mining_v3_deep_selection import checked_sources
from scripts.mining_v3_io import digest, rows, write_manifest

SEED = 20260910
EXPECTED_N = 4345
INITIAL_N = 200
ROLES = {'prior_development', 'pilot_train', 'pilot_validation', 'pilot_test',
         'new_train', 'new_validation', 'new_test', 'public_exposed'}
METHOD = (
    'Census of every canonical-unique candidate from the unchanged v3 FEN-only screen gate. '
    'The initial 200 frozen records and policy lines retain precedence for their states. '
    'Other states prefer an observation with recovered history, no BOT tag and no known '
    'public exposure; ties and other observations use a declared seeded SHA-256 ID rank. '
    'Every originating candidate observation is retained privately. No colour quota, '
    'per-game cap or source-stratum exclusion applies. Export is in original source order. '
    'No deep outcome, score magnitude, legal-move count or search complexity chooses a representative.'
)


def classify_strata(record):
    bot, history, public = (record.get(k) for k in ('contains_bot', 'history_available', 'known_public_game'))
    role = record.get('analysis_role')
    return {
        'bot_status': 'no_bot' if bot is False else 'bot_tagged' if bot is True else 'unknown',
        'history_status': 'recovered' if history is True else 'unavailable' if history is False else 'unknown',
        'public_exposure': ('known_public' if public is True or role == 'public_exposed' else
                            'not_known_public' if public is False else 'unknown'),
        'analysis_role': role if role in ROLES else 'unknown',
    }


def representative_rank(record, public_games, seed=SEED):
    strata = classify_strata(record)
    preferred = (strata['bot_status'] == 'no_bot' and strata['history_status'] == 'recovered'
                 and strata['public_exposure'] == 'not_known_public' and record['game_id'] not in public_games)
    rank = hashlib.sha256(f'muc-v3-full-deep:{seed}:representative:{record["id"]}'.encode()).hexdigest()
    return (not preferred, rank, record['id'])


def choose_census(candidates, initial_records, public_games=(), seed=SEED):
    """Keep all states; only duplicate representatives are ranked."""
    groups, seen = defaultdict(list), set()
    for record in candidates:
        if record['id'] in seen:
            raise ValueError('Duplicate candidate identity')
        seen.add(record['id'])
        verify_record(record)
        groups[canonical_fen(record['fen'])].append(record)
    initial_by_state = {}
    for record in initial_records:
        canon = canonical_fen(record['fen'])
        if canon in initial_by_state:
            raise ValueError('Initial selection is not canonical unique')
        if record['id'] not in seen or not any(record == origin for origin in groups.get(canon, [])):
            raise ValueError('Initial selection no longer matches a screen candidate')
        initial_by_state[canon] = record
    chosen, origins = [], {}
    for canon, members in groups.items():
        representative = initial_by_state.get(canon)
        if representative is None:
            representative = min(members, key=lambda r: representative_rank(r, public_games, seed))
        chosen.append(representative)
        origins[representative['id']] = sorted(members, key=lambda r: r['id'])
    return chosen, origins


def check_census_policy(record, policy):
    """Validate FEN-only inputs across every explicitly labelled source stratum."""
    board = verify_record(record)
    if record.get('history_available') is True and board_for(record).fen() != board.fen():
        raise ValueError('Recovered history does not reproduce selected board')
    legal = {move.uci() for move in board.legal_moves}
    if not legal or board.is_game_over(claim_draw=False):
        raise ValueError('Selected board is terminal or has no legal moves')
    if (policy.get('input_condition') != 'fen_only' or
            policy.get('maia3', {}).get('history') != {} or
            set(policy.get('maia3', {}).get('fen_only', {})) != {'1400', '1700', '2000', '2300'}):
        raise ValueError('Policy must preserve the four original FEN-only Maia3 conditions')
    maps = validated_policies(record, policy, legal)
    if set(maps) != {f'maia3/fen_only/{rating}' for rating in (1400, 1700, 2000, 2300)}:
        raise ValueError('Unexpected model or policy condition')
    return len(legal)


def checked_initial_selection(directory, input_hashes, expected_n=INITIAL_N):
    directory = Path(directory)
    manifest_path = directory / 'selection_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    position_path, policy_path = directory / 'positions.jsonl', directory / 'policies.jsonl'
    if (manifest.get('complete') is not True or manifest.get('selected_n') != expected_n or
            manifest.get('input_hashes') != input_hashes):
        raise ValueError('Initial selection is incomplete or refers to different original sources')
    for name, path in (('positions', position_path), ('policies', policy_path)):
        if digest(path) != manifest.get(f'{name}_sha256') or digest(path) != manifest.get('outputs', {}).get(f'{name}_sha256'):
            raise ValueError('Initial selection export hash changed')
    protocol_path = directory / 'selection_protocol.json'
    if (digest(protocol_path) != manifest.get('selection_protocol_sha256') or
            digest(ROOT / 'scripts/mining_v3_deep_selection.py') != manifest.get('selection_script_sha256')):
        raise ValueError('Initial selection protocol or script hash changed')
    initial, raw_positions, raw_policies = [], {}, {}
    with position_path.open('rb') as positions, policy_path.open('rb') as policies:
        for position_line, policy_line in itertools.zip_longest(positions, policies):
            if position_line is None or policy_line is None:
                raise ValueError('Initial selection export lengths differ')
            record, policy = json.loads(position_line), json.loads(policy_line)
            identifier = record['id']
            if identifier in raw_positions or policy.get('id') != identifier:
                raise ValueError('Initial selection identities do not align')
            count = check_census_policy(record, policy)
            if (manifest['selected_legal_roots'].get(identifier) != count or
                    manifest['original_policy_line_sha256'].get(identifier) != hashlib.sha256(policy_line).hexdigest()):
                raise ValueError('Initial selection policy or legal-root evidence changed')
            initial.append(record)
            raw_positions[identifier], raw_policies[identifier] = position_line, policy_line
    if len(initial) != expected_n or [r['id'] for r in initial] != manifest.get('selected_ids'):
        raise ValueError('Initial selection count or ordered identities changed')
    return manifest, initial, raw_positions, raw_policies


def origin_metadata(record, public_games):
    source = record.get('source', {})
    return {'id': record['id'], 'game_id': record['game_id'],
            'legacy_game_id': record.get('legacy_game_id'), 'side_to_move': record['side_to_move'],
            'strata': classify_strata(record), 'public_game_detected': record['game_id'] in public_games,
            'split': record.get('split'), 'source_split': record.get('source_split'),
            'cohort': record.get('cohort'), 'rating_bin': record.get('rating_bin'), 'phase': record.get('phase'),
            'prior_development_game': record.get('prior_development_game'),
            'history_recovery': record.get('history_recovery'), 'source': source}


def state_provenance(origins):
    strata = [origin['strata'] for origin in origins]
    return {'origin_observations_n': len(origins), 'origin_source_games_n': len({o['game_id'] for o in origins}),
            'any_bot_tagged': any(s['bot_status'] == 'bot_tagged' for s in strata),
            'any_unknown_bot_status': any(s['bot_status'] == 'unknown' for s in strata),
            'any_known_public': any(o['public_game_detected'] or o['strata']['public_exposure'] == 'known_public' for o in origins),
            'any_unknown_public_exposure': any(s['public_exposure'] == 'unknown' for s in strata),
            'any_unavailable_history': any(s['history_status'] == 'unavailable' for s in strata),
            'any_unknown_history': any(s['history_status'] == 'unknown' for s in strata),
            'all_origins_recovered_no_bot_not_known_public': all(
                s['bot_status'] == 'no_bot' and s['history_status'] == 'recovered' and
                s['public_exposure'] == 'not_known_public' and not o['public_game_detected']
                for s, o in zip(strata, origins)),
            'analysis_roles': sorted({s['analysis_role'] for s in strata})}


def aggregate_strata(strata):
    return {key: dict(Counter(row[key] for row in strata))
            for key in ('bot_status', 'history_status', 'public_exposure', 'analysis_role')}


def public_aggregate(manifest):
    """Explicit nested allowlist; raw metadata, origins, IDs and paths stay private."""
    public = {key: manifest[key] for key in ('schema_version', 'complete', 'created_at', 'seed',
        'selected_n', 'already_deep200_n', 'new_n', 'method', 'counts', 'source_strata',
        'any_origin_provenance_counts', 'validation', 'limitations')}
    public['legal_roots'] = {key: manifest['legal_roots'][key] for key in (
        'total', 'remaining', 'already_deep200', 'by_side', 'remaining_by_side', 'minimum', 'maximum')}
    return public


def select_full_census(metadata_path, run_dir, initial_dir, output_dir, public_output,
                       expected_n=EXPECTED_N, initial_n=INITIAL_N, seed=SEED):
    metadata_path, run_dir, initial_dir, output_dir, public_output = map(
        Path, (metadata_path, run_dir, initial_dir, output_dir, public_output))
    output_dir.mkdir(parents=True, exist_ok=True)
    positions_path, policies_path, manifest_path = (output_dir / name for name in
        ('positions.jsonl', 'policies.jsonl', 'selection_manifest.json'))
    if any(path.exists() for path in (positions_path, policies_path, manifest_path, public_output)):
        raise ValueError('Frozen census output already exists; it will not be overwritten')
    run, frozen, shards, stages, hashes = checked_sources(metadata_path, run_dir)
    initial_manifest, initial, initial_positions, initial_policies = checked_initial_selection(initial_dir, hashes, initial_n)
    fens, public_games, public_inputs = public_exclusions(ROOT)
    for record in rows(metadata_path):
        if (record.get('known_public_game') or record.get('analysis_role') == 'public_exposed' or
                record.get('legacy_game_id') in public_games or canonical_fen(record['fen']) in fens):
            public_games.add(record['game_id'])
    old_hashes = {name: digest(initial_dir / name) for name in (
        'selection_manifest.json', 'selection_protocol.json', 'positions.jsonl', 'policies.jsonl')}
    declaration = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'seed': seed, 'expected_n': expected_n, 'initial_n': initial_n, 'method': METHOD,
        'input_hashes': hashes, 'initial_selection_hashes': old_hashes, 'public_exclusion_sources': public_inputs,
        'selection_script_sha256': digest(__file__),
        'selection_function_sha256': hashlib.sha256(inspect.getsource(choose_census).encode()).hexdigest(),
        'screen_gate_function_sha256': hashlib.sha256(inspect.getsource(is_screen_candidate).encode()).hexdigest(),
        'timing': 'Declared before this census representative selection; no deep result is read.'}
    declaration_path = output_dir / 'selection_protocol.json'
    if declaration_path.exists():
        previous = json.loads(declaration_path.read_text())
        if {k: v for k, v in previous.items() if k != 'created_at'} != {k: v for k, v in declaration.items() if k != 'created_at'}:
            raise ValueError('A different frozen census declaration exists')
    else:
        write_manifest(declaration_path, declaration)
    candidates, seen = [], set()
    frozen_rows = iter(rows(frozen))
    for shard in shards:
        screened = {}
        for result in rows(stages[(shard['index'], 'engine')]['output']):
            if result['id'] in screened:
                raise ValueError('Duplicate screen identity within a shard')
            if result.get('mode') != 'fixed_node_screen' or result.get('verified') or result.get('board_context') != 'fen_only':
                raise ValueError('Input contains a different search regime or deep outcomes')
            screened[result['id']] = {'fen': result['fen'], 'side': result.get('side_to_move'),
                                       'candidate': is_screen_candidate(result, 'fen_only')}
        count = 0
        for source in rows(shard['input']):
            if source != next(frozen_rows, None):
                raise ValueError('Source shards do not exactly follow the frozen source sequence')
            result = screened.pop(source['id'], None)
            if (source['id'] in seen or result is None or result['fen'] != source['fen'] or
                    result['side'] != source['side_to_move']):
                raise ValueError('Screen identities do not exactly match their source shard')
            seen.add(source['id'])
            count += 1
            if result['candidate']:
                candidates.append(source)
        if count != shard['rows'] or screened:
            raise ValueError('Screen shard count differs from its manifest')
    if next(frozen_rows, None) is not None or len(seen) != run['input_n']:
        raise ValueError('Frozen source census is incomplete')
    chosen, groups = choose_census(candidates, initial, public_games, seed)
    if len(chosen) != expected_n:
        raise ValueError(f'Expected {expected_n} canonical candidate states, found {len(chosen)}')
    by_id = {r['id']: r for r in chosen}
    ordered_ids, legal_counts, policy_hashes, position_hashes = [], {}, {}, {}
    temp_positions, temp_policies = positions_path.with_suffix('.jsonl.tmp'), policies_path.with_suffix('.jsonl.tmp')
    try:
        with temp_positions.open('wb') as position_out, temp_policies.open('wb') as policy_out:
            for shard in shards:
                entry = stages[(shard['index'], 'policy')]
                if digest(shard['input']) != shard['input_sha256'] or digest(entry['output']) != entry['output_sha256']:
                    raise ValueError('Original input or policy shard changed during selection')
                count = 0
                with Path(shard['input']).open('rb') as source_file, Path(entry['output']).open('rb') as policy_file:
                    for source_line, policy_line in itertools.zip_longest(source_file, policy_file):
                        if source_line is None or policy_line is None:
                            raise ValueError('Policy and source lengths differ')
                        source, policy = json.loads(source_line), json.loads(policy_line)
                        if policy.get('id') != source['id'] or policy.get('fen') != source['fen']:
                            raise ValueError('Original policies are not in source order')
                        count += 1
                        identifier = source['id']
                        if identifier not in by_id:
                            continue
                        if source != by_id[identifier]:
                            raise ValueError('Selected metadata changed during export')
                        if identifier in initial_positions and (source_line != initial_positions[identifier] or policy_line != initial_policies[identifier]):
                            raise ValueError('Initial 200 source or policy bytes differ from original shards')
                        legal_counts[identifier] = check_census_policy(source, policy)
                        ordered_ids.append(identifier)
                        policy_hashes[identifier] = hashlib.sha256(policy_line).hexdigest()
                        position_hashes[identifier] = hashlib.sha256(source_line).hexdigest()
                        position_out.write(source_line)
                        policy_out.write(policy_line)
                if count != shard['rows']:
                    raise ValueError('Policy row count differs from its completed shard')
        if len(ordered_ids) != expected_n or set(ordered_ids) != set(by_id):
            raise ValueError('Selected census was not exported exactly once')
        if sum(legal_counts[i] for i in initial_positions) != initial_manifest['legal_roots']['total']:
            raise ValueError('Initial 200 legal-root total changed')
        for name, expected_hash in old_hashes.items():
            if digest(initial_dir / name) != expected_hash:
                raise ValueError('Initial frozen selection changed during export')
        temp_positions.replace(positions_path)
        temp_policies.replace(policies_path)
    finally:
        temp_positions.unlink(missing_ok=True)
        temp_policies.unlink(missing_ok=True)
    strata = {i: classify_strata(by_id[i]) for i in ordered_ids}
    origins = {i: [origin_metadata(r, public_games) for r in groups[i]] for i in ordered_ids}
    provenance = {i: state_provenance(origins[i]) for i in ordered_ids}
    new_ids = [i for i in ordered_ids if i not in initial_positions]
    boolean_flags = [key for key, value in next(iter(provenance.values())).items() if isinstance(value, bool)]
    manifest = {'schema_version': 1, 'complete': True, 'created_at': datetime.now(timezone.utc).isoformat(),
        'seed': seed, 'method': METHOD, 'selected_n': len(chosen), 'already_deep200_n': len(initial), 'new_n': len(new_ids),
        'positions_sha256': digest(positions_path), 'policies_sha256': digest(policies_path),
        'old200_selection_manifest_sha256': old_hashes['selection_manifest.json'],
        'initial_selection_hashes': old_hashes, 'input_hashes': hashes,
        'selection_protocol_sha256': digest(declaration_path), 'selection_script_sha256': digest(__file__),
        'public_exclusion_sources': public_inputs, 'selected_ids': ordered_ids,
        'already_deep200_ids': [r['id'] for r in initial], 'strata_by_id': strata,
        'canonical_origins_by_id': origins, 'state_provenance_by_id': provenance,
        'original_policy_line_sha256': policy_hashes, 'original_position_line_sha256': position_hashes,
        'counts': {'screened_n': len(seen), 'screen_candidates_n': len(candidates),
            'screen_candidates_by_side': dict(Counter(r['side_to_move'] for r in candidates)),
            'selected_n': len(chosen), 'selected_by_side': dict(Counter(r['side_to_move'] for r in chosen)),
            'new_by_side': dict(Counter(by_id[i]['side_to_move'] for i in new_ids)),
            'canonical_duplicate_rows_removed_n': len(candidates) - len(chosen),
            'selected_source_games_n': len({r['game_id'] for r in chosen}),
            'origin_source_games_n': len({r['game_id'] for r in candidates}),
            'maximum_selected_positions_per_game': max(Counter(r['game_id'] for r in chosen).values()),
            'source_stratum_exclusions_n': 0},
        'source_strata': {'representatives': aggregate_strata(list(strata.values())),
            'candidate_observations': aggregate_strata([classify_strata(r) for r in candidates]),
            'new_representatives': aggregate_strata([strata[i] for i in new_ids]),
            'representatives_by_side': {side: aggregate_strata([strata[i] for i in ordered_ids if by_id[i]['side_to_move'] == side])
                                        for side in ('white', 'black')}},
        'any_origin_provenance_counts': {flag: sum(p[flag] for p in provenance.values()) for flag in boolean_flags},
        'legal_roots': {'total': sum(legal_counts.values()), 'remaining': sum(legal_counts[i] for i in new_ids),
            'already_deep200': sum(legal_counts[i] for i in initial_positions), 'by_id': legal_counts,
            'by_side': {side: sum(legal_counts[i] for i in ordered_ids if by_id[i]['side_to_move'] == side) for side in ('white', 'black')},
            'remaining_by_side': {side: sum(legal_counts[i] for i in new_ids if by_id[i]['side_to_move'] == side) for side in ('white', 'black')},
            'minimum': min(legal_counts.values()), 'maximum': max(legal_counts.values())},
        'validation': {'screen_gate_unchanged': True, 'source_hashes_verified': True, 'old200_hashes_verified': True,
            'old200_position_and_policy_bytes_preserved': True, 'source_order_aligned': True,
            'unique_canonical_states': len(chosen), 'all_candidate_origins_recorded': True,
            'all_boards_valid_and_nonterminal': True, 'available_history_replayed': True,
            'original_policies_copied_verbatim': True, 'all_four_policies_legal_complete': True,
            'original_analysis_role_and_split_preserved': True, 'deep_outcomes_read': False},
        'limitations': ['Repeated positions are one state with several source observations, not independent rows.',
            'Repeated games remain correlated; this census does not impose a per-game cap.',
            'BOT-tagged, public-exposed and unresolved sources remain included and separately labelled.',
            'Any-origin exposure is reported separately from representative provenance.',
            'Prior-development and public-exposed games do not become fresh held-out data.',
            'Canonical state matching uses the legal-en-passant first four FEN fields; exact representative full FEN and policies are preserved.',
            'A successful engine check does not establish human difficulty, teachability or trainer readiness.']}
    write_manifest(manifest_path, manifest)
    public_output.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(public_output, public_aggregate(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'data/mining_v3/positions.jsonl')
    parser.add_argument('--run-dir', type=Path, default=ROOT / 'results/mining_v3/full')
    parser.add_argument('--initial-dir', type=Path, default=ROOT / 'data/mining_v3/deep200')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/mining_v3/deep_all')
    parser.add_argument('--public-output', type=Path, default=ROOT / 'results/mining_v3_full_deep_selection.json')
    args = parser.parse_args()
    result = select_full_census(args.input, args.run_dir, args.initial_dir, args.output_dir, args.public_output)
    print(json.dumps({'counts': result['counts'], 'legal_roots': public_aggregate(result)['legal_roots'],
        'positions_sha256': result['positions_sha256'], 'policies_sha256': result['policies_sha256']}, indent=2))


if __name__ == '__main__':
    main()
