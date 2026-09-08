"""Pipeline immutable source shards through Maia3 and Stockfish census screening.

One CPU policy process and one independent engine process pool overlap. Input,
policy and engine files remain sharded; only their small manifests are combined.
Every stage checks input/code/model hashes before resuming completed records.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import deque
import json
from pathlib import Path
import subprocess
import sys
import time

from mining_v3_io import digest, rows, write_manifest

SCRIPT_DIR = Path(__file__).resolve().parent


def prepare_shards(source, run_dir, shard_size):
    """Create reproducible shards, validating any files left by an interrupted preparation."""
    source, run_dir = Path(source), Path(run_dir)
    input_dir = run_dir/'inputs'
    input_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir/'shards.json'
    settings = {'source': str(source.resolve()), 'source_sha256': digest(source),
                'shard_size': shard_size}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['settings'] != settings:
            raise ValueError('Shard source or size changed; choose a new run directory')
        for shard in manifest['shards']:
            if digest(shard['input']) != shard['input_sha256']:
                raise ValueError('An immutable input shard was changed')
        return manifest
    shards, seen, chunk = [], set(), []

    def flush():
        if not chunk:
            return
        index = len(shards)
        destination = (input_dir/f'{index:05d}.jsonl').resolve()
        temporary = destination.with_suffix('.jsonl.tmp')
        temporary.write_text(''.join(json.dumps(row, separators=(',', ':'))+'\n' for row in chunk))
        checksum = digest(temporary)
        if destination.exists():
            if digest(destination) != checksum:
                raise ValueError('Existing shard differs from the immutable source')
            temporary.unlink()
        else:
            temporary.replace(destination)
        shards.append({'index': index, 'input': str(destination), 'input_sha256': checksum,
                       'rows': len(chunk), 'first_id': chunk[0]['id'], 'last_id': chunk[-1]['id']})
        chunk.clear()

    for row in rows(source):
        if row['id'] in seen:
            raise ValueError('Duplicate source record ID')
        seen.add(row['id'])
        chunk.append(row)
        if len(chunk) >= shard_size:
            flush()
    flush()
    manifest = {'settings': settings, 'rows': len(seen), 'shards': shards, 'complete': True}
    write_manifest(manifest_path, manifest)
    return manifest


def stage_paths(run_dir, shard):
    name = f'{shard["index"]:05d}.jsonl'
    return {'policy': str((Path(run_dir)/'policies'/name).resolve()),
            'engine': str((Path(run_dir)/'engine'/name).resolve())}


def run_stage(stage, shard, args):
    paths = stage_paths(args.run_dir, shard)
    command = [sys.executable, str(SCRIPT_DIR/f'mining_v3_{stage}.py'),
               '--input', shard['input'], '--output', paths[stage]]
    if args.repair_partial:
        command.append('--repair-partial')
    if stage == 'policy':
        command += ['--threads', str(args.policy_threads), '--batch-size', str(args.batch_size),
                    '--chunk-size', str(args.chunk_size)]
    else:
        command += ['--policies', paths['policy'], '--workers', str(args.engine_workers),
                    '--top-nodes', str(args.top_nodes), '--root-nodes', str(args.root_nodes),
                    '--max-human', str(args.max_human), '--coverage', str(args.coverage)]
    log_path = Path(args.run_dir)/'logs'/f'{shard["index"]:05d}-{stage}.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a') as log:
        log.write(json.dumps({'started_at': time.time(), 'command': command})+'\n')
        log.flush()
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'{stage} shard {shard["index"]} failed; inspect {log_path}')
    manifest_path = Path(paths[stage]).with_suffix('.manifest.json')
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get('complete') or manifest.get('completed_n') != shard['rows']:
        raise RuntimeError(f'{stage} shard {shard["index"]} did not confirm every source row')
    return {'index': shard['index'], 'stage': stage, 'rows': shard['rows'],
            'output': paths[stage], 'output_sha256': digest(paths[stage]),
            'manifest': str(manifest_path), 'manifest_sha256': digest(manifest_path)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--shard-size', type=int, default=8192)
    ap.add_argument('--policy-threads', type=int, default=2)
    ap.add_argument('--batch-size', type=int, default=128)
    ap.add_argument('--chunk-size', type=int, default=256)
    ap.add_argument('--engine-workers', type=int, default=8)
    ap.add_argument('--top-nodes', type=int, default=30000)
    ap.add_argument('--root-nodes', type=int, default=5000)
    ap.add_argument('--max-human', type=int, default=10)
    ap.add_argument('--coverage', type=float, default=.85)
    ap.add_argument('--repair-partial', action='store_true')
    args = ap.parse_args()
    if min(args.shard_size, args.policy_threads, args.batch_size, args.chunk_size,
           args.engine_workers, args.top_nodes, args.root_nodes) < 1:
        ap.error('Sizes, threads, workers and node budgets must be positive')
    directory = Path(args.run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    settings = {key: value for key, value in vars(args).items() if key != 'repair_partial'}
    settings.update(input_sha256=digest(args.input),
                    code_sha256={name: digest(SCRIPT_DIR/name) for name in (
                        'mining_v3_run.py', 'mining_v3_io.py', 'mining_v3_policy.py',
                        'mining_v3_engine.py', 'mining_v2_policy.py', 'mining_v2_engine.py')})
    manifest_path = directory/'run.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if previous and previous['settings'] != settings:
        raise ValueError('Run settings or implementation changed; choose a new run directory')
    plan = prepare_shards(args.input, directory, args.shard_size)
    manifest = {'settings': settings, 'started_at': previous['started_at'] if previous else time.time(),
                'complete': False, 'input_n': plan['rows'], 'shards_n': len(plan['shards']),
                'policy_completed_n': 0, 'engine_completed_n': 0,
                'shards': [], 'scope': 'common FEN-only Maia3-5M four-rating and fixed-node Stockfish 18 screen',
                'deeply_verified_n': 0}
    write_manifest(manifest_path, manifest)
    next_policy = 0
    ready = deque()
    futures = {}
    active = set()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            while next_policy < len(plan['shards']) or ready or futures:
                if 'policy' not in active and next_policy < len(plan['shards']) and len(ready) < 2:
                    shard = plan['shards'][next_policy]
                    futures[pool.submit(run_stage, 'policy', shard, args)] = ('policy', shard)
                    active.add('policy')
                    next_policy += 1
                    print(json.dumps({'stage': 'policy', 'shard': shard['index'], 'status': 'started'}), flush=True)
                if 'engine' not in active and ready:
                    shard = ready.popleft()
                    futures[pool.submit(run_stage, 'engine', shard, args)] = ('engine', shard)
                    active.add('engine')
                    print(json.dumps({'stage': 'engine', 'shard': shard['index'], 'status': 'started'}), flush=True)
                finished, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in finished:
                    stage, shard = futures.pop(future)
                    active.remove(stage)
                    result = future.result()
                    manifest['shards'].append(result)
                    manifest[f'{stage}_completed_n'] += result['rows']
                    manifest['updated_at'] = time.time()
                    if stage == 'policy':
                        ready.append(shard)
                    write_manifest(manifest_path, manifest)
                    print(json.dumps({'stage': stage, 'shard': shard['index'], 'status': 'complete',
                                      'completed': manifest[f'{stage}_completed_n'], 'total': plan['rows']}), flush=True)
        if manifest['engine_completed_n'] != plan['rows'] or manifest['policy_completed_n'] != plan['rows']:
            raise RuntimeError('Pipeline ended without complete row coverage')
        manifest['complete'] = True
    except BaseException as exc:
        manifest['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        manifest['finished_at'] = time.time()
        write_manifest(manifest_path, manifest)


if __name__ == '__main__':
    main()
