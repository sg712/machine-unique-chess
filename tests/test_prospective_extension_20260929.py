"""Mocked evidence/lifecycle checks: no real model or engine is started."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import chess
import chess.engine
from scripts import prospective_extension_20260929 as ext


def fixture(key, black=False):
    board = chess.Board()
    if black:
        board.push_uci('e2e4')
    legal = sorted(m.uci() for m in board.legal_moves)
    row = {'id': key, 'analysis_role': 'calibration_development', 'fen': board.fen(),
           'side_to_move': 'black' if black else 'white', 'white_elo': 1600, 'black_elo': 1900,
           'played_move': legal[0], 'player_hashes': {'white': key + 'w', 'black': key + 'b'}}
    policy = {'id': key, 'fen': board.fen(), 'rating_pairs': {'actual': [1900, 1600] if black else [1600, 1900]},
              'policies': {c: {'actual': {m: 1 / len(legal) for m in legal}} for c in ('history', 'fen_only')}}
    roots = {}
    for d in (20, 24):
        roots[str(d)] = {m: {'record_id': key, 'fen': row['fen'], 'target_depth': d, 'requested_root': m,
                            'board_context': 'fen_only', 'depth': d, 'reached_target': True,
                            'cp': 0, 'mate': None, 'lowerbound': False, 'upperbound': False,
                            'score_is_exact': True, 'status': 'complete_numeric',
                            'pv': [{'uci': m, 'san': board.san(chess.Move.from_uci(m))}]} for m in legal}
    roots['24'][legal[0]].update(depth=21, reached_target=False, status='capped_or_interrupted')
    return row, policy, roots


def snapshot():
    fixtures = [fixture('private-first'), fixture('private-second', True)]
    rows = [v[0] for v in fixtures]
    policies = {r['id']: p for r, p, _ in fixtures}
    roots = {r['id']: s for r, _, s in fixtures}
    return {'rows': rows, 'policies': policies, 'roots': roots,
            'controls': {'passed': True, 'max_paired_probability_difference': 0.0,
                         'max_equal_rating_adapter_difference': 0.0, 'same_input_controls_n': 4},
            'by_role': ext.role_summaries(rows, policies, roots), 'fingerprints': {'baseline': 'fixed'},
            'tasks': ext.select_unfinished(rows, roots)}


def result_for(snap, task, *, completed=True, reason=None, seconds=.1, status=None):
    result = copy.deepcopy(snap['roots'][task['record_id']]['24'][task['move']])
    if completed:
        result.update(depth=24, reached_target=True, status='complete_numeric')
    if status:
        result['status'] = status
    result.update(per_root_cap_seconds=120, wall_seconds=seconds, stop_reason=reason)
    return result


class FakeEngine:
    id = {'name': 'mock'}
    def __init__(self): self.configured = []; self.closed = False
    def configure(self, options): self.configured.append(options)
    def quit(self): self.closed = True
    def close(self): self.closed = True


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'base'; self.base.mkdir()
        for name in ('.run.lock', '.continuation.lock'):
            (self.base / name).write_bytes(b'')
        (self.base / 'sentinel').write_bytes(b'frozen baseline evidence')
        (self.base / 'engine_runtime.json').write_text(json.dumps({'engine_id': {'name': 'mock'}}))
        self.original = {p.name: p.read_bytes() for p in self.base.iterdir()}
        self.out = self.root / 'supplement'
        self.public = self.root / 'public.json'
        self.snap = snapshot()
        for patcher in (patch.object(ext, 'BASE', self.base), patch.object(ext, 'PUBLIC', self.public),
                        patch.object(ext, 'safe_output', side_effect=lambda p: Path(p)),
                        patch.object(ext, 'baseline_snapshot', return_value=self.snap),
                        patch.object(ext, 'dependency_hashes', return_value={'script': 'fixed'})):
            patcher.start(); self.addCleanup(patcher.stop)
        ext.prepare(self.out)

    def assert_base_unchanged(self):
        self.assertEqual({p.name: p.read_bytes() for p in self.base.iterdir()}, self.original)

    def run_mocked(self, search):
        engine = FakeEngine()
        with patch.object(ext.base, 'power_state', return_value='ac'), \
             patch.object(ext.chess.engine.SimpleEngine, 'popen_uci', return_value=engine), \
             patch.object(ext, 'supplemental_search', side_effect=search):
            result = ext.run(self.out)
        self.assertTrue(engine.closed)
        self.assertIn({'Threads': 1, 'Hash': 64}, engine.configured)
        self.assert_base_unchanged()
        return result

    def test_battery_never_launches_engine_or_consumes_invocation(self):
        with patch.object(ext.base, 'power_state', return_value='battery'), \
             patch.object(ext.chess.engine.SimpleEngine, 'popen_uci') as engine:
            result = ext.run(self.out)
        self.assertEqual(result['status'], 'paused_power')
        self.assertEqual(result['invocation_count'], 0)
        engine.assert_not_called()
        self.assert_base_unchanged()

    def test_completed_supplement_is_separate_and_original_files_unchanged(self):
        before_plan = copy.deepcopy(ext.base.PLAN)
        result = self.run_mocked(lambda _e, _r, task, _d, _s: result_for(self.snap, task))
        self.assertEqual(result['status'], 'searches_complete')
        self.assertEqual(result['completed_roots_n'], 2)
        self.assertEqual(result['baseline_by_role']['calibration_development']['verified_calibration_n'], 0)
        self.assertEqual(result['supplemented_by_role']['calibration_development']['verified_calibration_n'], 2)
        self.assertEqual(ext.base.PLAN, before_plan)
        text = self.public.read_text()
        for private in ('private-first', 'private-second', self.snap['rows'][0]['fen'], 'requested_root', 'played_move'):
            self.assertNotIn(private, text)

    def test_power_interruption_is_preserved_and_resumes_once(self):
        result = self.run_mocked(lambda _e, _r, task, _d, _s: result_for(self.snap, task, completed=False, reason='power_pause', seconds=3))
        self.assertEqual(result['status'], 'paused_power')
        self.assertEqual(result['completed_roots_n'], 0)
        initial = {p.name: p.read_bytes() for p in (self.out / 'attempts').iterdir()}
        result = self.run_mocked(lambda _e, _r, task, _d, _s: result_for(self.snap, task))
        self.assertEqual(result['status'], 'searches_complete')
        self.assertEqual(result['invocation_count'], 2)
        for name, payload in initial.items(): self.assertEqual((self.out / 'attempts' / name).read_bytes(), payload)
        self.assertEqual(len(list((self.out / 'attempts').glob('*.json'))), 3)

    def test_one_full_cap_each_is_exhausted_without_retry(self):
        result = self.run_mocked(lambda _e, _r, task, _d, _s: result_for(self.snap, task, completed=False, reason='root_cap', seconds=120.01))
        self.assertEqual(result['status'], 'cap_exhausted')
        self.assertEqual(result['exhausted_roots_n'], 2)
        with patch.object(ext.chess.engine.SimpleEngine, 'popen_uci') as engine:
            again = ext.run(self.out)
        engine.assert_not_called()
        self.assertEqual(again['invocation_count'], 1)
        self.assertEqual(again['completed_roots_n'], 0)
        self.assertEqual(len(list((self.out / 'attempts').glob('*.json'))), 2)

    def test_partial_results_only_promote_completed_root(self):
        seen = []
        def search(_e, _r, task, _d, _s):
            seen.append(task)
            return result_for(self.snap, task, completed=len(seen) == 1, reason=None if len(seen) == 1 else 'power_pause')
        result = self.run_mocked(search)
        self.assertEqual(result['completed_roots_n'], 1)
        self.assertEqual(result['incomplete_roots_n'], 1)
        group = result['supplemented_by_role']['calibration_development']
        self.assertEqual(group['verified_calibration_n'], 1)
        self.assertEqual(group['state_counts']['incomplete_roots'], 1)
        self.assertEqual(result['baseline_by_role']['calibration_development']['verified_calibration_n'], 0)

    def test_engine_error_stays_review_required_and_cannot_retry(self):
        def fail(_e, _r, task, _d, _s):
            value = result_for(self.snap, task, completed=False)
            value.update(status='engine_error', error='EngineTerminatedError')
            return value
        result = self.run_mocked(fail)
        self.assertEqual(result['status'], 'needs_review')
        with patch.object(ext.chess.engine.SimpleEngine, 'popen_uci') as engine:
            again = ext.run(self.out)
        engine.assert_not_called()
        self.assertEqual(again['status'], 'needs_review')
        self.assertEqual(again['invocation_count'], 1)

    def test_manifest_selection_and_baseline_hashes_fail_closed(self):
        path = self.out / 'manifest.json'; original = path.read_bytes()
        for mutate in (lambda m: m['tasks'][0].update(depth=20),
                       lambda m: m['base_fingerprints'].update(baseline='changed'),
                       lambda m: m['protocol'].update(per_root_seconds=240),
                       lambda m: m['dependencies'].update(script='changed')):
            manifest = json.loads(original); mutate(manifest); path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): ext.load_manifest(self.out)
        path.write_bytes(original)
        self.assert_base_unchanged()

    def test_attempt_evidence_cannot_be_overwritten(self):
        path = self.out / 'immutable.json'
        ext.write_once(path, {'original': True})
        original = path.read_bytes()
        with self.assertRaises(FileExistsError): ext.write_once(path, {'original': False})
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(FileExistsError): ext.prepare(self.out)
        self.assert_base_unchanged()

    def test_six_invocation_limit_never_resets(self):
        digest = ext.base.digest(self.out / 'manifest.json')
        for n in range(1, 7):
            ext.write_once(self.out / 'invocations' / f'{n:04d}.json', {'number': n, 'manifest_sha256': digest})
        ext.checkpoint(self.out, 'paused_power', 6)
        with patch.object(ext.base, 'power_state', return_value='ac'), \
             patch.object(ext.chess.engine.SimpleEngine, 'popen_uci') as engine:
            result = ext.run(self.out)
        engine.assert_not_called()
        self.assertEqual(result['status'], 'invocation_limit')
        self.assertEqual(result['invocation_count'], 6)

    def test_unfinished_reservation_requires_review_without_retry(self):
        digest = ext.base.digest(self.out / 'manifest.json')
        ext.write_once(self.out / 'invocations/0001.json', {'number': 1, 'manifest_sha256': digest})
        task = self.snap['tasks'][0]
        ext.write_once(self.out / 'reservations' / f"{task['key']}-0001.json",
                       {'task_key': task['key'], 'attempt_number': 1, 'invocation': 1, 'manifest_sha256': digest})
        with patch.object(ext.chess.engine.SimpleEngine, 'popen_uci') as engine:
            result = ext.run(self.out)
        engine.assert_not_called()
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['unresolved_reservations_n'], 1)

    def test_active_baseline_writer_blocks_supplement(self):
        import fcntl
        with (self.base / '.run.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'active writer'): ext.run(self.out)
        self.assert_base_unchanged()


class SearchTests(unittest.TestCase):
    def test_selected_only_exact_two_unfinished_roots(self):
        snap = snapshot()
        self.assertEqual(len(ext.select_unfinished(snap['rows'], snap['roots'])), 2)
        first = snap['tasks'][0]
        del snap['roots'][first['record_id']]['24'][first['move']]
        with self.assertRaisesRegex(ValueError, 'unattempted'): ext.select_unfinished(snap['rows'], snap['roots'])

    def test_interruptions_do_not_consume_full_opportunity(self):
        for reason in ext.INTERRUPTIONS:
            self.assertFalse(ext.consumes_opportunity({'status': 'capped_or_interrupted', 'wall_seconds': 4, 'stop_reason': reason}))
        self.assertTrue(ext.consumes_opportunity({'status': 'capped_or_interrupted', 'wall_seconds': 120, 'stop_reason': 'power_pause'}))
        self.assertTrue(ext.consumes_opportunity({'status': 'capped_or_interrupted', 'wall_seconds': 119.98, 'stop_reason': None}))

    def test_unscored_depth_update_does_not_promote_prior_score(self):
        snap = snapshot(); task = snap['tasks'][0]
        row = next(r for r in snap['rows'] if r['id'] == task['record_id'])
        class Analysis:
            def __iter__(self):
                yield {'score': chess.engine.PovScore(chess.engine.Cp(0), chess.Board(row['fen']).turn),
                       'depth': 23, 'pv': [chess.Move.from_uci(task['move'])]}
                yield {'depth': 24}
            def stop(self): pass
        class Engine(FakeEngine):
            def analysis(self, board, limit, **kwargs):
                self.limit = limit; return Analysis()
        engine = Engine()
        result = ext.supplemental_search(engine, row, task, time.monotonic() + 600, threading.Event())
        self.assertEqual(result['depth'], 23)
        self.assertEqual(result['status'], 'capped_or_interrupted')
        self.assertEqual(engine.limit.time, 120)
        self.assertEqual(engine.limit.depth, 24)
        self.assertIn({'Clear Hash': None}, engine.configured)

    def test_slow_power_read_cannot_delay_wall_cap(self):
        snap = snapshot(); task = snap['tasks'][0]
        row = next(r for r in snap['rows'] if r['id'] == task['record_id'])
        release_power = threading.Event()
        class Analysis:
            def __init__(self): self.stopped = threading.Event()
            def __iter__(self):
                yield {'score': chess.engine.PovScore(chess.engine.Cp(0), chess.Board(row['fen']).turn),
                       'depth': 20, 'pv': [chess.Move.from_uci(task['move'])]}
                self.stopped.wait(3)
            def stop(self): self.stopped.set()
        class Engine(FakeEngine):
            def analysis(self, *args, **kwargs): self.active = Analysis(); return self.active
            def close(self): self.active.stop(); super().close()
        def slow_power():
            release_power.wait(3)
            return 'ac'
        try:
            with patch.object(ext.base, 'power_state', side_effect=slow_power):
                started = time.monotonic()
                result = ext.supplemental_search(Engine(), row, task, started + .05, threading.Event())
        finally:
            release_power.set()
        self.assertEqual(result['stop_reason'], 'invocation_wall_cap')
        self.assertLess(result['wall_seconds'], 1)
        self.assertFalse(ext.consumes_opportunity(result))

    def test_unresponsive_search_is_closed_after_stop_grace(self):
        snap = snapshot(); task = snap['tasks'][0]
        row = next(r for r in snap['rows'] if r['id'] == task['record_id'])
        class Analysis:
            def __init__(self): self.closed = threading.Event()
            def __iter__(self):
                yield {'score': chess.engine.PovScore(chess.engine.Cp(0), chess.Board(row['fen']).turn),
                       'depth': 20, 'pv': [chess.Move.from_uci(task['move'])]}
                self.closed.wait(4)
            def stop(self): pass
        class Engine(FakeEngine):
            def analysis(self, *args, **kwargs): self.active = Analysis(); return self.active
            def close(self): self.active.closed.set(); super().close()
        engine = Engine()
        with patch.object(ext.base, 'power_state', return_value='ac'):
            result = ext.supplemental_search(engine, row, task, time.monotonic() + .05, threading.Event())
        self.assertTrue(engine.closed)
        self.assertEqual(result['stop_reason'], 'invocation_wall_cap')
        self.assertLess(result['wall_seconds'], 2.7)
        self.assertEqual(result['depth'], 20)

    def test_power_and_sigterm_event_stop_search_and_save_partial_evidence(self):
        snap = snapshot(); task = snap['tasks'][0]
        row = next(r for r in snap['rows'] if r['id'] == task['record_id'])
        class Analysis:
            def __init__(self): self.stopped = threading.Event()
            def __iter__(self):
                yield {'score': chess.engine.PovScore(chess.engine.Cp(0), chess.Board(row['fen']).turn),
                       'depth': 20, 'pv': [chess.Move.from_uci(task['move'])]}
                self.stopped.wait(2)
            def stop(self): self.stopped.set()
        class Engine(FakeEngine):
            def analysis(self, *args, **kwargs): self.active = Analysis(); return self.active
            def close(self): self.active.stop(); super().close()
        for reason in ('power_pause', 'user_stop'):
            stop = threading.Event()
            if reason == 'user_stop': stop.set()
            with self.subTest(reason=reason), patch.object(ext.base, 'power_state', return_value='battery' if reason == 'power_pause' else 'ac'):
                result = ext.supplemental_search(Engine(), row, task, time.monotonic() + 600, stop)
            self.assertEqual(result['stop_reason'], reason)
            self.assertEqual(result['status'], 'capped_or_interrupted')
            self.assertEqual(result['depth'], 20)
            self.assertFalse(ext.consumes_opportunity(result))
            self.assertLess(result['wall_seconds'], 2)


if __name__ == '__main__':
    unittest.main()
