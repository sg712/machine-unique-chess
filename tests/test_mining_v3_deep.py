"""Synthetic evidence contracts for the exhaustive v3 verification batch."""
import copy
import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import mining_v3_deep as deep


def fixture(colour=chess.WHITE):
    board = chess.Board()
    history = []
    if colour == chess.BLACK:
        board.push_uci('e2e4')
        history.append('e2e4')
    legal = sorted(move.uci() for move in board.legal_moves)
    record = {'id': 'synthetic-'+('white' if colour else 'black'), 'fen': board.fen(),
              'game_id': 'synthetic-source-'+('white' if colour else 'black'), 'side_to_move': 'white' if colour else 'black',
              'played_move': legal[-1], 'contains_bot': False, 'history_available': True,
              'initial_fen': chess.STARTING_FEN, 'history_uci': history,
              'history_fens': [chess.STARTING_FEN, board.fen()] if history else [board.fen()],
              'split': 'train', 'analysis_role': 'prior_development'}
    probabilities = {move: (.02 if index == 0 else .98/(len(legal)-1)) for index, move in enumerate(legal)}
    policy = {'id': record['id'], 'fen': record['fen'], 'history_available': True,
              'input_condition': 'fen_only',
              'maia3': {'history': {}, 'fen_only': {str(rating): copy.deepcopy(probabilities)
                                                  for rating in (1400, 1700, 2000, 2300)}}}
    roots = [root_result(record, depth, move, 0 if move == legal[0] else -100)
             for depth in deep.DEPTHS for move in legal]
    return record, policy, roots, legal


def root_result(record, depth, move, cp):
    board = chess.Board(record['fen'])
    return {'id': deep.task_id(record['id'], depth, move), 'record_id': record['id'],
            'fen': record['fen'], 'board_context': 'fen_only', 'uci': move,
            'target_depth': depth, 'depth': depth, 'reached_target': True,
            'score_is_exact': True, 'lowerbound': False, 'upperbound': False,
            'cp': cp, 'mate': None, 'nodes': 1234, 'seconds': .25, 'wall_seconds': .3,
            'pv': [{'uci': move, 'san': board.san(chess.Move.from_uci(move))}]}


class RootEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.record, _, self.roots, self.legal = fixture()

    def test_exact_numeric_and_typed_mate_evidence_are_valid(self):
        result = copy.deepcopy(self.roots[0])
        deep.validate_root(result, self.record)
        for value in (-3, 0, 3):
            result.update(cp=None, mate=value)
            deep.validate_root(result, self.record)

    def test_invalid_or_coexisting_score_values_fail(self):
        for cp, mate in ((0, 3), (0, 'bad'), ('bad', 3), (math.nan, 3),
                         (math.nan, None), (math.inf, None), (None, None),
                         (True, None), (None, True), (None, 2.5)):
            with self.subTest(cp=cp, mate=mate):
                result = copy.deepcopy(self.roots[0]); result.update(cp=cp, mate=mate)
                with self.assertRaises(ValueError):
                    deep.validate_root(result, self.record)

    def test_short_or_inexact_root_cannot_be_reused(self):
        mutations = ({'depth': 19}, {'reached_target': False}, {'score_is_exact': False},
                     {'lowerbound': True}, {'upperbound': True})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = copy.deepcopy(self.roots[0]); result.update(mutation)
                with self.assertRaises(ValueError):
                    deep.validate_root(result, self.record)

    def test_nonfinite_depth_and_boolean_nodes_are_not_evidence(self):
        for mutation in ({'depth': math.nan}, {'depth': math.inf}, {'nodes': True},
                         {'nodes': 0}, {'nodes': -1}, {'nodes': 1.5}):
            with self.subTest(mutation=mutation):
                result = copy.deepcopy(self.roots[0]); result.update(mutation)
                with self.assertRaises(ValueError):
                    deep.validate_root(result, self.record)

    def test_invalid_wall_time_is_not_a_valid_checkpoint(self):
        for elapsed in (math.nan, math.inf, -1, True, None):
            result = copy.deepcopy(self.roots[0]); result['wall_seconds'] = elapsed
            with self.assertRaises(ValueError):
                deep.validate_root(result, self.record)

    def test_history_context_cannot_enter_fen_only_checkpoint(self):
        for context in ('history', None):
            result = copy.deepcopy(self.roots[0]); result['board_context'] = context
            with self.assertRaises(ValueError):
                deep.validate_root(result, self.record)

    def test_record_fen_key_and_target_depth_must_match(self):
        for mutation in ({'record_id': 'other'}, {'fen': fixture(chess.BLACK)[0]['fen']},
                         {'id': 'wrong-checkpoint-key'}, {'target_depth': 16}):
            with self.subTest(mutation=mutation):
                result = copy.deepcopy(self.roots[0]); result.update(mutation)
                with self.assertRaises(ValueError):
                    deep.validate_root(result, self.record)

    def test_root_move_and_san_must_match_legal_pv(self):
        changed = copy.deepcopy(self.roots[0]); changed['pv'][0]['uci'] = self.legal[1]
        with self.assertRaises(ValueError):
            deep.validate_root(changed, self.record)
        changed = copy.deepcopy(self.roots[0]); changed['pv'][0]['san'] = 'invalid SAN'
        with self.assertRaises(ValueError):
            deep.validate_root(changed, self.record)
        changed = copy.deepcopy(self.roots[0]); changed['pv'] = []
        with self.assertRaises(ValueError):
            deep.validate_root(changed, self.record)

    def test_later_illegal_pv_move_fails(self):
        changed = copy.deepcopy(self.roots[0])
        changed['pv'].append({'uci': 'e2e4', 'san': 'e4'})
        with self.assertRaises(ValueError):
            deep.validate_root(changed, self.record)


