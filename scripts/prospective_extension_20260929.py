"""Separate, post-baseline two-root supplement; never rewrites frozen baseline evidence.

One 120-second opportunity per remaining root, with interrupted opportunities
resumable in at most six invocations. This is an outcome-authorized supplement,
not a change to the original 30-second protocol or an independent test set.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager, ExitStack
import copy
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prospective_analysis_20260916 as base

ROOT = base.ROOT
BASE = ROOT / 'data/mining_v3/prospective-analysis-20260916'
OUTPUT = ROOT / 'data/mining_v3/prospective-extension-20260929'
PUBLIC = ROOT / 'results/prospective_extension_20260929.json'
BASE_SCRIPT_SHA = 'c1b9011d6a319733d1422b4882961e79a736594710c5207293dedd4f986d5261'
BASE_PLAN_SHA = 'b0bb870524bb4be5016de18734af8c42b1ebb8e4f7bac4a5b8f9c82c3e452ff3'
HELPER_SHA = '3579e95e94afee1900da2614e879705a2d9d6a620c6db842c7f97026ebadc56b'
PROTOCOL = {
    'selected_roots_n': 2, 'requested_depth': 24, 'per_root_seconds': 120,
    'per_invocation_wall_seconds': 600, 'max_invocations': 6,
    'engine_threads': 1, 'engine_hash_mb': 64, 'clear_hash_each_search': True,
    'engine_stop_grace_seconds': 2, 'power_policy': 'confirmed AC before and during searches',
    'selection': 'all and only the two unfinished roots in the stopped frozen baseline',
    'retry_policy': 'one full capped attempt per root; only power/user/wall interruptions may resume',
    'authorization_timing': 'authorized after inspecting baseline outcomes on 29 September 2026',
    'baseline_authoritative': True, 'model_inference': False,
}
BASE_FILES = ('plan.json', 'inputs.json', 'model_runtime.json', 'engine_runtime.json',
              'model_controls.json', 'evidence_inventory.json', 'aggregate.json',
              'analysis_rows.json', 'status.json', 'continuation_status.json', 'continue_bounded.py')
COMPLETE = ('complete_numeric', 'mate_score')
INTERRUPTIONS = ('power_pause', 'user_stop', 'invocation_wall_cap')


def read(path):
    return json.loads(Path(path).read_text())


def safe_output(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT / 'data/mining_v3') or not path.name.startswith('prospective-extension-'):
        raise ValueError('Supplement output must be a separate private prospective-extension directory')
    if path == BASE or path.is_relative_to(BASE) or BASE.is_relative_to(path):
        raise ValueError('Never use the baseline directory for supplementary output')
    if subprocess.run(['git', 'check-ignore', '-q', str(path / 'manifest.json')], cwd=ROOT).returncode:
        raise ValueError('Supplement evidence must be ignored by git')
    if subprocess.check_output(['git', 'ls-files', '--', str(path)], cwd=ROOT, text=True).strip():
        raise ValueError('Supplement output contains tracked files')
    return path


@contextmanager
def locks(output=None):
    """Opening existing base lock files read-only changes no baseline file bytes."""
    with ExitStack() as stack:
        for name in ('.continuation.lock', '.run.lock'):
            handle = stack.enter_context((BASE / name).open('rb'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('Frozen baseline has an active writer') from error
        if output is not None:
            handle = stack.enter_context((output / '.extension.lock').open('a+'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('Supplement already has an active writer') from error
        yield


def write_once(path, value):
    """Atomically publish immutable evidence without ever replacing an existing file."""
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('xb') as handle:
        handle.write(base.encoded(value)); handle.flush(); os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def dependency_hashes():
    # Includes transitively imported project helpers without importing any models.
    files = {Path(base.__file__).resolve(), Path(__file__).resolve(), ROOT / 'scripts/mining_v2_policy.py'}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(ROOT / 'scripts') and path.suffix == '.py':
                files.add(path)
    return {str(path.relative_to(ROOT)): base.digest(path) for path in sorted(files)}


def role_summaries(rows, policies, roots):
    values = [base.position_result(row, roots[row['id']], policies.get(row['id'])) for row in rows]
    summary = {}
    for role in base.ROLES:
        group = [v for v in values if v['role'] == role]
        verified = [v for v in group if v['verified_for_calibration']]
        players = Counter(p for row in rows if row['analysis_role'] == role
                          for p in row.get('player_hashes', {}).values() if p)
        entry = {'selected_n': len(group), 'policy_completed_n': sum(v['model_policy_available'] for v in group),
                 'state_counts': dict(Counter(v['state'] for v in group)), 'verified_calibration_n': len(verified),
                 'root_status_counts': dict(sum((Counter(v['root_status_counts']) for v in group), Counter())),
                 'known_players_n': len(players), 'players_repeated_across_games_n': sum(n > 1 for n in players.values())}
        if role != 'targeted_endgame':
            entry['calibration'] = {c: base.calibration_metrics([
                (v['metrics'][c]['actual']['p_acceptable'], v['observed_move_acceptable']) for v in verified])
                for c in ('history', 'fen_only')}
        else:
            approximate = [v for v in group if v['state'] == 'approximate_targeted_screen' and v['model_policy_available']]
            entry['approximate_screen_with_policy_n'] = len(approximate)
            entry['history_fixed1700_to2000_probability_increases_n'] = sum(
                v['metrics']['history']['fixed2000']['p_acceptable'] > v['metrics']['history']['fixed1700']['p_acceptable']
                for v in approximate)
        summary[role] = entry
    return summary


def select_unfinished(rows, roots):
    tasks = []
    for row in rows:
        for depth in base.depths_for(row):
            for move in sorted(m.uci() for m in chess.Board(row['fen']).legal_moves):
                result = roots[row['id']].get(str(depth), {}).get(move)
                if result is None:
                    raise ValueError('Baseline still has unattempted roots')
                if result['status'] not in COMPLETE:
                    if depth != 24 or result['status'] != 'capped_or_interrupted':
                        raise ValueError('Unexpected unfinished baseline evidence')
                    tasks.append({'record_id': row['id'], 'depth': depth, 'move': move,
                                  'key': base.task_key(row, depth, move)})
    tasks.sort(key=lambda task: task['key'])
    if len(tasks) != 2:
        raise ValueError('Supplement must select exactly the two unfinished baseline roots')
    return tasks


def baseline_snapshot():
    if base.digest(base.__file__) != BASE_SCRIPT_SHA or base.digest(BASE / 'plan.json') != BASE_PLAN_SHA:
        raise ValueError('Frozen baseline script or plan changed')
    if base.digest(BASE / 'continue_bounded.py') != HELPER_SHA:
        raise ValueError('Baseline supervisor changed')
    if read(BASE / 'continuation_status.json')['state'] != 'needs_review':
        raise ValueError('Baseline must remain stopped for review')
    if read(BASE / 'status.json')['status'] != 'pass_complete_with_incomplete_roots':
        raise ValueError('Unexpected frozen baseline status')
    plan, rows = base.load_plan(BASE)
    engine_runtime = read(BASE / 'engine_runtime.json')
    if (engine_runtime['python_chess'] != chess.__version__ or engine_runtime['threads'] != 1
            or engine_runtime['hash_mb'] != 64 or engine_runtime['clear_hash_each_search'] is not True
            or engine_runtime['script_sha256'] != BASE_SCRIPT_SHA):
        raise ValueError('Engine runtime differs from frozen protocol')
    model_runtime = read(BASE / 'model_runtime.json')
    if (model_runtime['script_sha256'] != BASE_SCRIPT_SHA
            or any(model_runtime['model'].get(k) != v for k, v in base.MODEL.items())):
        raise ValueError('Saved model runtime differs from pinned baseline model')
    policies, roots, inventory = base.load_saved(BASE, plan, rows)
    controls = base.verified_model_controls(BASE, rows)
    if len(rows) != 64 or len(policies) != 64 or not controls or not controls['passed']:
        raise ValueError('Baseline coverage or model controls are incomplete')
    aggregate = read(BASE / 'aggregate.json')
    if inventory != read(BASE / 'evidence_inventory.json') or base.fingerprint(inventory) != aggregate['fingerprints']['evidence_inventory_sha256']:
        raise ValueError('Frozen baseline evidence inventory differs')
    if len(inventory) != aggregate['fingerprints']['evidence_files_n']:
        raise ValueError('Frozen baseline evidence file count differs')
    summaries = role_summaries(rows, policies, roots)
    if summaries != aggregate['by_role']:
        raise ValueError('Frozen baseline aggregate does not match evidence')
    fingerprints = {name: base.digest(BASE / name) for name in BASE_FILES}
    fingerprints['evidence_content_sha256'] = base.fingerprint(inventory)
    public_baseline = ROOT / 'results/prospective_analysis_20260916.json'
    if read(public_baseline) != aggregate:
        raise ValueError('Public baseline differs from frozen private aggregate')
    fingerprints['public_baseline_sha256'] = base.digest(public_baseline)
    return {'rows': rows, 'policies': policies, 'roots': roots, 'controls': controls,
            'by_role': summaries, 'fingerprints': fingerprints, 'tasks': select_unfinished(rows, roots)}


def prepare(output=OUTPUT):
    output = safe_output(output)
    if output.exists():
        raise FileExistsError('Never overwrite a prepared supplement')
    with locks():
        snapshot = baseline_snapshot()
        manifest = {'schema_version': 1, 'created_utc': base.now(), 'protocol': PROTOCOL,
                    'base_fingerprints': snapshot['fingerprints'], 'dependencies': dependency_hashes(),
                    'tasks': snapshot['tasks'], 'selection_sha256': base.fingerprint(snapshot['tasks'])}
        output.mkdir(parents=True)
        for name in ('attempts', 'reservations', 'invocations'):
            (output / name).mkdir()
        write_once(output / 'manifest.json', manifest)
        checkpoint(output, 'prepared', 0)
        return report_locked(output)


def load_manifest(output):
    manifest = read(output / 'manifest.json')
    if manifest['protocol'] != PROTOCOL or manifest['dependencies'] != dependency_hashes():
        raise ValueError('Supplement protocol or dependencies changed')
    snapshot = baseline_snapshot()
    if manifest['base_fingerprints'] != snapshot['fingerprints']:
        raise ValueError('Frozen baseline changed after supplement preparation')
    if manifest['tasks'] != snapshot['tasks'] or manifest['selection_sha256'] != base.fingerprint(snapshot['tasks']):
        raise ValueError('Frozen supplemental selection changed')
    return manifest, snapshot


def consumes_opportunity(result):
    if result['status'] in COMPLETE:
        return True
    # A genuinely full cap consumes the opportunity even if power drops at its end.
    if result.get('wall_seconds', 0) >= PROTOCOL['per_root_seconds'] - .01:
        return True
    # UCI may return slightly before its assigned time. Never reward an early
    # ordinary/errored return with another full attempt; stop for review instead.
    return result.get('stop_reason') not in INTERRUPTIONS


def load_attempts(output, manifest, snapshot):
    attempts = defaultdict(list)
    inventory = {}
    task_by_key = {task['key']: task for task in manifest['tasks']}
    rows = {row['id']: row for row in snapshot['rows']}
    invocations = sorted((output / 'invocations').glob('*.json'))
    if len(invocations) > PROTOCOL['max_invocations']:
        raise ValueError('Supplement exceeded its invocation limit')
    manifest_hash = base.digest(output / 'manifest.json')
    for n, path in enumerate(invocations, 1):
        value = read(path)
        if path.stem != f'{n:04d}' or value['number'] != n or value['manifest_sha256'] != manifest_hash:
            raise ValueError('Invalid invocation ledger')
        inventory[str(path.relative_to(output))] = base.digest(path)
    dangling = 0
    for path in sorted((output / 'reservations').glob('*.json')):
        reservation = read(path); key = reservation['task_key']; task = task_by_key.get(key)
        if task is None or reservation['manifest_sha256'] != manifest_hash or not 1 <= reservation['invocation'] <= len(invocations):
            raise ValueError('Unknown or changed reserved task')
        n = reservation['attempt_number']
        if path.stem != f'{key}-{n:04d}' or n != len(attempts[key]) + 1:
            raise ValueError('Supplement attempts are missing or out of order')
        if attempts[key] and consumes_opportunity(attempts[key][-1]):
            raise ValueError('A consumed capped opportunity was retried')
        inventory[str(path.relative_to(output))] = base.digest(path)
        result_path = output / 'attempts' / path.name
        if not result_path.exists():
            dangling += 1
            continue
        value = read(result_path)
        if value['manifest_sha256'] != manifest_hash or value['reservation_sha256'] != base.digest(path):
            raise ValueError('Attempt evidence is not bound to its frozen reservation')
        result = value['result']
        if result.get('per_root_cap_seconds') != 120 or result.get('attempt_number') != n:
            raise ValueError('Supplement attempt cap or sequence changed')
        status = base.evidence_status(rows[task['record_id']], result, task['depth'], task['move'])
        if status != result['status']:
            raise ValueError('Supplement attempt status differs from evidence')
        attempts[key].append(result)
        inventory[str(result_path.relative_to(output))] = base.digest(result_path)
    if len(list((output / 'attempts').glob('*.json'))) != sum(map(len, attempts.values())):
        raise ValueError('Supplement contains unreserved attempt evidence')
    return attempts, inventory, len(invocations), dangling


def combine(snapshot, tasks, attempts):
    combined = copy.deepcopy(snapshot['roots'])
    for task in tasks:
        saved = attempts.get(task['key'], [])
        if saved and saved[-1]['status'] in COMPLETE:
            combined[task['record_id']][str(task['depth'])][task['move']] = saved[-1]
    return combined


def checkpoint(output, status, invocations):
    base.atomic_json(output / 'status.json', {'status': status, 'invocation_count': invocations,
                                             'updated_utc': base.now()})


def report_locked(output, loaded=None):
    manifest, snapshot = loaded or load_manifest(output)
    attempts, inventory, count, dangling = load_attempts(output, manifest, snapshot)
    completed = sum(bool(attempts.get(t['key'])) and attempts[t['key']][-1]['status'] in COMPLETE for t in manifest['tasks'])
    exhausted = sum(bool(attempts.get(t['key'])) and attempts[t['key']][-1]['status'] not in COMPLETE
                    and consumes_opportunity(attempts[t['key']][-1]) for t in manifest['tasks'])
    status = read(output / 'status.json')['status']
    errors = any(v and v[-1]['status'] == 'engine_error' for v in attempts.values())
    if completed == 2:
        status = 'searches_complete'
    elif dangling or errors or status in ('needs_review', 'failed'):
        status = 'needs_review'
    elif completed + exhausted == 2:
        status = 'cap_exhausted'
    elif count >= 6 and status != 'running_engine':
        status = 'invocation_limit'
    elif status == 'running_engine':
        status = 'running_engine' if loaded is not None else 'interrupted_without_final_checkpoint'
    supplemented = role_summaries(snapshot['rows'], snapshot['policies'], combine(snapshot, manifest['tasks'], attempts))
    value = {'schema_version': 1, 'analysis': 'post-baseline capped-search supplement',
             'generated_utc': base.now(), 'status': status, 'selected_roots_n': 2,
             'completed_roots_n': completed, 'incomplete_roots_n': 2 - completed,
             'exhausted_roots_n': exhausted, 'unresolved_reservations_n': dangling,
             'invocation_count': count, 'max_invocations': 6, 'protocol': PROTOCOL,
             'base_fingerprints': manifest['base_fingerprints'],
             'extension_fingerprints': {'manifest_sha256': base.digest(output / 'manifest.json'),
                 'script_sha256': base.digest(__file__), 'selection_sha256': manifest['selection_sha256'],
                 'evidence_inventory_sha256': base.fingerprint(inventory), 'evidence_files_n': len(inventory)},
             'controls': snapshot['controls'], 'baseline_by_role': snapshot['by_role'],
             'supplemented_by_role': supplemented, 'trainer_ready_n': 0,
             'limitations': ['Separate supplement authorized after baseline outcomes were observed; not preregistered or an independent replication.',
                 'The original 30-second-cap baseline remains authoritative and unchanged; supplemented results must be labelled separately.',
                 'Only exact requested-depth completed supplemental roots are combined in memory; incomplete or bound evidence is never promoted.',
                 'Development and evaluation remain separate small source-game samples, not human puzzle calibration or evidence of learning.',
                 'Mate-valued and unstable positions remain excluded from calibration; targeted depth-14 endgames remain approximate.',
                 'No new model inference, probability fitting, source positions, trainer release or teaching approval.']}
    base.atomic_json(output / 'evidence_inventory.json', inventory)
    base.atomic_json(output / 'aggregate.json', value)
    base.atomic_json(PUBLIC, value)
    return value


def report(output=OUTPUT):
    output = safe_output(output)
    with locks(output):
        return report_locked(output)


def supplemental_search(engine, row, task, deadline, stop):
    """Dedicated cap and watchdog; the frozen baseline PLAN is never modified."""
    started = time.monotonic()
    board = chess.Board(row['fen'])
    result = {'record_id': row['id'], 'fen': row['fen'], 'target_depth': task['depth'],
              'requested_root': task['move'], 'board_context': 'fen_only', 'per_root_cap_seconds': 120}
    done, power_lost, reasons = threading.Event(), threading.Event(), []
    analysis, watcher, power_watcher, latest, caught = None, None, None, {}, None
    try:
        engine.configure({'Clear Hash': None})
        analysis = engine.analysis(board, chess.engine.Limit(depth=task['depth'], time=120),
                                   root_moves=[chess.Move.from_uci(task['move'])])
        def watch_power():
            # Power inspection may take several seconds; it must never block
            # the independent deadline/SIGTERM/engine-stop watchdog.
            while not done.is_set():
                if base.power_state() != 'ac':
                    power_lost.set(); return
                if done.wait(.5): return
        power_watcher = threading.Thread(target=watch_power, daemon=True)
        power_watcher.start()
        def watch():
            stopped = None
            while not done.wait(.2):
                now = time.monotonic()
                if stopped is None:
                    reason = ('root_cap' if now >= started + 120 else
                              'invocation_wall_cap' if now >= deadline else
                              'user_stop' if stop.is_set() else
                              'power_pause' if power_lost.is_set() else None)
                    if reason:
                        reasons.append(reason)
                        stopped = (started + 120 if reason == 'root_cap' else
                                   deadline if reason == 'invocation_wall_cap' else now)
                        try: analysis.stop()
                        except (RuntimeError, chess.engine.EngineError): pass
                elif now - stopped >= 2:
                    engine.close(); break
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        for update in analysis:
            if 'score' in update:
                latest = {k: update.get(k) for k in ('score', 'depth', 'pv', 'nodes', 'lowerbound', 'upperbound')}
    except Exception as error:
        caught = type(error).__name__
    finally:
        done.set()
        if watcher is not None:
            watcher.join(timeout=3)
        if power_watcher is not None:
            power_watcher.join(timeout=.01)
        if analysis is not None:
            try: analysis.stop()
            except (RuntimeError, chess.engine.EngineError): pass
        result['stop_reason'] = reasons[0] if reasons else None
        result['wall_seconds'] = time.monotonic() - started
    if latest:
        try:
            score = latest['score'].pov(board.turn)
            replay, pv = board.copy(), []
            for action in (latest.get('pv') or [])[:20]:
                if action not in replay.legal_moves:
                    raise ValueError('Illegal engine continuation')
                pv.append({'uci': action.uci(), 'san': replay.san(action)}); replay.push(action)
            depth = latest.get('depth') or 0
            result.update(cp=score.score(), mate=score.mate(), depth=depth, reached_target=depth >= task['depth'],
                          lowerbound=bool(latest.get('lowerbound')), upperbound=bool(latest.get('upperbound')),
                          score_is_exact=not latest.get('lowerbound') and not latest.get('upperbound'),
                          nodes=latest.get('nodes'), pv=pv)
        except Exception as error:
            result['error'] = type(error).__name__
    elif result['stop_reason'] in INTERRUPTIONS:
        result.update(depth=0, reached_target=False)
    else:
        result['error'] = caught or 'NoScoredContinuation'
    if caught and result['stop_reason'] not in INTERRUPTIONS and result.get('depth', 0) < task['depth']:
        result['error'] = caught
    result['status'] = base.evidence_status(row, result, task['depth'], task['move'])
    return result


def run_locked(output, stop):
    started = time.monotonic(); deadline = started + 600
    loaded = load_manifest(output); manifest, snapshot = loaded
    attempts, _, count, dangling = load_attempts(output, manifest, snapshot)
    def finish(status):
        checkpoint(output, status, count)
        return report_locked(output, loaded)
    if dangling:
        return finish('needs_review')
    pending = [t for t in manifest['tasks'] if not attempts.get(t['key']) or not consumes_opportunity(attempts[t['key']][-1])]
    if any(v and v[-1]['status'] == 'engine_error' for v in attempts.values()):
        return finish('needs_review')
    if not pending:
        return finish('searches_complete' if all(attempts[t['key']][-1]['status'] in COMPLETE for t in manifest['tasks']) else 'cap_exhausted')
    if read(output / 'status.json')['status'] in ('needs_review', 'failed'):
        return finish('needs_review')
    if count >= 6:
        return finish('invocation_limit')
    if stop.is_set():
        return finish('stopped')
    if base.power_state() != 'ac':
        return finish('paused_power')
    count += 1
    write_once(output / 'invocations' / f'{count:04d}.json', {'number': count, 'created_utc': base.now(),
                                                          'manifest_sha256': base.digest(output / 'manifest.json')})
    checkpoint(output, 'running_engine', count)
    engine = None
    try:
        engine = chess.engine.SimpleEngine.popen_uci(str(base.DEFAULT_ENGINE), timeout=5)
        if engine.id != read(BASE / 'engine_runtime.json')['engine_id']:
            raise ValueError('Supplement engine identity differs from baseline')
        engine.configure({'Threads': 1, 'Hash': 64})
        rows = {row['id']: row for row in snapshot['rows']}
        for task in pending:
            if stop.is_set(): return finish('stopped')
            if base.power_state() != 'ac': return finish('paused_power')
            if time.monotonic() + 122 > deadline: return finish('paused_wall_cap')
            n = len(attempts.get(task['key'], [])) + 1
            filename = f"{task['key']}-{n:04d}.json"
            reservation_path = output / 'reservations' / filename
            write_once(reservation_path, {'task_key': task['key'], 'attempt_number': n, 'invocation': count,
                       'created_utc': base.now(), 'manifest_sha256': base.digest(output / 'manifest.json')})
            result = supplemental_search(engine, rows[task['record_id']], task, deadline, stop)
            result['attempt_number'] = n
            write_once(output / 'attempts' / filename, {'manifest_sha256': base.digest(output / 'manifest.json'),
                'reservation_sha256': base.digest(reservation_path), 'created_utc': base.now(), 'result': result})
            attempts[task['key']].append(result)
            if result.get('stop_reason') == 'power_pause': return finish('paused_power')
            if stop.is_set() or result.get('stop_reason') == 'user_stop': return finish('stopped')
            if result.get('stop_reason') == 'invocation_wall_cap': return finish('paused_wall_cap')
            if result['status'] == 'engine_error': return finish('needs_review')
        return finish('searches_complete' if all(attempts[t['key']][-1]['status'] in COMPLETE for t in manifest['tasks']) else 'cap_exhausted')
    except Exception:
        finish('needs_review')
        raise
    finally:
        if engine is not None:
            try: engine.quit()
            except (chess.engine.EngineError, TimeoutError): engine.close()


def run(output=OUTPUT):
    output = safe_output(output)
    stop = threading.Event()
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for sig in previous: signal.signal(sig, lambda _s, _f: stop.set())
        with locks(output):
            return run_locked(output, stop)
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run', 'report'))
    parser.add_argument('--directory', type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = globals()[args.action](args.directory)
    print(json.dumps({key: result[key] for key in ('status', 'selected_roots_n', 'completed_roots_n',
          'incomplete_roots_n', 'exhausted_roots_n', 'invocation_count')}, indent=2))


if __name__ == '__main__':
    main()
