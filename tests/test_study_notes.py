"""Keep authored teaching notes tied to the positions and legal continuations."""
import hashlib
import json
from pathlib import Path
import unittest

import chess

ROOT = Path(__file__).resolve().parents[1]


class StudyNoteTests(unittest.TestCase):
    def test_every_example_has_matching_verified_notes(self):
        source = ROOT / 'webapp/concepts.json'
        groups = json.loads(source.read_text())
        notes = json.loads((ROOT / 'webapp/study_notes.json').read_text())
        self.assertEqual(notes['concepts_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        by_id = {n['id']: n for n in notes['items']}
        expected = {f'{g["id"]}:{i}' for g in groups for i in range(len(g['study']))}
        self.assertEqual(set(by_id), expected)
        self.assertEqual(len(notes['items']), 32)
        positions = [p for g in groups for role in ('study', 'drill') for p in g[role]]
        self.assertEqual(len(positions), 320)
        self.assertEqual(len({' '.join(p['fen'].split()[:4]) for p in positions}), 320)
        for group in groups:
            self.assertEqual(len(group['study']), 4)
            self.assertEqual(len(group['drill']), 36)
            for index, position in enumerate(group['study']):
                note = by_id[f'{group["id"]}:{index}']
                with self.subTest(example=note['id']):
                    self.assertEqual(note['fen'], position['fen'])
                    self.assertEqual(note['best'], position['best'])
                    self.assertEqual(note['engine']['pv'][0]['uci'], position['best'])
                    self.assertEqual(note['comparison']['uci'], position['human'][0]['uci'])
                    self.assertEqual(note['comparison']['pv'][0]['uci'], note['comparison']['uci'])
                    for key in ('title', 'why', 'alternative', 'notice'):
                        self.assertTrue(note[key].strip())
                    for key in ('engine', 'comparison'):
                        self.assertGreaterEqual(note[key]['depth'], 20)
                        self.assertTrue(note[key]['cp'] is not None or note[key].get('mate') is not None)
                    for line in [note['engine'], note['comparison'], *note.get('variations', [])]:
                        board = chess.Board(note['fen'])
                        for step in line['pv']:
                            move = chess.Move.from_uci(step['uci'])
                            self.assertIn(move, board.legal_moves)
                            self.assertEqual(board.san(move), step['san'])
                            board.push(move)
                        if line.get('terminal') == 'checkmate':
                            self.assertTrue(board.is_checkmate())

    def test_retired_example_is_not_offered_in_training(self):
        groups = json.loads((ROOT / 'webapp/concepts.json').read_text())
        correction = json.loads((ROOT / 'results/34_study_corrections.json').read_text())
        offered = {p['fen'] for g in groups for role in ('study', 'drill') for p in g[role]}
        for change in correction['corrections']:
            self.assertNotIn(change['retired']['fen'], offered)
            self.assertIn(change['replacement']['fen'], offered)