class VerificationGateTests(unittest.TestCase):
    def setUp(self):
        self.record, self.policy, self.roots, self.legal = fixture()

    def summary(self):
        return deep.summarize_position(self.record, self.policy, self.roots)

    def test_engine_stability_retained_criterion_and_teaching_review_are_separate(self):
        result = self.summary()
        self.assertTrue(result['engine_verified'])
        self.assertTrue(result['survives'])
        self.assertEqual(result['candidate_criterion_by_depth'], {'20': True, '24': True})
        self.assertFalse(result['trainer_ready'])
        self.assertEqual(result['board_context'], 'fen_only')
        self.assertEqual(result['reasons'], [])

    def test_all_legal_roots_required_at_each_depth(self):
        for depth in (20, 24):
            roots = [root for root in self.roots
                     if not (root['target_depth'] == depth and root['uci'] == self.legal[-1])]
            with self.assertRaisesRegex(ValueError, 'Every legal root'):
                deep.summarize_position(self.record, self.policy, roots)

    def test_duplicate_evidence_cannot_fill_missing_roots(self):
        self.roots.append(copy.deepcopy(self.roots[0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate root evidence'):
            self.summary()

    def test_bounds_or_short_depth_reject_the_position_evidence(self):
        for mutation in ({'depth': 23}, {'score_is_exact': False}, {'upperbound': True}):
            roots = copy.deepcopy(self.roots); roots[-1].update(mutation)
            with self.assertRaises(ValueError):
                deep.summarize_position(self.record, self.policy, roots)

    def test_mate_of_either_sign_at_either_depth_excludes_verification(self):
        for depth in (20, 24):
            for mate in (-2, 0, 2):
                roots = copy.deepcopy(self.roots)
                root = next(root for root in roots if root['target_depth'] == depth and root['uci'] == self.legal[-1])
                root.update(cp=None, mate=mate)
                result = deep.summarize_position(self.record, self.policy, roots)
                self.assertFalse(result['engine_verified']); self.assertFalse(result['survives'])
                self.assertIn('mate_in_any_legal_root', result['reasons'])

    def test_same_acceptance_set_can_include_multiple_good_moves(self):
        good = set(self.legal[:2])
        for rating, probs in self.policy['maia3']['fen_only'].items():
            for move in probs:
                probs[move] = .02 if move in good else .96/(len(self.legal)-2)
        for root in self.roots:
            if root['uci'] in good:
                root['cp'] = 0 if ((root['target_depth'] == 20) == (root['uci'] == self.legal[0])) else -10
        result = self.summary()
        self.assertTrue(result['engine_verified']); self.assertTrue(result['survives'])
        self.assertEqual(result['accepted']['20'], self.legal[:2])
        self.assertEqual(result['accepted']['24'], self.legal[:2])
        self.assertNotEqual(result['best_moves']['20'], result['best_moves']['24'])

    def test_changed_acceptable_set_fails_even_if_both_mu_gates_pass(self):
        root = next(root for root in self.roots if root['target_depth'] == 24 and root['uci'] == self.legal[1])
        root['cp'] = -10
        result = self.summary()
        self.assertEqual(result['candidate_criterion_by_depth'], {'20': True, '24': True})
        self.assertFalse(result['engine_verified']); self.assertFalse(result['survives'])
        self.assertIn('acceptable_set_changed', result['reasons'])

    def test_numeric_range_is_reapplied_at_both_depths(self):
        for depth in (20, 24):
            for best in (-201, 201):
                roots = copy.deepcopy(self.roots)
                for root in roots:
                    if root['target_depth'] == depth:
                        root['cp'] += best
                result = deep.summarize_position(self.record, self.policy, roots)
                self.assertTrue(result['engine_verified'])
                self.assertFalse(result['survives'])
                self.assertFalse(result['candidate_criterion_by_depth'][str(depth)])

    def test_numeric_range_includes_exact_endpoints(self):
        for best in (-200, 200):
            roots = copy.deepcopy(self.roots)
            for root in roots:
                root['cp'] += best
            result = deep.summarize_position(self.record, self.policy, roots)
            self.assertTrue(result['survives'])

    def test_probability_gate_checks_both_ratings(self):
        for rating in ('1700', '2000'):
            policy = copy.deepcopy(self.policy)
            policy['maia3']['fen_only'][rating] = {move: .11 if move == self.legal[0] else .89/(len(self.legal)-1)
                                                 for move in self.legal}
            result = deep.summarize_position(self.record, policy, self.roots)
            self.assertTrue(result['engine_verified']); self.assertFalse(result['survives'])
            self.assertEqual(result['candidate_criterion_by_depth'], {'20': False, '24': False})

    def test_regret_gate_checks_each_depth_independently(self):
        for depth in (20, 24):
            roots = copy.deepcopy(self.roots)
            for root in roots:
                if root['target_depth'] == depth and root['uci'] != self.legal[0]:
                    root['cp'] = -40
            result = deep.summarize_position(self.record, self.policy, roots)
            self.assertTrue(result['engine_verified']); self.assertFalse(result['survives'])
            self.assertFalse(result['candidate_criterion_by_depth'][str(depth)])
            self.assertTrue(result['candidate_criterion_by_depth'][str(44-depth)])

    def test_missing_required_policy_or_illegal_move_mass_fails(self):
        policy = copy.deepcopy(self.policy); del policy['maia3']['fen_only']['2300']
        with self.assertRaises(ValueError):
            deep.summarize_position(self.record, policy, self.roots)
        policy = copy.deepcopy(self.policy); policy['maia3']['fen_only']['2000']['a1a8'] = 0.
        with self.assertRaises(ValueError):
            deep.summarize_position(self.record, policy, self.roots)

    def test_available_history_is_not_replayed_for_fen_only_metrics(self):
        record, policy, roots, _ = fixture(chess.BLACK)
        # This deliberately unusable history makes any accidental replay fail.
        record['history_uci'] = ['not a chess move']
        with patch.object(deep.base, 'board_for', side_effect=AssertionError('History must not be replayed')):
            result = deep.summarize_position(record, policy, roots)
        self.assertEqual(result['side_to_move'], 'black')
        self.assertTrue(result['survives'])

    def test_colour_metadata_cannot_contradict_fen(self):
        self.record['side_to_move'] = 'black'
        with self.assertRaises(ValueError):
            self.summary()


class FakeEngine:
    def __init__(self):
        self.settings = []
        self.closed = False

    def configure(self, settings):
        self.settings.append(settings)

    def close(self):
        self.closed = True


class RunAndResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        samples = [fixture(chess.BLACK), fixture(chess.WHITE)]
        self.records = [sample[0] for sample in samples]
        self.policies = [sample[1] for sample in samples]
        self.args = SimpleNamespace(input=self.directory/'inputs.jsonl',
                                    policies=self.directory/'policies.jsonl',
                                    selection_manifest=self.directory/'selection.json',
                                    run_dir=self.directory/'run', engine=self.directory/'fake-engine',
                                    workers=1, repair_partial=False)
        self.args.engine.write_bytes(b'synthetic engine identity, never executed')
        self.save_exports()
        self.expected_roots = sum(2*chess.Board(record['fen']).legal_moves.count() for record in self.records)

    def save_exports(self):
        self.args.input.write_text(''.join(json.dumps(record)+'\n' for record in self.records))
        self.args.policies.write_text(''.join(json.dumps(policy)+'\n' for policy in self.policies))
        self.selection = {'complete': True, 'selected_n': len(self.records),
                          'positions_sha256': deep.digest(self.args.input),
                          'policies_sha256': deep.digest(self.args.policies),
                          'selected_ids': [record['id'] for record in self.records]}
        self.args.selection_manifest.write_text(json.dumps(self.selection)+'\n')

    def invoke(self, fail_at=None, corrupt=False, expect_calls=None):
        calls, engines = [], []

        def create_engine(_):
            engine = FakeEngine(); engines.append(engine)
            return engine

        def search(engine, board, depth, seconds, roots=None, multipv=None):
            self.assertFalse(board.move_stack, 'Primary search must be FEN-only even when history is available')
            self.assertIsNone(seconds, 'Depth-only verification must not have a time stop')
            self.assertIsNone(multipv)
            self.assertEqual(len(roots), 1)
            move = roots[0].uci()
            record = next(record for record in self.records if record['fen'] == board.fen())
            calls.append((record['id'], depth, move))
            if fail_at is not None and len(calls) == fail_at:
                raise RuntimeError('Synthetic engine interruption')
            legal = sorted(action.uci() for action in board.legal_moves)
            result = root_result(record, depth, move, 0 if move == legal[0] else -100)
            if corrupt:
                result['upperbound'] = True
            return [result]

        try:
            with patch.object(deep.chess.engine.SimpleEngine, 'popen_uci', side_effect=create_engine), \
                    patch.object(deep.base, 'search', side_effect=search), \
                    patch.object(deep.base, 'board_for', side_effect=AssertionError('Must not replay history')), \
                    patch.object(deep, 'battery_is_critical', return_value=False), \
                    contextlib.redirect_stdout(io.StringIO()):
                deep.run(self.args)
        finally:
            self.last_calls = calls
            self.assertTrue(all(engine.closed for engine in engines))
        if expect_calls is not None:
            self.assertEqual(len(calls), expect_calls)
        return calls

    def cached(self):
        path = self.args.run_dir/'roots.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_depth_only_fen_only_run_completes_every_root_and_resumes_without_searches(self):
        self.invoke(expect_calls=self.expected_roots)
        manifest = json.loads((self.args.run_dir/'run.json').read_text())
        self.assertTrue(manifest['complete'])
        self.assertEqual(manifest['completed_root_searches_n'], self.expected_roots)
        self.assertEqual(manifest['completed_positions_n'], 2)
        self.assertIsNone(manifest['settings']['time_limit'])
        self.assertIsNone(manifest['settings']['node_limit'])
        checksum = deep.digest(self.args.run_dir/'roots.jsonl')
        self.invoke(expect_calls=0)
        self.assertEqual(deep.digest(self.args.run_dir/'roots.jsonl'), checksum)
        positions = [json.loads(line) for line in (self.args.run_dir/'positions.jsonl').read_text().splitlines()]
        self.assertTrue(all(position['engine_verified'] and position['survives'] for position in positions))
        self.assertTrue(all(position['trainer_ready'] is False for position in positions))

    def test_interruption_preserves_valid_roots_and_resume_only_searches_missing_tasks(self):
        with self.assertRaisesRegex(RuntimeError, 'Synthetic engine interruption'):
            self.invoke(fail_at=7)
        cached = {result['id']: result for result in self.cached()}
        self.assertGreater(len(cached), 0)
        self.assertLess(len(cached), self.expected_roots)
        manifest = json.loads((self.args.run_dir/'run.json').read_text())
        self.assertFalse(manifest['complete'])
        self.invoke(expect_calls=self.expected_roots-len(cached))
        after = {result['id']: result for result in self.cached()}
        for key, value in cached.items():
            self.assertEqual(after[key], value)
        searched = {deep.task_id(*task) for task in self.last_calls}
        self.assertTrue(searched.isdisjoint(cached))

    def test_partial_final_line_requires_explicit_repair_and_does_not_discard_saved_roots(self):
        with self.assertRaises(RuntimeError):
            self.invoke(fail_at=7)
        cached_n = len(self.cached())
        with (self.args.run_dir/'roots.jsonl').open('ab') as output:
            output.write(b'{"id":"unfinished')
        with self.assertRaisesRegex(ValueError, 'incomplete final line'):
            self.invoke()
        self.args.repair_partial = True
        self.invoke(expect_calls=self.expected_roots-cached_n)

    def test_changed_checkpoint_prefix_cannot_be_reused(self):
        with self.assertRaises(RuntimeError):
            self.invoke(fail_at=7)
        rows = self.cached(); rows[0]['cp'] += 1
        (self.args.run_dir/'roots.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'checkpoint prefix changed'):
            self.invoke()

    def test_inexact_fresh_result_is_not_checkpointed(self):
        with self.assertRaisesRegex(ValueError, 'exact target-depth score'):
            self.invoke(corrupt=True)
        self.assertEqual(self.cached(), [])
        self.assertFalse(json.loads((self.args.run_dir/'run.json').read_text())['complete'])

    def test_changed_selection_export_hash_fails_before_starting_an_engine(self):
        self.selection['positions_sha256'] = 'wrong'
        self.args.selection_manifest.write_text(json.dumps(self.selection)+'\n')
        with self.assertRaisesRegex(ValueError, 'Selection manifest'):
            self.invoke()
        self.assertEqual(self.last_calls, [])

    def test_duplicate_ids_in_selection_manifest_fail(self):
        self.selection['selected_ids'].append(self.selection['selected_ids'][0])
        self.args.selection_manifest.write_text(json.dumps(self.selection)+'\n')
        with self.assertRaisesRegex(ValueError, 'Selection manifest'):
            self.invoke()

    def test_unrecovered_game_is_not_eligible_even_if_bot_flag_is_false(self):
        self.records[0]['history_available'] = False
        self.policies[0]['history_available'] = False
        self.save_exports()
        with self.assertRaises(ValueError):
            self.invoke()

    def test_publicly_exposed_or_bot_tagged_game_is_ineligible(self):
        for key, value in (('contains_bot', True), ('known_public_game', True), ('analysis_role', 'public_exposed')):
            original = copy.deepcopy(self.records)
            self.records[0][key] = value
            self.save_exports()
            with self.assertRaises(ValueError):
                self.invoke()
            self.assertEqual(self.last_calls, [])
            self.records = original

    def test_reused_source_game_is_rejected_before_search(self):
        self.records[0]['game_id'] = self.records[1]['game_id']
        self.save_exports()
        with self.assertRaisesRegex(ValueError, 'distinct source games'):
            self.invoke()
        self.assertEqual(self.last_calls, [])

    def test_record_order_does_not_change_balanced_processing_order(self):
        records = copy.deepcopy(self.records)*2
        for index, record in enumerate(records):
            records[index] = {**record, 'id': record['id']+'-'+str(index)}
        first = deep.balanced_task_order(records)
        second = deep.balanced_task_order(list(reversed(records)))
        self.assertEqual([record['id'] for record in first], [record['id'] for record in second])
        self.assertEqual([record['side_to_move'] for record in first], ['white','black','white','black'])


if __name__ == '__main__':
    unittest.main()
