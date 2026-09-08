"""Resumable Stockfish 18 screening and exhaustive, two-depth item verification.

Screening is explicitly approximate. Only complete depth-20/24 legal-move
searches with stable acceptance sets qualify as verified material.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import threading
import time

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENGINE = ROOT / 'models/stockfish18/stockfish/stockfish-macos-m1-apple-silicon'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def board_for(row):
    if row.get('history_available', True) and row.get('initial_fen'):
        board = chess.Board(row['initial_fen'])
        if not board.is_valid():
            raise ValueError(f'{row["id"]}: invalid initial board')
        for uci in row.get('history_uci', []):
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError(f'{row["id"]}: illegal source history')
            board.push(move)
        if board.fen() != chess.Board(row['fen']).fen():
            raise ValueError(f'{row["id"]}: history does not reach the supplied FEN')
        return board
    board = chess.Board(row['fen'])
    if not board.is_valid():
        raise ValueError(f'{row["id"]}: invalid source board')
    return board


def policy_maps(policy):
    out = {}
    for model in ('maia3', 'maia2'):
        data = policy.get(model, {})
        if not isinstance(data, dict):
            raise ValueError(f'{model}: policy data must be an object')
        if model == 'maia3' or 'fen_only' in data or 'history' in data:
            for condition in ('history', 'fen_only'):
                ratings = data.get(condition, {})
                if not isinstance(ratings, dict):
                    raise ValueError(f'{model}/{condition}: ratings must be an object')
                for rating, probs in ratings.items():
                    out[f'{model}/{condition}/{rating}'] = probs
        else:
            for rating, probs in data.items():
                out[f'{model}/fen_only/{rating}'] = probs
    return out


def validated_policies(row, policy, legal):
    if not policy:
        return {}
    if policy.get('id') != row['id']:
        raise ValueError(f'{row["id"]}: policy ID does not match the source')
    try:
        matches = chess.Board(policy['fen']).fen() == chess.Board(row['fen']).fen()
    except (KeyError, ValueError, TypeError):
        matches = False
    if not matches:
        raise ValueError(f'{row["id"]}: policy FEN does not match the source')
    if ('history_available' in policy and
            policy['history_available'] != row.get('history_available', True)):
        raise ValueError(f'{row["id"]}: policy history availability does not match the source')
    policies = policy_maps(policy)
    if not policies:
        raise ValueError(f'{row["id"]}: supplied policy row contains no usable distributions')
    for name, probs in policies.items():
        if (not isinstance(probs, dict) or set(probs) != legal or
                any(isinstance(p, bool) or not isinstance(p, (int, float)) or
                    not math.isfinite(p) or p < 0 or p > 1 for p in probs.values()) or
                abs(sum(probs.values()) - 1.) > 1e-5):
            raise ValueError(f'{row["id"]}: {name} must give finite nonnegative probabilities for every legal move and sum to one')
    return policies


def wdl_summary(scores, probs):
    """Expected engine self-play score sensitivity, never a human win forecast."""
    values = {}
    for move, result in scores.items():
        wdl = result.get('wdl')
        if wdl and sum(wdl.values()) > 0:
            values[move] = (wdl['wins'] + .5*wdl['draws']) / sum(wdl.values())
    if not values:
        return {'available': False}
    best = max(values.values())
    mass = sum(probs.get(m, 0.) for m in values)
    tail = max(0., 1.-mass)
    loss = sum(probs.get(m, 0.) * max(0., best-v) for m, v in values.items())
    complete = set(probs) <= set(values)
    return {'available': True, 'interpretation': 'Stockfish self-play expected-score loss; not human win probability',
            'conditional_on_observed_reference': True, 'all_policy_moves_scored': complete,
            'reference_expected_score': best, 'unscored_mass': tail,
            'loss_lower': loss, 'loss_upper': loss + best*tail if complete else 1.,
            'conditional_loss_upper': loss + best*tail}


def probability_summary(scores, probs, tolerance=20, loss_cap=300):
    """Bounds conditional on the best numeric value encountered, no tail renormalization.

    Regret is capped at 300cp. A losing mate has maximal capped regret, but its
    score remains mate-valued; a winning mate prevents numeric summaries.
    """
    numeric = {m: v['cp'] for m, v in scores.items() if v.get('cp') is not None}
    if not numeric or any(v.get('mate') is not None and v['mate'] > 0 for v in scores.values()):
        return {'available': False, 'reason': 'winning_mate_or_no_numeric_reference'}
    best = max(numeric.values())
    good = {m for m, cp in numeric.items() if best - cp <= tolerance}
    measured_mass = sum(probs.get(m, 0.) for m in scores)
    unmeasured = max(0., 1. - measured_mass)
    good_mass = sum(probs.get(m, 0.) for m in good)
    known_loss = sum(probs.get(m, 0.) * min(loss_cap, max(0., best-cp)) for m, cp in numeric.items())
    known_loss += sum(probs.get(m, 0.) * loss_cap for m, v in scores.items()
                      if v.get('cp') is None and v.get('mate') is not None and v['mate'] <= 0)
    complete = set(probs) <= set(scores)
    return {'available': True, 'reference': 'best_numeric_root_score_encountered',
            'conditional_on_observed_reference': True, 'all_policy_moves_scored': complete,
            'reference_cp': best, 'tolerance_cp': tolerance, 'acceptable': sorted(good),
            'evaluated_mass': measured_mass, 'unscored_mass': unmeasured,
            'p_good_lower': good_mass if complete else 0., 'p_good_upper': min(1., good_mass+unmeasured),
            'conditional_p_good_lower': good_mass,
            'capped_regret_lower_cp': known_loss,
            'capped_regret_upper_cp': known_loss+loss_cap*unmeasured if complete else loss_cap,
            'conditional_capped_regret_upper_cp': known_loss+loss_cap*unmeasured,
            'regret_cap_cp': loss_cap}


def search(engine, board, depth, seconds, roots=None, multipv=None):
    engine.configure({'Clear Hash': None})
    infos = engine.analyse(board, chess.engine.Limit(depth=depth, time=seconds),
                           root_moves=roots, multipv=multipv)
    if not isinstance(infos, list):
        infos = [infos]
    results = []
    for info in infos:
        score = info['score'].pov(board.turn)
        b = board.copy(); pv = []
        for move in info.get('pv', [])[:20]:
            if move not in b.legal_moves:
                raise ValueError('Engine returned an illegal continuation')
            pv.append({'uci': move.uci(), 'san': b.san(move)}); b.push(move)
        if not pv or (roots is not None and chess.Move.from_uci(pv[0]['uci']) not in roots):
            raise ValueError('Engine returned a missing or unexpected root continuation')
        lowerbound, upperbound = bool(info.get('lowerbound')), bool(info.get('upperbound'))
        wdl = info.get('wdl')
        if wdl:
            wdl = wdl.pov(board.turn)
        results.append({'uci': pv[0]['uci'] if pv else None,
                        'cp': score.score(), 'mate': score.mate(),
                        'depth': info.get('depth', 0), 'target_depth': depth,
                        'reached_target': info.get('depth', 0) >= depth,
                        'lowerbound': lowerbound, 'upperbound': upperbound,
                        'score_is_exact': not lowerbound and not upperbound,
                        'nodes': info.get('nodes'), 'seconds': info.get('time'), 'pv': pv,
                        'wdl': {'wins': wdl.wins, 'draws': wdl.draws, 'losses': wdl.losses} if wdl else None})
    return results


def candidate_moves(board, top, policies, coverage=.85, max_human=12):
    required = {x['uci'] for x in top if x['uci']}
    ranked = {}
    for probs in policies.values():
        mass = 0.
        for move, p in sorted(probs.items(), key=lambda x: (-x[1], x[0])):
            ranked[move] = max(ranked.get(move, 0.), p)
            mass += p
            if mass >= coverage:
                break
    for move, _ in sorted(ranked.items(), key=lambda x: (-x[1], x[0]))[:max_human]:
        required.add(move)
    legal = {m.uci() for m in board.legal_moves}
    if not required <= legal:
        raise ValueError('Human policy contains illegal candidate moves')
    return required


def inspect(engine, row, policy, args):
    board = board_for(row)
    if board.is_game_over():
        return {'id': row['id'], 'fen': row['fen'], 'error': 'terminal_position'}
    legal = {m.uci() for m in board.legal_moves}
    policies = validated_policies(row, policy, legal)
    out = {'id': row['id'], 'fen': row['fen'], 'game_id': row['game_id'],
           'split': row.get('split'), 'mode': args.mode, 'legal_count': len(legal)}
    if args.mode == 'screen':
        top = search(engine, board, args.screen_depth, args.screen_seconds, multipv=min(3, len(legal)))
        roots = candidate_moves(board, top, policies, args.coverage, args.max_human)
        if row.get('played_move') in legal:
            roots.add(row['played_move'])
        scores = {move: search(engine, board, args.screen_depth, args.root_seconds,
                              roots=[chess.Move.from_uci(move)])[0] for move in sorted(roots)}
        out.update(top=top, scores=scores, exhaustive=set(scores)==legal,
                   all_searches_reached_target=all(s['reached_target'] for s in [*top, *scores.values()]),
                   all_scores_exact=all(s['score_is_exact'] for s in [*top, *scores.values()]))
        out['metrics'] = {key: {str(tol): probability_summary(scores, probs, tol)
                              for tol in (20, 50)} for key, probs in policies.items()}
        out['wdl_sensitivity'] = {key: wdl_summary(scores, probs) for key, probs in policies.items()}
        numeric = [s for s in scores.values() if s['cp'] is not None]
        out['best'] = max(numeric, key=lambda x:x['cp'])['uci'] if numeric else top[0]['uci']
        out['best_cp'] = max((s['cp'] for s in numeric), default=None)
        out['has_mate'] = any(s['mate'] is not None for s in scores.values())
    else:
        by_depth = {}
        for depth in (20, 24):
            by_depth[str(depth)] = {move: search(engine, board, depth, args.deep_seconds,
                                       roots=[chess.Move.from_uci(move)])[0] for move in sorted(legal)}
        out['searches'] = by_depth
        out['exhaustive'] = True
        out['all_searches_reached_target'] = all(s['reached_target'] for d in by_depth.values() for s in d.values())
        out['all_scores_exact'] = all(s['score_is_exact'] for d in by_depth.values() for s in d.values())
        out['has_mate'] = any(s['mate'] is not None for d in by_depth.values() for s in d.values())
        out['accepted'] = {}
        for depth, scores in by_depth.items():
            nums = {m: s['cp'] for m, s in scores.items() if s['cp'] is not None}
            best = max(nums.values(), default=None)
            out['accepted'][depth] = sorted(m for m, cp in nums.items() if best-cp <= 20) if best is not None else []
        out['stable_acceptance'] = out['accepted']['20'] == out['accepted']['24'] and bool(out['accepted']['24'])
        out['verified'] = (out['all_searches_reached_target'] and out['all_scores_exact']
                           and not out['has_mate'] and out['stable_acceptance'])
        out['metrics'] = {key: {depth: {str(tol): probability_summary(scores, probs, tol)
                                     for tol in (20, 50)} for depth, scores in by_depth.items()}
                          for key, probs in policies.items()}
        out['wdl_sensitivity'] = {key: {depth: wdl_summary(scores, probs)
                                      for depth, scores in by_depth.items()} for key, probs in policies.items()}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True); ap.add_argument('--policies')
    ap.add_argument('--output', required=True); ap.add_argument('--engine', default=str(DEFAULT_ENGINE))
    ap.add_argument('--mode', choices=['screen', 'deep'], default='screen')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--screen-depth', type=int, default=16)
    ap.add_argument('--screen-seconds', type=float, default=.5)
    ap.add_argument('--root-seconds', type=float, default=.2)
    ap.add_argument('--deep-seconds', type=float, default=5.)
    ap.add_argument('--coverage', type=float, default=.85)
    ap.add_argument('--max-human', type=int, default=10)
    args = ap.parse_args()
    rows = load_jsonl(args.input)
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate input IDs')
    policy_rows = load_jsonl(args.policies) if args.policies else []
    if len({r['id'] for r in policy_rows}) != len(policy_rows):
        raise ValueError('Duplicate policy IDs')
    policies = {r['id']: r for r in policy_rows}
    if args.policies and not {r['id'] for r in rows} <= policies.keys():
        raise ValueError('Missing policies for input positions')
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = path.with_suffix('.manifest.json')
    settings = vars(args).copy(); settings.update(engine_sha256=digest(args.engine),
                 scorer_sha256=digest(__file__),
                 input_sha256=digest(args.input), policy_sha256=digest(args.policies) if args.policies else None,
                 engine_threads=1, hash_mb=64, clear_hash_each_search=True)
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous['settings'] != settings:
            raise ValueError('Cache settings changed; choose a new output file')
    elif path.exists():
        raise ValueError('Output exists without a matching manifest')
    manifest = {'settings': settings, 'started_at': previous['started_at'] if manifest_path.exists() else time.time(),
                'complete': False, 'input_n':len(rows)}
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    done = {r['id']: r for r in load_jsonl(path)} if path.exists() else {}
    local = threading.local(); engines=[]; lock=threading.Lock()
    def run(row):
        if not hasattr(local, 'engine'):
            local.engine = chess.engine.SimpleEngine.popen_uci(args.engine)
            local.engine.configure({'Threads':1, 'Hash':64, 'UCI_ShowWDL':True})
            with lock: engines.append(local.engine)
        start = time.monotonic()
        result = inspect(local.engine, row, policies.get(row['id'], {}), args)
        result['elapsed_seconds'] = time.monotonic()-start
        return result
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool, path.open('a') as out:
            pending = {pool.submit(run, r):r for r in rows if r['id'] not in done}
            for future in as_completed(pending):
                result = future.result()
                out.write(json.dumps(result)+'\n'); out.flush(); done[result['id']]=result
                if len(done)%20==0 or len(done)==len(rows):
                    print(json.dumps({'completed':len(done),'total':len(rows),'mode':args.mode}),flush=True)
    finally:
        for engine in engines:
            engine.quit()
        manifest.update(finished_at=time.time(), complete=len(done)==len(rows), completed_n=len(done),
                        verified_n=sum(bool(r.get('verified')) for r in done.values()))
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')


if __name__ == '__main__':
    main()
