"""Resume the complete candidate-state census under the frozen deep200 contract.

Imported evidence is kept byte-for-byte separate from new searches. A small,
durable checkpoint authenticates the new-root prefix; the progress manifest may
lag it. No unanchored complete row is reused. Only this new runner is mutable;
the original scorer, evidence and policies remain frozen.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time

import chess
import chess.engine

import mining_v3_deep as original
from mining_v2_sampling import canonical_fen
from mining_v3_io import digest

ROOT = Path(__file__).resolve().parents[1]
FROZEN_DEEP200_SHA256 = '06579e53688f24a62fd9c4e423ee1b0d02684d3a90677775091370cbcb9d5e65'
ROLES = {'prior_development', 'pilot_train', 'pilot_validation', 'pilot_test',
         'new_train', 'new_validation', 'new_test', 'public_exposed'}
SCORE_SETTINGS = {'depths': [20, 24], 'board_context': 'fen_only', 'engine_threads': 1,
                  'hash_mb': 64, 'clear_hash_each_search': True, 'time_limit': None,
                  'node_limit': None}


class BatteryPause(RuntimeError):
    """The CLI uses temporary-failure exit 75 only for this deliberate pause."""


def classify_strata(record):
    """Report metadata explicitly; these are strata, never scoring exclusions."""
    for field in ('contains_bot', 'history_available', 'known_public_game'):
        if record.get(field) is not None and type(record[field]) is not bool:
            raise ValueError(f'Invalid metadata type: {field}')
    role = record.get('analysis_role')
    if role is not None and role not in ROLES:
        raise ValueError('Unknown non-null analysis role')
    bot, history, public = (record.get(k) for k in ('contains_bot', 'history_available', 'known_public_game'))
    return {'bot_status': 'bot_tagged' if bot is True else 'no_bot' if bot is False else 'unknown',
            'history_status': 'recovered' if history is True else 'unavailable' if history is False else 'unknown',
            'public_exposure': 'known_public' if public is True or role == 'public_exposed'
                               else 'not_known_public' if public is False else 'unknown',
            'analysis_role': role if role is not None else 'unknown'}


def strict_rows(path):
    """Yield physical newline-terminated JSON rows, retaining exact byte evidence."""
    with Path(path).open('rb') as stream:
        while line := stream.readline():
            offset = stream.tell() - len(line)
            if not line.endswith(b'\n'):
                raise ValueError(f'Unterminated evidence row: {path}')
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError(f'Invalid evidence JSON: {path}') from exc
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
                raise ValueError(f'Missing evidence identity: {path}')
            yield row, offset, line


def checked_hash(path, expected):
    value = digest(path)
    if value != expected:
        raise ValueError(f'Frozen evidence hash changed: {path}')
    return value


def load_census(args):
    census = json.loads(Path(args.selection_manifest).read_text())
    source_rows, policy_rows = list(strict_rows(args.input)), list(strict_rows(args.policies))
    records, policies = [r for r, _, _ in source_rows], [r for r, _, _ in policy_rows]
    ids = [r['id'] for r in records]
    if (census.get('complete') is not True or not records or len(set(ids)) != len(ids) or
            census.get('selected_n') != len(records) or census.get('selected_ids') != ids or
            [p['id'] for p in policies] != ids):
        raise ValueError('Census manifest must identify exact ordered unique inputs and policies')
    checked_hash(args.input, census.get('positions_sha256'))
    checked_hash(args.policies, census.get('policies_sha256'))
    if len({canonical_fen(r['fen']) for r in records}) != len(records):
        raise ValueError('Census repeats a canonical state')
    legal, strata = {}, {}
    for record, policy in zip(records, policies):
        board = chess.Board(record['fen'])
        if not board.is_valid() or board.is_game_over():
            raise ValueError(f'Invalid or terminal census board: {record["id"]}')
        if record.get('side_to_move') != ('white' if board.turn else 'black'):
            raise ValueError('Side-to-move metadata differs from board')
        if not isinstance(record.get('game_id'), str) or not record['game_id']:
            raise ValueError('Missing source-game identity')
        legal[record['id']] = {move.uci() for move in board.legal_moves}
        strata[record['id']] = classify_strata(record)
        maps = original.base.validated_policies(record, policy, legal[record['id']])
        if (policy.get('input_condition') != 'fen_only' or
                set(maps) != {f'maia3/fen_only/{rating}' for rating in (1400, 1700, 2000, 2300)}):
            raise ValueError('Census requires exactly the original four FEN-only policies')
    if census.get('strata_by_id') != strata:
        raise ValueError('Explicit census strata do not match source metadata')
    legal_summary = census.get('legal_roots', {})
    if legal_summary.get('total') != sum(map(len, legal.values())):
        raise ValueError('Census legal-root plan differs from its boards')
    if 'by_id' in legal_summary and legal_summary['by_id'] != {k: len(v) for k, v in legal.items()}:
        raise ValueError('Census per-position legal-root plan differs')
    return records, policies, census, legal, strata, {
        'sources': {r['id']: hashlib.sha256(line).hexdigest() for r, _, line in source_rows},
        'policies': {r['id']: hashlib.sha256(line).hexdigest() for r, _, line in policy_rows}}


def scoring_fingerprints(engine):
    return {'engine_sha256': digest(engine), 'runner_sha256': digest(__file__),
            'original_runner_sha256': digest(original.__file__),
            'search_and_metrics_sha256': digest(original.base.__file__),
            'canonicalization_sha256': digest(ROOT/'scripts/mining_v2_sampling.py'),
            'io_sha256': digest(ROOT/'scripts/mining_v3_io.py')}


def validate_reuse(args, records, policies, census, line_hashes):
    """Authenticate the whole completed original run before importing any root."""
    directory = Path(args.reuse_run_dir)
    paths = {'run_manifest_sha256': directory/'run.json', 'input_sha256': Path(args.reuse_input),
             'policy_sha256': Path(args.reuse_policies), 'selection_manifest_sha256': Path(args.reuse_selection_manifest),
             'roots_sha256': directory/'roots.jsonl', 'positions_sha256': directory/'positions.jsonl',
             'prior_public_summary_sha256': Path(args.reuse_public_summary)}
    run = json.loads(paths['run_manifest_sha256'].read_text())
    selected = json.loads(paths['selection_manifest_sha256'].read_text())
    prior_public = json.loads(paths['prior_public_summary_sha256'].read_text())
    if (prior_public.get('complete') is not True or
            prior_public.get('fingerprints', {}).get('run_manifest_sha256') != digest(paths['run_manifest_sha256']) or
            prior_public.get('fingerprints', {}).get('roots_sha256') != run.get('roots_sha256') or
            prior_public.get('fingerprints', {}).get('positions_sha256') != run.get('positions_sha256')):
        raise ValueError('Prior published summary does not identify the imported evidence')
    old = list(strict_rows(paths['input_sha256'])); old_policies = list(strict_rows(paths['policy_sha256']))
    old_ids = [r['id'] for r, _, _ in old]
    index = {r['id']: r for r in records}; policy_index = {r['id']: r for r in policies}
    if (run.get('complete') is not True or not old_ids or len(set(old_ids)) != len(old_ids) or
            [r['id'] for r, _, _ in old_policies] != old_ids or selected.get('selected_ids') != old_ids or
            selected.get('complete') is not True or selected.get('selected_n') != len(old_ids) or
            census.get('already_deep200_ids') != old_ids or census.get('already_deep200_n') != len(old_ids) or
            census.get('new_n') != len(records)-len(old_ids)):
        raise ValueError('Original completed selection or census reuse identities disagree')
    checked_hash(paths['selection_manifest_sha256'], census.get('old200_selection_manifest_sha256'))
    for key in ('input_sha256', 'policy_sha256', 'selection_manifest_sha256'):
        checked_hash(paths[key], run['settings'].get(key))
    checked_hash(paths['input_sha256'], selected.get('positions_sha256'))
    checked_hash(paths['policy_sha256'], selected.get('policies_sha256'))
    for key in ('roots_sha256', 'positions_sha256'):
        checked_hash(paths[key], run.get(key))
    now = scoring_fingerprints(args.engine)
    if now['original_runner_sha256'] != FROZEN_DEEP200_SHA256:
        raise ValueError('Original deep200 scorer is no longer frozen')
    expected = {**SCORE_SETTINGS, 'python_chess_version': chess.__version__,
                'runner_sha256': now['original_runner_sha256'],
                **{k: now[k] for k in ('engine_sha256', 'search_and_metrics_sha256', 'canonicalization_sha256', 'io_sha256')}}
    if any(run['settings'].get(k) != v or k not in run['settings'] for k, v in expected.items()):
        raise ValueError('Original run used a different scoring contract')
    by_position = defaultdict(list); seen = set()
    for record, _, line in old:
        if (record != index.get(record['id']) or
                hashlib.sha256(line).hexdigest() != line_hashes['sources'].get(record['id'])):
            raise ValueError('Imported source record or bytes differ from census')
    for policy, _, line in old_policies:
        if (policy != policy_index.get(policy['id']) or
                hashlib.sha256(line).hexdigest() != line_hashes['policies'].get(policy['id'])):
            raise ValueError('Imported policy record or bytes differ from census')
    for root, _, _ in strict_rows(paths['roots_sha256']):
        if root['record_id'] not in old_ids or root['id'] in seen:
            raise ValueError('Original roots contain unexpected or duplicate identities')
        original.validate_root(root, index[root['record_id']]); seen.add(root['id'])
        by_position[root['record_id']].append(root)
    expected_n = 2*sum(chess.Board(r['fen']).legal_moves.count() for r, _, _ in old)
    if (len(seen) != expected_n or run.get('root_searches_n') != expected_n or
            run.get('completed_root_searches_n') != expected_n or run.get('input_n') != len(old_ids) or
            run.get('completed_positions_n') != len(old_ids) or
            run.get('roots_checkpoint_bytes') != paths['roots_sha256'].stat().st_size or
            run.get('roots_checkpoint_sha256') != run['roots_sha256']):
        raise ValueError('Original completed root plan is incomplete')
    saved = [r for r, _, _ in strict_rows(paths['positions_sha256'])]
    recalculated = [original.summarize_position(r, policy_index[r['id']], by_position[r['id']]) for r, _, _ in old]
    if saved != recalculated:
        raise ValueError('Original outcomes do not match original root evidence')
    return {'fingerprints': {k: digest(p) for k, p in paths.items()}, 'positions_n': len(old_ids),
            'root_searches_n': len(seen), 'position_ids': old_ids,
            'root_search_seconds_sum': sum(r['root_search_seconds_sum'] for r in saved),
            'nodes': sum(r['nodes'] for r in saved), 'roots_path': paths['roots_sha256']}


def fsync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_json(path, value):
    path = Path(path); temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('wb') as output:
        output.write((json.dumps(value, indent=2, allow_nan=False)+'\n').encode())
        output.flush(); os.fsync(output.fileno())
    temporary.replace(path); fsync_directory(path.parent)


@contextmanager
def process_lock(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    with (directory/'writer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another process is writing this census run') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class RootLedger:
    """Retain offsets and identities rather than all parsed principal variations."""
    def __init__(self, records, legal):
        self.records = {r['id']: r for r in records}; self.legal = legal
        self.ids = set(); self.locations = defaultdict(list)
        self.seconds = Counter(); self.nodes = Counter(); self.counts = Counter()

    def add(self, row, origin, path, offset, length):
        rid = row.get('record_id')
        if rid not in self.records or row.get('id') in self.ids:
            raise ValueError('Unexpected or duplicate root identity')
        original.validate_root(row, self.records[rid])
        self.ids.add(row['id']); self.locations[rid].append((path, offset, length))
        self.counts[origin] += 1; self.seconds[origin] += row['wall_seconds']; self.nodes[origin] += row['nodes']

    def complete(self, rid):
        return len(self.locations[rid]) == 2*len(self.legal[rid])

    def roots_for(self, rid):
        handles = {}; result = []
        try:
            for path, offset, length in self.locations[rid]:
                if path not in handles: handles[path] = Path(path).open('rb')
                source = handles[path]; source.seek(offset); result.append(json.loads(source.read(length)))
        finally:
            for stream in handles.values(): stream.close()
        return result


def summarize_record(record, policy, roots, strata, imported):
    result = original.summarize_position(record, policy, roots)
    result.update(strata=strata, evidence_origin='imported_deep200' if imported else 'new_full_census',
                  imported_root_search_seconds_sum=result['root_search_seconds_sum'] if imported else 0.,
                  new_root_search_seconds_sum=0. if imported else result['root_search_seconds_sum'])
    return result


def load_new_checkpoint(path, checkpoint_path, settings_hash, repair_partial=False, discard_uncommitted=False):
    """Only the durable anchored prefix is eligible for checkpoint reuse."""
    path, checkpoint_path = Path(path), Path(checkpoint_path)
    if not checkpoint_path.exists():
        if path.exists() and path.stat().st_size:
            raise ValueError('New roots exist without an authenticated checkpoint')
        path.touch(exist_ok=True)
        checkpoint = {'settings_sha256': settings_hash, 'bytes': 0, 'sha256': hashlib.sha256().hexdigest(),
                      'root_searches_n': 0, 'updated_at': time.time()}
        durable_json(checkpoint_path, checkpoint)
    else:
        checkpoint = json.loads(checkpoint_path.read_text())
    if checkpoint.get('settings_sha256') != settings_hash:
        raise ValueError('Checkpoint settings changed')
    size = checkpoint.get('bytes')
    if type(size) is not int or size < 0:
        raise ValueError('Invalid checkpoint byte count')
    hasher = hashlib.sha256()
    with path.open('rb+') as stream:
        remaining = size
        while remaining:
            block = stream.read(min(1024*1024, remaining))
            if not block: raise ValueError('Anchored root prefix is truncated')
            hasher.update(block); remaining -= len(block)
        if hasher.hexdigest() != checkpoint.get('sha256'):
            raise ValueError('Anchored root prefix hash changed')
        tail = stream.read()
        if tail:
            partial_only = b'\n' not in tail
            if not discard_uncommitted and not (repair_partial and partial_only):
                raise ValueError('Unanchored root tail; explicitly repair a partial tail or discard uncommitted rows')
            stream.truncate(size); stream.flush(); os.fsync(stream.fileno())
    return checkpoint, hasher


def run(args):
    if type(args.workers) is not int or args.workers < 1:
        raise ValueError('workers must be a positive integer')
    protected = {Path(p).resolve() for p in (args.input, args.policies, args.selection_manifest,
        args.reuse_input, args.reuse_policies, args.reuse_selection_manifest, args.reuse_public_summary,
        args.engine, Path(args.reuse_run_dir)/'run.json', Path(args.reuse_run_dir)/'roots.jsonl',
        Path(args.reuse_run_dir)/'positions.jsonl', __file__, original.__file__, original.base.__file__)}
    outputs = {Path(args.run_dir).joinpath(name).resolve() for name in (
        'run.json','checkpoint.json','roots.jsonl','positions.jsonl','imported_roots.jsonl','writer.lock')}
    if protected & outputs:
        raise ValueError('Run outputs would overwrite protected frozen inputs or original evidence')
    with process_lock(args.run_dir):
        return run_locked(args)


def run_locked(args):
    records, policies, census, legal, strata, line_hashes = load_census(args)
    reuse = validate_reuse(args, records, policies, census, line_hashes)
    imported_ids = set(reuse['position_ids']); directory = Path(args.run_dir)
    output = directory/'roots.jsonl'; imported_file = directory/'imported_roots.jsonl'
    manifest_path = directory/'run.json'; checkpoint_path = directory/'checkpoint.json'
    settings = {**SCORE_SETTINGS, **scoring_fingerprints(args.engine),
                'input_sha256': digest(args.input), 'policy_sha256': digest(args.policies),
                'selection_manifest_sha256': digest(args.selection_manifest), 'reuse': reuse['fingerprints'],
                'python_chess_version': chess.__version__, 'workers': args.workers,
                'task_order': 'Original deterministic interleaved colour order; depth then sorted UCI root',
                'monotonic_clock_implementation': time.get_clock_info('monotonic').implementation}
    settings_hash = hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if previous and previous.get('settings') != settings:
        raise ValueError('Frozen inputs, implementation or scoring settings changed')
    if not previous and any(p.exists() for p in (output, imported_file, checkpoint_path)):
        raise ValueError('Evidence exists without a provenance manifest')
    total_roots = 2*sum(map(len, legal.values()))
    manifest = previous or {'settings': settings, 'settings_sha256': settings_hash, 'complete': False,
        'input_n': len(records), 'root_searches_n': total_roots,
        'imported_positions_n': len(imported_ids), 'imported_root_searches_n': reuse['root_searches_n'],
        'planned_new_positions_n': len(records)-len(imported_ids),
        'planned_new_root_searches_n': total_roots-reuse['root_searches_n'],
        'reuse': {k:v for k,v in reuse.items() if k not in ('position_ids','roots_path')},
        'started_at': time.time(), 'attempts': []}
    if not previous: durable_json(manifest_path, manifest)
    if not imported_file.exists():
        temporary = imported_file.with_suffix('.tmp')
        with reuse['roots_path'].open('rb') as source, temporary.open('wb') as destination:
            shutil.copyfileobj(source, destination); destination.flush(); os.fsync(destination.fileno())
        temporary.replace(imported_file); fsync_directory(directory)
    checked_hash(imported_file, reuse['fingerprints']['roots_sha256'])
    if previous and previous.get('complete'):
        checked_hash(output, previous.get('roots_sha256'))
        checked_hash(directory/'positions.jsonl', previous.get('positions_sha256'))
    checkpoint, hasher = load_new_checkpoint(output, checkpoint_path, settings_hash,
        getattr(args, 'repair_partial', False), getattr(args, 'discard_uncommitted', False))
    ledger = RootLedger(records, legal)
    for root, offset, line in strict_rows(imported_file):
        if root['record_id'] not in imported_ids: raise ValueError('Imported root is outside original selection')
        ledger.add(root, 'imported', imported_file, offset, len(line))
    for root, offset, line in strict_rows(output):
        if (root['record_id'] in imported_ids or root.get('evidence_origin') != 'new_full_census' or
                type(root.get('attempt_index')) is not int or not 1 <= root['attempt_index'] <= len(manifest['attempts'])):
            raise ValueError('New checkpoint root has invalid provenance')
        ledger.add(root, 'new', output, offset, len(line))
    if ledger.counts['new'] != checkpoint.get('root_searches_n'):
        raise ValueError('Checkpoint root count differs from its anchored prefix')
    if previous and previous.get('complete'):
        if len(ledger.ids) != total_roots or not all(ledger.complete(r['id']) for r in records):
            raise ValueError('Completed census lacks exact root coverage')
        return manifest
    manifest['complete'] = False; manifest.pop('error', None); manifest.pop('pause_reason', None)
    attempt_mono = time.monotonic(); attempt_index = len(manifest['attempts'])+1
    manifest['attempts'].append({'started_at': time.time(), 'new_root_searches_before': ledger.counts['new'],
                                'monotonic_started': attempt_mono})
    root_bytes = checkpoint['bytes']; imported_seconds = reuse['root_search_seconds_sum']

    def save_progress(force=False):
        manifest.update(updated_at=time.time(), completed_positions_n=sum(ledger.complete(r['id']) for r in records),
            completed_new_positions_n=sum(ledger.complete(r['id']) for r in records if r['id'] not in imported_ids),
            completed_root_searches_n=len(ledger.ids), completed_new_root_searches_n=ledger.counts['new'],
            roots_checkpoint_bytes=root_bytes, roots_checkpoint_sha256=hasher.hexdigest(),
            imported_roots_sha256=reuse['fingerprints']['roots_sha256'],
            imported_root_search_seconds_sum=imported_seconds, new_root_search_seconds_sum=ledger.seconds['new'],
            imported_nodes=reuse['nodes'], new_nodes=ledger.nodes['new'])
        durable_json(manifest_path, manifest)
    save_progress()
    engines, engine_lock, local, stop = [], threading.Lock(), threading.local(), threading.Event()

    def perform(task):
        if stop.is_set(): raise RuntimeError('Computation paused')
        record, depth, move = task
        if not hasattr(local, 'engine'):
            engine = chess.engine.SimpleEngine.popen_uci(args.engine)
            try:
                engine.configure({'Threads':1, 'Hash':64, 'UCI_ShowWDL':True})
                with engine_lock:
                    if stop.is_set(): raise RuntimeError('Computation paused')
                    engines.append(engine); local.engine = engine
            except BaseException:
                engine.close(); raise
        started = time.monotonic()
        result = original.base.search(local.engine, chess.Board(record['fen']), depth, None,
                                     roots=[chess.Move.from_uci(move)])[0]
        result.update(id=original.task_id(record['id'], depth, move), record_id=record['id'], fen=record['fen'],
                      board_context='fen_only', wall_seconds=time.monotonic()-started,
                      evidence_origin='new_full_census', attempt_index=attempt_index)
        original.validate_root(result, record)
        return result

    queue = ((record, depth, move) for record in original.balanced_task_order(records)
             for depth in original.DEPTHS for move in sorted(legal[record['id']])
             if original.task_id(record['id'],depth,move) not in ledger.ids)
    pool = ThreadPoolExecutor(max_workers=args.workers)
    pending = {}; exhausted = False; last_battery = 0.; last_progress = time.monotonic()
    try:
        with output.open('ab') as destination:
            while pending or not exhausted:
                if time.monotonic()-last_battery >= 30:
                    last_battery = time.monotonic()
                    if original.battery_is_critical():
                        manifest['pause_reason'] = 'battery'
                        raise BatteryPause('Paused: battery at or below 5% without AC power')
                while not exhausted and len(pending) < args.workers*2:
                    task = next(queue, None)
                    if task is None: exhausted = True
                    else: pending[pool.submit(perform,task)] = task
                if not pending: break
                finished, _ = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
                batch = []
                for future in finished:
                    pending.pop(future); batch.append(future.result())
                for result in batch:
                    line = (json.dumps(result,separators=(',', ':'),allow_nan=False)+'\n').encode()
                    destination.write(line); ledger.add(result,'new',output,root_bytes,len(line))
                    root_bytes += len(line); hasher.update(line)
                if batch:
                    destination.flush(); os.fsync(destination.fileno())
                    checkpoint = {'settings_sha256':settings_hash,'bytes':root_bytes,'sha256':hasher.hexdigest(),
                                  'root_searches_n':ledger.counts['new'],'updated_at':time.time()}
                    durable_json(checkpoint_path,checkpoint)
                if time.monotonic()-last_progress >= 30:
                    save_progress(); last_progress=time.monotonic()
                    print(json.dumps({k:manifest[k] for k in ('completed_positions_n','input_n','completed_root_searches_n','root_searches_n')}),flush=True)
        if len(ledger.ids) != total_roots or not all(ledger.complete(r['id']) for r in records):
            raise ValueError('Incomplete legal-root census')
        position_file = directory/'positions.jsonl'; temporary = position_file.with_suffix('.tmp')
        with temporary.open('wb') as destination:
            for record, policy in zip(records, policies):
                result = summarize_record(record,policy,ledger.roots_for(record['id']),strata[record['id']],record['id'] in imported_ids)
                destination.write((json.dumps(result,separators=(',', ':'),allow_nan=False)+'\n').encode())
            destination.flush(); os.fsync(destination.fileno())
        temporary.replace(position_file); fsync_directory(directory)
        manifest.update(complete=True,roots_sha256=digest(output),positions_sha256=digest(position_file))
    except BaseException as exc:
        manifest['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        stop.set()
        for future in pending: future.cancel()
        with engine_lock:
            for engine in engines:
                try: engine.close()
                except Exception: pass
        pool.shutdown(wait=True,cancel_futures=True)
        manifest['attempts'][-1].update(finished_at=time.time(),complete=manifest['complete'],
            new_root_searches_after=ledger.counts['new'],monotonic_elapsed_seconds=time.monotonic()-attempt_mono)
        manifest.update(finished_at=time.time())
        save_progress()
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=ROOT/'data/mining_v3/deep_all/positions.jsonl')
    ap.add_argument('--policies',type=Path,default=ROOT/'data/mining_v3/deep_all/policies.jsonl')
    ap.add_argument('--selection-manifest',type=Path,default=ROOT/'data/mining_v3/deep_all/selection_manifest.json')
    ap.add_argument('--run-dir',type=Path,default=ROOT/'results/mining_v3/deep_all')
    ap.add_argument('--reuse-run-dir',type=Path,default=ROOT/'results/mining_v3/deep200')
    ap.add_argument('--reuse-input',type=Path,default=ROOT/'data/mining_v3/deep200/positions.jsonl')
    ap.add_argument('--reuse-policies',type=Path,default=ROOT/'data/mining_v3/deep200/policies.jsonl')
    ap.add_argument('--reuse-selection-manifest',type=Path,default=ROOT/'data/mining_v3/deep200/selection_manifest.json')
    ap.add_argument('--reuse-public-summary',type=Path,default=ROOT/'results/mining_v3_deep200.json')
    ap.add_argument('--engine',type=Path,default=original.base.DEFAULT_ENGINE)
    ap.add_argument('--workers',type=int,default=8)
    ap.add_argument('--repair-partial',action='store_true')
    ap.add_argument('--discard-uncommitted',action='store_true',help='Discard only bytes after the intact authenticated new-root prefix')
    try:
        run(ap.parse_args())
    except BatteryPause as exc:
        print(str(exc),flush=True)
        raise SystemExit(75) from exc


if __name__=='__main__': main()
