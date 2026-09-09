"""Bind practice explanations to public positions and check concrete chess claims.

No engine runs here: legal replay checks what a saved line demonstrates, not
whether its moves are optimal or its continuation is forced.
"""
import copy
import hashlib
import json
from pathlib import Path
import unittest

import chess


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(fen, pv):
    boards = [chess.Board(fen)]
    for step in pv:
        before = boards[-1]
        move = chess.Move.from_uci(step['uci'])
        assert move in before.legal_moves, f'illegal saved move: {step}'
        assert before.san(move) == step['san'], f'incorrect SAN: {step}'
        after = before.copy()
        after.push(move)
        boards.append(after)
    return boards


def check_claim(claim, boards, pv):
    ply = claim['ply']
    assert type(ply) is int and 0 <= ply < len(boards)
    board = boards[ply]
    kind = claim['type']
    if kind == 'piece_at':
        piece = board.piece_at(chess.parse_square(claim['square']))
        assert (piece.symbol() if piece else None) == claim['piece']
    elif kind == 'attacks':
        source = chess.parse_square(claim['from_square'])
        target = chess.parse_square(claim['to_square'])
        assert (target in board.attacks(source)) is claim['expected']
    elif kind == 'capture':
        assert ply > 0
        before = boards[ply - 1]
        move = chess.Move.from_uci(pv[ply - 1]['uci'])
        assert before.is_capture(move)
        en_passant = before.is_en_passant(move)
        assert en_passant is claim['en_passant']
        square = move.to_square
        if en_passant:
            square += -8 if before.turn == chess.WHITE else 8
        assert before.piece_at(square).symbol() == claim['captured_piece']
    elif kind == 'check':
        assert board.is_check() is claim['expected']
    elif kind == 'checkmate':
        assert board.is_checkmate() is claim['expected']
    elif kind == 'pinned':
        assert claim['color'] in ('white', 'black')
        color = claim['color'] == 'white'
        assert board.is_pinned(color, chess.parse_square(claim['square'])) is claim['expected']
    elif kind == 'legal_move':
        move = chess.Move.from_uci(claim['uci'])
        # Avoid accepting a negative claim merely because it names the wrong side.
        piece = board.piece_at(move.from_square)
        assert piece is not None and piece.color == board.turn
        assert (move in board.legal_moves) is claim['expected']
    elif kind == 'castling_right':
        assert claim['color'] in ('white', 'black')
        assert claim['side'] in ('kingside', 'queenside')
        color = claim['color'] == 'white'
        predicate = (board.has_kingside_castling_rights
                     if claim['side'] == 'kingside'
                     else board.has_queenside_castling_rights)
        assert predicate(color) is claim['expected']
    else:
        raise AssertionError(f'unsupported claim type: {kind}')


class PracticeNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.concepts_path = ROOT / 'webapp/concepts.json'
        cls.research_path = ROOT / 'webapp/research_examples.json'
        cls.groups = json.loads(cls.concepts_path.read_text())
        cls.research = json.loads(cls.research_path.read_text())
        cls.notes = json.loads((ROOT / 'webapp/practice_notes.json').read_text())
        cls.items = cls.notes['items']

    def test_three_existing_public_drills_per_group_with_exact_identity(self):
        self.assertEqual(self.notes['schema_version'], 1)
        self.assertEqual(self.notes['concepts_sha256'], digest(self.concepts_path))
        self.assertEqual(len(self.items), 24)
        self.assertEqual({n['concept_id'] for n in self.items}, set(range(8)))
        self.assertEqual(len({n['id'] for n in self.items}), 24)
        self.assertEqual(len({n['fen'] for n in self.items}), 24)
        for group_id in range(8):
            self.assertEqual(sum(n['concept_id'] == group_id for n in self.items), 3)
        for note in self.items:
            with self.subTest(note=note['id']):
                group = next(g for g in self.groups if g['id'] == note['concept_id'])
                position = group['drill'][note['drill_index']]
                self.assertEqual(note['id'], f"{group['id']}:{note['drill_index']}")
                self.assertEqual(note['fen'], position['fen'])
                self.assertEqual(note['best'], position['best'])
                self.assertEqual(note['evidence']['pv'][0]['uci'], position['best'])
                for key in ('title', 'constraint', 'purpose', 'continuation', 'notice'):
                    self.assertTrue(note[key].strip())

    def test_lines_and_scores_are_exactly_bound_to_existing_caches(self):
        comparisons = []
        research_by = {e['concept']: e['related'] for e in self.research['examples']}
        for note in self.items:
            evidence = note['evidence']
            with self.subTest(note=note['id']):
                # This allowlist prevents private mining rows becoming note evidence.
                self.assertIn(evidence['source'], (
                    'webapp/concepts.json', 'webapp/research_examples.json'))
                self.assertEqual(evidence['source_sha256'], digest(ROOT / evidence['source']))
                if evidence['source'] == 'webapp/concepts.json':
                    position = self.groups[note['concept_id']]['drill'][note['drill_index']]
                    self.assertEqual(evidence['locator'], {
                        'concept_id': note['concept_id'], 'role': 'drill',
                        'drill_index': note['drill_index']})
                    self.assertEqual(evidence['pv'], position['pv'])
                    self.assertEqual(evidence['source_kind'], 'published_pv_excerpt')
                    for key in ('engine_name', 'depth', 'target_depth', 'actual_depth',
                                'cp', 'mate', 'score_perspective'):
                        self.assertIsNone(evidence[key], key)
                    self.assertNotIn('comparison', note)
                else:
                    cached = research_by[note['concept_id']]
                    self.assertEqual((note['fen'], note['best'], note['drill_index']),
                                     (cached['fen'], cached['best'], cached['drill_index']))
                    self.assertEqual(evidence['locator'], {
                        'concept_id': note['concept_id'], 'role': 'related'})
                    self.assertEqual(evidence['pv'], cached['pv'])
                    self.assertEqual(evidence['cp'], cached['best_cp'])
                    self.assertEqual(evidence['engine_name'], self.research['engine']['name'])
                    self.assertEqual(evidence['depth'], cached['depth'])
                    self.assertEqual(evidence['target_depth'], 20)
                    self.assertIsNone(evidence['actual_depth'])
                    self.assertIn('minimum', evidence['depth_kind'])
                    self.assertEqual(evidence['score_perspective'], 'root_mover')
                    self.assertIsNone(evidence['mate'])
                    self.assertEqual(evidence['method_source'], 'experiments/32_research_examples.py')
                    self.assertEqual(evidence['method_sha256'], digest(ROOT / evidence['method_source']))
                    comparison = note['comparison']
                    comparisons.append(note['id'])
                    self.assertTrue(comparison['explanation'].strip())
                    self.assertEqual(comparison['locator'], {
                        'concept_id': note['concept_id'], 'role': 'related.human'})
                    self.assertEqual(comparison['source'], evidence['source'])
                    self.assertEqual(comparison['source_sha256'], evidence['source_sha256'])
                    self.assertEqual(comparison['pv'], cached['human']['pv'])
                    self.assertEqual(comparison['uci'], cached['human']['uci'])
                    self.assertEqual(comparison['san'], cached['human']['san'])
                    self.assertEqual(comparison['pv'][0]['uci'], comparison['uci'])
                    self.assertEqual(comparison['cp'], cached['human_cp'])
                    for key in ('engine_name', 'depth', 'depth_kind', 'target_depth',
                                'actual_depth', 'mate', 'score_perspective',
                                'method_source', 'method_sha256'):
                        self.assertEqual(comparison[key], evidence[key])
        self.assertEqual(set(comparisons), {'0:0', '3:0', '5:0'})

    def test_every_saved_move_and_authored_board_claim(self):
        for note in self.items:
            with self.subTest(note=note['id']):
                lines = {'engine': note['evidence']}
                if 'comparison' in note:
                    lines['comparison'] = note['comparison']
                states = {name: replay(note['fen'], line['pv']) for name, line in lines.items()}
                supported = set()
                self.assertTrue(note['claims'])
                for claim in note['claims']:
                    self.assertIn(claim['line'], lines)
                    check_claim(claim, states[claim['line']], lines[claim['line']]['pv'])
                    self.assertTrue(claim['supports'])
                    supported.update(claim['supports'])
                self.assertTrue({'constraint', 'purpose', 'continuation'} <= supported)
                if 'comparison' in note:
                    self.assertIn('comparison.explanation', supported)

    def test_discovered_check_is_from_bishop_and_en_passant_is_explicit(self):
        by_id = {n['id']: n for n in self.items}
        note = by_id['3:0']
        board = replay(note['fen'], note['evidence']['pv'])[5]
        self.assertEqual(set(board.checkers()), {chess.B6})
        self.assertNotIn(chess.F2, board.attacks(chess.F3))
        note = by_id['0:0']
        board = replay(note['fen'], note['comparison']['pv'])[2]
        self.assertTrue(board.is_en_passant(chess.Move.from_uci('e4f3')))

    def test_pin_legality_and_defensive_score_are_not_misreported(self):
        note = next(n for n in self.items if n['id'] == '5:0')
        states = replay(note['fen'], note['evidence']['pv'])
        self.assertTrue(states[1].is_pinned(chess.WHITE, chess.G3))
        self.assertNotIn(chess.Move.from_uci('g3h4'), states[1].legal_moves)
        self.assertFalse(states[2].is_pinned(chess.WHITE, chess.G3))
        self.assertLess(note['evidence']['cp'], 0)
        self.assertLess(note['comparison']['cp'], 0)
        self.assertGreater(note['evidence']['cp'], note['comparison']['cp'])

    def test_saved_mate_is_terminal_and_not_claimed_before_recapture(self):
        note = next(n for n in self.items if n['id'] == '4:9')
        pv = note['evidence']['pv']
        states = replay(note['fen'], pv)
        self.assertEqual({m.uci() for m in states[1].legal_moves}, {'f1h2'})
        self.assertFalse(states[1].is_checkmate())
        self.assertTrue(states[3].is_checkmate())
        with self.assertRaises(AssertionError):
            check_claim({'ply': 1, 'type': 'checkmate', 'expected': True}, states, pv)

    def test_queen_pin_does_not_mean_every_queen_move_is_illegal(self):
        note = next(n for n in self.items if n['id'] == '6:35')
        board = replay(note['fen'], note['evidence']['pv'])[3]
        self.assertTrue(board.is_pinned(chess.WHITE, chess.F2))
        # Capturing along the pin line remains legal. It is not the saved reply,
        # and these legality checks do not assign an engine score to that branch.
        capture = chess.Move.from_uci('f2d4')
        self.assertIn(capture, board.legal_moves)
        board.push(capture)
        self.assertIn(chess.Move.from_uci('c5d4'), board.legal_moves)

    def test_checker_rejects_a_false_attacker_or_capture_claim(self):
        note = next(n for n in self.items if n['id'] == '3:0')
        pv = note['evidence']['pv']
        states = replay(note['fen'], pv)
        false_claim = {'ply': 5, 'type': 'attacks', 'from_square': 'f3',
                       'to_square': 'f2', 'expected': True}
        with self.assertRaises(AssertionError):
            check_claim(false_claim, states, pv)
        note = next(n for n in self.items if n['id'] == '0:0')
        pv = note['comparison']['pv']
        states = replay(note['fen'], pv)
        false_claim = {'ply': 3, 'type': 'capture', 'captured_piece': 'P',
                       'en_passant': False}
        with self.assertRaises(AssertionError):
            check_claim(false_claim, states, pv)

    def test_replay_rejects_legal_but_incorrect_san(self):
        note = self.items[0]
        pv = copy.deepcopy(note['evidence']['pv'])
        pv[0]['san'] += '+'
        with self.assertRaises(AssertionError):
            replay(note['fen'], pv)


if __name__ == '__main__':
    unittest.main()
