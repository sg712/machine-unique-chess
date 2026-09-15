"""Versioned, evidence-bound practice answers. No engine or model runs here.

The legacy adapter preserves exact-match grading. Explicit sets must agree with
complete, numeric legal-root evidence at both declared search depths. Validating
this contract does not establish independent chess review or teaching readiness.
"""
from functools import lru_cache
import hashlib
import json
import re

import chess


SCHEMA = "acceptable-moves/v1"
SHA256 = re.compile(r"[a-f0-9]{64}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError("Invalid answer evidence: " + message)


def _fields(value, names, label):
    _require(isinstance(value, dict) and set(value) == set(names), label)


def _pv(fen, moves, root):
    _require(isinstance(moves, list) and 0 < len(moves) <= 256 and moves[0] == root,
             "each root needs its own continuation")
    board = chess.Board(fen)
    out = []
    for value in moves:
        _require(isinstance(value, str), "non-string continuation move")
        try:
            move = chess.Move.from_uci(value)
        except ValueError as exc:
            raise ValueError("Invalid answer evidence: malformed continuation move") from exc
        _require(move in board.legal_moves, "illegal continuation move")
        out.append({"uci": value, "san": board.san(move)})
        board.push(move)
    return out


@lru_cache(maxsize=1024)
def _validated(fen, best, serialized):
    board = chess.Board(fen)
    legal = {move.uci() for move in board.legal_moves}
    _require(board.is_valid() and best in legal, "invalid board or reference move")
    if serialized is None:
        identity = digest({"schema": "legacy-exact/v1", "fen": fen, "best": best})
        return {"schema": "legacy-exact/v1", "grading_id": identity,
                "accepted": (best,), "branches": {}, "explicit": False}
    answer = json.loads(serialized)
    _fields(answer, ("schema", "version", "accepted", "criterion", "engine",
                     "evidence", "evidence_sha256"), "answer fields")
    _require(answer["schema"] == SCHEMA, "unknown schema")
    _require(isinstance(answer["version"], str) and
             re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,95}", answer["version"]),
             "missing or malformed bank version")
    criterion = answer["criterion"]
    _fields(criterion, ("id", "depths", "tolerance_cp", "score_perspective"), "criterion fields")
    _require(criterion["id"] == "stable-complete-root-cp/v1" and
             criterion["depths"] == [20, 24] and
             all(type(depth) is int for depth in criterion["depths"]) and
             criterion["score_perspective"] == "side_to_move", "unsupported criterion")
    tolerance = criterion["tolerance_cp"]
    _require(type(tolerance) is int and 0 <= tolerance <= 100, "invalid tolerance")
    engine = answer["engine"]
    _fields(engine, ("name", "version", "binary_sha256", "threads", "hash_mb",
                     "clear_hash_per_root", "context"), "engine provenance fields")
    _require(engine["name"] == "Stockfish" and isinstance(engine["version"], str) and
             0 < len(engine["version"]) <= 64 and isinstance(engine["binary_sha256"], str) and
             SHA256.fullmatch(engine["binary_sha256"]) and engine["threads"] == 1 and
             type(engine["threads"]) is int and engine["hash_mb"] == 64 and
             type(engine["hash_mb"]) is int and engine["clear_hash_per_root"] is True and
             engine["context"] == "fen_only", "unsupported or missing search provenance")
    evidence = answer["evidence"]
    _fields(evidence, ("fen", "roots"), "evidence fields")
    _require(evidence["fen"] == fen and isinstance(answer["evidence_sha256"], str) and
             SHA256.fullmatch(answer["evidence_sha256"]) and
             digest(evidence) == answer["evidence_sha256"], "evidence hash or position mismatch")
    roots = evidence["roots"]
    _require(isinstance(roots, dict) and set(roots) == legal, "incomplete legal-root coverage")
    branches = {}
    for root, records in roots.items():
        _fields(records, ("20", "24"), "search depth coverage")
        for depth, record in records.items():
            _fields(record, ("score_cp", "depth", "bound", "pv"), "root evidence fields")
            _require(type(record["score_cp"]) is int and abs(record["score_cp"]) < 100000 and
                     type(record["depth"]) is int and record["depth"] >= int(depth) and
                     record["bound"] == "exact", "non-numeric, bounded or incomplete search")
            line = _pv(fen, record["pv"], root)
            if depth == "24":
                branches[root] = line
    accepted = answer["accepted"]
    _require(isinstance(accepted, list) and accepted and
             all(isinstance(move, str) for move in accepted) and
             len(accepted) == len(set(accepted)) and set(accepted) <= legal,
             "invalid accepted moves")
    for depth in ("20", "24"):
        top = max(root[depth]["score_cp"] for root in roots.values())
        expected = {move for move, root in roots.items()
                    if top - root[depth]["score_cp"] <= tolerance}
        _require(set(accepted) == expected, "declared set disagrees with complete-root evidence")
    top = max(root["24"]["score_cp"] for root in roots.values())
    _require(best in accepted and roots[best]["24"]["score_cp"] == top,
             "reference move is not a depth-24 best move")
    return {"schema": SCHEMA, "grading_id": digest({"fen": fen, "best": best, "answer": answer}),
            "accepted": tuple(sorted(accepted)), "branches": branches, "explicit": True,
            "version": answer["version"], "tolerance_cp": tolerance,
            "evidence_sha256": answer["evidence_sha256"]}


def answer_spec(position):
    """The canonical identity includes grading evidence, never mutable UI copy."""
    try:
        serialized = (json.dumps(position["answer"], sort_keys=True, allow_nan=False)
                      if "answer" in position else None)
        return _validated(position["fen"], position["best"], serialized)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid answer evidence: malformed answer") from exc


def grade(position, picked):
    spec = answer_spec(position)
    return picked in spec["accepted"]


def feedback_metadata(position, picked):
    """Only call after a legal response; never include this in question payloads."""
    spec = answer_spec(position)
    board = chess.Board(position["fen"])
    return {"answer_schema": spec["schema"], "grading_id": spec["grading_id"],
            "acceptable_moves": [{"uci": move, "san": board.san(chess.Move.from_uci(move))}
                                 for move in spec["accepted"]],
            "accepted_alternative": picked in spec["accepted"] and picked != position["best"],
            "tolerance_cp": spec.get("tolerance_cp"),
            "answer_version": spec.get("version")}
