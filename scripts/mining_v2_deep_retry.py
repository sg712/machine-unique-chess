"""Retry deep checks, reusing only auditable exact root scores that reached depth.

Run after applying the streaming bound-flag fix to mining_v2_engine.py. A prior
unstable acceptance set forces fresh searches for every legal move at both depths.
This does not convert screening output into deep verification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
import math
from pathlib import Path
import threading
import time

import chess
import chess.engine

# Support both direct execution and import by the test suite.
try:
    from scripts import mining_v2_engine as scoring
except ModuleNotFoundError:
    import mining_v2_engine as scoring

SOURCE_FIELDS = ('id', 'fen', 'game_id', 'initial_fen', 'history_available', 'history_uci')


def reusable_root(result, move, board, depth):
    if not isinstance(result, dict):
        return False
    cp, mate = result.get('cp'), result.get('mate')
    numeric = isinstance(cp, (int, float)) and not isinstance(cp, bool) and math.isfinite(cp)
    mate_score = isinstance(mate, int) and not isinstance(mate, bool)
    if (result.get('score_is_exact') is not True or result.get('lowerbound') or result.get('upperbound') or
            result.get('reached_target') is not True or result.get('depth', 0) < depth or
            result.get('target_depth') != depth or result.get('uci') != move or
            not (numeric ^ mate_score) or not result.get('nodes')):
        return False
    try:
        current = board.copy()
        pv = result['pv']
        if not pv or pv[0]['uci'] != move:
            return False
        for step in pv:
            action = chess.Move.from_uci(step['uci'])
            if action not in current.legal_moves or current.san(action) != step['san']:
                return False
            current.push(action)
    except (KeyError, TypeError, ValueError):
        return False
    return True


def inspect_retry(engine, row, policy, seconds, prior, provenance):
    board = scoring.board_for(row)
    if board.is_game_over():
        return {'id': row['id'], 'fen': row['fen'], 'error': 'terminal_position', 'verified': False}
    legal = {move.uci() for move in board.legal_moves}
    policies = scoring.validated_policies(row, policy, legal)
    same_position = (prior.get('id') == row['id'] and prior.get('fen') == row['fen'] and
                     prior.get('game_id') == row['game_id'] and prior.get('mode') == 'deep')
    allow_reuse = same_position and prior.get('stable_acceptance') is True
    out = {'id': row['id'], 'fen': row['fen'], 'game_id': row['game_id'], 'split': row.get('split'),
           'mode': 'deep', 'legal_count': len(legal), 'prior': provenance,
           'reuse_policy': 'exact achieved-depth roots only; unstable prior acceptance reruns every root',
           'rerun_all_due_to_prior_instability': same_position and prior.get('stable_acceptance') is False}
    by_depth, reused = {}, 0
    for depth in (20, 24):
        scores = {}
        for move in sorted(legal):
            cached = prior.get('searches', {}).get(str(depth), {}).get(move) if allow_reuse else None
            if reusable_root(cached, move, board, depth):
                result = copy.deepcopy(cached)
                result['reused_from'] = {'output_sha256': provenance['output_sha256'],
                                         'scorer_sha256': provenance['scorer_sha256']}
                reused += 1
            else:
                result = scoring.search(engine, board, depth, seconds, roots=[chess.Move.from_uci(move)])[0]
            scores[move] = result
        by_depth[str(depth)] = scores
    out.update(searches=by_depth, exhaustive=True, reused_root_searches=reused,
               fresh_root_searches=2*len(legal)-reused)
    out['all_searches_reached_target'] = all(s['reached_target'] for scores in by_depth.values() for s in scores.values())
    out['all_scores_exact'] = all(s['score_is_exact'] for scores in by_depth.values() for s in scores.values())
    out['has_mate'] = any(s['mate'] is not None for scores in by_depth.values() for s in scores.values())
    out['accepted'] = {}
    for depth, scores in by_depth.items():
        numeric = {move: result['cp'] for move, result in scores.items() if result['cp'] is not None}
        best = max(numeric.values(), default=None)
        out['accepted'][depth] = sorted(move for move, cp in numeric.items() if best-cp <= 20) if best is not None else []
    out['stable_acceptance'] = out['accepted']['20'] == out['accepted']['24'] and bool(out['accepted']['24'])
    out['verified'] = (out['all_searches_reached_target'] and out['all_scores_exact'] and
                       not out['has_mate'] and out['stable_acceptance'])
    out['metrics'] = {key: {depth: {str(tolerance): scoring.probability_summary(scores, probs, tolerance)
                                   for tolerance in (20, 50)} for depth, scores in by_depth.items()}
                      for key, probs in policies.items()}
    out['wdl_sensitivity'] = {key: {depth: scoring.wdl_summary(scores, probs)
                                  for depth, scores in by_depth.items()} for key, probs in policies.items()}
    return out


def read_index(path):
    rows = scoring.load_jsonl(path)
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError(f'Duplicate IDs in {path}')
    return {row['id']: row for row in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--policies')
    parser.add_argument('--prior', required=True)
    parser.add_argument('--prior-manifest', help='Defaults to prior output with .manifest.json suffix.')
    parser.add_argument('--output', required=True)
    parser.add_argument('--engine', default=str(scoring.DEFAULT_ENGINE))
    parser.add_argument('--deep-seconds', type=float, default=30.)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1 or not math.isfinite(args.deep_seconds) or args.deep_seconds <= 0:
        parser.error('Use positive workers and a finite positive per-root time budget.')
    prior_path = Path(args.prior)
    prior_manifest_path = Path(args.prior_manifest) if args.prior_manifest else prior_path.with_suffix('.manifest.json')
    prior_manifest = json.loads(prior_manifest_path.read_text())
    previous_settings = prior_manifest['settings']
    prior_input = Path(previous_settings['input'])
    if scoring.digest(prior_input) != previous_settings['input_sha256']:
        raise ValueError('Prior source input changed since analysis.')
    compatible = (previous_settings.get('engine_sha256') == scoring.digest(args.engine) and
                  previous_settings.get('engine_threads') == 1 and previous_settings.get('hash_mb') == 64 and
                  previous_settings.get('clear_hash_each_search') is True and previous_settings.get('scorer_sha256'))
    if not compatible:
        raise ValueError('Prior engine/options/provenance differ; run fresh verification.')
    rows = read_index(args.input)
    prior_inputs, priors = read_index(prior_input), read_index(prior_path)
    policies = read_index(args.policies) if args.policies else {}
    if args.policies and not rows.keys() <= policies.keys():
        raise ValueError('Missing policies for retry inputs.')
    for key, row in rows.items():
        if key in priors and (key not in prior_inputs or
                any(row.get(field) != prior_inputs[key].get(field) for field in SOURCE_FIELDS)):
            raise ValueError(f'{key}: retry source/history differs from prior analysis.')
    provenance = {'output_sha256': scoring.digest(prior_path),
                  'manifest_sha256': scoring.digest(prior_manifest_path),
                  'scorer_sha256': previous_settings['scorer_sha256'],
                  'input_sha256': previous_settings['input_sha256']}
    settings = vars(args).copy()
    settings.update(engine_sha256=scoring.digest(args.engine), scorer_sha256=scoring.digest(scoring.__file__),
                    retry_helper_sha256=scoring.digest(__file__), input_sha256=scoring.digest(args.input),
                    policy_sha256=scoring.digest(args.policies) if args.policies else None,
                    engine_threads=1, hash_mb=64, clear_hash_each_search=True, prior_provenance=provenance)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix('.manifest.json')
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old['settings'] != settings:
            raise ValueError('Retry settings changed; choose a new output file.')
        start = old['started_at']
    elif output.exists():
        raise ValueError('Retry output exists without its manifest.')
    else:
        start = time.time()
    done = read_index(output) if output.exists() else {}
    if not done.keys() <= rows.keys():
        raise ValueError('Retry cache includes IDs outside the current input.')
    manifest = {'settings': settings, 'started_at': start, 'input_n': len(rows), 'complete': False}
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    local, engines, lock = threading.local(), [], threading.Lock()
    def run(row):
        if not hasattr(local, 'engine'):
            local.engine = chess.engine.SimpleEngine.popen_uci(args.engine)
            local.engine.configure({'Threads': 1, 'Hash': 64, 'UCI_ShowWDL': True})
            with lock:
                engines.append(local.engine)
        started = time.monotonic()
        result = inspect_retry(local.engine, row, policies.get(row['id'], {}), args.deep_seconds,
                               priors.get(row['id'], {}), provenance)
        result['elapsed_seconds'] = time.monotonic()-started
        return result
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool, output.open('a') as handle:
            futures = [pool.submit(run, row) for key, row in rows.items() if key not in done]
            for future in as_completed(futures):
                result = future.result()
                handle.write(json.dumps(result)+'\n')
                handle.flush()
                done[result['id']] = result
                print(json.dumps({'completed': len(done), 'total': len(rows),
                                  'verified': result.get('verified', False),
                                  'reused_roots': result.get('reused_root_searches', 0)}), flush=True)
    finally:
        for engine in engines:
            engine.quit()
        manifest.update(finished_at=time.time(), complete=len(done)==len(rows), completed_n=len(done),
                        verified_n=sum(bool(row.get('verified')) for row in done.values()))
        manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    main()
