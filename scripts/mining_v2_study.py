"""Validate, export and schedule an unpublished grouped-versus-shuffled study.

No participant recruitment, randomization of real people or website changes occur.
See docs/LEARNING_STUDY_V2.md for the bank contract and readiness gates.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import re

import chess

SCHEMA_VERSION = 2
ARMS = ('grouped', 'shuffled')
FORMS = ('A', 'B', 'C')
STRATA = ('1800-2200', '2201-2600')
MANUAL_GATES = ('consent_ready', 'preregistered', 'allocation_concealed',
                'retention_policy_ready', 'delivery_reviewed', 'difficulty_reviewed',
                'independent_chess_reviewed', 'public_exposure_reviewed')


def canonical(fen):
    """Ignore clocks, and normalize impossible en-passant claims via python-chess."""
    return ' '.join(chess.Board(fen).fen().split()[:4])


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def acceptance(scores, tolerance=20):
    """All legal moves within tolerance of the best root-mover cp score."""
    if not scores or not all(_number(value) for value in scores.values()):
        raise ValueError('Acceptance requires nonempty finite centipawn scores.')
    best = max(scores.values())
    return sorted(move for move, score in scores.items() if best - score <= tolerance)


def validate(bank, public_fens=(), public_game_ids=()):
    """Check reported evidence; never imply the engine ran or a reviewer signed off."""
    errors = []
    if bank.get('schema_version') != SCHEMA_VERSION:
        errors.append('schema_version must be 2.')
    engine = bank.get('engine', {})
    if engine.get('name') != 'Stockfish 18':
        errors.append('Pin the verification engine as Stockfish 18.')
    if not re.fullmatch(r'[0-9a-f]{64}', str(engine.get('binary_sha256', ''))):
        errors.append('Record the verification binary SHA-256.')
    if engine.get('threads') != 1 or isinstance(engine.get('threads'), bool):
        errors.append('Use one engine thread.')
    if not _positive_integer(engine.get('hash_mb')):
        errors.append('Record a fixed positive integer engine hash size in MB.')
    items = bank.get('items', [])
    if not isinstance(items, list):
        items = []
        errors.append('items must be an array.')
    public_states = {canonical(fen) for fen in public_fens}
    public_games = {str(game) for game in public_game_ids}
    ids, states, games = set(), set(), set()
    families = set()
    valid_items = []
    for item in items:
        if not isinstance(item, dict):
            errors.append('Every item must be an object.')
            continue
        label = item.get('id')
        if not isinstance(label, str) or not label.strip() or label in ids:
            errors.append(f'{label!r}: missing or duplicate item ID.')
        else:
            ids.add(label)
        family = item.get('family')
        if not isinstance(family, str) or not family.strip():
            errors.append(f'{label}: family must be a nonempty string.')
        else:
            families.add(family)
        role, kind = item.get('role'), item.get('kind')
        if role not in {'training', 'test'}:
            errors.append(f'{label}: role must be training or test.')
        if kind not in {'positive', 'boundary'}:
            errors.append(f'{label}: kind must be positive or boundary.')
        if role == 'test' and item.get('form') not in FORMS:
            errors.append(f'{label}: test items require form A, B or C.')
        if role == 'training' and item.get('form') not in (None, ''):
            errors.append(f'{label}: training items must not belong to a test form.')
        if not isinstance(item.get('explanation'), str) or not item['explanation'].strip():
            errors.append(f'{label}: a reviewed explanation is required, including held-back test feedback.')
        try:
            board = chess.Board(item['fen'])
            if not board.is_valid() or board.is_game_over():
                raise ValueError('not a valid playable board')
            state = canonical(item['fen'])
        except (KeyError, ValueError, TypeError):
            errors.append(f'{label}: invalid or terminal FEN.')
            continue
        if state in states:
            errors.append(f'{label}: duplicate canonical board state in the bank.')
        states.add(state)
        if role == 'test' and state in public_states:
            errors.append(f'{label}: test position is already public.')
        game = str(item.get('game_id', '')).strip()
        if not game or game in {'?', 'None'} or game.startswith('orph_'):
            errors.append(f'{label}: source game must be resolved.')
        elif game in games:
            errors.append(f'{label}: source game is reused in the bank.')
        games.add(game)
        if role == 'test' and game in public_games:
            errors.append(f'{label}: test source game already appears in public materials.')
        legal = {move.uci() for move in board.legal_moves}
        sets = []
        evidence = item.get('engine', {})
        if evidence.get('all_scores_exact') is not True or evidence.get('verified') is not True:
            errors.append(f'{label}: complete exact-score engine verification is pending or failed.')
        for depth in (20, 24):
            scores = item.get(f'scores_{depth}', {})
            if (not isinstance(scores, dict) or set(scores) != legal or
                    not scores or not all(_number(score) for score in scores.values())):
                errors.append(f'{label}: depth {depth} requires finite cp scores for every legal move; no mate scores.')
                continue
            accepted = acceptance(scores)
            sets.append(accepted)
            declared = item.get(f'accepted{depth}')
            if (not isinstance(declared, list) or any(not isinstance(move, str) for move in declared)
                    or sorted(declared) != accepted):
                errors.append(f'{label}: accepted{depth} does not match its 20cp score set.')
            achieved = evidence.get(f'depth{depth}')
            if not _positive_integer(achieved) or achieved < depth:
                errors.append(f'{label}: every depth-{depth} root search must actually reach that depth.')
            if not _positive_integer(evidence.get(f'nodes{depth}')):
                errors.append(f'{label}: record depth-{depth} search nodes.')
        if len(sets) == 2 and sets[0] != sets[1]:
            errors.append(f'{label}: acceptance changes between depths 20 and 24.')
        review = item.get('review', {})
        if review.get('chess') is not True or review.get('near_duplicates') is not True:
            errors.append(f'{label}: chess and near-duplicate review are pending.')
        valid_items.append(item)
    if not 8 <= len(families) <= 12:
        errors.append('Require 8–12 reviewed teaching families.')
    training = [item for item in valid_items if item.get('role') == 'training']
    training_counts = Counter((item.get('family'), item.get('kind')) for item in training)
    for family in sorted(families):
        if training_counts[family, 'positive'] < 2 or training_counts[family, 'boundary'] < 1:
            errors.append(f'{family}: training needs at least two positives and one boundary example.')
    form_counts = {}
    for form in FORMS:
        subset = [item for item in valid_items if item.get('role') == 'test' and item.get('form') == form]
        counts = Counter(item.get('family') for item in subset)
        kinds = Counter(item.get('kind') for item in subset)
        form_counts[form] = {'items': len(subset), 'kinds': dict(kinds)}
        if set(counts) != families or any(count != 1 for count in counts.values()) or not subset:
            errors.append(f'Form {form}: require exactly one unseen item per family.')
        if abs(kinds['positive'] - kinds['boundary']) > 1:
            errors.append(f'Form {form}: balance positive and boundary test items within one item.')
    for family in sorted(families):
        kinds = {item.get('kind') for item in valid_items
                 if item.get('role') == 'test' and item.get('family') == family}
        if kinds != {'positive', 'boundary'}:
            errors.append(f'{family}: the three test forms must include both positive and boundary cases.')
    pending = [gate for gate in MANUAL_GATES if bank.get('readiness', {}).get(gate) is not True]
    return {
        'schema_version': SCHEMA_VERSION,
        'material_checks_passed': not errors,
        'ready_for_recruitment': not errors and not pending,
        'errors': errors,
        'pending_manual_gates': pending,
        'counts': {'items': len(items), 'families': len(families), 'training': len(training),
                   'test': sum(form['items'] for form in form_counts.values()), 'forms': form_counts},
        'scope': 'Checks declared data only; does not certify engine execution, independent review or study completion.'
    }


def _seed(seed, *parts):
    return int.from_bytes(hashlib.sha256(json.dumps([seed, *parts], separators=(',', ':')).encode()).digest()[:16], 'big')


def practice_order(items, arm, seed):
    """The arm changes ordering only; item identity/content/time are shared."""
    if arm not in ARMS:
        raise ValueError('Unknown study arm.')
    grouped = defaultdict(list)
    for item in items:
        if item.get('role') == 'training':
            grouped[item['family']].append(item)
    rng = random.Random(_seed(seed, 'family-order'))
    families = sorted(grouped)
    rng.shuffle(families)
    order = []
    for family in families:
        for kind in ('positive', 'boundary'):
            subset = sorted((item['id'] for item in grouped[family] if item['kind'] == kind))
            rng.shuffle(subset)
            order.extend(subset)
    if arm == 'shuffled':
        random.Random(_seed(seed, 'item-order')).shuffle(order)
    return order


def assignment_plan(items, seed, slots_per_stratum=24):
    """Unassigned concealed slots, not enrolled participants; stop at total target 24."""
    if not _positive_integer(slots_per_stratum) or slots_per_stratum % 4:
        raise ValueError('slots_per_stratum must be a positive multiple of four.')
    plan = []
    for stratum in STRATA:
        rng = random.Random(_seed(seed, stratum, 'allocation'))
        form_queues = {arm: [] for arm in ARMS}
        for block in range(slots_per_stratum // 4):
            arms = list(ARMS) * 2
            rng.shuffle(arms)
            for offset, arm in enumerate(arms):
                slot = block * 4 + offset + 1
                if not form_queues[arm]:
                    form_queues[arm] = list(itertools.permutations(FORMS))
                    rng.shuffle(form_queues[arm])
                forms = list(form_queues[arm].pop())
                practice_seed = _seed(seed, stratum, slot, 'practice')
                plan.append({'stratum': stratum, 'slot': slot, 'block': block + 1, 'arm': arm,
                             'forms': dict(zip(('baseline', 'immediate', 'delayed'), forms)),
                             'practice_order': practice_order(items, arm, practice_seed),
                             'assigned_participant_id': None})
    return {'target_participants_total': 24, 'slots_are_not_participants': True,
            'stop_rule': 'Stop after 24 total randomized participants; do not replace dropouts.',
            'allocation': plan}


def public_training_items(items):
    """Build a training-only view. Test answers remain in the private bank."""
    output = []
    for item in items:
        if item.get('role') != 'training':
            continue
        row = {key: item[key] for key in ('id', 'fen', 'family', 'family_title', 'kind', 'explanation', 'accepted24') if key in item}
        row['answer_verified'] = item.get('engine', {}).get('verified') is True
        try:
            board = chess.Board(item['fen'])
            row['accepted_san'] = [board.san(chess.Move.from_uci(move)) for move in item.get('accepted24', [])
                                   if row['answer_verified'] and chess.Move.from_uci(move) in board.legal_moves]
        except (KeyError, ValueError, TypeError):
            row['accepted_san'] = []
        output.append(row)
    return output


def material_review_html(schedule, items, seed):
    """A portable material reviewer, deliberately not a participant collection client."""
    payload = dict(schedule)
    payload['orders'] = {arm: practice_order(items, arm, seed) for arm in ARMS}
    encoded = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Machine Unique Chess · Study material review</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#fbfaf7;color:#171711;font:18px/1.5 Georgia,serif}
main{max-width:960px;margin:auto;padding:28px 20px 60px}h1{font-size:32px;line-height:1.15}h2{font-size:23px}
p{max-width:65ch}.notice{border-left:3px solid #8a1f11;padding:8px 15px;background:#f0ede6}
.controls{display:flex;gap:14px;flex-wrap:wrap;margin:25px 0}label,button,select,.meta{font:15px/1.5 system-ui,sans-serif}
select,button{padding:7px 10px;color:inherit;background:transparent;border:1px solid #827f74;border-radius:0}
button:focus-visible,select:focus-visible{outline:3px solid #8a1f11;outline-offset:2px}button{cursor:pointer}
button:disabled{opacity:.45;cursor:default}.stage{display:grid;grid-template-columns:minmax(0,430px) minmax(0,1fr);gap:30px}
.board{display:grid;grid-template-columns:repeat(8,1fr);aspect-ratio:1;border:1px solid #5d5a51}
.square{position:relative;display:flex;align-items:center;justify-content:center;font:clamp(23px,5vw,43px)/1 'Arial Unicode MS','DejaVu Sans',serif}
.light{background:#eee9da}.dark{background:#a8ad90}.coord{position:absolute;left:2px;bottom:1px;font:9px system-ui;color:#272a20}
.piece{color:#10110d;text-shadow:0 1px 1px #fff8}.white{color:white;text-shadow:1px 0 #222,-1px 0 #222,0 1px #222,0 -1px #222}
#feedback{border-top:1px solid #b9b4a7;margin-top:16px;padding-top:16px}nav{display:flex;gap:12px;align-items:center;margin-top:20px}
@media(max-width:700px){.stage{grid-template-columns:1fr;gap:18px}main{padding:18px 14px}.board{max-width:430px}.square{font-size:clamp(27px,8vw,43px)}}
</style><main><h1>Study material review</h1>
<p class="notice">For checking draft materials. This page does not enroll participants, collect responses or run a timed study. Test answers are withheld. Keep unpublished test positions private.</p>
<p id="status" class="meta"></p>
<div class="controls"><label>Order <select id="arm"><option value="grouped">Grouped</option><option value="shuffled">Shuffled</option></select></label>
<label>Materials <select id="phase"><option value="training">Practice</option><option value="A">Test form A</option><option value="B">Test form B</option><option value="C">Test form C</option></select></label></div>
<section class="stage"><div><p id="turn" class="meta"></p><div class="board" id="board" role="img"></div></div>
<div><h2 id="heading"></h2><p id="family"></p><p id="instructions"></p><button id="reveal" type="button">Read the explanation</button>
<div id="feedback" hidden><p id="accepted"></p><p id="explanation"></p></div></div></section>
<nav aria-label="Review positions"><button id="previous" type="button">Previous</button><span id="counter" class="meta"></span><button id="next" type="button">Next</button></nav>
</main><script>
const DATA=__DATA__;
const $=id=>document.getElementById(id);let index=0;
const pieces={k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟',K:'♚',Q:'♛',R:'♜',B:'♝',N:'♞',P:'♟'};
function rows(){if($('phase').value!=='training')return DATA.test_forms[$('phase').value]||[];
const byId=Object.fromEntries(DATA.training_items.map(item=>[item.id,item]));return DATA.orders[$('arm').value].map(id=>byId[id]).filter(Boolean)}
function render(){const list=rows(),item=list[index];$('feedback').hidden=true;$('previous').disabled=index===0;$('next').disabled=index>=list.length-1;
$('counter').textContent=list.length?`${index+1} / ${list.length}`:'No items';$('board').replaceChildren();
if(!item){$('heading').textContent='Materials pending';$('family').textContent='';$('turn').textContent='';$('instructions').textContent='This draft does not yet contain positions for this selection.';$('reveal').hidden=true;return}
const training=$('phase').value==='training';$('heading').textContent=training?`Example ${index+1}`:`Position ${index+1}`;
$('family').textContent=training?(item.family_title||item.family):'';$('instructions').textContent=training?'Both orders use the same positions and explanations.':'No feedback is shown during an assessment.';
$('reveal').hidden=!training;$('accepted').textContent=(item.accepted_san||[]).length?`Accepted moves: ${item.accepted_san.join(', ')}`:'Engine verification pending.';
$('explanation').textContent=item.explanation||'Explanation pending review.';
const [placement,turn]=item.fen.split(' ');const cells={};placement.split('/').forEach((rank,i)=>{let file=0;for(const char of rank){if(/[1-8]/.test(char)){file+=Number(char)}else{cells['abcdefgh'[file]+(8-i)]=char;file++}}});
const files=turn==='w'?'abcdefgh':'hgfedcba',ranks=turn==='w'?[8,7,6,5,4,3,2,1]:[1,2,3,4,5,6,7,8];
$('turn').textContent=turn==='w'?'White to move':'Black to move';$('board').setAttribute('aria-label',`${$('turn').textContent}. Position ${item.id}. FEN ${item.fen}`);
for(const rank of ranks)for(const file of files){const sq=file+rank,node=document.createElement('div');node.className='square '+(('abcdefgh'.indexOf(file)+rank)%2?'dark':'light');
const piece=cells[sq];if(piece){const span=document.createElement('span');span.className='piece '+(piece===piece.toUpperCase()?'white':'');span.textContent=pieces[piece];node.append(span)}
const coord=document.createElement('small');coord.className='coord';coord.textContent=sq;node.append(coord);$('board').append(node)}}
$('status').textContent=`${DATA.draft?'Draft':'Frozen material export'} · ${DATA.training_slots} practice positions · ${DATA.training_slot_seconds} seconds planned per practice position`;
for(const id of ['arm','phase'])$(id).addEventListener('change',()=>{index=0;render()});$('previous').onclick=()=>{index--;render()};$('next').onclick=()=>{index++;render()};$('reveal').onclick=()=>{$('feedback').hidden=false};render();
</script></html>'''.replace('__DATA__', encoded)


def export_bundle(bank, output, seed, *, draft=False, public_fens=(), public_game_ids=()):
    report = validate(bank, public_fens, public_game_ids)
    if not draft and not report['ready_for_recruitment']:
        raise ValueError('Bank is not ready to freeze; inspect validation or explicitly export a draft.')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Create files exclusively: a new run cannot overwrite a frozen allocation.
    payload = json.dumps(bank, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    digest = hashlib.sha256(payload.encode()).hexdigest()
    items = bank.get('items', [])
    usable = [item for item in items if isinstance(item, dict) and
              all(isinstance(item.get(key), str) for key in ('id', 'family', 'kind'))]
    assignment = assignment_plan(usable, seed)
    assignment.update({'bank_sha256': digest, 'draft': draft, 'seed': seed})
    schedule = {'draft': draft, 'bank_sha256': digest, 'training_slot_seconds': 60,
                'training_answer_seconds': 30, 'training_feedback_seconds': 30,
                'training_slots': sum(item.get('role') == 'training' for item in usable),
                'test_item_seconds': 60, 'test_feedback': False,
                'delayed_days': 7, 'delayed_window_days': [5, 9],
                'training_items': public_training_items(usable),
                'test_forms': {form: [{'id': item['id'], 'fen': item['fen']}
                                     for item in usable if item.get('role') == 'test' and item.get('form') == form
                                     and 'fen' in item] for form in FORMS}}
    exports = {'private-bank.json': bank, 'readiness.json': report,
               'private-allocation.json': assignment, 'materials.json': schedule}
    for name in [*exports, 'material-review.html']:
        if (output / name).exists():
            raise FileExistsError(f'Refusing to overwrite {output / name}; choose a new output directory.')
    for name, content in exports.items():
        text = payload if name == 'private-bank.json' else json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
        with (output / name).open('x') as handle:
            handle.write(text)
    with (output / 'material-review.html').open('x') as handle:
        handle.write(material_review_html(schedule, usable, seed))
    return report


def _public_references(root):
    fens = []
    path = root / 'webapp/concepts.json'
    if path.exists():
        fens.extend(item['fen'] for group in json.loads(path.read_text())
                    for role in ('study', 'drill') for item in group[role])
    path = root / 'webapp/research_examples.json'
    if path.exists():
        fens.extend(example[key]['fen'] for example in json.loads(path.read_text())['examples']
                    for key in ('primary', 'related'))
    return fens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'export'))
    parser.add_argument('bank', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--draft', action='store_true')
    parser.add_argument('--public-game-ids', type=Path, help='JSON array of resolved source IDs used by the public site.')
    parser.add_argument('--strict', action='store_true', help='Validation also fails when manual readiness gates remain open.')
    args = parser.parse_args()
    bank = json.loads(args.bank.read_text())
    public_fens = _public_references(Path(__file__).resolve().parents[1])
    games = json.loads(args.public_game_ids.read_text()) if args.public_game_ids else ()
    if args.command == 'export':
        if args.output is None or args.seed is None:
            parser.error('export requires --output and --seed (keep the allocation seed private).')
        report = export_bundle(bank, args.output, args.seed, draft=args.draft,
                               public_fens=public_fens, public_game_ids=games)
    else:
        report = validate(bank, public_fens, games)
    print(json.dumps(report, indent=2))
    if args.command == 'validate' and not report['material_checks_passed']:
        raise SystemExit(1)
    if args.strict and not report['ready_for_recruitment']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
