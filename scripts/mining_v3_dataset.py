"""Assemble and audit the colour-balanced expansion without changing old data.

Historical rows retain their identities, including duplicate board states.
New White states must be distinct from one another and the existing White pilot.
Counts describe observations, not independent positions or validated puzzles.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import sqlite3
import sys

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mining_v2_sampling import canonical_fen, file_sha256, public_exclusions, split_for_game


def read_rows(path):
    with Path(path).open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def original_white(path):
    for row in read_rows(path):
        if chess.Board(row['fen']).turn:
            row = dict(row)
            row['pilot_id'] = row['id']
            row['id'] = 'v3-pilot-' + row['id']
            row['history_available'] = True
            row['history_recovery'] = 'preserved_v2_actual_history'
            row['contains_bot'] = False
            yield row


def rating_band(elo):
    value = int(float(elo))
    if value < 1800:
        return 'under_1800'
    if value >= 2800:
        return '2800_plus'
    floor = value // 200 * 200
    return f'{floor}_{floor+199}'


def verify_record(row):
    board = chess.Board(row['fen'])
    side = 'white' if board.turn else 'black'
    if not board.is_valid() or row['side_to_move'] != side:
        raise ValueError(f"{row['id']}: invalid board or side metadata")
    if chess.Move.from_uci(row['played_move']) not in board.legal_moves:
        raise ValueError(f"{row['id']}: observed move is illegal")
    if not row.get('game_id'):
        raise ValueError(f"{row['id']}: missing game identity")
    return board


def assemble(black_path, pilot_path, white_path, output_path, summary_path,
             expected_black=124405, expected_new_white=123405, expected_pilot_white=1000):
    paths = [Path(p) for p in (black_path, pilot_path, white_path)]
    output_path, summary_path = Path(output_path), Path(summary_path)
    if {output_path.resolve(), summary_path.resolve()} & {path.resolve() for path in paths}:
        raise ValueError('Assembled outputs must not overwrite any source input')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    public_fens, public_games, exclusion_manifest = public_exclusions(ROOT)
    pilot_splits = {}
    for row in read_rows(pilot_path):
        if row['game_id'] in pilot_splits and pilot_splits[row['game_id']] != row['split']:
            raise ValueError('Pilot source game appears in conflicting splits')
        pilot_splits[row['game_id']] = row['split']
    db_path = output_path.with_suffix('.audit.sqlite')
    db = sqlite3.connect(db_path)
    try:
        db.executescript('DROP TABLE IF EXISTS rows; DROP TABLE IF EXISTS games; '
                         'CREATE TABLE rows (id TEXT PRIMARY KEY, fen TEXT, game TEXT, '
                         'side TEXT, origin TEXT, split TEXT, public INTEGER); '
                         'CREATE TABLE games (id TEXT PRIMARY KEY, legacy INTEGER, public INTEGER);')
        counts, sides, cohorts, cells, history, clocks, bots = (Counter() for _ in range(7))
        historical_cells, new_white_cells = Counter(), Counter()
        supplements = Counter()
        time_controls = defaultdict(Counter)

        def sources():
            return (('historical_or_pilot_black', read_rows(black_path)),
                    ('pilot_white', original_white(pilot_path)),
                    ('new_white', read_rows(white_path)))

        # A compact disk index checks identities and determines exposure at game level.
        for origin, rows in sources():
            for row in rows:
                board = verify_record(row)
                side = 'white' if board.turn else 'black'
                if (origin == 'historical_or_pilot_black') != (side == 'black'):
                    raise ValueError('Input file contains the wrong side to move')
                canon, gid = canonical_fen(row['fen']), row['game_id']
                prior = bool(row.get('legacy_game_id') or 'master_row_index' in row.get('source', {}))
                exposed = canon in public_fens or gid in public_games or row.get('legacy_game_id') in public_games
                if origin == 'new_white' and exposed:
                    raise ValueError('New White input contains a public position or known public game')
                split = pilot_splits.get(gid, split_for_game(gid))
                db.execute('INSERT INTO rows VALUES (?,?,?,?,?,?,?)',
                           (row['id'], canon, gid, side, origin, split, int(exposed)))
                db.execute('INSERT INTO games VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET '
                           'legacy=max(legacy,excluded.legacy), public=max(public,excluded.public)',
                           (gid, int(prior), int(exposed)))
                counts[origin] += 1
                sides[side] += 1
                cohort = row.get('cohort', row.get('source', {}).get('cohort', 'unknown'))
                cohorts[f'{side}/{cohort}'] += 1
                cells[(side, cohort, rating_band(row['mover_elo']), row['phase'])] += 1
                cell = (cohort, rating_band(row['mover_elo']), row['phase'])
                if side == 'black' and prior:
                    historical_cells[cell] += 1
                elif origin == 'new_white':
                    new_white_cells[cell] += 1
                    supplement = row.get('selection_supplement')
                    if supplement in ('cached_game_additional_white_plies', 'elite_archive_slow_game'):
                        supplements[supplement] += 1
                history[side] += bool(row.get('history_available', True))
                clocks[side] += row.get('clock_seconds_before') is not None
                bots[f"{side}/{row.get('contains_bot')}"] += 1
                time_controls[side][row.get('time_control') or 'unknown'] += 1
        db.commit()
        expected = {'historical_or_pilot_black': expected_black,
                    'new_white': expected_new_white, 'pilot_white': expected_pilot_white}
        if counts != Counter(expected) or sides['white'] != sides['black']:
            raise ValueError(f'Incomplete or unbalanced inputs: {dict(counts)}; expected {expected}')
        newly_exposed = db.execute("SELECT count(*) FROM rows JOIN games ON rows.game=games.id "
                                  "WHERE rows.origin='new_white' AND games.public=1").fetchone()[0]
        if newly_exposed:
            raise ValueError('New White input shares a source game with a public position')
        white_duplicates = db.execute("SELECT count(*) FROM (SELECT fen FROM rows WHERE side='white' GROUP BY fen HAVING count(*)>1)").fetchone()[0]
        if white_duplicates:
            raise ValueError(f'White sample has {white_duplicates} repeated canonical states')
        games = {gid: (bool(old), bool(public)) for gid, old, public in db.execute('SELECT * FROM games')}
        duplicate_n = {}
        for side in ('black', 'white'):
            unique = db.execute('SELECT count(DISTINCT fen) FROM rows WHERE side=?', (side,)).fetchone()[0]
            duplicate_n[side] = sides[side] - unique
        cross_split = db.execute('SELECT count(*) FROM (SELECT fen FROM rows GROUP BY fen HAVING count(DISTINCT split)>1)').fetchone()[0]
        role_counts = Counter()
        temp_path = output_path.with_suffix('.jsonl.partial')
        # Interleave sides so every resumable prefix has almost identical colour counts.
        white = itertools.chain(original_white(pilot_path), read_rows(white_path))
        with temp_path.open('w') as stream:
            for pair in zip(read_rows(black_path), white, strict=True):
                for row in pair:
                    row = dict(row)
                    old, exposed = games[row['game_id']]
                    row['source_split'] = row.get('split')
                    row['split'] = pilot_splits.get(row['game_id'], split_for_game(row['game_id']))
                    row['prior_development_game'] = old
                    row['known_public_game'] = exposed
                    row['analysis_role'] = ('public_exposed' if exposed else 'prior_development' if old
                                            else 'pilot_' + row['split'] if row['game_id'] in pilot_splits
                                            else 'new_' + row['split'])
                    row['history_available'] = bool(row.get('history_available', True))
                    role_counts[row['analysis_role']] += 1
                    stream.write(json.dumps(row, separators=(',', ':')) + '\n')
        temp_path.replace(output_path)
        summary = {
            'schema_version': 3, 'assembled_at': datetime.now(timezone.utc).isoformat(),
            'complete': True, 'record_count': sum(sides.values()), 'sides': dict(sides),
            'origins': dict(counts), 'cohort_cells': dict(cohorts),
            'new_white_supplements': dict(supplements),
            'distinct_recorded_game_ids': len(games),
            'canonical_duplicate_rows': duplicate_n,
            'unique_canonical_states': {s: sides[s] - duplicate_n[s] for s in sides},
            'canonical_states_crossing_hash_splits': cross_split,
            'history_available': dict(history), 'mover_clock_available': dict(clocks),
            'bot_metadata': dict(bots), 'analysis_roles': dict(role_counts),
            'time_controls': {s: dict(c) for s, c in time_controls.items()},
            'matching_cells': [dict(side=s, cohort=c, rating_band=r, phase=p, n=n)
                               for (s, c, r, p), n in sorted(cells.items())],
            'historical_vs_new_white_matching': {
                'exact': historical_cells == new_white_cells,
                'cell_differences': [dict(cohort=c, rating_band=r, phase=p,
                                          historical_black=historical_cells[(c,r,p)],
                                          new_white=new_white_cells[(c,r,p)],
                                          white_minus_black=new_white_cells[(c,r,p)]-historical_cells[(c,r,p)])
                                     for c,r,p in sorted(historical_cells.keys() | new_white_cells.keys())
                                     if historical_cells[(c,r,p)] != new_white_cells[(c,r,p)]],
                'note': 'White quotas use the source profile available at selection. Later recovered rating corrections may leave small cell differences; the older pilot also has its own distribution.'},
            'input_sha256': {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name:
                             file_sha256(p) for p in paths},
            'positions_sha256': file_sha256(output_path),
            'exclusions': exclusion_manifest,
            'limitations': [
                'Balanced observation counts do not imply independent positions or equal unique-state counts.',
                'Historical records and their related games have already informed development; a hash split does not make them fresh held-out data.',
                'Game identities may remain unresolved, and distinct recorded IDs may refer to the same game.',
                'New White sampling matches specified cohort/rating/phase cells; missing clocks and time controls remain missing.',
                'This is a constructed archive sample, not representative of all human chess.',
                'Dataset completion does not mean every row has completed fresh engine/model analysis or qualifies as a puzzle.',
            ],
        }
        summary_path.write_text(json.dumps(summary, indent=2) + '\n')
        return summary
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--black', type=Path, default=ROOT/'data/mining_v3/black.jsonl')
    ap.add_argument('--pilot', type=Path, default=ROOT/'data/mining_v2/positions.jsonl')
    ap.add_argument('--white', type=Path, default=ROOT/'data/mining_v3/white_new.jsonl')
    ap.add_argument('--output', type=Path, default=ROOT/'data/mining_v3/positions.jsonl')
    ap.add_argument('--summary', type=Path, default=ROOT/'results/mining_v3_dataset.json')
    args = ap.parse_args()
    out = assemble(args.black, args.pilot, args.white, args.output, args.summary)
    print(json.dumps({k: out[k] for k in ('record_count', 'sides', 'origins', 'canonical_duplicate_rows', 'history_available')}, indent=2))


if __name__ == '__main__':
    main()
