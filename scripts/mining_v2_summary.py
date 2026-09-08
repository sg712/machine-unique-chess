"""Publish aggregate results without exposing a prospective private assessment bank."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

import chess


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def index_records(rows, label):
    records = {r['id']: r for r in rows}
    if len(records) != len(rows):
        raise ValueError(f'{label} contains duplicate position IDs.')
    return records


def check_identity(rows, records, label):
    indexed = index_records(rows, label)
    if indexed.keys() != records.keys():
        raise ValueError(f'{label} IDs do not match its input records.')
    if any(row.get('fen') != records[key]['fen'] for key, row in indexed.items()):
        raise ValueError(f'{label} FENs do not match its input records.')
    return indexed


def check_screen_manifest(manifest, input_path, policy_path, rows, records, label):
    check_identity(rows, records, label)
    if (not manifest.get('complete') or manifest.get('input_n') != len(records)
            or manifest.get('completed_n') != len(rows)):
        raise ValueError(f'{label} must be complete before publication.')
    settings = manifest.get('settings', {})
    if (settings.get('input_sha256') != sha(input_path)
            or settings.get('policy_sha256') != sha(policy_path)):
        raise ValueError(f'{label} input/policy hashes do not match the completed run.')


def check_policy_manifest(manifest, input_path, policy_path, rows, records):
    check_identity(rows, records, 'Policy batch')
    if (manifest.get('record_count') != len(rows)
            or manifest.get('input_sha256') != sha(input_path)
            or manifest.get('output_sha256') != sha(policy_path)):
        raise ValueError('Policy manifest does not match its input and output files.')


def metric(row, condition, rating, tolerance=20):
    return row.get('metrics', {}).get(f'maia3/{condition}/{rating}', {}).get(str(tolerance), {})


def competitive(row):
    return not row.get('has_mate', True) and row.get('best_cp') is not None and abs(row['best_cp']) <= 200


def selected(row, condition='history', tolerance=20, ceiling=.10, regret=50):
    if not competitive(row):
        return False
    values = [metric(row, condition, rating, tolerance) for rating in (1700, 2000)]
    return all(v.get('available') and v['p_good_upper'] <= ceiling and
               v['capped_regret_lower_cp'] >= regret for v in values)


def describe(rows, records, condition):
    chosen = [r for r in rows if selected(r, condition)]
    counts = Counter(records[r['id']]['split'] for r in chosen)
    cells = Counter(('White' if records[r['id']]['fen'].split()[1] == 'w' else 'Black',
                     records[r['id']]['source']['cohort']) for r in chosen)
    return {'screened_n': len(rows), 'competitive_numeric_n': sum(competitive(r) for r in rows),
            'mate_in_scored_roots_n': sum(r.get('has_mate', False) for r in rows),
            'all_roots_scored_n': sum(r.get('exhaustive', False) for r in rows),
            'all_requested_depths_reached_n': sum(r.get('all_searches_reached_target', False) for r in rows),
            'screen_candidates_n': len(chosen), 'candidate_splits': dict(counts),
            'family_discovery_train_candidates_n': counts.get('train', 0),
            'discovery_note': 'Only training-split pilot rows may inform teaching-family discovery; held-out rows are summarized without publishing their positions.',
            'candidate_cells': [{'side':s,'cohort':c,'n':n} for (s,c),n in sorted(cells.items())],
            'threshold_sensitivity': [
                {'tolerance_cp':t,'p_good_ceiling':p,'regret_floor_cp':loss,
                 'n':sum(selected(r,condition,t,p,loss) for r in rows)}
                for t in (20,50) for p in (.05,.10,.20) for loss in (25,50,100)]}


def policy_comparison(policies):
    changes, size_changes, model_compared, distances = 0, 0, 0, []
    for row in policies:
        h = row.get('maia3', {}).get('history', {}).get('2000')
        f = row.get('maia3', {}).get('fen_only', {}).get('2000')
        m = (row.get('maia2') or {}).get('fen_only', {}).get('2000')
        if f and m:
            model_compared += 1
            size_changes += max(f,key=f.get) != max(m,key=m.get)
        if h and f:
            changes += max(h,key=h.get) != max(f,key=f.get)
            distances.append(sum(abs(h.get(move, 0)-f.get(move, 0)) for move in h.keys() | f.keys())/2)
    return {'n':len(policies), 'history_compared_n':len(distances),
            'history_changes_top_move_n': changes,
            'history_mean_total_variation':statistics.mean(distances) if distances else None,
            'maia2_vs_maia3_compared_n': model_compared,
            'maia2_vs_maia3_fen_top_move_disagreements_n':size_changes,
            'interpretation':'Fixed 2000 rating inputs; model sensitivity, not independent human evidence or puzzle calibration.'}


def deep_summary(result_dir):
    """Count completed evidence; a later failure supersedes an earlier success."""
    checks, latest, complete_batches, incomplete_batches = 0, {}, 0, 0
    for file in sorted(Path(result_dir).glob('*deep*.jsonl')):
        manifest_path = file.with_suffix('.manifest.json')
        if not manifest_path.exists():
            raise ValueError(f'Deep batch {file.name} has no provenance manifest.')
        manifest = json.loads(manifest_path.read_text())
        if not manifest.get('complete'):
            incomplete_batches += 1
            continue
        rows = read(file)
        indexed = index_records(rows, file.name)
        if (manifest.get('input_n') != len(rows) or manifest.get('completed_n') != len(rows)
                or any(r.get('mode') != 'deep' for r in rows)):
            raise ValueError(f'Completed deep batch {file.name} has inconsistent counts.')
        settings = manifest.get('settings', {})
        input_path = Path(settings['input'])
        policy_path = Path(settings['policies'])
        if not input_path.is_absolute(): input_path = ROOT / input_path
        if not policy_path.is_absolute(): policy_path = ROOT / policy_path
        input_rows = index_records(read(input_path), file.name + ' inputs')
        check_screen_manifest(manifest, input_path, policy_path, rows, input_rows, file.name)
        complete_batches += 1
        checks += len(rows)
        stamp = (manifest.get('finished_at', 0), file.name)
        for row in indexed.values():
            key = ' '.join(chess.Board(row['fen']).fen(en_passant='legal').split()[:4])
            if key not in latest or stamp > latest[key][0]:
                latest[key] = (stamp, row)
    newest = [entry[1] for entry in latest.values()]
    return {'completed_batches_n': complete_batches, 'incomplete_batches_n': incomplete_batches,
            'completed_position_checks_n': checks, 'unique_positions_n': len(newest),
            'verified_unique_n': sum(bool(r.get('verified')) for r in newest),
            'verified_training_positions_n': sum(bool(r.get('verified')) and r.get('split') == 'train' for r in newest),
            'rejection_reasons_overlapping': {
                'mate_in_any_legal_root': sum(bool(r.get('has_mate')) for r in newest if not r.get('verified')),
                'requested_depth_not_reached': sum(not r.get('all_searches_reached_target') for r in newest if not r.get('verified')),
                'acceptance_set_unstable': sum(not r.get('stable_acceptance') for r in newest if not r.get('verified')),
                'nonexact_root_score': sum(any(not s.get('score_is_exact') for d in r.get('searches', {}).values()
                                              for s in d.values()) for r in newest if not r.get('verified'))},
            'note': 'Only completed batches count; the latest completed check per canonical position determines verification. No position IDs, FENs or solutions are published. Verification is engine evidence, not teaching review.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',default=str(ROOT/'results/mining_v2_summary.json'))
    args=ap.parse_args()
    data=ROOT/'data/mining_v2'; result=ROOT/'results/mining_v2'
    records=index_records(read(data/'positions.jsonl'), 'Pilot input')
    policies=read(data/'policies.jsonl'); screen=read(result/'pilot_screen.jsonl')
    manifest=json.loads((result/'pilot_screen.manifest.json').read_text())
    check_screen_manifest(manifest, data/'positions.jsonl', data/'policies.jsonl', screen, records, 'Pilot screening')
    policy_manifest=json.loads((data/'policy_manifest.json').read_text())
    check_policy_manifest(policy_manifest, data/'positions.jsonl', data/'policies.jsonl', policies, records)
    sampling=json.loads((data/'sampling_manifest.json').read_text())
    if sampling.get('positions_sha256') != sha(data/'positions.jsonl'):
        raise ValueError('Sampling manifest does not match the pilot positions.')
    out={'schema_version':2, 'date':'2026-09-08',
         'status':'Exploratory screening; not a validated teaching bank or human learning result',
         'definition':{'evaluation_range_cp':[-200,200], 'acceptable_tolerance_cp':20,
                       'max_p_good_upper_each_rating':.10,'min_capped_regret_lower_cp_each_rating':50,
                       'ratings':[1700,2000],'regret_cap_cp':300,
                       'selection_note':'Transparent operational shortlist, not tuned to participant outcomes. Both ratings must pass; mate-containing positions excluded.'},
         'sample':{'n':len(records),'games':len({r['game_id'] for r in records.values()}),
                   'sides':dict(Counter('White' if r['fen'].split()[1]=='w' else 'Black' for r in records.values())),
                   'cohorts':dict(Counter(r['source']['cohort'] for r in records.values())),
                   'phases':dict(Counter(r['phase'] for r in records.values())),
                   'splits':dict(Counter(r['split'] for r in records.values())),
                   'history_n':sum(bool(r.get('history_available')) for r in policies),
                   'clock_n':sum(r.get('clock_seconds_before') is not None for r in records.values())},
         'pilot':describe(screen,records,'history'),
         'policy_sensitivity':policy_comparison(policies),
         'engine_settings':manifest['settings'],
         'limitations':[
             'All 123,405 version-1 positions were Black to move; preserved historical results do not describe a balanced sample.',
             'Club data are a bounded prefix of June 2026, elite data September–November 2025; this constructed pilot is not representative of all chess.',
             'Game and selected canonical-state splits do not separate players, openings or all transpositions.',
             'Clocks are preserved for later ablation, not supplied to the current policy model; elite clocks are absent.',
             'Screening is time-capped and usually partial. Probability bounds assume the recorded finite-search scores; depth instability remains.',
             'Fixed-rating model policies have not been calibrated to independent puzzle-solving responses.',
             'WDL sensitivity is Stockfish self-play expected score, not human winning probability.',
             'Private final items require exhaustive depth-20/24 stable acceptance, chess review and independent review before recruitment.'],
         'input_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [data/'positions.jsonl',data/'policies.jsonl',result/'pilot_screen.jsonl']}}
    # Keep production metadata portable and free of private absolute machine paths.
    for k in ('engine','input','policies','output'):
        value=out['engine_settings'].get(k)
        if value:
            try: out['engine_settings'][k]=str(Path(value).resolve().relative_to(ROOT))
            except ValueError: out['engine_settings'][k]=Path(value).name
    hp=data/'historical_stratified.jsonl'; hs=result/'historical_stratified_screen.jsonl'
    if hp.exists() and hs.exists():
        historical=read(hp); hrows=read(hs)
        hm=json.loads(hs.with_suffix('.manifest.json').read_text())
        hr=index_records(historical, 'Historical input')
        hpolicy=data/'historical_stratified_policies.jsonl'
        check_screen_manifest(hm, hp, hpolicy, hrows, hr, 'Historical stratified screening')
        check_policy_manifest(json.loads((data/'historical_stratified_policy_manifest.json').read_text()),
                              hp, hpolicy, read(hpolicy), hr)
        out['historical']={cohort:describe([r for r in hrows if hr[r['id']]['source']['cohort']==cohort],hr,'fen_only')
                           for cohort in sorted({r['source']['cohort'] for r in historical})}
        out['historical']['note']='FEN-only; no verified historical move histories. Matched cases and controls are a constructed audit.'
        out['input_sha256'].update({str(p.relative_to(ROOT)):sha(p) for p in (hp,hs)})
    out['deep_checks']=deep_summary(result)
    Path(args.output).write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({k:out[k] for k in ('sample','pilot','policy_sensitivity','deep_checks')},indent=2))


if __name__=='__main__': main()
