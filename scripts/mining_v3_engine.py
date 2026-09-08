"""Fixed-node, resumable Stockfish 18 screening for both colours.

Every position receives the same 30,000-node top-three search. Its three leaders,
played move, and up to ten policy candidates then receive separate 5,000-node
root searches. Node targets are UCI stopping requests, so Stockfish may slightly
overshoot them. Every search starts with cleared hash and FEN-only context.

The budget is deliberately a first-pass screen. Achieved depth is recorded;
none of these rows qualifies as a deeply verified puzzle. Later verification
must examine all legal moves and stability at higher depths.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
from pathlib import Path
import multiprocessing
from multiprocessing.util import Finalize
import time

import chess
import chess.engine

from mining_v2_engine import (DEFAULT_ENGINE, candidate_moves, probability_summary,
                              validated_policies, wdl_summary)
from mining_v3_io import check_manifest, completed_ids, digest, paired_rows, write_manifest

_WORKER_ENGINE = None
_WORKER_ARGS = None


def initialize_worker(args):
    global _WORKER_ENGINE, _WORKER_ARGS
    _WORKER_ARGS = args
    _WORKER_ENGINE = chess.engine.SimpleEngine.popen_uci(args.engine)
    _WORKER_ENGINE.configure({'Threads': 1, 'Hash': 32, 'UCI_ShowWDL': True})
    Finalize(None, _WORKER_ENGINE.quit, exitpriority=10)


def run_worker(pair):
    began = time.monotonic()
    result = inspect(_WORKER_ENGINE, *pair, _WORKER_ARGS)
    result['elapsed_seconds'] = time.monotonic() - began
    return result


def search_nodes(engine, board, nodes, roots=None, multipv=None):
    engine.configure({'Clear Hash': None})
    latest = {}
    exact_iterations = {}
    with engine.analysis(board, chess.engine.Limit(nodes=nodes),
                         root_moves=roots, multipv=multipv) as analysis:
        for update in analysis:
            index = update.get('multipv', 1)
            current = latest.setdefault(index, {})
            if 'score' in update:
                # python-chess' merged analyse() dictionaries can retain bounds
                # from an older score; each score event supersedes those flags.
                current.pop('lowerbound', None)
                current.pop('upperbound', None)
            current.update(update)
            if ('score' in update and current.get('pv') and
                    not current.get('lowerbound') and not current.get('upperbound')):
                exact_iterations.setdefault(current.get('depth', 0), {})[index] = current.copy()
    expected = multipv or 1
    completed = {depth: iteration for depth, iteration in exact_iterations.items()
                 if set(iteration) == set(range(1, expected+1)) and
                 len({info['pv'][0] for info in iteration.values()}) == expected}
    # A node stop can arrive during an aspiration retry. The last complete,
    # exact iteration still fits inside the same budget and is more useful than
    # treating the unfinished bound as an exact value or discarding all scores.
    selected = completed[max(completed)] if completed else latest
    search_nodes_used = max((info.get('nodes', 0) for info in latest.values()), default=0)
    search_seconds = max((info.get('time', 0.) for info in latest.values()), default=0.)
    results = []
    for index in sorted(selected):
        info = selected[index]
        if 'score' not in info:
            continue
        score = info['score'].pov(board.turn)
        current = board.copy(stack=False)
        pv = []
        for move in info.get('pv', [])[:12]:
            if move not in current.legal_moves:
                raise ValueError('Engine returned an illegal continuation')
            pv.append(move.uci())
            current.push(move)
        if not pv or (roots is not None and chess.Move.from_uci(pv[0]) not in roots):
            raise ValueError('Engine returned a missing or unexpected root continuation')
        lower, upper = bool(info.get('lowerbound')), bool(info.get('upperbound'))
        wdl = info.get('wdl')
        if wdl:
            wdl = wdl.pov(board.turn)
        results.append({'uci': pv[0], 'cp': score.score(), 'mate': score.mate(),
                        'depth': info.get('depth', 0), 'nodes': search_nodes_used,
                        'score_nodes': info.get('nodes'),
                        'node_budget': nodes, 'seconds': search_seconds, 'pv_uci': pv,
                        'lowerbound': lower, 'upperbound': upper,
                        'score_is_exact': not lower and not upper,
                        'score_selection': 'last_completed_exact_iteration' if completed else 'latest_reported_score',
                        'last_reported': {
                            'depth': latest[index].get('depth', 0),
                            'uci': latest[index]['pv'][0].uci() if latest[index].get('pv') else None,
                            'cp': latest[index]['score'].pov(board.turn).score(),
                            'mate': latest[index]['score'].pov(board.turn).mate(),
                            'lowerbound': bool(latest[index].get('lowerbound')),
                            'upperbound': bool(latest[index].get('upperbound'))},
                        'wdl': {'wins': wdl.wins, 'draws': wdl.draws, 'losses': wdl.losses} if wdl else None})
    if not results:
        raise ValueError('Engine returned no scored continuation')
    return results


def inspect(engine, row, policy, args):
    # Full history is not available for all historical observations. The primary
    # census therefore uses the same FEN-only context for both colours.
    board = chess.Board(row['fen'])
    if not board.is_valid():
        raise ValueError(f'{row["id"]}: invalid source FEN')
    legal = {move.uci() for move in board.legal_moves}
    if not legal:
        raise ValueError(f'{row["id"]}: terminal source FEN')
    policies = validated_policies(row, policy, legal)
    required = {f'maia3/fen_only/{rating}' for rating in (1400, 1700, 2000, 2300)}
    if set(policies) != required:
        raise ValueError(f'{row["id"]}: expected exactly the four common Maia3 FEN-only conditions')
    top = search_nodes(engine, board, args.top_nodes, multipv=min(3, len(legal)))
    roots = candidate_moves(board, top, policies, coverage=args.coverage, max_human=args.max_human)
    if row.get('played_move') in legal:
        roots.add(row['played_move'])
    scores = {move: search_nodes(engine, board, args.root_nodes,
                                roots=[chess.Move.from_uci(move)])[0]
              for move in sorted(roots)}
    # Bound-valued output is retained but cannot masquerade as an exact value
    # in acceptance sets, good-move probability or regret summaries.
    exact_scores = {move: value for move, value in scores.items() if value['score_is_exact']}
    numeric = [value for value in exact_scores.values() if value['cp'] is not None]
    best = max(numeric, key=lambda value: value['cp']) if numeric else None
    mate = any(value['mate'] is not None for value in [*top, *scores.values()])
    metrics = {key: {str(tolerance): probability_summary(exact_scores, probs, tolerance)
                     for tolerance in (20, 50)} for key, probs in policies.items()}
    return {'id': row['id'], 'fen': row['fen'], 'game_id': row.get('game_id'),
            'split': row.get('split'), 'side_to_move': 'white' if board.turn else 'black',
            'mode': 'fixed_node_screen', 'board_context': 'fen_only',
            'verified': False, 'legal_count': len(legal), 'top': top, 'scores': scores,
            'exhaustive': set(exact_scores) == legal,
            'all_scores_exact': all(value['score_is_exact'] for value in [*top, *scores.values()]),
            'has_mate': mate, 'best': best['uci'] if best else top[0]['uci'],
            'best_cp': best['cp'] if best else None, 'metrics': metrics,
            'wdl_sensitivity': {key: wdl_summary(exact_scores, probs) for key, probs in policies.items()},
            'engine_leader_probability': {key: probs[top[0]['uci']] for key, probs in policies.items()},
            'observed_played_is_top_engine_move': row.get('played_move') == top[0]['uci'],
            'search_nodes_total': max(value['nodes'] or 0 for value in top)
                                  + sum(value['nodes'] or 0 for value in scores.values())}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--policies', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--engine', default=str(DEFAULT_ENGINE))
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--top-nodes', type=int, default=30000)
    ap.add_argument('--root-nodes', type=int, default=5000)
    ap.add_argument('--max-human', type=int, default=10)
    ap.add_argument('--coverage', type=float, default=.85)
    ap.add_argument('--repair-partial', action='store_true')
    args = ap.parse_args()
    if min(args.workers, args.top_nodes, args.root_nodes) < 1 or args.max_human < 0 or not 0 < args.coverage <= 1:
        ap.error('Workers and node budgets must be positive; max-human >= 0; 0 < coverage <= 1')
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = {'input': str(Path(args.input).resolve()), 'input_sha256': digest(args.input),
                'policies': str(Path(args.policies).resolve()), 'policy_sha256': digest(args.policies),
                'engine_sha256': digest(args.engine), 'scorer_sha256': digest(__file__),
                'v2_helpers_sha256': digest(Path(__file__).with_name('mining_v2_engine.py')),
                'io_sha256': digest(Path(__file__).with_name('mining_v3_io.py')),
                'top_nodes': args.top_nodes, 'root_nodes': args.root_nodes,
                'max_human': args.max_human, 'coverage': args.coverage,
                'board_context': 'fen_only', 'engine_threads': 1, 'hash_mb': 32,
                'clear_hash_each_search': True, 'node_budget_interpretation': 'UCI node stopping target; slight overshoot possible'}
    manifest_path, previous = check_manifest(path, settings)
    done = completed_ids(path, args.repair_partial)
    resumed = len(done)
    manifest = {'settings': settings, 'started_at': previous['started_at'] if previous else time.time(),
                'complete': False, 'completed_n': len(done), 'verified_n': 0, 'workers': args.workers}
    write_manifest(manifest_path, manifest)
    seen = set()
    start = time.monotonic()

    def pending_pairs():
        for row, policy in paired_rows(args.input, args.policies):
            if row['id'] in seen:
                raise ValueError('Duplicate input ID')
            seen.add(row['id'])
            if row['id'] not in done:
                yield row, policy

    try:
        pairs = iter(pending_pairs())
        with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize_worker,
                                 initargs=(args,), mp_context=multiprocessing.get_context('spawn')) as pool, path.open('a') as destination:
            pending = set()
            exhausted = False
            while pending or not exhausted:
                while not exhausted and len(pending) < 2*args.workers:
                    pair = next(pairs, None)
                    if pair is None:
                        exhausted = True
                    else:
                        pending.add(pool.submit(run_worker, pair))
                if not pending:
                    break
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    result = future.result()
                    destination.write(json.dumps(result, separators=(',', ':')) + '\n')
                    destination.flush()
                    done.add(result['id'])
                if len(done)//256 != manifest['completed_n']//256 or not pending and exhausted:
                    manifest.update(completed_n=len(done), updated_at=time.time(),
                                    elapsed_current_run_seconds=time.monotonic()-start)
                    write_manifest(manifest_path, manifest)
                    print(json.dumps({'completed': len(done), 'new': len(done)-resumed,
                                      'seconds': round(time.monotonic()-start, 2)}), flush=True)
        if done != seen:
            raise ValueError('Completed output contains IDs absent from the input')
        manifest.update(complete=True, input_n=len(seen))
    finally:
        manifest.update(completed_n=len(done), finished_at=time.time(),
                        elapsed_current_run_seconds=time.monotonic()-start)
        write_manifest(manifest_path, manifest)


if __name__ == '__main__':
    main()
