"""Adapt actual provisional family notes and engine evidence into a candid draft bank.

Only explicit positive_ids/verified_boundary_ids become assigned training items.
Related unverified examples remain an unassigned candidate pool. No test items,
negative examples or human-review approvals are inferred.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import chess

try:
    from scripts import mining_v2_study as study
except ModuleNotFoundError:
    import mining_v2_study as study

ROOT = Path(__file__).resolve().parents[1]
GENERATED_EXPORTS = ('private-bank.json', 'readiness.json', 'private-allocation.json',
                     'materials.json', 'material-review.html')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot(path, jsonl=False):
    path = Path(path)
    raw = path.read_bytes()
    metadata = {'path': str(path.resolve()), 'snapshot_sha256': sha(raw), 'bytes': len(raw)}
    if not jsonl:
        return json.loads(raw), metadata
    rows = []
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if index == len(lines)-1 and not line.endswith(b'\n'):
                metadata['incomplete_last_line_omitted'] = True
                break
            raise
    metadata['complete_rows_in_snapshot'] = len(rows)
    return rows, metadata


def indexed(rows):
    output = {}
    for row in rows:
        if row['id'] in output:
            raise ValueError(f'Duplicate ID in source: {row["id"]}')
        output[row['id']] = row
    return output


def deep_snapshots(paths):
    selected, all_evidence, provenance = {}, {}, []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        rows, metadata = snapshot(path, jsonl=True)
        manifest_path = path.with_suffix('.manifest.json')
        if manifest_path.exists():
            try:
                manifest, manifest_meta = snapshot(manifest_path)
                metadata.update(manifest_snapshot=manifest_meta, manifest=manifest)
            except json.JSONDecodeError:
                metadata['manifest_temporarily_unreadable'] = True
        provenance.append(metadata)
        for row in rows:
            if row.get('mode') != 'deep':
                raise ValueError(f'{path}: screening output cannot be used as depth verification')
            # Later --deep inputs supersede earlier evidence for the same position.
            selected[row['id']] = (row, metadata)
            all_evidence.setdefault(row['id'], []).append({
                'source_snapshot_sha256': metadata['snapshot_sha256'],
                'verified': row.get('verified', False),
                'stable_acceptance': row.get('stable_acceptance'),
                'all_searches_reached_target': row.get('all_searches_reached_target'),
                'all_scores_exact': row.get('all_scores_exact'), 'has_mate': row.get('has_mate')})
    return selected, all_evidence, provenance


def item_from_anchor(key, family, kind, source, policies, selected, all_evidence):
    row = source[key]
    evidence = family.get('evidence', {}).get(key, {})
    if evidence and (evidence.get('fen') != row['fen'] or evidence.get('source_game_id') != row['game_id']):
        raise ValueError(f'{key}: editorial note FEN/source game does not match the source row')
    if key in policies and chess.Board(policies[key]['fen']).fen() != chess.Board(row['fen']).fen():
        raise ValueError(f'{key}: policy FEN does not match the source row')
    item = {'id': key, 'fen': row['fen'], 'game_id': row['game_id'],
            'role': 'training', 'form': None, 'family': family['id'],
            'family_title': family.get('title', family['id']), 'kind': kind,
            'explanation': family.get('notes_by_id', {}).get(key, ''),
            'source_row': row, 'model_policy': policies.get(key),
            'family_membership_status': 'provisional_editorial_anchor',
            'editorial_reference': {'source_status': family.get('status'), 'screen_evidence': evidence},
            'review': {'chess': False, 'near_duplicates': False,
                       'agent_screen_note_present': bool(family.get('notes_by_id', {}).get(key)),
                       'reviewer': 'agent-reviewed-provisionally',
                       'pending': 'Reconcile the teaching claim with complete deep branches; independent review and near-duplicate review remain open.'},
            'scores_20': {}, 'scores_24': {}, 'accepted20': [], 'accepted24': [],
            'engine': {'depth20': 0, 'depth24': 0, 'nodes20': 0, 'nodes24': 0,
                       'verified': False, 'status': 'deep_verification_pending'},
            'deep_evidence_history': all_evidence.get(key, [])}
    if key not in selected:
        return item
    deep, metadata = selected[key]
    if deep['fen'] != row['fen'] or deep['game_id'] != row['game_id']:
        raise ValueError(f'{key}: deep evidence FEN/source mismatch')
    item['raw_deep_evidence'] = deep
    item['deep_source_snapshot'] = {key: value for key, value in metadata.items() if key != 'manifest'}
    for depth in (20, 24):
        roots = deep.get('searches', {}).get(str(depth), {})
        item[f'scores_{depth}'] = {move: result.get('cp') for move, result in roots.items()}
        item[f'accepted{depth}'] = deep.get('accepted', {}).get(str(depth), [])
        item['engine'][f'depth{depth}'] = min((result.get('depth', 0) for result in roots.values()), default=0)
        item['engine'][f'nodes{depth}'] = sum(result.get('nodes') or 0 for result in roots.values())
    item['engine'].update(verified=deep.get('verified') is True,
                          all_scores_exact=deep.get('all_scores_exact') is True,
                          all_searches_reached_target=deep.get('all_searches_reached_target') is True,
                          has_mate=deep.get('has_mate'), stable_acceptance=deep.get('stable_acceptance'),
                          status='engine_verified_only' if deep.get('verified') else 'deep_checks_failed')
    item['review']['deep_confirms_editorial_move'] = (deep.get('verified') is True and
                                                     evidence.get('best_uci') in item['accepted24'])
    return item


def apply_agent_review(item, record):
    if not record:
        return
    item['review']['chess'] = False
    item['review']['agent_review_record'] = record
    deep = item.get('raw_deep_evidence')
    deep_hash = sha(json.dumps(deep, sort_keys=True, separators=(',', ':')).encode()) if deep else None
    identity_matches = (record.get('id') == item['id'] and record.get('fen') == item['fen'] and
               record.get('game_id') == item['game_id'] and
               record.get('explanation_sha256') == sha(item['explanation'].encode()) and
               record.get('deep_row_sha256') == deep_hash and
               record.get('accepted20') == item['accepted20'] and record.get('accepted24') == item['accepted24'])
    matched = (identity_matches and record.get('status') == 'agent_chess_review_passed' and
               item['engine'].get('verified') is True)
    item['review']['agent_review_record_status'] = 'matched' if matched else 'stale_or_unmatched'
    if identity_matches and record.get('status') == 'agent_chess_claims_checked_engine_gate_failed':
        item['review'].update(agent_review_record_status='claims_checked_engine_gate_failed',
                              reviewer=record.get('reviewer'),
                              pending='Specific explanation claims checked; complete engine acceptance verification failed. Study-item approval remains pending.')
    if matched:
        item['review'].update(chess=True, reviewer=record.get('reviewer'),
                              pending='Position explanation reviewed; near-duplicate review, independent chess review and family validation remain pending.')


def build_bank(family_review, source_rows, policy_rows, selected, all_evidence, provenance, agent_reviews=(), boundary_document=None):
    source, policies = indexed(source_rows), indexed(policy_rows)
    items, unassigned = [], []
    for family in family_review['families']:
        for kind, id_key in [('positive', 'positive_ids'), ('boundary', 'verified_boundary_ids')]:
            for key in family.get(id_key, []):
                items.append(item_from_anchor(key, family, kind, source, policies, selected, all_evidence))
        for key in family.get('related_unverified_ids', []):
            candidate = item_from_anchor(key, family, 'positive', source, policies, selected, all_evidence)
            candidate.update(role='unassigned', family_membership_status='related_unverified_not_counted_as_training')
            unassigned.append(candidate)
    for anchor in family_review.get('additional_anchors', []):
        key = anchor['id']
        if key in {item['id'] for item in [*items, *unassigned]}:
            continue
        provisional = {'id': 'unassigned', 'notes_by_id': {key: anchor.get('mechanism', '')},
                       'evidence': {key: anchor.get('evidence', {})}, 'status': anchor.get('status')}
        candidate = item_from_anchor(key, provisional, 'positive', source, policies, selected, all_evidence)
        candidate.update(role='unassigned', family=None, title=anchor.get('title'),
                         family_membership_status='unassigned_single_anchor', anchor_review=anchor)
        unassigned.append(candidate)
    families_by_id = {family['id']: family for family in family_review['families']}
    for candidate in (boundary_document or {}).get('candidates', []):
        key, family_id = candidate['id'], candidate['family_link']
        if family_id not in families_by_id:
            raise ValueError(f'{key}: boundary refers to an unknown provisional family')
        if candidate['positive_anchor_id'] not in families_by_id[family_id].get('positive_ids', []):
            raise ValueError(f'{key}: boundary positive anchor is not assigned to its family')
        if key in {item['id'] for item in [*items, *unassigned]}:
            raise ValueError(f'{key}: boundary is already assigned elsewhere')
        evidence = {'fen': candidate['fen'], 'source_game_id': candidate['game_id'],
                    'best_uci': candidate.get('comparison', {}).get('knight_capture', {}).get('root')}
        family = {'id': family_id, 'title': families_by_id[family_id].get('title', family_id),
                  'status': candidate.get('verification_status'),
                  'notes_by_id': {key: candidate['explanation']}, 'evidence': {key: evidence}}
        item = item_from_anchor(key, family, 'boundary', source, policies, selected, all_evidence)
        item.update(family_membership_status='provisional_natural_boundary', boundary_review=candidate)
        items.append(item)
    reviews = indexed(agent_reviews)
    for item in [*items, *unassigned]:
        apply_agent_review(item, reviews.get(item['id']))
    engine_runs = [entry.get('manifest', {}).get('settings', {}) for entry in provenance.get('deep_runs', [])]
    binary_hashes = {entry.get('engine_sha256') for entry in engine_runs if entry.get('engine_sha256')}
    if len(binary_hashes) > 1:
        raise ValueError('Deep sources use different engine binaries; do not pool them.')
    engine = {'name': 'Stockfish 18', 'binary_sha256': next(iter(binary_hashes), ''), 'threads': 1, 'hash_mb': 64}
    counts = Counter(item['kind'] for item in items)
    return {'schema_version': 2, 'status': 'draft_materials_incomplete', 'engine': engine,
            'items': items, 'unassigned_candidates': unassigned, 'family_review': family_review,
            'provenance': provenance,
            'candidate_summary': {'provisional_families': len(family_review['families']),
                                  'assigned_positive_anchors': counts['positive'],
                                  'assigned_boundary_anchors': counts['boundary'],
                                  'test_items': 0, 'unassigned_candidates': len(unassigned),
                                  'unassigned_related_candidates': sum(item['family_membership_status'] == 'related_unverified_not_counted_as_training' for item in unassigned),
                                  'unassigned_single_anchors': sum(item['family_membership_status'] == 'unassigned_single_anchor' for item in unassigned),
                                  'engine_verified_assigned_items': sum(item['engine']['verified'] for item in items),
                                  'agent_chess_reviewed_assigned_items': sum(item['review']['chess'] for item in items),
                                  'agent_claims_checked_engine_failed_items': sum(item['review'].get('agent_review_record_status') == 'claims_checked_engine_gate_failed' for item in items),
                                  'fully_reviewed_study_items': 0,
                                  'side_to_move': dict(Counter(chess.Board(item['fen']).turn and 'white' or 'black' for item in items))},
            'readiness': {gate: False for gate in study.MANUAL_GATES}}


def export_draft(bank, output, seed, refresh=False):
    output = Path(output)
    payload = json.dumps(bank, indent=2, sort_keys=True, ensure_ascii=False)+'\n'
    existing = [name for name in GENERATED_EXPORTS if (output/name).exists()]
    if existing:
        if not refresh:
            raise FileExistsError('Draft export exists; pass --refresh to archive and replace this draft.')
        if set(existing) != set(GENERATED_EXPORTS):
            raise ValueError('Incomplete previous export; inspect it manually before refreshing.')
        allocation = json.loads((output/'private-allocation.json').read_text())
        materials = json.loads((output/'materials.json').read_text())
        if allocation.get('draft') is not True or materials.get('draft') is not True:
            raise ValueError('Refusing to refresh a frozen export.')
        old_bytes = (output/'private-bank.json').read_bytes()
        if old_bytes == payload.encode() and allocation.get('seed') == seed:
            return json.loads((output/'readiness.json').read_text())
        archive = output/'archive'/sha(old_bytes)[:16]
        if archive.exists():
            raise FileExistsError('Archive already exists; preserve it and choose a new export location.')
        archive.mkdir(parents=True)
        for name in GENERATED_EXPORTS:
            shutil.move(str(output/name), str(archive/name))
    return study.export_bundle(bank, output, seed, draft=True,
                               public_fens=study._public_references(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--families', type=Path, default=ROOT/'data/mining_v2/family_review.json')
    parser.add_argument('--rows', type=Path, action='append', help='Repeat to include historical and balanced-pilot rows.')
    parser.add_argument('--policies', type=Path, action='append', help='Repeat to include the corresponding policy outputs.')
    parser.add_argument('--boundaries', type=Path, default=ROOT/'data/mining_v2/private_boundary_candidates.json')
    parser.add_argument('--agent-reviews', type=Path, default=ROOT/'data/mining_v2/chess_review.json')
    parser.add_argument('--deep', type=Path, action='append', help='Earlier sources are superseded by later sources for the same ID.')
    parser.add_argument('--output', type=Path, default=ROOT/'data/mining_v2/candidate-bank.json')
    parser.add_argument('--export', type=Path, default=ROOT/'data/mining_v2/study-review')
    parser.add_argument('--seed', type=int, default=712, help='Draft rehearsal seed only; not a recruitment allocation.')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    families, families_meta = snapshot(args.families)
    rows, rows_meta, policies, policies_meta = [], [], [], []
    row_paths = args.rows or [ROOT/'data/mining_v2/historical.jsonl', ROOT/'data/mining_v2/positions.jsonl']
    if args.rows is None and (ROOT/'data/mining_v2/boundary_deep_input.jsonl').exists():
        row_paths.append(ROOT/'data/mining_v2/boundary_deep_input.jsonl')
    for path in row_paths:
        records, metadata = snapshot(path, jsonl=True)
        rows.extend(records); rows_meta.append(metadata)
    policy_paths = args.policies or [ROOT/'data/mining_v2/historical_policies.jsonl', ROOT/'data/mining_v2/policies.jsonl']
    if args.policies is None and (ROOT/'data/mining_v2/boundary_policies.jsonl').exists():
        policy_paths.append(ROOT/'data/mining_v2/boundary_policies.jsonl')
    for path in policy_paths:
        records, metadata = snapshot(path, jsonl=True)
        policies.extend(records); policies_meta.append(metadata)
    deep_paths = args.deep if args.deep is not None else [ROOT/'results/mining_v2/historical_deep_first.jsonl',
                    ROOT/'results/mining_v2/historical_deep_retry.jsonl', ROOT/'results/mining_v2/family_deep.jsonl',
                    ROOT/'results/mining_v2/pilot_deep.jsonl', ROOT/'results/mining_v2/historical_deep_final.jsonl',
                    ROOT/'results/mining_v2/boundary_deep.jsonl']
    selected, all_evidence, deep_meta = deep_snapshots(deep_paths)
    agent_reviews, reviews_meta = [], None
    if args.agent_reviews.exists():
        review_document, reviews_meta = snapshot(args.agent_reviews)
        agent_reviews = review_document.get('items', [])
    boundary_document, boundaries_meta = None, None
    if args.boundaries.exists():
        boundary_document, boundaries_meta = snapshot(args.boundaries)
    provenance = {'adapter_sha256': sha(Path(__file__).read_bytes()),
                  'study_validator_sha256': sha(Path(study.__file__).read_bytes()), 'family_review': families_meta,
                  'source_rows': rows_meta, 'policies': policies_meta, 'deep_runs': deep_meta, 'agent_reviews': reviews_meta, 'boundaries': boundaries_meta,
                  'selection_rule': 'Latest supplied deep file supersedes earlier evidence; related candidates are not assigned family membership.',
                  'snapshot_notice': 'Running output files are captured as snapshots. Refresh after runs finish.'}
    bank = build_bank(families, rows, policies, selected, all_evidence, provenance, agent_reviews, boundary_document)
    report = export_draft(bank, args.export, args.seed, args.refresh)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bank, indent=2, sort_keys=True, ensure_ascii=False)+'\n')
    print(json.dumps({'candidate_bank': str(args.output), 'export': str(args.export),
                      'summary': bank['candidate_summary'], 'material_errors': len(report['errors']),
                      'ready_for_recruitment': report['ready_for_recruitment'],
                      'pending_manual_gates': report['pending_manual_gates']}, indent=2))


if __name__ == '__main__':
    main()
