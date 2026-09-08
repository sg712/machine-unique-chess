"""Resumable, bounded-memory Maia3-5M policies for the full colour census.

The primary condition is FEN-only for every row, with both hypothetical players
rated 1400, 1700, 2000, or 2300. Real history availability is recorded separately;
it never changes the model input in this primary comparison. No game clocks are
fed to the model. This is screening, not human puzzle calibration.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import chess
import torch

from mining_v2_policy import Maia3Policy
from mining_v3_io import check_manifest, completed_ids, digest, rows, write_manifest

RATINGS = (1400, 1700, 2000, 2300)


class CensusPolicy(Maia3Policy):
    """Same pinned forward pass and vocabulary as v2; avoid unused history replay."""

    @torch.inference_mode()
    def predict_fen(self, records, ratings=RATINGS):
        output, tasks = [], []
        for record in records:
            board = chess.Board(record['fen'])
            legal = {move.uci() for move in board.legal_moves}
            if not board.is_valid() or not legal:
                raise ValueError(f'{record["id"]}: invalid or terminal target board')
            mask = self.get_legal_moves_mask(board, self.move_index)
            indices = mask.nonzero().flatten().tolist()
            moves = [self.all_moves[index] for index in indices]
            if board.turn == chess.BLACK:
                moves = [self.mirror_move(move) for move in moves]
            if len(moves) != len(legal) or set(moves) != legal:
                raise ValueError(f'{record["id"]}: Maia3 vocabulary does not cover the legal moves')
            result = {'id': record['id'], 'fen': record['fen'],
                      'history_available': record.get('history_available', True),
                      'input_condition': 'fen_only',
                      'maia3': {'history': {}, 'fen_only': {}}}
            output.append(result)
            tokens = self.tokens([board])
            for rating in ratings:
                tasks.append((result, rating, tokens, mask, indices, moves))
        for start in range(0, len(tasks), self.batch_size):
            batch = tasks[start:start+self.batch_size]
            tokens = torch.stack([task[2] for task in batch]).to(self.device)
            rating_tensor = torch.tensor([task[1] for task in batch], dtype=torch.long, device=self.device)
            masks = torch.stack([task[3] for task in batch]).to(self.device)
            logits, _, _ = self.model(tokens, rating_tensor, rating_tensor)
            probabilities = logits.float().masked_fill(~masks, float('-inf')).softmax(-1).cpu()
            for (result, rating, _, _, indices, moves), probs in zip(batch, probabilities):
                values = probs[indices].tolist()
                if (any(not 0 <= value <= 1 for value in values) or
                        abs(sum(values) - 1.) > 2e-6):
                    raise ValueError(f'{result["id"]}: invalid legal policy probabilities')
                result['maia3']['fen_only'][str(rating)] = dict(zip(moves, values))
        return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--threads', type=int, default=2)
    ap.add_argument('--batch-size', type=int, default=128)
    ap.add_argument('--chunk-size', type=int, default=256)
    ap.add_argument('--repair-partial', action='store_true')
    args = ap.parse_args()
    if args.chunk_size < 1:
        ap.error('--chunk-size must be positive')
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = {'input': str(Path(args.input).resolve()), 'input_sha256': digest(args.input),
                'scorer_sha256': digest(__file__),
                'adapter_sha256': digest(Path(__file__).with_name('mining_v2_policy.py')),
                'io_sha256': digest(Path(__file__).with_name('mining_v3_io.py')),
                'ratings': list(RATINGS), 'context': 'fen_only', 'threads': args.threads,
                'batch_size': args.batch_size, 'chunk_size': args.chunk_size}
    manifest_path, previous = check_manifest(path, settings)
    done = completed_ids(path, args.repair_partial)
    manifest = {'settings': settings, 'started_at': previous['started_at'] if previous else time.time(),
                'complete': False, 'completed_n': len(done)}
    write_manifest(manifest_path, manifest)
    model = CensusPolicy(device='cpu', threads=args.threads, batch_size=args.batch_size,
                         local_files_only=True, model_size='5m')
    manifest['model'] = model.manifest
    write_manifest(manifest_path, manifest)
    start = time.monotonic()
    resumed = len(done)
    seen = set()
    buffer = []
    missing_seen = False
    try:
        with path.open('a') as destination:
            def flush():
                if not buffer:
                    return
                predictions = model.predict_fen(buffer)
                for prediction in predictions:
                    destination.write(json.dumps(prediction, separators=(',', ':')) + '\n')
                    done.add(prediction['id'])
                destination.flush()
                buffer.clear()
                manifest.update(completed_n=len(done), updated_at=time.time(),
                                elapsed_current_run_seconds=time.monotonic()-start)
                write_manifest(manifest_path, manifest)
                print(json.dumps({'completed': len(done), 'new': len(done)-resumed,
                                  'seconds': round(time.monotonic()-start, 2)}), flush=True)
            for record in rows(args.input):
                if record['id'] in seen:
                    raise ValueError('Duplicate input ID')
                seen.add(record['id'])
                if record['id'] in done:
                    if missing_seen:
                        raise ValueError('Policy resume output must be a contiguous prefix of the input')
                    continue
                missing_seen = True
                buffer.append(record)
                if len(buffer) >= args.chunk_size:
                    flush()
            flush()
        if done != seen:
            raise ValueError('Completed output contains IDs absent from the input')
        manifest.update(complete=True, input_n=len(seen))
    finally:
        manifest.update(completed_n=len(done), finished_at=time.time(),
                        elapsed_current_run_seconds=time.monotonic()-start)
        write_manifest(manifest_path, manifest)


if __name__ == '__main__':
    main()
