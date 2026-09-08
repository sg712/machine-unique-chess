"""Checkpoint every legal-root search in a frozen, FEN-only depth-20/24 batch.

The full legal move set is searched independently at each depth, with cleared
hash and no time/node stopping limit. Engine stability and retention of the
original candidate criterion are separate from teaching review.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import threading
import time

import chess
import chess.engine

import mining_v2_engine as base
from mining_v2_sampling import canonical_fen
from mining_v3_io import completed_ids, digest, rows, write_manifest

ROOT = Path(__file__).resolve().parents[1]
DEPTHS = (20, 24)


def task_id(identifier, depth, move):
    return f'{identifier}|{depth}|{move}'


def balanced_task_order(records):
    ranked = {side: sorted((row for row in records if row['side_to_move'] == side),
                           key=lambda row: hashlib.sha256(('v3-deep-order-20260909:'+row['id']).encode()).digest())
              for side in ('white', 'black')}
    ordered = []
    for i in range(max(map(len, ranked.values()), default=0)):
        ordered.extend(ranked[side][i] for side in ('white', 'black') if i < len(ranked[side]))
    if len(ordered) != len(records):
        raise ValueError('Unknown side-to-move metadata')
    return ordered


def validate_root(result, record):
    """A cached root is reusable only with exact, achieved-depth legal evidence."""
    depth, move = result.get('target_depth'), result.get('uci')
    if (not isinstance(depth, int) or isinstance(depth, bool) or depth not in DEPTHS or
            result.get('record_id') != record['id'] or result.get('fen') != record['fen'] or
            result.get('board_context') != 'fen_only'):
        raise ValueError('Root identity, FEN or depth mismatch')
    if result.get('id') != task_id(record['id'], depth, move):
        raise ValueError('Root checkpoint key mismatch')
    cp, mate = result.get('cp'), result.get('mate')
    numeric = isinstance(cp, (int, float)) and not isinstance(cp, bool) and math.isfinite(cp)
    mate_value = isinstance(mate, int) and not isinstance(mate, bool)
    if not ((numeric and mate is None) or (mate_value and cp is None)):
        raise ValueError('Root must have exactly one numeric or typed mate score')
    achieved = result.get('depth')
    if (not isinstance(achieved, int) or isinstance(achieved, bool) or achieved < depth or result.get('reached_target') is not True or
            result.get('score_is_exact') is not True or result.get('lowerbound') or result.get('upperbound')):
        raise ValueError('Root did not reach an exact target-depth score')
    if not isinstance(result.get('nodes'), int) or isinstance(result['nodes'], bool) or result['nodes'] <= 0:
        raise ValueError('Root search lacks node evidence')
    elapsed = result.get('wall_seconds')
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('Root search lacks finite nonnegative timing evidence')
    board = chess.Board(record['fen'])
    if not board.is_valid() or record.get('side_to_move') != ('white' if board.turn else 'black'):
        raise ValueError('Invalid board or mismatched side metadata')
    pv = result.get('pv')
    if not pv or pv[0].get('uci') != move:
        raise ValueError('Missing or different root continuation')
    for step in pv:
        action = chess.Move.from_uci(step['uci'])
        if action not in board.legal_moves or board.san(action) != step['san']:
            raise ValueError('Invalid root continuation')
        board.push(action)


def root_metrics(scores, policies):
    return {key: {str(tol): base.probability_summary(scores, probs, tol)
                  for tol in (20, 50)} for key, probs in policies.items()}


def passes_candidate(scores, metrics):
    if any(score['mate'] is not None for score in scores.values()):
        return False
    best = max(score['cp'] for score in scores.values())
    if not -200 <= best <= 200:
        return False
    return all((value := metrics[f'maia3/fen_only/{rating}']['20']).get('available') and
               value['all_policy_moves_scored'] and value['p_good_upper'] <= .10 and
               value['capped_regret_lower_cp'] >= 50 for rating in (1700, 2000))


def summarize_position(record, policy, roots):
    board = chess.Board(record['fen'])
    legal = {move.uci() for move in board.legal_moves}
    policies = base.validated_policies(record, policy, legal)
    if set(policies) != {f'maia3/fen_only/{r}' for r in (1400, 1700, 2000, 2300)}:
        raise ValueError('Expected the frozen four-rating FEN-only policy')
    scores = {str(depth): {} for depth in DEPTHS}
    for result in roots:
        validate_root(result, record)
        bucket = scores[str(result['target_depth'])]
        if result['uci'] in bucket:
            raise ValueError('Duplicate root evidence')
        bucket[result['uci']] = result
    if any(set(bucket) != legal for bucket in scores.values()):
        raise ValueError('Every legal root must be complete at both depths')
    accepted, best_moves, best_cp, metrics, gate = {}, {}, {}, {}, {}
    has_mate = any(result['mate'] is not None for bucket in scores.values() for result in bucket.values())
    for depth, bucket in scores.items():
        numeric = {move: result['cp'] for move, result in bucket.items() if result['cp'] is not None}
        best = max(numeric.values(), default=None)
        best_cp[depth] = best
        accepted[depth] = sorted(move for move, cp in numeric.items() if best-cp <= 20)
        best_moves[depth] = sorted(move for move, cp in numeric.items() if cp == best)
        metrics[depth] = root_metrics(bucket, policies)
        gate[depth] = passes_candidate(bucket, metrics[depth])
    stable = accepted['20'] == accepted['24'] and bool(accepted['24'])
    engine_verified = not has_mate and stable
    survives = engine_verified and all(gate.values())
    reasons = []
    if has_mate:
        reasons.append('mate_in_any_legal_root')
    if not stable:
        reasons.append('acceptable_set_changed')
    reasons.extend(f'candidate_criterion_not_retained_at_{depth}' for depth, passed in gate.items() if not passed)
    return {'id': record['id'], 'fen': record['fen'], 'game_id': record['game_id'],
            'side_to_move': record['side_to_move'], 'analysis_role': record.get('analysis_role'),
            'split': record.get('split'), 'mode': 'exhaustive_depth20_24', 'board_context': 'fen_only',
            'legal_count': len(legal), 'exhaustive': True, 'all_searches_reached_target': True,
            'all_scores_exact': True, 'has_mate': has_mate, 'accepted': accepted,
            'best_moves': best_moves, 'best_cp': best_cp, 'metrics': metrics,
            'stable_acceptance': stable, 'engine_verified': engine_verified,
            'candidate_criterion_by_depth': gate, 'survives': survives,
            'trainer_ready': False, 'reasons': reasons,
            'root_search_seconds_sum': sum(result['wall_seconds'] for result in roots),
            'nodes': sum(result['nodes'] for result in roots)}


def battery_is_critical():
    """Read-only macOS safeguard; unavailable battery information is not zero."""
    try:
        value = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    charge = re.search(r'(\d+)%;', value.stdout)
    return "'Battery Power'" in value.stdout and charge is not None and int(charge[1]) <= 5


def run(args):
    records = list(rows(args.input)); policies = list(rows(args.policies))
    index = {record['id']: record for record in records}
    if len(index) != len(records) or [r['id'] for r in records] != [p['id'] for p in policies]:
        raise ValueError('Inputs and policies must have identical unique IDs in the same order')
    if (len({record['game_id'] for record in records}) != len(records) or
            len({canonical_fen(record['fen']) for record in records}) != len(records)):
        raise ValueError('Batch requires distinct source games and canonical states')
    selection = json.loads(Path(args.selection_manifest).read_text())
    selection_ids = selection.get('selected_ids', [])
    if (selection.get('complete') is not True or selection.get('selected_n') != len(records) or
            selection.get('positions_sha256') != digest(args.input) or
            selection.get('policies_sha256') != digest(args.policies) or
            len(selection_ids) != len(records) or len(set(selection_ids)) != len(records) or
            set(selection_ids) != set(index)):
        raise ValueError('Selection manifest does not identify the exact frozen exports')
    tasks, legal_by_id = [], {}
    for record, policy in zip(records, policies):
        board = chess.Board(record['fen'])
        if (not board.is_valid() or board.is_game_over() or record.get('contains_bot') is not False or
                record.get('history_available') is not True or record.get('known_public_game') or
                record.get('analysis_role') == 'public_exposed'):
            raise ValueError('Batch requires valid nonterminal boards from games without BOT tags')
        if record['side_to_move'] != ('white' if board.turn else 'black'):
            raise ValueError('Side-to-move metadata differs from the board')
        legal = {move.uci() for move in board.legal_moves}
        legal_by_id[record['id']] = legal
        distributions = base.validated_policies(record, policy, legal)
        if set(distributions) != {f'maia3/fen_only/{r}' for r in (1400, 1700, 2000, 2300)}:
            raise ValueError('Policies must use only the frozen four-rating FEN-only condition')
    for record in balanced_task_order(records):
        tasks.extend((record, depth, move) for depth in DEPTHS for move in sorted(legal_by_id[record['id']]))
    directory = Path(args.run_dir); directory.mkdir(parents=True, exist_ok=True)
    output = directory/'roots.jsonl'; manifest_path = directory/'run.json'
    settings = {'input_sha256': digest(args.input), 'policy_sha256': digest(args.policies),
                'selection_manifest_sha256': digest(args.selection_manifest),
                'engine_sha256': digest(args.engine), 'runner_sha256': digest(__file__),
                'search_and_metrics_sha256': digest(base.__file__),
                'canonicalization_sha256': digest(ROOT/'scripts/mining_v2_sampling.py'),
                'io_sha256': digest(ROOT/'scripts/mining_v3_io.py'),
                'depths': list(DEPTHS), 'board_context': 'fen_only', 'engine_threads': 1,
                'task_order': 'SHA256(v3-deep-order-20260909:id) within side, interleaved White/Black; depth then sorted UCI root',
                'hash_mb': 64, 'clear_hash_each_search': True, 'time_limit': None, 'node_limit': None,
                'python_chess_version': chess.__version__, 'workers': args.workers}
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if previous and previous['settings'] != settings:
        raise ValueError('Frozen inputs, settings or implementation changed; use a new run directory')
    if output.exists() and previous is None:
        raise ValueError('Root output exists without a provenance manifest')
    completed_ids(output, repair_partial=args.repair_partial)
    if previous and previous.get('complete') and digest(output) != previous.get('roots_sha256'):
        raise ValueError('Completed root output hash changed')
    if previous and previous.get('roots_checkpoint_bytes', 0):
        prefix_n = previous['roots_checkpoint_bytes']
        with output.open('rb') as stream:
            prefix = stream.read(prefix_n)
        if len(prefix) != prefix_n or hashlib.sha256(prefix).hexdigest() != previous['roots_checkpoint_sha256']:
            raise ValueError('Saved root checkpoint prefix changed')
    root_hasher, root_bytes = hashlib.sha256(), 0
    if output.exists():
        with output.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                root_hasher.update(block); root_bytes += len(block)
    done, by_position = {}, {record['id']: [] for record in records}
    if output.exists():
        for result in rows(output):
            if result.get('record_id') not in index:
                raise ValueError('Cached root is outside the frozen batch')
            validate_root(result, index[result['record_id']])
            done[result['id']] = result; by_position[result['record_id']].append(result)
    expected = {task_id(record['id'], depth, move) for record, depth, move in tasks}
    if not set(done) <= expected:
        raise ValueError('Cached root does not belong to the task plan')
    manifest = {'settings': settings, 'input_n': len(records), 'root_searches_n': len(tasks),
                'started_at': previous['started_at'] if previous else time.time(),
                'complete': False, 'completed_root_searches_n': len(done),
                'completed_positions_n': sum(len(by_position[r['id']]) == 2*len(legal_by_id[r['id']]) for r in records),
                'roots_checkpoint_bytes': root_bytes, 'roots_checkpoint_sha256': root_hasher.hexdigest(),
                'attempts': (previous or {}).get('attempts', []) + [{'started_at': time.time()}]}
    write_manifest(manifest_path, manifest)
    engines, lock, local = [], threading.Lock(), threading.local()
    stop = threading.Event()

    def perform(task):
        if stop.is_set():
            raise RuntimeError('Computation paused')
        record, depth, move = task
        if not hasattr(local, 'engine'):
            local.engine = chess.engine.SimpleEngine.popen_uci(args.engine)
            local.engine.configure({'Threads': 1, 'Hash': 64, 'UCI_ShowWDL': True})
            with lock:
                if stop.is_set():
                    local.engine.close()
                    raise RuntimeError('Computation paused')
                engines.append(local.engine)
        started = time.monotonic()
        result = base.search(local.engine, chess.Board(record['fen']), depth, None,
                             roots=[chess.Move.from_uci(move)])[0]
        result.update(id=task_id(record['id'], depth, move), record_id=record['id'], fen=record['fen'],
                      board_context='fen_only', wall_seconds=time.monotonic()-started)
        validate_root(result, record)
        return result

    queue = iter(task for task in tasks if task_id(task[0]['id'], task[1], task[2]) not in done)
    pool = ThreadPoolExecutor(max_workers=args.workers)
    pending, exhausted, last_battery_check, last_progress = {}, False, 0., 0.
    try:
        with output.open('a') as destination:
            while pending or not exhausted:
                if time.monotonic()-last_battery_check >= 30:
                    last_battery_check = time.monotonic()
                    if battery_is_critical():
                        raise RuntimeError('Paused: host battery at or below 5% without AC power')
                while not exhausted and len(pending) < args.workers*2:
                    task = next(queue, None)
                    if task is None:
                        exhausted = True
                    else:
                        pending[pool.submit(perform, task)] = task
                if not pending:
                    break
                finished, _ = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
                for future in finished:
                    task = pending.pop(future)
                    result = future.result()
                    line = json.dumps(result, separators=(',', ':'))+'\n'
                    destination.write(line); destination.flush()
                    encoded = line.encode(); root_hasher.update(encoded); root_bytes += len(encoded)
                    done[result['id']] = result; by_position[result['record_id']].append(result)
                complete_n = sum(len(by_position[r['id']]) == 2*len(legal_by_id[r['id']]) for r in records)
                manifest.update(completed_root_searches_n=len(done), completed_positions_n=complete_n, updated_at=time.time(),
                                roots_checkpoint_bytes=root_bytes, roots_checkpoint_sha256=root_hasher.hexdigest())
                write_manifest(manifest_path, manifest)
                if time.monotonic()-last_progress >= 30 or finished and not pending and exhausted:
                    last_progress = time.monotonic()
                    print(json.dumps({'positions': complete_n, 'total_positions': len(records),
                                      'root_searches': len(done), 'total_root_searches': len(tasks)}), flush=True)
        if set(done) != expected:
            raise ValueError('Incomplete legal-root coverage')
        completed = [summarize_position(record, policy, by_position[record['id']]) for record, policy in zip(records, policies)]
        position_file = directory/'positions.jsonl'
        temporary = position_file.with_suffix('.tmp')
        temporary.write_text(''.join(json.dumps(row, separators=(',', ':'))+'\n' for row in completed))
        temporary.replace(position_file)
        manifest.update(complete=True, roots_sha256=digest(output), positions_sha256=digest(position_file))
    except BaseException as exc:
        manifest['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        stop.set()
        for future in pending:
            future.cancel()
        with lock:
            for engine in engines:
                engine.close()
        pool.shutdown(wait=True, cancel_futures=True)
        manifest['attempts'][-1].update(finished_at=time.time(), complete=manifest['complete'],
                                       completed_root_searches_n=len(done))
        manifest.update(finished_at=time.time(), completed_root_searches_n=len(done))
        write_manifest(manifest_path, manifest)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=ROOT/'data/mining_v3/deep200/positions.jsonl')
    ap.add_argument('--policies', type=Path, default=ROOT/'data/mining_v3/deep200/policies.jsonl')
    ap.add_argument('--selection-manifest', type=Path, default=ROOT/'data/mining_v3/deep200/selection_manifest.json')
    ap.add_argument('--run-dir', type=Path, default=ROOT/'results/mining_v3/deep200')
    ap.add_argument('--engine', type=Path, default=base.DEFAULT_ENGINE)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--repair-partial', action='store_true')
    args = ap.parse_args()
    if args.workers < 1:
        ap.error('--workers must be positive')
    run(args)


if __name__ == '__main__':
    main()
