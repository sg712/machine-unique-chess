"""Search only admitted editorial states for concrete teaching contrasts.

Mechanism screens are deliberate, fallible retrieval rules, not concept labels.
They inspect geometry and saved PVs without engine/model execution. Selection is
post-outcome development; no family, independent review or trainer gate is set.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import candidate_review as review
import draft_teaching_cases as drafts

AUTHORSHIP = "AI-assisted development research; no independent chess review or teaching validation"


def queen_counterattack(board, move):
    """A non-queen move attacks the enemy queen while ours is attacked.

    Geometric attacks only: the screen does not claim a capture is compulsory or
    that attacking the other queen is sufficient to save material.
    """
    color = board.turn
    own, enemy = list(board.pieces(chess.QUEEN, color)), list(board.pieces(chess.QUEEN, not color))
    if len(own) != 1 or len(enemy) != 1 or not board.is_attacked_by(not color, own[0]):
        return None
    if board.piece_type_at(move.from_square) == chess.QUEEN:
        return None
    after = board.copy()
    after.push(move)
    if enemy[0] not in after.pieces(chess.QUEEN, not color):
        return None
    if enemy[0] not in after.attacks(move.to_square):
        return None
    return {"own_queen": chess.square_name(own[0]), "enemy_queen": chess.square_name(enemy[0]),
            "moved_piece": chess.piece_name(board.piece_type_at(move.from_square)),
            "own_queen_still_attacked": after.is_attacked_by(not color, own[0]),
            "also_check": after.is_check()}


def relative_pins(board):
    """Find one friendly blocker between an enemy slider and our rook/queen.

    Unlike python-chess is_pinned(), these are relative pins to material. The
    blocker can legally move; whether it should move is a score/continuation
    question, explicitly outside this geometry screen.
    """
    color, result = board.turn, []
    for target in board.pieces(chess.ROOK, color) | board.pieces(chess.QUEEN, color):
        for attacker in (board.pieces(chess.BISHOP, not color) | board.pieces(chess.ROOK, not color)
                         | board.pieces(chess.QUEEN, not color)):
            ray = chess.between(target, attacker)
            blockers = chess.SquareSet(ray & board.occupied)
            if len(blockers) != 1:
                continue
            blocker = next(iter(blockers))
            if board.color_at(blocker) != color:
                continue
            probe = board.copy()
            probe.remove_piece_at(blocker)
            if target in probe.attacks(attacker):
                result.append({"target": target, "blocker": blocker, "attacker": attacker})
    return result


def pin_target_shift(board, move):
    matches = []
    for pin in relative_pins(board):
        if move.from_square != pin["target"]:
            continue
        after = board.copy()
        after.push(move)
        matches.append({**{key: chess.square_name(value) for key, value in pin.items()},
                        "new_target": chess.square_name(move.to_square),
                        "new_target_defenders": [chess.square_name(s) for s in after.attackers(board.turn, move.to_square)],
                        "blocker_captures_available": [board.san(m) for m in board.legal_moves
                                                       if m.from_square == pin["blocker"] and board.is_capture(m)]})
    return matches


def knight_forks(board, pv, max_plies=6):
    """Locate opponent knight checks that also attack our nonpawn material."""
    color, replay, found = board.turn, board.copy(), []
    for index, step in enumerate(pv[:max_plies]):
        move = chess.Move.from_uci(step["uci"])
        if move not in replay.legal_moves or replay.san(move) != step["san"]:
            raise ValueError("Invalid saved continuation")
        knight = replay.piece_type_at(move.from_square) == chess.KNIGHT and replay.turn != color
        replay.push(move)
        if knight and replay.is_check():
            targets = [s for s in replay.attacks(move.to_square)
                       if replay.color_at(s) == color and replay.piece_type_at(s) not in (chess.KING, chess.PAWN)]
            if targets:
                found.append({"ply": index + 1, "san": step["san"], "knight": chess.square_name(move.to_square),
                              "targets": [chess.square_name(s) for s in targets]})
    return found


def load_editorial(root=ROOT):
    records, outcomes, manifest, paths, hashes, aggregate = review.verify_bundle(root)
    ids, counts = review.editorial_pool(records, outcomes, manifest)
    safe = set(ids)
    # Filter identities before constructing boards or inspecting any PV.
    records = {key: records[key] for key in ids}
    outcomes = {key: outcomes[key] for key in ids}
    policies = {key: row for key, row in review.load_rows(paths["policy_sha256"]).items() if key in safe}
    roots = defaultdict(list)
    for name in ("new_roots_sha256", "imported_roots_sha256"):
        with paths[name].open() as source:
            for line in source:
                row = json.loads(line)
                if row["record_id"] in safe:
                    roots[row["record_id"]].append(row)
    return records, outcomes, manifest, policies, roots, hashes, counts


def scan(records, outcomes, roots):
    result = {"queen_counterattack": [], "pin_target_shift": [], "knight_fork_contrast": []}
    for key in sorted(records):
        board = chess.Board(records[key]["fen"])
        roots24 = {row["uci"]: row for row in roots[key] if row["target_depth"] == 24}
        roots20 = {row["uci"]: row for row in roots[key] if row["target_depth"] == 20}
        for uci, row in roots24.items():
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError("Root is not legal in the admitted state")
            accepted = uci in outcomes[key]["accepted"]["24"]
            losses = {str(d): outcomes[key]["best_cp"][str(d)] - source[uci]["cp"]
                      for d, source in ((20, roots20), (24, roots24))}
            base = {"id": key, "uci": uci, "san": board.san(move), "accepted": accepted, "loss_cp": losses}
            if feature := queen_counterattack(board, move):
                result["queen_counterattack"].append({**base, "feature": feature})
            if feature := pin_target_shift(board, move):
                result["pin_target_shift"].append({**base, "feature": feature})
            if not accepted and min(losses.values()) >= 100:
                forks = knight_forks(board, row["pv"])
                if forks:
                    result["knight_fork_contrast"].append({**base, "feature": forks})
    return result


def validate_selection(notes, records, manifest):
    """Reject heldout IDs before accessing their boards, and all source overlap."""
    drafts.closed_gates(notes["readiness"])
    if notes.get("authorship") != AUTHORSHIP:
        raise ValueError("AI authorship must be explicit")
    seen_ids, seen_games, seen_states = set(), set(), set()
    for family in notes["families"]:
        if Counter(case["role"] for case in family["cases"]) != {"positive": 2, "boundary": 1}:
            raise ValueError("Each proposed family needs two positives and one boundary")
        for case in family["cases"]:
            key = case["id"]
            if key not in records:
                raise ValueError("Selected identity is not in the admitted editorial pool")
            if key in seen_ids:
                raise ValueError("A case cannot be reused across lesson roles")
            origins = manifest["canonical_origins_by_id"][key]
            if any(origin["strata"]["analysis_role"] not in review.EDITORIAL_ROLES for origin in origins):
                raise ValueError("Every origin must have a permitted development/training role")
            if manifest["state_provenance_by_id"][key]["all_origins_recovered_no_bot_not_known_public"] is not True:
                raise ValueError("Every origin must meet the editorial provenance condition")
            games = review.source_games(origins)
            if seen_games & games:
                raise ValueError("Source games or legacy aliases overlap across lesson roles")
            state = review.selection.canonical_fen(records[key]["fen"])
            if state in seen_states:
                raise ValueError("Canonical states overlap across lesson roles")
            seen_ids.add(key)
            seen_games.update(games)
            seen_states.add(state)
    return seen_ids


def verify_question(item, question):
    board = drafts.legal_line(item["fen"], question["after"])
    if question["scope"] == "saved_pv":
        branch = next((b for b in item["branches"] if b["depth"] == 24 and b["uci"] == question["root_uci"]), None)
        if branch is None:
            raise ValueError("Continuation question has no saved depth-24 root")
        line = [step["san"] for step in branch["pv"]]
        index = len(question["after"])
        if line[:index] != question["after"] or len(line) <= index or line[index] != question["answer_san"]:
            raise ValueError("Question answer differs from the exact saved continuation")
        board.parse_san(question["answer_san"])
    elif question["scope"] == "legality_only":
        try:
            board.parse_san(question["answer_san"])
            legal = True
        except ValueError:
            legal = False
        if legal is not question["answer_is_legal"]:
            raise ValueError("Continuation legality answer is wrong")
    else:
        raise ValueError("Question must distinguish saved evidence from legality-only analysis")
    return {**question, "verification": "Exact saved continuation or legal-move check only; not human validation"}


def verify_accepted_coverage(item, note):
    discussions = note.get("accepted_move_discussions", {})
    if set(discussions) != set(item["accepted"]["24"]) or any(
            not isinstance(value, str) or not value.strip() for value in discussions.values()):
        raise ValueError("The authored explanation must discuss every accepted move exactly once")


def verify_note_sources(notes, root=ROOT):
    root, fingerprints = Path(root).resolve(), {}
    for source in notes.get("source_bindings", []):
        path = (root / source["path"]).resolve()
        if not path.is_relative_to(root / "data/mining_v3"):
            raise ValueError("Seed evidence must remain in the private research directory")
        if source["path"] in fingerprints:
            raise ValueError("Duplicate seed evidence binding")
        fingerprints[source["path"]] = review.check_hash(path, source["sha256"])
    if not fingerprints:
        raise ValueError("Authored notes require unchanged seed evidence bindings")
    return fingerprints


def compile_bank(notes, records, outcomes, manifest, policies, roots, hashes, counts):
    validate_selection(notes, records, manifest)
    compiled, roots_checked, plies_checked = [], 0, 0
    for family in notes["families"]:
        cases = []
        for note in family["cases"]:
            key = note["id"]
            item = review.make_item(records[key], policies[key], outcomes[key], roots[key], manifest)
            verify_accepted_coverage(item, note)
            plies_checked += drafts.verify_item(item)
            roots_checked += len(item["branches"])
            alternatives = set(note["comparison_uci"])
            if not alternatives or not alternatives <= {b["uci"] for b in item["branches"]}:
                raise ValueError("Every lesson comparison must have a saved legal root")
            facts = [drafts.verify_fact(item["fen"], fact) for fact in note["board_facts"]]
            questions = [verify_question(item, question) for question in note["continuation_questions"]]
            branches = [branch for branch in item["branches"] if branch["acceptable"] or branch["uci"] in alternatives]
            cases.append({**note, "fen": item["fen"], "phase": item["phase"],
                          "side_to_move": item["side_to_move"], "evidence_sha256": item["evidence_sha256"],
                          "origins": item["origins"], "provenance": item["provenance"],
                          "accepted": item["accepted"], "accepted_san": item["accepted_san"],
                          "board_facts": facts, "continuation_questions": questions,
                          "saved_branches": branches, "screening": drafts.screening(item),
                          "readiness": {gate: False for gate in review.MANUAL_GATES}})
        compiled.append({**family, "cases": cases,
                         "status": "contrasting development draft, not validated family",
                         "readiness": {gate: False for gate in review.MANUAL_GATES}})
    return {"schema_version": 1, "authorship": AUTHORSHIP, "fingerprints": hashes,
            "counts": {**counts, "families_drafted": len(compiled),
                       "cases_drafted": sum(len(f["cases"]) for f in compiled),
                       "saved_roots_replayed": roots_checked, "saved_plies_replayed": plies_checked},
            "selection": "Deliberate mechanism screening and post-outcome editorial selection; no population or learning inference",
            "engine_searches_run": 0, "model_inferences_run": 0,
            "families": compiled, "rejections": notes["rejections"],
            "readiness": {gate: False for gate in review.MANUAL_GATES}}


def markdown(bank):
    out = ["# Private contrasting lesson drafts", "", AUTHORSHIP + ".",
           "All nine cases are development material. None is a validated family, assessment item or trainer release.",
           "Scores are centipawns from the initial side-to-move perspective. Maia probabilities are model predictions, not human success rates.",
           "Every comparison uses unchanged complete legal-root depth-20/depth-24 evidence. All acceptable alternatives remain visible.", ""]
    for family in bank["families"]:
        out += [f"## {family['title']}", "", family["conditional_rule"], "", "**Limit:** " + family["limit"], "",
                "**How to teach it:** " + family["teaching_order"], ""]
        for case in family["cases"]:
            out += [f"### {case['role'].title()}: {case['title']}", "",
                    f"Private ID: `{case['id']}`. {case['side_to_move'].title()} to move; {case['phase']}.",
                    f"FEN: `{case['fen']}`", "", "```", chess.Board(case["fen"]).unicode(borders=True), "```", "",
                    "**Prompt:** " + case["prompt"], "",
                    "**All accepted moves:** " + ", ".join(case["accepted_san"]) + ".", "",
                    "**Explanation:** " + case["explanation"], "", "**Contrast:** " + case["contrast"], "",
                    "**Accepted-answer coverage:**", ""]
            board = chess.Board(case["fen"])
            for uci, discussion in case["accepted_move_discussions"].items():
                out += [f"- **{board.san(chess.Move.from_uci(uci))}**: {discussion}"]
            out += ["", "**Mechanically checked facts:**", ""]
            for fact in case["board_facts"]:
                after = " ".join(fact.get("after", [])) or "Initial position"
                out += [f"- {fact['text']} After: {after}."]
            out += ["", "Board-only variations establish legality and geometry, not an engine score or forced reply.", "",
                    "**Continuation questions:**", ""]
            for question in case["continuation_questions"]:
                out += [f"- After {' '.join(question['after'])}: {question['prompt']} Answer: {question['explanation']} ({question['scope']})."]
            out += ["", "**Exact saved evidence:**", ""]
            for branch in case["saved_branches"]:
                out += [f"- Depth {branch['depth']}, **{branch['san']}**: {branch['cp']:+d} cp; loss {branch['loss_cp']} cp; accepted {str(branch['acceptable']).lower()}; Maia 2000 {100 * branch['maia']['2000']:.3f}%.",
                        "", "  " + " ".join(step["san"] for step in branch["pv"]), "",
                        f"  Saved-root SHA-256: `{branch['root_sha256']}`.", ""]
            out += ["**Still requiring review:**", ""]
            out += ["- " + text for text in case["requires_review"] + case["screening"]["flags"]]
            out += [""]
    out += ["## Rejected or deferred matches", ""]
    for row in bank["rejections"]:
        out += [f"- **{row['hypothesis']}**: {row['reason']}"]
    out += ["", "All chess-review, independent-review, near-duplicate, family-validation, public-exposure-review and trainer-readiness gates remain false."]
    return "\n".join(out) + "\n"


def export_bank(bank, output, root=ROOT):
    output = review.require_private_output(output, root)
    output.mkdir(parents=True, exist_ok=False)
    payload = review.encoded(bank)
    (output / "bank.json").write_bytes(payload)
    (output / "Contrasting lesson drafts.md").write_text(markdown(bank))
    (output / "manifest.json").write_bytes(review.encoded({
        "schema_version": 1, "bank_sha256": drafts.sha256(payload),
        "authorship": AUTHORSHIP, "trainer_ready": False,
        "counts": bank["counts"], "fingerprints": bank["fingerprints"]}))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-output", type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--bank-output", type=Path)
    args = parser.parse_args()
    if bool(args.scan_output) == bool(args.notes) or bool(args.notes) != bool(args.bank_output):
        parser.error("Use --scan-output OR --notes together with --bank-output")
    out = review.require_private_output(args.scan_output or args.bank_output, ROOT)
    records, outcomes, manifest, policies, roots, hashes, counts = load_editorial()
    hashes["lesson_research_builder_sha256"] = review.digest(__file__)
    if args.notes:
        hashes["private_authored_notes_sha256"] = review.digest(args.notes)
        notes = json.loads(args.notes.read_text())
        hashes["seed_evidence_sha256"] = verify_note_sources(notes)
        bank = compile_bank(notes, records, outcomes, manifest, policies, roots, hashes, counts)
        export_bank(bank, out)
        print(json.dumps(bank["counts"]))
        return
    result = {"schema_version": 1, "authorship": AUTHORSHIP, "fingerprints": hashes,
              "counts": counts, "engine_searches_run": 0, "model_inferences_run": 0,
              "readiness": {gate: False for gate in review.MANUAL_GATES},
              "screens": scan(records, outcomes, roots)}
    out.mkdir(parents=True, exist_ok=False)
    (out / "screen.json").write_bytes(review.encoded(result))
    print(json.dumps({"editorial_states": len(records), "screened_roots": sum(map(len, roots.values())),
                      "hits": {name: len(rows) for name, rows in result["screens"].items()}}))


if __name__ == "__main__":
    main()
