"""Validate a private learning-study item bank before recruitment.

Usage: python experiments/33_validate_study_manifest.py /path/to/manifest.json
Schema: {"engine": {"name": "Stockfish 17.1", "binary_sha256": "...",
"threads": 1, "hash_mb": 128}, "items": [{"id": "A-1", "role": "test",
"form": "A", "family": 0, "fen": "...", "game_id": "...",
"scores_20": {"e2e4": 12, ...all legal UCI moves...},
"scores_24": {...}, "accepted": [...]}]}.

Roles: test, grouped_training, ordinary_training. Test forms: A/B/C.
Family is 0..7 for selected positions or null for ordinary positions.
Scores are numeric centipawns from the side-to-move perspective; no mate scores.
This checks reported data, not whether the claimed engine analyses were performed.
"""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[1]


def canonical(fen):
    return ' '.join(chess.Board(fen).fen().split()[:4])


def validate(manifest, public_fens=()):
    errors = []
    engine = manifest.get('engine', {})
    if engine.get('name') != 'Stockfish 17.1' or len(engine.get('binary_sha256', '')) != 64:
        errors.append('Pin Stockfish 17.1 and its SHA-256.')
    if engine.get('threads') != 1 or not isinstance(engine.get('hash_mb'), int):
        errors.append('Record one thread and a fixed hash size.')
    items = manifest.get('items', [])
    public = {canonical(f) for f in public_fens}
    ids, states, games = set(), set(), set()
    for item in items:
        label = item.get('id', '<missing id>')
        if not isinstance(label, str) or label in ids or label == '<missing id>':
            errors.append(f'{label}: missing or duplicate item ID.')
        ids.add(label)
        if item.get('role') not in {'test', 'grouped_training', 'ordinary_training'}:
            errors.append(f'{label}: unknown role.')
        try:
            board = chess.Board(item['fen'])
            if not board.is_valid():
                raise ValueError('invalid chess position')
            state = canonical(item['fen'])
        except (KeyError, ValueError):
            errors.append(f'{label}: invalid FEN.')
            continue
        if state in states:
            errors.append(f'{label}: repeated board state across the item bank.')
        states.add(state)
        if item.get('role') == 'test' and state in public:
            errors.append(f'{label}: test position already appears in the public trainer/examples.')
        game = item.get('game_id')
        if not game or game == '?' or str(game).startswith('orph_') or game in games:
            errors.append(f'{label}: missing, unresolved or reused source game.')
        games.add(game)
        legal = {m.uci() for m in board.legal_moves}
        sets = []
        for depth in (20, 24):
            scores = item.get(f'scores_{depth}', {})
            if set(scores) != legal or not scores or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in scores.values()):
                errors.append(f'{label}: depth {depth} needs finite cp scores for every legal move.')
                continue
            best = max(scores.values())
            sets.append({move for move, score in scores.items() if best - score <= 20})
        if len(sets) == 2 and (sets[0] != sets[1] or set(item.get('accepted', [])) != sets[1]):
            errors.append(f'{label}: acceptance set changes by depth or disagrees with frozen scoring.')
    for form in 'ABC':
        subset = [i for i in items if i.get('role') == 'test' and i.get('form') == form]
        counts = Counter(i.get('family') for i in subset)
        if len(subset) != 12 or counts[None] != 4 or any(counts[f] != 1 for f in range(8)):
            errors.append(f'Form {form}: require one item per family and four ordinary items.')
    if any(i.get('role') == 'test' and i.get('form') not in {'A', 'B', 'C'} for i in items):
        errors.append('Test forms must be A, B or C.')
    grouped = [i for i in items if i.get('role') == 'grouped_training']
    ordinary = [i for i in items if i.get('role') == 'ordinary_training']
    if len(grouped) < 8 or len(grouped) != len(ordinary) or {i.get('family') for i in grouped} != set(range(8)):
        errors.append('Training pools need equal counts, with all eight families in grouped training.')
    if any(i.get('family') is not None for i in ordinary):
        errors.append('Ordinary training must use family=null.')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    concepts = json.loads((ROOT / 'webapp/concepts.json').read_text())
    public_fens = [p['fen'] for c in concepts for slot in ['study', 'drill'] for p in c[slot]]
    examples = json.loads((ROOT / 'webapp/research_examples.json').read_text())
    public_fens += [e[key]['fen'] for e in examples['examples'] for key in ['primary', 'related']]
    errors = validate(json.loads(raw), public_fens)
    if errors:
        raise SystemExit('\n'.join(errors))
    print('Structural checks passed. SHA-256:', hashlib.sha256(raw).hexdigest())
    print('Engine verification, matching, consent and preregistration still require separate review.')
