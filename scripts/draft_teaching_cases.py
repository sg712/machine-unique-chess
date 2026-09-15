"""Compile private, AI-assisted teaching hypotheses against an unchanged review packet.

This is a board-legality and evidence-link checker, not a chess engine or an
independent review. Narrative explanations remain hypotheses even when every
associated position, attack and continuation passes these checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import chess

ROOT = Path(__file__).resolve().parents[1]
GATES = ("chess_review", "independent_chess_review", "near_duplicate_review",
         "family_validation", "public_exposure_review", "trainer_ready")
AUTHORSHIP = "AI-assisted draft authoring; no independent chess review or teaching validation"
ALLOWED_ROLES = {"prior_development", "pilot_train", "new_train"}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def closed_gates(value):
    if not isinstance(value, dict) or set(value) != set(GATES) or any(value[k] is not False for k in GATES):
        raise ValueError("Every manual readiness gate must remain false")


def legal_line(fen, sans):
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("Invalid initial position")
    for san in sans:
        move = board.parse_san(san)
        if board.san(move) != san:
            raise ValueError("Non-canonical SAN in a board-only variation")
        board.push(move)
    return board


def verify_fact(fen, fact):
    """Check concrete board assertions; does not certify a prose explanation."""
    board = legal_line(fen, fact.get("after", []))
    assertions = fact.get("assertions", [])
    if not assertions:
        raise ValueError("A board fact needs at least one executable assertion")
    for assertion in assertions:
        kind = assertion["type"]
        if kind == "piece":
            piece = board.piece_at(chess.parse_square(assertion["square"]))
            actual = piece.symbol() if piece else None
        elif kind == "attacks":
            actual = chess.parse_square(assertion["to"]) in board.attacks(chess.parse_square(assertion["from"]))
        elif kind == "check":
            actual = board.is_check()
        elif kind == "legal_san":
            try:
                board.parse_san(assertion["san"])
                actual = True
            except ValueError:
                actual = False
        else:
            raise ValueError(f"Unsupported assertion: {kind}")
        if actual != assertion["value"]:
            raise ValueError(f"Board assertion failed: {assertion}")
    return {**fact, "assertions_verified": len(assertions),
            "verification_scope": "Legality, occupancy and geometric attacks only; no score or best-play proof"}


def verify_item(item):
    closed_gates(item["readiness"])
    if any(origin["strata"]["analysis_role"] not in ALLOWED_ROLES for origin in item["origins"]):
        raise ValueError("An untouched holdout or unknown analysis role cannot become a teaching draft")
    if item["provenance"].get("all_origins_recovered_no_bot_not_known_public") is not True:
        raise ValueError("Editorial provenance requirement failed")
    board = chess.Board(item["fen"])
    if not board.is_valid():
        raise ValueError("Invalid packet position")
    if item["accepted"]["20"] != item["accepted"]["24"]:
        raise ValueError("Acceptance changed between the saved depths")
    seen, plies = set(), 0
    for branch in item["branches"]:
        key = (branch["depth"], branch["uci"])
        if key in seen:
            raise ValueError("Duplicate saved root")
        seen.add(key)
        if branch["depth"] not in (20, 24) or branch["achieved_depth"] < branch["depth"]:
            raise ValueError("Unexpected or unfinished saved depth")
        move = chess.Move.from_uci(branch["uci"])
        if move not in board.legal_moves or board.san(move) != branch["san"]:
            raise ValueError("Illegal root or mismatched root SAN")
        if not branch["pv"] or branch["pv"][0]["uci"] != branch["uci"]:
            raise ValueError("Saved PV does not start with its root")
        replay, frames = board.copy(), [board.fen()]
        for step in branch["pv"]:
            move = chess.Move.from_uci(step["uci"])
            if move not in replay.legal_moves or replay.san(move) != step["san"]:
                raise ValueError("Illegal move or mismatched SAN in saved PV")
            replay.push(move)
            frames.append(replay.fen())
            plies += 1
        if frames != branch["frames"]:
            raise ValueError("Saved frame differs from replayed PV")
        depth = str(branch["depth"])
        if branch["acceptable"] != (branch["uci"] in item["accepted"][depth]):
            raise ValueError("Root acceptance disagrees with packet")
        if branch["loss_cp"] != item["outcome"]["best_cp"][depth] - branch["cp"]:
            raise ValueError("Root loss disagrees with saved score")
    expected = {(depth, move.uci()) for depth in (20, 24) for move in board.legal_moves}
    if seen != expected:
        raise ValueError("Packet is not exhaustive at both saved depths")
    return plies


def screening(item):
    board = chess.Board(item["fen"])
    accepted = [b for b in item["branches"] if b["depth"] == 24 and b["acceptable"]]
    best = item["outcome"]["best_cp"]["24"]
    flags = ["Saved root PVs do not verify all opponent responses or prove a teaching explanation"]
    if len(accepted) > 1:
        flags.append("Multiple accepted moves: do not teach or grade a unique answer")
    if best < 0:
        flags.append("Best saved evaluation is negative: frame as limiting damage, not winning")
    if best == 0:
        flags.append("Zero engine evaluation is not a proven draw or tablebase result")
    if any(len(b["pv"]) < 20 for b in accepted):
        flags.append("At least one accepted PV is shorter than 20 plies; no extrapolated ending")
    if any(board.is_capture(chess.Move.from_uci(b["uci"])) or board.gives_check(chess.Move.from_uci(b["uci"])) for b in accepted):
        flags.append("Accepted set includes a capture/check: generic quiet-move labeling is misleading")
    near = [b["san"] for b in item["branches"] if b["depth"] == 24 and not b["acceptable"] and b["loss_cp"] <= 50]
    if near:
        flags.append("Additional moves fall within 50 cp: avoid treating the 20 cp cutoff as a categorical blunder boundary")
    return {"id": item["id"], "accepted_san": item["accepted_san"], "best_cp": best,
            "additional_within_50_cp": near, "flags": flags, "readiness": {g: False for g in GATES}}


def compile_drafts(packet_bytes, notes):
    if sha256(packet_bytes) != notes["packet_sha256"]:
        raise ValueError("Drafts refer to a different packet")
    packet = json.loads(packet_bytes)
    closed_gates(packet["readiness"])
    closed_gates(notes["readiness"])
    if notes.get("authorship") != AUTHORSHIP:
        raise ValueError("AI-assisted draft authorship must be explicit")
    by_id = {item["id"]: item for item in packet["items"]}
    if len(by_id) != len(packet["items"]):
        raise ValueError("Duplicate packet identity")
    plies = sum(verify_item(item) for item in packet["items"])
    cases, used = [], set()
    for note in notes["cases"]:
        key = note["id"]
        if key in used or key not in by_id:
            raise ValueError("Duplicate or missing teaching case")
        used.add(key)
        item = by_id[key]
        if item["evidence_sha256"] != note["evidence_sha256"]:
            raise ValueError("Case evidence fingerprint changed")
        facts = [verify_fact(item["fen"], fact) for fact in note["board_facts"]]
        alternatives = set(note["plausible_alternatives"])
        legal = {b["uci"] for b in item["branches"]}
        if not alternatives or not alternatives <= legal:
            raise ValueError("Every comparison must have a saved legal root")
        citations = []
        for branch in item["branches"]:
            if branch["acceptable"] or branch["uci"] in alternatives:
                citations.append({k: branch[k] for k in ("depth", "uci", "san", "cp", "loss_cp", "acceptable", "maia", "pv", "root_sha256")})
        cases.append({**note, "side_to_move": item["side_to_move"], "fen": item["fen"],
                      "board_facts": facts, "saved_pv_citations": citations,
                      "screening": screening(item), "readiness": {g: False for g in GATES}})
    return {"schema_version": 1, "authorship": AUTHORSHIP,
            "packet_sha256": notes["packet_sha256"], "engine_searches_run": 0,
            "packet_positions_checked": len(by_id), "saved_roots_checked": sum(len(i["branches"]) for i in by_id.values()),
            "saved_plies_checked": plies, "cases": cases,
            "packet_screening": [screening(i) for i in packet["items"]],
            "readiness": {g: False for g in GATES}}


def markdown(result):
    out = ["# Private teaching research — AI-assisted drafts", "", AUTHORSHIP + ".",
           "These are hypotheses, not reviewed lessons. All readiness gates remain false.",
           "Scores are centipawns from the original side-to-move perspective. Maia percentages are model probabilities, not measured human response rates.",
           f"Packet SHA-256: `{result['packet_sha256']}`.", "",
           f"Checked {result['packet_positions_checked']} positions, {result['saved_roots_checked']} saved roots and {result['saved_plies_checked']} PV plies without engine search."]
    for case in result["cases"]:
        out += ["", f"## {case['title']}", "", f"Private ID: `{case['id']}`; {case['side_to_move']} to move.",
                f"FEN: `{case['fen']}`", "", case["hypothesis"], "", "### Board facts checked mechanically", ""]
        for fact in case["board_facts"]:
            line = " ".join(fact.get("after", [])) or "Initial position"
            out += [f"- {fact['text']} Position after: **{line}**."]
        out += ["", "These assertions verify occupancy, legal moves or attacks only. Board-only variations are not saved engine PVs and have no engine evaluation.",
                "", "### Why the accepted move(s) may work", "", case["accepted_explanation"],
                "", "### Plausible alternatives", "", case["alternative_explanation"],
                "", "### Lesson draft", "", case["teaching_prompt"], "", case["draft_feedback"],
                "", "### What still needs checking", ""]
        out += [f"- {text}" for text in case["requires_review"] + case["screening"]["flags"]]
        out += ["", "### Exact saved continuations", ""]
        for b in case["saved_pv_citations"]:
            out += [f"**Depth {b['depth']}, {b['san']}**: {b['cp']:+d} cp; loss {b['loss_cp']} cp; accepted {str(b['acceptable']).lower()}; Maia 2000 {100*b['maia']['2000']:.3f}%.",
                    "", " ".join(step["san"] for step in b["pv"]), "", f"Saved-root SHA-256: `{b['root_sha256']}`.", ""]
    out += ["## Whole-packet editorial exclusions and cautions", ""]
    for item in result["packet_screening"]:
        out += [f"- `{item['id']}`: " + "; ".join(item["flags"]) + "."]
    return "\n".join(out) + "\n"


def export(result, output, root=ROOT):
    output, root = Path(output).resolve(), Path(root).resolve()
    private = root / "data/mining_v3"
    if not output.is_relative_to(private) or output == private:
        raise ValueError("Teaching drafts must remain inside ignored data/mining_v3")
    rel = str(output.relative_to(root))
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", rel + "/drafts.json"], cwd=root).returncode == 0
    tracked = subprocess.run(["git", "ls-files", "--", rel], cwd=root, capture_output=True, text=True, check=True).stdout
    if not ignored or tracked.strip():
        raise ValueError("Teaching drafts must be Git-ignored and untracked")
    output.mkdir(parents=True, exist_ok=False)
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    (output / "drafts.json").write_bytes(payload)
    (output / "Teaching research drafts.md").write_text(markdown(result))
    (output / "manifest.json").write_text(json.dumps({"packet_sha256": result["packet_sha256"],
        "drafts_sha256": sha256(payload), "authorship": AUTHORSHIP, "readiness": {g: False for g in GATES}}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--notes", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compile_drafts(args.packet.read_bytes(), json.loads(args.notes.read_text()))
    export(result, args.output)
    print(json.dumps({"cases": len(result["cases"]), "positions_checked": result["packet_positions_checked"],
                      "saved_roots_checked": result["saved_roots_checked"], "saved_plies_checked": result["saved_plies_checked"],
                      "output": str(args.output.resolve()), "trainer_ready": False}))


if __name__ == "__main__":
    main()
