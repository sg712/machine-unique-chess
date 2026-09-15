"""Assemble a private editorial review from completed v3 evidence; never run an engine.

The packet is not a trainer bank, a new experiment or a human-review approval.
All validation/test source roles are excluded from editorial consumption.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import mining_v3_full_deep as scorer
import mining_v3_full_deep_selection as selection

EDITORIAL_ROLES = {"prior_development", "pilot_train", "new_train"}
SEED = 20260916
STATUSES = ("pending", "promising", "revise", "reject")
NOTE_FIELDS = ("reviewer", "family_hypothesis", "explanation", "why_alternatives_fail",
               "limiting_case", "near_duplicate_notes", "source_review_notes")
MANUAL_GATES = ("chess_review", "independent_chess_review", "near_duplicate_review",
                "family_validation", "public_exposure_review", "trainer_ready")
METHOD = ("Editorial selection after observing engine outcomes, not a representative sample or "
          "a held-out test. Require retained full criterion and every origin recovered, without "
          "BOT tags or known public exposure. Only prior_development, pilot_train and new_train "
          "roles may enter. Alternate White/Black; round-robin declared phase and single/multiple "
          "acceptable-move buckets; rank within buckets by seeded SHA-256. No repeated game "
          "across any originating observation, including recorded legacy aliases. "
          "The packet runs no searches and grants no review or trainer approval.")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_rows(path):
    index = {}
    with Path(path).open() as source:
        for line in source:
            row = json.loads(line)
            key = row.get("id")
            if not isinstance(key, str) or not key or key in index:
                raise ValueError("Missing or duplicate evidence identity")
            index[key] = row
    return index


def check_hash(path, expected):
    actual = digest(path)
    if not isinstance(expected, str) or actual != expected:
        raise ValueError(f"Evidence hash changed: {Path(path).name}")
    return actual


def source_games(origins):
    if not origins or any(not isinstance(row.get("game_id"), str) or not row["game_id"] for row in origins):
        raise ValueError("Origin is missing its source game")
    return {row[key] for row in origins for key in ("game_id", "legacy_game_id")
            if isinstance(row.get(key), str) and row[key]}


def editorial_pool(records, outcomes, manifest):
    if set(records) != set(outcomes) or set(records) != set(manifest["canonical_origins_by_id"]):
        raise ValueError("Source and outcome identities differ")
    eligible, counts = [], Counter()
    for key, row in records.items():
        outcome = outcomes[key]
        origins = manifest["canonical_origins_by_id"][key]
        provenance = selection.state_provenance(origins)
        if provenance != manifest["state_provenance_by_id"][key]:
            raise ValueError("Any-origin provenance changed")
        if outcome.get("fen") != row["fen"] or outcome.get("trainer_ready") is not False:
            raise ValueError("Outcome identity or readiness differs from frozen evidence")
        if outcome.get("survives") is not True:
            counts["not_retained"] += 1
            continue
        if outcome.get("engine_verified") is not True:
            raise ValueError("Retained outcome lacks engine verification")
        counts["retained"] += 1
        if provenance["all_origins_recovered_no_bot_not_known_public"] is not True:
            counts["source_excluded"] += 1
            continue
        counts["source_eligible_retained"] += 1
        roles = set(provenance["analysis_roles"])
        if not roles or not roles <= EDITORIAL_ROLES:
            counts["noneditorial_role_excluded"] += 1
            continue
        source_games(origins)
        eligible.append(key)
    counts["editorial_eligible"] = len(eligible)
    return eligible, dict(counts)


def choose_batch(eligible, records, outcomes, manifest, count=24, seed=SEED):
    if type(count) is not int or count <= 0 or count % 2:
        raise ValueError("Batch count must be a positive even number")
    buckets = {side: defaultdict(list) for side in ("white", "black")}
    for key in eligible:
        row, outcome = records[key], outcomes[key]
        side = row["side_to_move"]
        if side not in buckets:
            raise ValueError("Unknown side to move")
        bucket = (row.get("phase", "unknown"), "single" if len(outcome["accepted"]["24"]) == 1 else "multiple")
        buckets[side][bucket].append(key)
    rank = lambda key: (hashlib.sha256(f"muc-editorial-v1:{seed}:{key}".encode()).hexdigest(), key)
    for side in buckets:
        for bucket in buckets[side]:
            buckets[side][bucket] = deque(sorted(buckets[side][bucket], key=rank))
    order = {side: deque(sorted(buckets[side])) for side in buckets}
    used_games, chosen = set(), []
    for index in range(count):
        side = ("white", "black")[index % 2]
        selected = None
        for _ in range(len(order[side])):
            bucket = order[side][0]
            order[side].rotate(-1)
            queue = buckets[side][bucket]
            while queue:
                key = queue.popleft()
                games = source_games(manifest["canonical_origins_by_id"][key])
                if games.isdisjoint(used_games):
                    selected = key
                    used_games.update(games)
                    break
            if selected is not None:
                break
        if selected is None:
            raise ValueError(f"Insufficient distinct-source {side} positions for the requested batch")
        chosen.append(selected)
    return chosen


def verify_bundle(root=ROOT):
    root = Path(root)
    run_dir, source_dir = root / "results/mining_v3/deep_all", root / "data/mining_v3/deep_all"
    aggregate_path = root / "results/mining_v3_full_deep.json"
    aggregate = json.loads(aggregate_path.read_text())
    if aggregate.get("complete") is not True or not aggregate.get("validation") or not all(v is True for v in aggregate["validation"].values()):
        raise ValueError("A completely validated census is required")
    expected = {"checked_n": 4345, "completed_positions_n": 4345, "pending_positions_n": 0,
                "partially_searched_positions_n": 0, "completed_root_searches_n": 304068,
                "imported_root_searches_n": 14208, "new_completed_root_searches_n": 289860,
                "new_pending_root_searches_n": 0, "trainer_ready_n": 0}
    if any(aggregate["counts"].get(key) != value for key, value in expected.items()):
        raise ValueError("Completed census coverage is inconsistent")
    paths = {"input_sha256": source_dir / "positions.jsonl", "policy_sha256": source_dir / "policies.jsonl",
             "selection_manifest_sha256": source_dir / "selection_manifest.json",
             "positions_sha256": run_dir / "positions.jsonl", "new_roots_sha256": run_dir / "roots.jsonl",
             "imported_roots_sha256": run_dir / "imported_roots.jsonl",
             "run_manifest_snapshot_sha256": run_dir / "run.json",
             "checkpoint_manifest_snapshot_sha256": run_dir / "checkpoint.json",
             "runner_sha256": root / "scripts/mining_v3_full_deep.py",
             "original_runner_sha256": root / "scripts/mining_v3_deep.py",
             "search_and_metrics_sha256": root / "scripts/mining_v2_engine.py",
             "canonicalization_sha256": root / "scripts/mining_v2_sampling.py",
             "io_sha256": root / "scripts/mining_v3_io.py",
             "summary_builder_sha256": root / "scripts/mining_v3_full_deep_summary.py"}
    hashes = {key: check_hash(path, aggregate["fingerprints"].get(key)) for key, path in paths.items()}
    run, checkpoint = (json.loads(paths[key].read_text()) for key in ("run_manifest_snapshot_sha256", "checkpoint_manifest_snapshot_sha256"))
    if run.get("complete") is not True or checkpoint["bytes"] != paths["new_roots_sha256"].stat().st_size or checkpoint["sha256"] != hashes["new_roots_sha256"]:
        raise ValueError("Run or exact durable checkpoint is incomplete")
    manifest = json.loads(paths["selection_manifest_sha256"].read_text())
    check_hash(selection.__file__, manifest["selection_script_sha256"])
    records, outcomes = load_rows(paths["input_sha256"]), load_rows(paths["positions_sha256"])
    if len(records) != expected["checked_n"]:
        raise ValueError("Input count does not match the complete census")
    for key, field in (("engine_verified_n", "engine_verified"), ("survives_candidate_criterion_n", "survives")):
        if sum(row[field] is True for row in outcomes.values()) != aggregate["counts"][key]:
            raise ValueError("Outcome counts differ from the validated aggregate")
    hashes.update(aggregate_sha256=digest(aggregate_path), review_builder_sha256=digest(__file__))
    return records, outcomes, manifest, paths, hashes, aggregate


def make_item(record, policy, outcome, roots, manifest):
    key = record["id"]
    roots = sorted(roots, key=lambda row: (row["target_depth"], row["uci"]))
    imported = key in set(manifest["already_deep200_ids"])
    recomputed = scorer.summarize_record(record, policy, roots, manifest["strata_by_id"][key], imported)
    if recomputed != outcome or recomputed["survives"] is not True:
        raise ValueError("Selected outcome differs from complete root recomputation")
    board = chess.Board(record["fen"])
    branches = []
    for root in roots:
        replay, frames = board.copy(), [board.fen()]
        for step in root["pv"]:
            replay.push_uci(step["uci"])
            frames.append(replay.fen())
        branches.append({"depth": root["target_depth"], "achieved_depth": root["depth"],
                         "uci": root["uci"], "san": board.san(chess.Move.from_uci(root["uci"])),
                         "cp": root["cp"], "loss_cp": outcome["best_cp"][str(root["target_depth"])] - root["cp"],
                         "acceptable": root["uci"] in outcome["accepted"][str(root["target_depth"])],
                         "pv": root["pv"], "frames": frames,
                         "maia": {rating: mapping[root["uci"]] for rating, mapping in policy["maia3"]["fen_only"].items()},
                         "root_sha256": hashlib.sha256(encoded(root)).hexdigest()})
    identity = hashlib.sha256(encoded({"id": key, "fen": record["fen"], "outcome": outcome, "roots": roots})).hexdigest()
    return {"id": key, "fen": record["fen"], "side_to_move": record["side_to_move"],
            "phase": record.get("phase", "unknown"), "accepted": outcome["accepted"],
            "accepted_san": [board.san(chess.Move.from_uci(move)) for move in outcome["accepted"]["24"]],
            "outcome": outcome, "branches": branches, "evidence_sha256": identity,
            "origins": manifest["canonical_origins_by_id"][key],
            "provenance": manifest["state_provenance_by_id"][key],
            "readiness": {gate: False for gate in MANUAL_GATES}}


def blank_reviews(packet, packet_hash):
    return {"schema_version": 1, "packet_sha256": packet_hash,
            "items": [{"id": item["id"], "evidence_sha256": item["evidence_sha256"], "status": "pending",
                       **{field: "" for field in NOTE_FIELDS}} for item in packet["items"]]}


def validate_reviews(value, packet, packet_hash):
    if not isinstance(value, dict) or set(value) != {"schema_version", "packet_sha256", "items"} or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["packet_sha256"] != packet_hash:
        raise ValueError("Review file belongs to different packet evidence")
    expected = {row["id"]: row["evidence_sha256"] for row in packet["items"]}
    if not isinstance(value["items"], list) or len(value["items"]) != len(expected):
        raise ValueError("Review file has missing or extra positions")
    seen = set()
    for row in value["items"]:
        if (not isinstance(row, dict) or set(row) != {"id", "evidence_sha256", "status", *NOTE_FIELDS}
                or row.get("id") not in expected or row["id"] in seen or row["evidence_sha256"] != expected[row["id"]]
                or row["status"] not in STATUSES or any(not isinstance(row[field], str) or len(row[field]) > 20000 for field in NOTE_FIELDS)):
            raise ValueError("Invalid review identity, status or note fields")
        seen.add(row["id"])
    return value


def require_private_output(output, root=ROOT):
    output, root = Path(output).resolve(), Path(root).resolve()
    private = root / "data/mining_v3"
    if not output.is_relative_to(private) or output == private:
        raise ValueError("Private packets must be inside the ignored data/mining_v3 directory")
    relative = str(output.relative_to(root) / "packet.json")
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", relative], cwd=root).returncode == 0
    tracked = subprocess.run(["git", "ls-files", "--", str(output.relative_to(root))], cwd=root, capture_output=True, text=True, check=True).stdout
    if not ignored or tracked.strip():
        raise ValueError("Output must be Git-ignored and contain no tracked files")
    if output.exists():
        raise FileExistsError("Review packet already exists; choose a new directory to preserve reviews")
    return output


def build_packet(root=ROOT, count=24, seed=SEED):
    records, outcomes, manifest, paths, hashes, aggregate = verify_bundle(root)
    eligible, counts = editorial_pool(records, outcomes, manifest)
    chosen = choose_batch(eligible, records, outcomes, manifest, count, seed)
    policies = load_rows(paths["policy_sha256"])
    roots = defaultdict(list)
    wanted = set(chosen)
    for path in (paths["imported_roots_sha256"], paths["new_roots_sha256"]):
        with path.open() as source:
            for line in source:
                row = json.loads(line)
                if row["record_id"] in wanted:
                    roots[row["record_id"]].append(row)
    items = [make_item(records[key], policies[key], outcomes[key], roots[key], manifest) for key in chosen]
    return {"schema_version": 1, "purpose": "private_editorial_review", "method": METHOD, "seed": seed,
            "source_aggregate_created_at": aggregate["created_at"], "fingerprints": hashes,
            "pool_counts": counts, "selected_n": len(items),
            "selected_by_side": dict(Counter(item["side_to_move"] for item in items)),
            "selected_by_phase": dict(Counter(item["phase"] for item in items)),
            "editorial_pool_ids": sorted(eligible), "items": items,
            "readiness": {gate: False for gate in MANUAL_GATES}}


def export_packet(packet, output, root=ROOT):
    output = require_private_output(output, root)
    payload = encoded(packet)
    fingerprint = hashlib.sha256(payload).hexdigest()
    reviews = blank_reviews(packet, fingerprint)
    exports = {"packet.json": payload, "reviews.json": encoded(reviews),
               "review.html": review_html(packet, fingerprint).encode(),
               "README.md": ("# Private chess review\n\nOpen review.html locally. No server, engine or internet connection is needed. "
                             "The browser keeps edits in memory: export review notes before closing; import them next time. "
                             "Keep packet.json unchanged. Use a new folder for any regenerated packet.\n\n"
                             f"{packet['selected_n']} positions; {packet['selected_by_side'].get('white', 0)} White and "
                             f"{packet['selected_by_side'].get('black', 0)} Black. Evidence SHA-256: {fingerprint}.\n\n"
                             "Saved branches are exact continuations from the frozen searches, not explanations or new analysis. "
                             "All scores are centipawns from the original side-to-move perspective. Maia percentages are model predictions, "
                             "not observed human success rates. All readiness gates remain false regardless of review-note status.\n\n"
                             + METHOD + "\n").encode()}
    exports["manifest.json"] = encoded({"schema_version": 1, "packet_sha256": fingerprint,
                                       "files_sha256": {name: hashlib.sha256(content).hexdigest() for name, content in exports.items()},
                                       "review_notes_are_separate": True, "trainer_ready": False})
    output.mkdir(parents=True, exist_ok=False)
    for name, content in exports.items():
        with (output / name).open("xb") as handle:
            handle.write(content)
    return {"selected_n": packet["selected_n"], "selected_by_side": packet["selected_by_side"],
            "pool_counts": packet["pool_counts"], "packet_sha256": fingerprint,
            "review_path": str(output / "review.html"), "trainer_ready": False}


def review_html(packet, fingerprint):
    data = encoded({"packet": packet, "reviews": blank_reviews(packet, fingerprint)}).decode().replace("<", "\\u003c")
    return HTML.replace("__DATA__", data)


HTML = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Machine Unique Chess · Private review desk</title><style>
*{box-sizing:border-box}body{margin:0;background:#faf9f5;color:#24251e;font:17px/1.5 Georgia,serif}main{max-width:1150px;margin:auto;padding:28px 24px 70px}h1{font-size:34px;margin:0}h2{font-size:23px}.meta,label,button,select,textarea,input,summary{font:14px/1.5 system-ui,sans-serif}p{max-width:76ch}.notice{border-left:3px solid #7d3524;padding:8px 14px;background:#efebe2}.toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:20px 0}button,select,input,textarea{border:1px solid #aaa496;border-radius:3px;padding:8px;background:#fffefa;color:inherit}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}:focus-visible{outline:3px solid #873d29;outline-offset:3px}.workspace{display:grid;grid-template-columns:minmax(280px,440px) minmax(0,1fr);gap:32px}.board{display:grid;grid-template-columns:repeat(8,1fr);aspect-ratio:1}.square{position:relative;display:flex;align-items:center;justify-content:center;font:44px/1 Georgia}.light{background:#eeeadb}.dark{background:#9da386}.white{color:#fff;text-shadow:1px 0 #24251e,-1px 0 #24251e,0 1px #24251e,0 -1px #24251e}.coord{position:absolute;left:3px;bottom:3px;font:10px system-ui;color:#25261f}.form label{display:block;margin:14px 0 4px}.form textarea,.form input{display:block;width:100%}.form textarea{min-height:85px;resize:vertical}#branch{max-width:100%}#line{min-height:3em;overflow-wrap:anywhere}details{margin:18px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 monospace}#notice{min-height:1.5em;color:#783621}@media(max-width:760px){main{padding:20px 15px}.workspace{grid-template-columns:1fr}.board{max-width:440px}.square{font-size:clamp(28px,8vw,44px)}}
</style><main><p class="meta">MACHINE UNIQUE CHESS / EDITORIAL</p><h1>Private review desk</h1>
<p class="notice">Read the position, test a teaching claim, and record what still needs work. These are engine-checked candidates. No position is approved for the trainer. Review notes stay separate from the frozen evidence.</p>
<div class="toolbar"><button id="previous">Previous position</button><label>Position <select id="position"></select></label><button id="next">Next position</button><span id="progress" class="meta"></span></div>
<div class="workspace"><section><h2 id="heading"></h2><p id="accepted"></p><div id="board" class="board" role="img"></div>
<div class="toolbar"><label>Depth <select id="depth"><option>24</option><option>20</option></select></label><label>Saved branch <select id="branch"></select></label></div>
<p id="score" class="meta"></p><div class="toolbar"><button id="start">Start</button><button id="back">Back</button><span id="ply" class="meta"></span><button id="forward">Forward</button><button id="end">End</button></div>
<p id="line"></p><p class="meta">A saved continuation is one engine line, not a complete explanation. Scores stay in the original mover’s perspective as you step through it. Maia percentages describe model choice probabilities.</p>
<details><summary>Source and evidence</summary><pre id="provenance"></pre></details></section>
<section class="form"><h2>Editorial notes</h2><label for="status">Working decision</label><select id="status"><option value="pending">Not reviewed</option><option value="promising">Promising teaching example</option><option value="revise">Needs more work</option><option value="reject">Do not use</option></select>
<label for="reviewer">Reviewer</label><input id="reviewer" autocomplete="off">
<label for="family_hypothesis">Possible shared idea — a hypothesis to check</label><input id="family_hypothesis" autocomplete="off">
<label for="explanation">What should a player notice? Explain why the acceptable move(s) work.</label><textarea id="explanation"></textarea>
<label for="why_alternatives_fail">Why do plausible alternatives fall short? Cite the saved branch and its limit.</label><textarea id="why_alternatives_fail"></textarea>
<label for="limiting_case">When would this idea fail? Describe a real boundary example still needed.</label><textarea id="limiting_case"></textarea>
<label for="near_duplicate_notes">Related positions / near-duplicate review</label><textarea id="near_duplicate_notes"></textarea>
<label for="source_review_notes">Source or public-exposure concerns</label><textarea id="source_review_notes"></textarea>
<p class="meta">“Promising” is an editorial note. Chess review, independent review, family validation, near-duplicate review, exposure review and trainer readiness remain pending.</p></section></div>
<div class="toolbar"><button id="export">Export review notes</button><label>Import saved notes <input id="import" type="file" accept="application/json,.json"></label></div><p id="notice" role="status" aria-live="polite">Edits are kept in this tab’s memory. Export before closing.</p>
<details><summary>How this batch was chosen</summary><p id="method"></p><pre id="selection"></pre></details></main>
<script>
const DATA=__DATA__;
const $=id=>document.getElementById(id), packet=DATA.packet;
const fields=['reviewer','family_hypothesis','explanation','why_alternatives_fail','limiting_case','near_duplicate_notes','source_review_notes'];
const statuses=['pending','promising','revise','reject'];let reviews=DATA.reviews,index=0,step=0,dirty=false,branches=[];
const pieces={p:'♟',r:'♜',n:'♞',b:'♝',q:'♛',k:'♚'};
function item(){return packet.items[index]}function note(){return reviews.items.find(row=>row.id===item().id)}
function capture(){const row=note();row.status=$('status').value;for(const field of fields)row[field]=$(field).value}
function updateProgress(){$('progress').textContent=`${reviews.items.filter(row=>row.status!=='pending').length} / ${packet.items.length} given an editorial decision`}
function draw(){const branch=branches[Number($('branch').value)],fen=branch.frames[step],cells={};fen.split(' ')[0].split('/').forEach((rank,i)=>{let f=0;for(const c of rank){if(/[1-8]/.test(c))f+=Number(c);else cells['abcdefgh'[f++]+(8-i)]=c}});
const white=item().side_to_move==='white',files=white?'abcdefgh':'hgfedcba',ranks=white?[8,7,6,5,4,3,2,1]:[1,2,3,4,5,6,7,8];$('board').replaceChildren();
for(const r of ranks)for(const f of files){const sq=f+r,cell=document.createElement('div');cell.className='square '+(('abcdefgh'.indexOf(f)+r)%2?'dark':'light');const p=cells[sq];if(p){const piece=document.createElement('span');piece.className=p===p.toUpperCase()?'white':'';piece.textContent=pieces[p.toLowerCase()];cell.append(piece)}const label=document.createElement('small');label.className='coord';label.textContent=sq;cell.append(label);$('board').append(cell)}
$('board').setAttribute('aria-label',`${item().side_to_move} was the original mover. Saved continuation after ${step} plies. FEN ${fen}`);
$('ply').textContent=`${step} / ${branch.pv.length} plies`;$('back').disabled=$('start').disabled=step===0;$('forward').disabled=$('end').disabled=step===branch.pv.length;
$('line').textContent=branch.pv.map((move,i)=>`${i===step-1?'[':''}${move.san}${i===step-1?']':''}`).join(' ');
$('score').textContent=`${branch.cp} cp · ${branch.loss_cp} cp behind the best root · Maia 1700: ${(branch.maia['1700']*100).toFixed(1)}% · Maia 2000: ${(branch.maia['2000']*100).toFixed(1)}% · achieved depth ${branch.achieved_depth}`}
function chooseBranches(){branches=item().branches.filter(row=>String(row.depth)===$('depth').value).sort((a,b)=>Number(b.acceptable)-Number(a.acceptable)||b.cp-a.cp||a.uci.localeCompare(b.uci));$('branch').replaceChildren(...branches.map((row,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${row.acceptable?'✓ ':''}${row.san} (${row.loss_cp} cp loss)`;return o}));step=0;draw()}
function render(){$('position').value=index;$('previous').disabled=index===0;$('next').disabled=index===packet.items.length-1;$('heading').textContent=`${index+1}. ${item().side_to_move==='white'?'White':'Black'} to move · ${item().phase}`;$('accepted').textContent=`Complete acceptable set at depths 20 and 24: ${item().accepted_san.join(', ')}`;
$('status').value=note().status;for(const field of fields)$(field).value=note()[field];$('provenance').textContent=JSON.stringify({id:item().id,evidence_sha256:item().evidence_sha256,origins:item().origins,provenance:item().provenance},null,2);chooseBranches();updateProgress()}
function importReviews(value){const own=(object,keys)=>object&&typeof object==='object'&&!Array.isArray(object)&&Object.keys(object).sort().join('|')===keys.sort().join('|');
if(!own(value,['schema_version','packet_sha256','items'])||value.schema_version!==1||value.packet_sha256!==DATA.reviews.packet_sha256||!Array.isArray(value.items)||value.items.length!==packet.items.length)throw Error('These notes belong to a different packet.');
const expected=new Map(packet.items.map(row=>[row.id,row.evidence_sha256])),seen=new Set();for(const row of value.items){if(!own(row,['id','evidence_sha256','status',...fields])||!expected.has(row.id)||seen.has(row.id)||row.evidence_sha256!==expected.get(row.id)||!statuses.includes(row.status)||fields.some(f=>typeof row[f]!=='string'||row[f].length>20000))throw Error('Invalid review identities or note fields.');seen.add(row.id)}
reviews=JSON.parse(JSON.stringify(value));dirty=false;render();$('notice').textContent='Saved notes imported. Evidence and readiness have not changed.'}
window.reviewDesk={importReviews,exportValue:()=>{capture();return JSON.parse(JSON.stringify(reviews))}};
$('position').replaceChildren(...packet.items.map((row,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${i+1} · ${row.side_to_move} · ${row.phase}`;return o}));
$('position').onchange=()=>{capture();index=Number($('position').value);render()};$('previous').onclick=()=>{capture();index--;render()};$('next').onclick=()=>{capture();index++;render()};
$('depth').onchange=chooseBranches;$('branch').onchange=()=>{step=0;draw()};$('back').onclick=()=>{step--;draw()};$('forward').onclick=()=>{step++;draw()};$('start').onclick=()=>{step=0;draw()};$('end').onclick=()=>{step=branches[Number($('branch').value)].pv.length;draw()};
for(const field of ['status',...fields])$(field).addEventListener('input',()=>{dirty=true;capture();updateProgress();$('notice').textContent='Unsaved notes. Export before closing.'});
$('export').onclick=()=>{capture();const blob=new Blob([JSON.stringify(reviews,null,2)+'\\n'],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='chess-review-notes.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);dirty=false;$('notice').textContent='Download requested. Keep the downloaded notes to import next time.'};
$('import').onchange=async()=>{const file=$('import').files[0];if(!file)return;try{if(file.size>4000000)throw Error('Review file is too large.');if(dirty&&!window.confirm('Replace this tab’s unsaved notes with the imported file?'))return;importReviews(JSON.parse(await file.text()))}catch(error){$('notice').textContent=error.message}finally{$('import').value=''}};
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue=''}});
$('method').textContent=packet.method;$('selection').textContent=JSON.stringify({pool_counts:packet.pool_counts,selected_by_side:packet.selected_by_side,selected_by_phase:packet.selected_by_phase,packet_sha256:DATA.reviews.packet_sha256},null,2);render();
</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate-reviews"))
    parser.add_argument("--output", type=Path, default=ROOT / "data/mining_v3/editorial-review-20260916")
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        require_private_output(args.output)
        print(json.dumps(export_packet(build_packet(count=args.count, seed=args.seed), args.output), indent=2))
    else:
        if args.reviews is None:
            parser.error("validate-reviews requires --reviews")
        path = args.output / "packet.json"
        manifest = json.loads((args.output / "manifest.json").read_text())
        fingerprint = check_hash(path, manifest["packet_sha256"])
        value = validate_reviews(json.loads(args.reviews.read_text()), json.loads(path.read_text()), fingerprint)
        print(json.dumps({"valid": True, "editorial_decisions": dict(Counter(row["status"] for row in value["items"])),
                          "trainer_ready": False}, indent=2))


if __name__ == "__main__":
    main()
