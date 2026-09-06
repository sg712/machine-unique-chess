"""Regression tests run only against a disposable local database."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import uuid
from urllib.parse import parse_qs, urlparse

_SANDBOX = tempfile.TemporaryDirectory(prefix="muc-tests-")
os.environ.pop("DATABASE_URL", None)
os.environ["DB_PATH"] = str(Path(_SANDBOX.name) / "initial.db")
os.environ["SECRET_KEY"] = "tests-only-never-production"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))
import app as site


class TrainingTests(unittest.TestCase):
    def setUp(self):
        site.DB = Path(_SANDBOX.name) / (uuid.uuid4().hex + ".db")
        site.app.config.update(TESTING=True)
        site.init_db()
        self.client = site.app.test_client()

    def count(self, table):
        with site.app.app_context():
            return site.db().execute(f"SELECT COUNT(*) n FROM {table}").fetchone()["n"]

    def answer(self, index=0, picked=None, key=None, client=None):
        return (client or self.client).post('/api/answer', json={
            'concept': 0, 'idx': index,
            'picked': picked or site.BY_ID[0]['drill'][index]['best'],
            'seconds': 1, 'request_id': key or str(uuid.uuid4())})

    def new_test(self):
        response = self.client.get('/test?new=1')
        token = parse_qs(urlparse(response.location).query)['attempt'][0]
        attempt = site.read_test(token)
        answers = []
        for key in attempt['items']:
            cid, idx = map(int, key.split(':'))
            answers.append(site.BY_ID[cid]['drill'][idx]['best'])
        return token, answers, response.location

    def test_pages_and_legacy_redirects(self):
        routes = ['/', '/learn', '/research', '/test', '/register', '/login', '/claim']
        routes += [f'/pattern/{i}{suffix}' for i in range(8) for suffix in ('', '/drill')]
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)
        self.assertEqual(self.client.get('/concept/0').status_code, 301)
        _, _, url = self.new_test()
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_legal_data(self):
        for concept in site.CONCEPTS:
            for kind in ('study', 'drill'):
                for pos in concept[kind]:
                    board = site.chess.Board(pos['fen'])
                    self.assertIn(site.chess.Move.from_uci(pos['best']), board.legal_moves)
                    for step in pos['pv']:
                        move = site.chess.Move.from_uci(step['uci'])
                        self.assertIn(move, board.legal_moves)
                        board.push(move)

    def register(self):
        self.answer()
        response = self.client.post('/register', data={'email': 'test@example.invalid', 'password': 'local-test-password'})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            return session['code']

    def test_claim_cannot_enter_registered_account(self):
        code = self.register()
        other = site.app.test_client()
        response = other.post('/claim', data={'resume': code})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b'test@example.invalid', response.data)
        self.assertEqual(other.get('/me').status_code, 302)

    def test_old_code_cookie_does_not_authenticate_email_account(self):
        code = self.register()
        other = site.app.test_client()
        with other.session_transaction() as session:
            session['code'] = code
        self.assertEqual(other.get('/me').status_code, 302)
        self.assertNotIn(b'test@example.invalid', other.get('/').data)
        self.assertEqual(self.answer(client=other).status_code, 200)
        with other.session_transaction() as session:
            self.assertNotEqual(session['code'], code)

    def test_anonymous_recovery_and_password_login(self):
        self.answer()
        with self.client.session_transaction() as session:
            code = session['code']
        other = site.app.test_client()
        self.assertEqual(other.post('/claim', data={'resume': code}).status_code, 302)
        self.assertEqual(other.get('/me').status_code, 200)
        self.register()
        self.client.get('/logout')
        self.assertIn(b'Wrong email', self.client.post('/login', data={'email':'test@example.invalid','password':'wrong'}).data)
        self.assertEqual(self.client.post('/login', data={'email':'test@example.invalid','password':'local-test-password'}).status_code, 302)
        self.assertEqual(self.client.get('/me').status_code, 200)

    def test_invalid_move_never_saved(self):
        self.assertEqual(self.answer(picked='xxxxx').status_code, 400)
        self.assertEqual(self.count('attempt'), 0)
        self.assertEqual(self.count('player'), 0)

    def test_bad_payloads_return_400(self):
        for payload in ([], None, {'concept':'zero'}, {'concept':0, 'idx':999}):
            self.assertEqual(self.client.post('/api/answer', json=payload).status_code, 400)
        self.assertEqual(self.client.post('/api/blindspot', json=[]).status_code, 400)
        self.assertEqual(self.client.get('/test?attempt=bad').status_code, 400)

    def test_retry_is_idempotent(self):
        key = str(uuid.uuid4())
        first = self.answer(key=key)
        again = self.answer(key=key)
        self.assertEqual(first.json, again.json)
        self.assertEqual(self.count('attempt'), 1)
        pos = site.BY_ID[0]['drill'][0]
        other = next(m for m in site.board_of(pos['fen'])['legal'] if m != pos['best'])
        self.assertEqual(self.answer(picked=other, key=key).status_code, 409)
        self.assertEqual(self.count('attempt'), 1)

    def test_feedback_does_not_call_model_loss_user_loss(self):
        result = self.answer().json
        self.assertIn('model_move_cost_cp', result)
        self.assertNotIn('cost_cp', result)

    def test_repeat_practice_does_not_inflate_unique_solved(self):
        self.answer(); self.answer()
        with self.client.session_transaction() as session:
            code = session['code']
        with site.app.app_context():
            progress = site.concept_progress(code)[0]
        self.assertEqual((progress['n'], progress['correct']), (1, 1))

    def test_restart_and_missed_and_resume(self):
        pos = site.BY_ID[0]['drill'][0]
        wrong = next(m for m in site.board_of(pos['fen'])['legal'] if m != pos['best'])
        self.answer(picked=wrong)
        self.answer(index=2)
        def positions(mode):
            html = self.client.get('/pattern/0/drill?mode=' + mode).get_data(as_text=True)
            match = re.search(r'const POS = (.*?), PIECES = ', html)
            return json.loads(match.group(1)) if match else []
        self.assertEqual([p['idx'] for p in positions('missed')], [0])
        self.assertEqual(positions('continue')[0]['idx'], 1)
        self.assertEqual(positions('restart')[0]['idx'], 0)
        for i in range(36): self.answer(index=i)
        self.assertEqual(positions('continue'), [])
        self.assertEqual(len(positions('restart')), 36)
        self.assertEqual(positions('missed'), [])

    def test_tests_are_independent_and_reload_stable(self):
        token_a, answers_a, url_a = self.new_test()
        token_b, answers_b, _ = self.new_test()
        self.client.get(url_a)
        for token, picks in ((token_a, answers_a), (token_b, answers_b)):
            result = self.client.post('/api/blindspot', json={'attempt': token, 'picks': picks})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['correct'], 12)
            self.assertEqual(result.json['band'], '2800+')
            self.assertIn('line', result.json['reveal'][0])
        self.assertEqual(self.count('blindspot'), 2)

    def test_test_retry_and_validation(self):
        token, answers, _ = self.new_test()
        bad = answers.copy(); bad[0] = 'xxxxx'
        self.assertEqual(self.client.post('/api/blindspot', json={'attempt': token, 'picks': bad}).status_code, 400)
        self.assertEqual(self.count('blindspot'), 0)
        payload = {'attempt': token, 'picks': answers}
        first = self.client.post('/api/blindspot', json=payload)
        second = self.client.post('/api/blindspot', json=payload)
        self.assertEqual(first.json, second.json)
        self.assertEqual(self.count('blindspot'), 1)

    def test_test_token_tampering(self):
        token, picks, _ = self.new_test()
        self.assertEqual(self.client.post('/api/blindspot', json={'attempt': token + 'x', 'picks': picks}).status_code, 400)
        self.assertEqual(self.count('blindspot'), 0)


if __name__ == '__main__':
    unittest.main()
