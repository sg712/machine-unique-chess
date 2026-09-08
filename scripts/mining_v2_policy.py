"""Full legal move policies for the balanced mining pilot.

Use the pinned Maia3 Python forward pass: UCI MultiPV is capped at 20 and
its ``score cp`` is a value estimate, not a move probability. Probabilities
here are the raw move logits softmaxed over *all* legal moves, at temperature
one. Both players receive the same hypothetical rating in each condition.

Run with the research environment, not the web application's environment::

    python scripts/mining_v2_policy.py --include-maia2

The 5M checkpoint is a screening model; these policies are model predictions,
not observations of human choices or evidence that a teaching method works.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

import chess
import torch


ROOT = Path(__file__).resolve().parents[1]
MAIA3_SOURCE = ROOT / "models/maia3-repo"
MAIA3_SOURCE_COMMIT = "1e13597c42d4858b7cfd7cfdae01e297263364b2"
MAIA3_REPO = "UofTCSSLab/Maia3-5M"
MAIA3_REVISION = "b6559de2398d7140b985f28fd2c19fb5e47ddabe"
MAIA3_WEIGHT_SHA256 = "ba14208b2992d85502f5fb501934abf6aaaeb355e9f3fdf90e326911f562524f"
MAIA3_MODELS = {
    "5m": {"repo": MAIA3_REPO, "revision": MAIA3_REVISION, "sha256": MAIA3_WEIGHT_SHA256},
    "79m": {"repo": "UofTCSSLab/Maia3-79M", "revision": "a107d6ceb7b298cb04ae1da4edffe2939858b894",
            "sha256": "3fc6181d5db789b45a15305732148757ae74efa3e0028e81ba335b462dac45c2"},
}
MAIA2_VERSION = "0.11.0"
MAIA2_WEIGHT_SHA256 = "65aae8465eed5e65df66a24ea7370715579f9e5435098d06fe18bdb1e267e997"
HISTORY_RATINGS = (1400, 1700, 2000, 2300)
FEN_RATINGS = (1700, 2000)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source_manifest(directory: Path) -> dict:
    return {str(p.relative_to(directory)): sha256(p)
            for p in sorted(directory.rglob("*.py"))}


def _maia3_imports():
    commit = subprocess.check_output(
        ["git", "-C", str(MAIA3_SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if commit != MAIA3_SOURCE_COMMIT:
        raise ValueError(f"Maia3 source must be pinned to {MAIA3_SOURCE_COMMIT}; found {commit}")
    dirty = subprocess.check_output(
        ["git", "-C", str(MAIA3_SOURCE), "status", "--porcelain", "--untracked-files=no"],
        text=True).strip()
    if dirty:
        raise ValueError("Pinned Maia3 source has local modifications")
    sys.path.insert(0, str(MAIA3_SOURCE))
    import maia3
    if not Path(maia3.__file__).resolve().is_relative_to(MAIA3_SOURCE.resolve()):
        raise RuntimeError("Another Maia3 package was imported before the pinned source")
    from maia3.dataset import get_historical_tokens, get_legal_moves_mask, tokenize_board
    from maia3.models import MAIA3Model
    from maia3.uci import parse_args
    from maia3.utils import get_all_possible_moves, mirror_move
    return (get_historical_tokens, get_legal_moves_mask, tokenize_board,
            MAIA3Model, parse_args, get_all_possible_moves, mirror_move)


def history_boards(record: dict) -> list[chess.Board]:
    """Validate full replay and the chronological last-eight-position cache."""
    board = chess.Board(record["initial_fen"])
    if not board.is_valid():
        raise ValueError(f"{record['id']}: invalid initial position")
    history = deque([board.copy(stack=False)], maxlen=8)
    for uci in record["history_uci"]:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"{record['id']}: illegal history move {uci}")
        board.push(move)
        history.append(board.copy(stack=False))
    if board.fen() != chess.Board(record["fen"]).fen():
        raise ValueError(f"{record['id']}: history does not reach target FEN")
    cached = [chess.Board(fen).fen() for fen in record["history_fens"]]
    if cached != [position.fen() for position in history]:
        raise ValueError(f"{record['id']}: history_fens must be chronological last eight including target")
    if not board.is_valid() or not any(board.legal_moves):
        raise ValueError(f"{record['id']}: target must be valid and have legal moves")
    return list(history)


def validate_policy(board: chess.Board, policy: dict[str, float]) -> None:
    if set(policy) != {move.uci() for move in board.legal_moves}:
        raise ValueError("Policy must contain every legal move and no illegal moves")
    if any(not 0 <= probability <= 1 for probability in policy.values()):
        raise ValueError("Non-finite or out-of-range move probability")
    if abs(sum(policy.values()) - 1) > 2e-6:
        raise ValueError("Legal policy does not sum to one")


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Maia3Policy:
    def __init__(self, device="auto", threads=2, batch_size=32,
                 checkpoint: str | Path | None = None, local_files_only=False, model_size="5m"):
        if batch_size < 1 or threads < 1:
            raise ValueError("batch_size and threads must be positive")
        torch.set_num_threads(threads)
        (self.get_historical_tokens, self.get_legal_moves_mask, self.tokenize_board,
         model_type, parse_args, get_all_possible_moves, self.mirror_move) = _maia3_imports()
        self.device = resolve_device(device)
        self.batch_size = batch_size
        model_spec = MAIA3_MODELS[model_size]
        model_name = f"maia3-{model_size}"
        filename = model_name + ".pt"
        if checkpoint is None:
            from huggingface_hub import hf_hub_download
            checkpoint = hf_hub_download(
                repo_id=model_spec["repo"], filename=filename, revision=model_spec["revision"],
                local_files_only=local_files_only)
        checkpoint = Path(checkpoint)
        if sha256(checkpoint) != model_spec["sha256"]:
            raise ValueError(f"Maia3 checkpoint checksum does not match the pinned {model_size.upper()} weights")
        self.cfg = parse_args(["--model", model_name, "--checkpoint-path", str(checkpoint),
                               "--device", self.device, "--no-use-amp"])
        self.model = model_type(self.cfg)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if isinstance(state, dict) and "model_state_dict" in state:
            state = state["model_state_dict"]
        state = {key.replace("smolgen", "gab"): value for key, value in state.items()}
        # A missing weight must fail the run, not silently create random weights.
        self.model.load_state_dict(state, strict=True)
        self.model.to(self.device).eval()
        self.all_moves = get_all_possible_moves()
        self.move_index = {move: idx for idx, move in enumerate(self.all_moves)}
        self.manifest = {
            "model": f"Maia3-{model_size.upper()}", "source_url": "https://github.com/CSSLab/maia3",
            "source_commit": MAIA3_SOURCE_COMMIT,
            "source_files_sha256": _source_manifest(MAIA3_SOURCE / "maia3"),
            "weights_repo": model_spec["repo"], "weights_revision": model_spec["revision"],
            "weights_filename": filename, "weights_sha256": model_spec["sha256"],
            "device": self.device, "threads": threads, "batch_size": batch_size,
            "torch_version": torch.__version__, "precision": "float32", "amp": False,
            "history_length_including_current": 8,
            "history_order": "chronological; each board tokenized from its own side to move",
            "short_history_padding": "repeat earliest available position on the left",
            "fen_only_padding": "repeat current position eight times",
            "include_time_info": False, "clk_ponder": 0.0,
            "rating_conditioning": "self and opponent both set to the requested rating",
            "policy": "temperature-one softmax of raw move logits over every legal move",
            "top_k": None, "top_p": 1.0,
        }

    def tokens(self, boards: list[chess.Board]):
        history = deque((self.tokenize_board(board) for board in boards), maxlen=8)
        return self.get_historical_tokens(
            history, self.cfg, base=0.0, inc=0.0, clk_left_before=0.0, clk_ponder=0.0)

    @torch.inference_mode()
    def predict(self, records, history_ratings=HISTORY_RATINGS, fen_ratings=FEN_RATINGS):
        rows, tasks = [], []
        for record in records:
            boards = history_boards(record)
            board = boards[-1]
            mask = self.get_legal_moves_mask(board, self.move_index)
            if int(mask.sum()) != board.legal_moves.count():
                raise ValueError("Maia3 vocabulary is missing a legal move")
            history_available = record.get("history_available", True)
            row = {"id": record["id"], "fen": record["fen"],
                   "history_available": history_available,
                   "maia3": {"history": {}, "fen_only": {}}}
            rows.append(row)
            conditions = (("history", history_ratings, boards), ("fen_only", fen_ratings, [board]))
            if not history_available:
                conditions = (("fen_only", tuple(dict.fromkeys((*history_ratings, *fen_ratings))), [board]),)
            for mode, ratings, token_boards in conditions:
                tokens = self.tokens(token_boards)
                for rating in ratings:
                    tasks.append((row, mode, rating, tokens, mask, board))
        for start in range(0, len(tasks), self.batch_size):
            batch = tasks[start:start + self.batch_size]
            tokens = torch.stack([task[3] for task in batch]).to(self.device)
            ratings = torch.tensor([task[2] for task in batch], dtype=torch.long, device=self.device)
            masks = torch.stack([task[4] for task in batch]).to(self.device)
            logits, _, _ = self.model(tokens, ratings, ratings)
            probabilities = logits.float().masked_fill(~masks, float("-inf")).softmax(-1).cpu()
            for task, probs in zip(batch, probabilities):
                row, mode, rating, _, mask, board = task
                policy = {}
                for idx in mask.nonzero().flatten().tolist():
                    move = self.all_moves[idx]
                    if board.turn == chess.BLACK:
                        move = self.mirror_move(move)
                    policy[move] = float(probs[idx])
                validate_policy(board, policy)
                row["maia3"][mode][str(rating)] = policy
        return rows


class Maia2Policy:
    """Full-precision Maia2 comparison; package helper rounds to four decimals."""
    def __init__(self, device="auto", batch_size=32):
        if importlib.metadata.version("maia2") != MAIA2_VERSION:
            raise ValueError(f"Maia2 comparison requires package version {MAIA2_VERSION}")
        from maia2 import inference, model
        import maia2
        self.inference = inference
        self.device = resolve_device(device)
        self.batch_size = batch_size
        self.model = model.from_pretrained(
            "rapid", device=self.device, save_root=str(ROOT / "maia2_models")).eval()
        if sha256(ROOT / "maia2_models/rapid_model.pt") != MAIA2_WEIGHT_SHA256:
            raise ValueError("Maia2 checkpoint checksum does not match the pinned rapid weights")
        self.move_index, self.elo_dict, self.index_move = inference.prepare()
        self.manifest = {
            "model": "Maia2 rapid", "package_version": MAIA2_VERSION,
            "package_source_files_sha256": _source_manifest(Path(maia2.__file__).parent),
            "weights_sha256": MAIA2_WEIGHT_SHA256,
            "device": self.device, "batch_size": batch_size,
            "policy": "full-precision temperature-one softmax over every legal move",
            "history": False, "ratings": [1700, 2000],
        }

    @torch.inference_mode()
    def predict(self, records, ratings=FEN_RATINGS):
        rows = [{} for _ in records]
        tasks = [(idx, record["fen"], rating) for idx, record in enumerate(records) for rating in ratings]
        for start in range(0, len(tasks), self.batch_size):
            batch = tasks[start:start + self.batch_size]
            prepared = [self.inference.preprocessing(fen, rating, rating, self.elo_dict, self.move_index)
                        for _, fen, rating in batch]
            tokens = torch.stack([item[0] for item in prepared]).to(self.device)
            elo_self = torch.tensor([item[1] for item in prepared], device=self.device)
            elo_oppo = torch.tensor([item[2] for item in prepared], device=self.device)
            masks = torch.stack([item[3] for item in prepared]).bool().to(self.device)
            logits, _, _ = self.model(tokens, elo_self, elo_oppo)
            probabilities = logits.float().masked_fill(~masks, float("-inf")).softmax(-1).cpu()
            for (idx, fen, rating), item, probs in zip(batch, prepared, probabilities):
                board = chess.Board(fen)
                policy = {}
                for move_idx in item[3].nonzero().flatten().tolist():
                    move = self.index_move[move_idx]
                    if board.turn == chess.BLACK:
                        move = self.inference.mirror_move(move)
                    policy[move] = float(probs[move_idx])
                validate_policy(board, policy)
                rows[idx][str(rating)] = policy
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/mining_v2/positions.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "data/mining_v2/policies.jsonl")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/mining_v2/policy_manifest.json")
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    parser.add_argument("--model-size", choices=tuple(MAIA3_MODELS), default="5m")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--chunk-size", type=int, default=64)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-maia2", action="store_true")
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    if args.chunk_size < 1 or (args.limit is not None and args.limit < 1):
        parser.error("chunk-size and limit must be positive")
    records = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    if args.limit is not None:
        records = records[:args.limit]
    if not records or len({row["id"] for row in records}) != len(records):
        parser.error("input must contain records with unique IDs")
    started = time.monotonic()
    maia3 = Maia3Policy(args.device, args.threads, args.batch_size,
                       local_files_only=args.local_files_only, model_size=args.model_size)
    maia2 = Maia2Policy(args.device, args.batch_size) if args.include_maia2 else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    with temporary.open("w") as stream:
        for start in range(0, len(records), args.chunk_size):
            chunk = records[start:start + args.chunk_size]
            rows = maia3.predict(chunk)
            if maia2 is not None:
                for row, policy in zip(rows, maia2.predict(chunk)):
                    row["maia2"] = {"fen_only": policy}
            for row in rows:
                stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
            stream.flush()
            print(f"Policies: {min(start + args.chunk_size, len(records))}/{len(records)} "
                  f"({time.monotonic() - started:.1f}s)", flush=True)
    temporary.replace(args.output)
    manifest = {
        "schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input.relative_to(ROOT)) if args.input.is_relative_to(ROOT) else str(args.input),
        "input_sha256": sha256(args.input), "record_count": len(records),
        "output_sha256": sha256(args.output), "seconds": time.monotonic() - started,
        "adapter_sha256": sha256(Path(__file__)), "maia3": maia3.manifest,
        "history_ratings": list(HISTORY_RATINGS), "fen_only_ratings": list(FEN_RATINGS),
        "missing_history": "history map empty; all four screening ratings evaluated with FEN only",
        "maia2": maia2.manifest if maia2 is not None else None,
        "clock_note": "PGN clock fields are preserved in inputs; this screening model uses zero ponder time.",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {args.output} and {args.manifest}", flush=True)


if __name__ == "__main__":
    main()
