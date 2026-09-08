"""Freeze a colour-balanced, game-disjoint random subset for initial deep checks.

Selection uses the frozen v3 screen gate, source provenance, canonical states,
and a declared hash ranking. Deep outcomes and search complexity are never read.
Private rows retain their original metadata and policy bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import inspect
import itertools
import json
from pathlib import Path
import sys

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mining_v2_engine import board_for, validated_policies
from scripts.mining_v2_sampling import canonical_fen, public_exclusions
from scripts.mining_v2_summary import selected as is_screen_candidate
from scripts.mining_v3_dataset import verify_record
from scripts.mining_v3_io import digest, rows, write_manifest

SEED = 20260909
PER_SIDE = 100
METHOD = ("Screen candidates from recovered games without BOT tags, excluding known public-exposed source games. "
          "Canonical duplicate states receive one representative chosen by a seeded ID hash. Unique states are "
          "ranked by a separate SHA-256 hash of the declared seed and canonical FEN; traverse that ranking, "
          "accepting at most one position per actual source game globally and exactly 100 per colour. "
          "No depth, legal-move count, evaluation magnitude or deep outcome ranks candidates. Export in original "
          "source order. This constrained archive sample is for initial feasibility and survival assessment; "
          "it is not a uniform sample of all screen rows or a fresh held-out evaluation.")


def hash_rank(kind, value, seed=SEED):
    return hashlib.sha256(f"muc-v3-deep:{seed}:{kind}:{value}".encode()).hexdigest()


def choose_candidates(candidates, per_side=PER_SIDE, seed=SEED):
    """Input order, score magnitude, and search complexity cannot affect ranking."""
    representatives = {}
    observed_ids = set()
    for row in candidates:
        if row['id'] in observed_ids:
            raise ValueError('Duplicate candidate ID')
        observed_ids.add(row['id'])
        canon = canonical_fen(row['fen'])
        prior = representatives.get(canon)
        if prior is None or (hash_rank('representative', row['id'], seed), row['id']) < (
                hash_rank('representative', prior['id'], seed), prior['id']):
            representatives[canon] = row
    counts, rejected = Counter(), Counter()
    games, chosen = set(), []
    ranked = sorted(representatives.items(), key=lambda item: (hash_rank('state', item[0], seed), item[0]))
    for canon, row in ranked:
        side = 'white' if chess.Board(row['fen']).turn else 'black'
        if row['side_to_move'] != side:
            raise ValueError('Candidate side differs from its board')
        if counts[side] >= per_side:
            rejected['colour_quota_full'] += 1
        elif row['game_id'] in games:
            rejected['global_game_cap'] += 1
        else:
            chosen.append(row)
            games.add(row['game_id'])
            counts[side] += 1
    if counts != Counter(white=per_side, black=per_side):
        raise ValueError(f'Cannot fill both colour quotas with the strict global one-game cap: {dict(counts)}; no fallback selected')
    return chosen, {'eligible_rows_n': len(candidates),
                    'eligible_unique_states_n': len(representatives),
                    'canonical_duplicate_rows_removed_n': len(candidates) - len(representatives),
                    'eligible_unique_states_by_side': dict(Counter(r['side_to_move'] for r in representatives.values())),
                    'eligible_games_n': len({r['game_id'] for r in candidates}),
                    'eligible_games_by_side': {s: len({r['game_id'] for r in candidates if r['side_to_move'] == s})
                                               for s in ('white', 'black')},
                    'rank_traversal_exclusions': dict(rejected)}


def check_selected_policy(record, policy):
    board = verify_record(record)
    if (record.get('history_available') is not True or record.get('contains_bot') is not False or
            record.get('known_public_game') or record.get('analysis_role') == 'public_exposed'):
        raise ValueError('Selected observation has invalid eligibility metadata')
    # Replay real history, even though the primary saved policy remains FEN-only.
    replayed = board_for(record)
    if replayed.fen() != board.fen():
        raise ValueError('Recovered history does not reproduce selected board')
    legal = {move.uci() for move in board.legal_moves}
    if not legal:
        raise ValueError('Selected board has no legal moves')
    if (policy.get('input_condition') != 'fen_only' or
            policy.get('maia3', {}).get('history') != {} or
            set(policy.get('maia3', {}).get('fen_only', {})) != {'1400', '1700', '2000', '2300'}):
        raise ValueError('Policy must preserve the four original FEN-only Maia3 conditions')
    maps = validated_policies(record, policy, legal)
    if set(maps) != {f'maia3/fen_only/{r}' for r in (1400, 1700, 2000, 2300)}:
        raise ValueError('Unexpected model or policy condition')
    return len(legal)


def checked_sources(metadata_path, run_dir):
    run_path, plan_path = run_dir / 'run.json', run_dir / 'shards.json'
    run, plan = json.loads(run_path.read_text()), json.loads(plan_path.read_text())
    n = run.get('input_n')
    if (not run.get('complete') or not plan.get('complete') or
            run.get('engine_completed_n') != n or run.get('policy_completed_n') != n or plan.get('rows') != n):
        raise ValueError('The original policy and screen census must be complete')
    source = Path(plan['settings']['source'])
    source_hash = digest(source)
    if source_hash != digest(metadata_path) or source_hash != plan['settings']['source_sha256'] or source_hash != run['settings']['input_sha256']:
        raise ValueError('Metadata and frozen source hashes disagree')
    shards = plan['shards']
    if [s['index'] for s in shards] != list(range(len(shards))) or sum(s['rows'] for s in shards) != n:
        raise ValueError('Invalid source shard sequence or count')
    stages = {(s['index'], s['stage']): s for s in run['shards']}
    if len(stages) != len(run['shards']) or set(stages) != {(s['index'], stage) for s in shards for stage in ('engine', 'policy')}:
        raise ValueError('Completed stage inventory does not match source shards')
    fingerprints = []
    for shard in shards:
        if digest(shard['input']) != shard['input_sha256']:
            raise ValueError('Source shard hash changed')
        for stage in ('engine', 'policy'):
            entry = stages[(shard['index'], stage)]
            if (entry['rows'] != shard['rows'] or digest(entry['output']) != entry['output_sha256'] or
                    digest(entry['manifest']) != entry['manifest_sha256']):
                raise ValueError('Completed stage hash or count changed')
            manifest = json.loads(Path(entry['manifest']).read_text())
            if (not manifest.get('complete') or manifest.get('input_n') != shard['rows'] or
                    manifest.get('completed_n') != shard['rows'] or manifest['settings']['input_sha256'] != shard['input_sha256']):
                raise ValueError('Stage is incomplete or refers to another source')
            if stage == 'engine':
                if (manifest['settings'].get('board_context') != 'fen_only' or
                        manifest['settings']['policy_sha256'] != stages[(shard['index'], 'policy')]['output_sha256']):
                    raise ValueError('Screen is not based on the original FEN-only policies')
            elif manifest['settings'].get('context') != 'fen_only' or manifest['settings'].get('ratings') != [1400, 1700, 2000, 2300]:
                raise ValueError('Saved policies have unexpected conditions')
            fingerprints.append({'shard': shard['index'], 'stage': stage,
                'output': entry['output'], 'output_sha256': entry['output_sha256'],
                'manifest': entry['manifest'], 'manifest_sha256': entry['manifest_sha256']})
    return run, source, shards, stages, {'metadata_sha256': source_hash,
        'run_sha256': digest(run_path), 'shard_plan_sha256': digest(plan_path),
        'source_shards': [{'index': s['index'], 'path': s['input'], 'sha256': s['input_sha256']} for s in shards],
        'completed_stages': fingerprints}


def public_aggregate(manifest):
    """Explicit allowlist: no positions, game IDs, moves, or filesystem paths."""
    return {key: manifest[key] for key in (
        'schema_version', 'complete', 'created_at', 'seed', 'per_side_target', 'method',
        'counts', 'eligibility', 'canonical_selection', 'selection_counts',
        'legal_roots', 'validation', 'limitations')}


def select_batch(metadata_path, run_dir, output_dir, public_output, per_side=PER_SIDE, seed=SEED):
    metadata_path, run_dir, output_dir, public_output = map(Path, (metadata_path, run_dir, output_dir, public_output))
    if per_side != 100:
        raise ValueError('This preregistered batch requires exactly 100 positions of each colour')
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [output_dir / name for name in ('positions.jsonl', 'policies.jsonl', 'selection_manifest.json')]
    if any(path.exists() for path in outputs) or public_output.exists():
        raise ValueError('Frozen selection output already exists; it will not be overwritten')
    run, frozen, shards, stages, hashes = checked_sources(metadata_path, run_dir)
    fens, public_games, public_inputs = public_exclusions(ROOT)
    # Establish game exposure from all metadata, not merely the sampled position.
    for record in rows(metadata_path):
        if (record.get('known_public_game') or record.get('analysis_role') == 'public_exposed' or
                record.get('legacy_game_id') in public_games or canonical_fen(record['fen']) in fens):
            public_games.add(record['game_id'])
    declaration = {'created_at': datetime.now(timezone.utc).isoformat(), 'seed': seed,
        'per_side_target': per_side, 'method': METHOD, 'input_hashes': hashes,
        'public_exclusion_sources': public_inputs, 'selection_script_sha256': digest(__file__),
        'selection_function_sha256': hashlib.sha256(inspect.getsource(choose_candidates).encode()).hexdigest(),
        'screen_gate_function_sha256': hashlib.sha256(inspect.getsource(is_screen_candidate).encode()).hexdigest(),
        'timing': 'Written before candidate hash selection and before any deep result is read or produced for this batch.'}
    declaration_path = output_dir / 'selection_protocol.json'
    if declaration_path.exists():
        previous = json.loads(declaration_path.read_text())
        if {k: v for k, v in previous.items() if k != 'created_at'} != {k: v for k, v in declaration.items() if k != 'created_at'}:
            raise ValueError('A different frozen selection declaration exists')
        declaration = previous
    else:
        write_manifest(declaration_path, declaration)
    candidates, excluded, seen = [], Counter(), set()
    candidate_sides, candidate_roles = Counter(), Counter()
    frozen_rows = iter(rows(frozen))
    for shard in shards:
        engine = stages[(shard['index'], 'engine')]
        screened = {}
        for result in rows(engine['output']):
            if result['id'] in screened:
                raise ValueError('Duplicate screen identity within a shard')
            if result.get('mode') != 'fixed_node_screen' or result.get('verified') or result.get('board_context') != 'fen_only':
                raise ValueError('Input contains a different search regime or deep outcomes')
            screened[result['id']] = {'fen': result['fen'], 'side': result.get('side_to_move'),
                                       'candidate': is_screen_candidate(result, 'fen_only')}
        n = 0
        for source in rows(shard['input']):
            if source != next(frozen_rows, None):
                raise ValueError('Source shards do not exactly follow the frozen source sequence')
            identifier = source['id']
            result = screened.pop(identifier, None)
            if (identifier in seen or result is None or result['fen'] != source['fen'] or
                    result['side'] != source['side_to_move']):
                raise ValueError('Screen identities do not exactly match their source shard')
            seen.add(identifier)
            n += 1
            if not result['candidate']:
                excluded['not_screen_candidate'] += 1
                continue
            candidate_sides[source['side_to_move']] += 1
            candidate_roles[source.get('analysis_role', 'unknown')] += 1
            if source['game_id'] in public_games:
                excluded['known_public_exposed_game'] += 1
            elif source.get('contains_bot') is not False:
                excluded['bot_tagged_game' if source.get('contains_bot') is True else 'unknown_bot_status'] += 1
            elif source.get('history_available') is not True:
                excluded['source_history_not_recovered'] += 1
            else:
                verify_record(source)
                candidates.append(source)
        if n != shard['rows'] or screened:
            raise ValueError('Screen shard record count differs from its manifest')
    if next(frozen_rows, None) is not None or len(seen) != run['input_n']:
        raise ValueError('Frozen source census is incomplete')
    chosen, canonical_selection = choose_candidates(candidates, per_side, seed)
    selected_by_id = {r['id']: r for r in chosen}
    ordered_ids, legal_counts, output_policy_hashes = [], {}, {}
    temporary_positions, temporary_policies = (path.with_suffix('.jsonl.tmp') for path in outputs[:2])
    try:
        with temporary_positions.open('w') as position_out, temporary_policies.open('w') as policy_out:
            for shard in shards:
                policy_entry = stages[(shard['index'], 'policy')]
                if digest(policy_entry['output']) != policy_entry['output_sha256']:
                    raise ValueError('Saved policy shard changed during selection')
                with Path(shard['input']).open() as source_file, Path(policy_entry['output']).open() as policy_file:
                    count = 0
                    for source_line, policy_line in itertools.zip_longest(source_file, policy_file):
                        if source_line is None or policy_line is None:
                            raise ValueError('Policy and source lengths differ')
                        source, policy = json.loads(source_line), json.loads(policy_line)
                        if policy.get('id') != source['id'] or policy.get('fen') != source['fen']:
                            raise ValueError('Original policies are not in source order')
                        count += 1
                        if source['id'] not in selected_by_id:
                            continue
                        if source != selected_by_id[source['id']]:
                            raise ValueError('Selected metadata changed during export')
                        legal_counts[source['id']] = check_selected_policy(source, policy)
                        ordered_ids.append(source['id'])
                        output_policy_hashes[source['id']] = hashlib.sha256(policy_line.encode()).hexdigest()
                        position_out.write(source_line)
                        policy_out.write(policy_line)
                    if count != shard['rows']:
                        raise ValueError('Policy row count differs from the completed shard')
        if len(ordered_ids) != 2 * per_side or len(set(ordered_ids)) != len(ordered_ids):
            raise ValueError('Selected records were not exported exactly once')
        temporary_positions.replace(outputs[0])
        temporary_policies.replace(outputs[1])
    finally:
        temporary_positions.unlink(missing_ok=True)
        temporary_policies.unlink(missing_ok=True)
    legal_by_side = {s: [legal_counts[r['id']] for r in chosen if r['side_to_move'] == s] for s in ('white', 'black')}
    manifest = {'schema_version': 1, 'complete': True, 'created_at': datetime.now(timezone.utc).isoformat(),
        'selected_n': len(chosen), 'positions_sha256': digest(outputs[0]), 'policies_sha256': digest(outputs[1]),
        'seed': seed, 'per_side_target': per_side, 'method': METHOD,
        'counts': {'screened_n': len(seen), 'screen_candidates_n': sum(candidate_sides.values()),
                   'screen_candidates_by_side': dict(candidate_sides), 'selected_n': len(chosen),
                   'selected_by_side': dict(Counter(r['side_to_move'] for r in chosen)),
                   'selected_source_games_n': len({r['game_id'] for r in chosen})},
        'eligibility': {'exclusions_in_precedence_order': dict(excluded),
                        'eligible_by_side': dict(Counter(r['side_to_move'] for r in candidates)),
                        'candidate_analysis_roles': dict(candidate_roles)},
        'canonical_selection': canonical_selection,
        'selection_counts': {key: dict(Counter(str(r.get(key, 'unknown')) for r in chosen))
                             for key in ('cohort', 'phase', 'rating_bin', 'analysis_role', 'split')},
        'legal_roots': {'total': sum(legal_counts.values()), 'by_side': {s: sum(v) for s, v in legal_by_side.items()},
                        'minimum': min(legal_counts.values()), 'maximum': max(legal_counts.values())},
        'validation': {'screen_gate': True, 'recovered_history_replay': True, 'explicit_bot_games': 0,
                       'known_public_exposed_games': 0, 'unique_canonical_states': len(chosen),
                       'global_max_positions_per_game': 1, 'source_order_aligned': True,
                       'original_policies_copied_verbatim': True, 'all_four_policies_legal_complete': True,
                       'original_analysis_role_and_split_preserved': True},
        'input_hashes': hashes, 'selection_protocol_sha256': digest(declaration_path),
        'selection_script_sha256': digest(__file__), 'public_exclusion_sources': public_inputs,
        'selected_ids': ordered_ids, 'selected_id_hash_ranks': {r['id']: hash_rank('state', canonical_fen(r['fen']), seed) for r in chosen},
        'selected_legal_roots': legal_counts, 'original_policy_line_sha256': output_policy_hashes,
        'outputs': {'positions_sha256': digest(outputs[0]), 'policies_sha256': digest(outputs[1])},
        'limitations': ['One observation per game changes selection probabilities across the candidate pool.',
            'The colour quotas do not match cohorts, rating, phase, time controls or source months.',
            'Prior-development games keep that status; source split names do not create new held-out data.',
            'Passing this screen or subsequent deep search does not establish human puzzle difficulty or learning benefit.']}
    write_manifest(outputs[2], manifest)
    public_output.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(public_output, public_aggregate(manifest))
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=ROOT / 'data/mining_v3/positions.jsonl')
    ap.add_argument('--run-dir', type=Path, default=ROOT / 'results/mining_v3/full')
    ap.add_argument('--output-dir', type=Path, default=ROOT / 'data/mining_v3/deep200')
    ap.add_argument('--public-output', type=Path, default=ROOT / 'results/mining_v3_deep_selection.json')
    args = ap.parse_args()
    manifest = select_batch(args.input, args.run_dir, args.output_dir, args.public_output)
    print(json.dumps({'counts': manifest['counts'], 'legal_roots': manifest['legal_roots'],
                      'outputs': manifest['outputs']}, indent=2))


if __name__ == '__main__':
    main()
