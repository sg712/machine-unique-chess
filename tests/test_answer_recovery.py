"""Saved-answer recovery and browser-owner binding use disposable SQLite only."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_app import site


class ElementsByID(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if 'id' in values:
            self.elements[values['id']] = (tag, values)


class AnswerRecoveryTests(unittest.TestCase):
    def setUp(self):
        previous_db = site.DB
        directory = tempfile.TemporaryDirectory(prefix='muc-answer-recovery-')
        self.addCleanup(directory.cleanup)
        self.addCleanup(setattr, site, 'DB', previous_db)
        site.DB = Path(directory.name) / 'test.db'
        site.app.config.update(TESTING=True)
        site.init_db()
        self.client = site.app.test_client()

    def snapshot(self):
        with site.app.app_context():
            return {table: [dict(row) for row in site.db().execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('player', 'attempt', 'submission', 'studied', 'account', 'blindspot', 'sqlite_sequence')}

    def open_practice(self, client=None):
        client = client or self.client
        self.assertEqual(client.get('/pattern/0/drill').status_code, 200)
        with client.session_transaction() as session:
            return session['code']

    def payload(self, owner, index=0, key=None, picked=None):
        position = site.BY_ID[0]['drill'][index]
        return {'owner': owner, 'concept': 0, 'idx': index, 'fen': position['fen'],
                'picked': picked or position['best'], 'seconds': 3,
                'request_id': key or str(uuid.uuid4())}

    def save(self, payload, client=None):
        response = (client or self.client).post('/api/answer', json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response

    def test_saved_feedback_recovers_exactly_under_database_readonly_mode(self):
        owner = self.open_practice()
        payload = self.payload(owner)
        accepted = self.save(payload)
        before = self.snapshot()
        original_db = site.db

        def read_only_db():
            connection = original_db()
            connection.execute('PRAGMA query_only = ON')
            return connection

        with patch.object(site, 'db', read_only_db), \
             patch.object(site, 'ensure_player', side_effect=AssertionError('Recovery must not create a player')), \
             patch.object(site, 'practice_line', side_effect=AssertionError('Recovery must read the receipt without recomputing')):
            for _ in range(2):
                recovered = self.client.post('/api/answer/recover', json=payload)
                self.assertEqual(recovered.status_code, 200)
                self.assertEqual(recovered.json, {'status': 'saved', 'result': accepted.json})
                self.assertEqual(recovered.headers.get('Cache-Control'), 'no-store')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(before['attempt']), 1)
        self.assertEqual(len(before['submission']), 1)

    def test_unknown_receipt_and_changed_legal_choice_are_missing_without_writes(self):
        owner = self.open_practice()
        payload = self.payload(owner)
        self.save(payload)
        other = next(move for move in site.board_of(payload['fen'])['legal'] if move != payload['picked'])
        changed_position = self.payload(owner, index=1, key=payload['request_id'])
        before = self.snapshot()
        for request in ({**payload, 'request_id': str(uuid.uuid4())}, {**payload, 'picked': other}, changed_position):
            with self.subTest(request=request):
                response = self.client.post('/api/answer/recover', json=request)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {'status': 'missing'})
                self.assertEqual(self.snapshot(), before)

    def test_another_player_receipt_never_leaks_feedback_or_changes_the_database(self):
        owner = self.open_practice()
        payload = self.payload(owner)
        self.save(payload)
        other_client = site.app.test_client()
        other_owner = self.open_practice(other_client)
        before = self.snapshot()
        response = other_client.post('/api/answer/recover', json={**payload, 'owner': other_owner})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status': 'missing'})
        mismatch = other_client.post('/api/answer/recover', json=payload)
        self.assertEqual(mismatch.status_code, 403)
        self.assertEqual(set(mismatch.json), {'error'})
        self.assertNotIn(payload['picked'], mismatch.get_data(as_text=True))
        self.assertEqual(self.snapshot(), before)

    def test_absent_or_expired_player_cannot_recover_and_is_not_created(self):
        payload = self.payload('ABCDEF')
        for stale_cookie in (False, True):
            client = site.app.test_client()
            if stale_cookie:
                with client.session_transaction() as session:
                    session['code'] = 'ABCDEF'
            before = self.snapshot()
            response = client.post('/api/answer/recover', json=payload)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(set(response.json), {'error'})
            self.assertEqual(self.snapshot(), before)
            if not stale_cookie:
                with client.session_transaction() as session:
                    self.assertNotIn('code', session)
        self.assertEqual(len(self.snapshot()['player']), 0)

    def test_old_tab_owner_cannot_save_after_the_session_changes_or_expires(self):
        old_owner = self.open_practice()
        stale = self.payload(old_owner)
        self.client.get('/logout')
        before = self.snapshot()
        self.assertEqual(self.client.post('/api/answer', json=stale).status_code, 403)
        self.assertEqual(self.snapshot(), before)
        current_owner = self.open_practice()
        self.assertNotEqual(old_owner, current_owner)
        before = self.snapshot()
        response = self.client.post('/api/answer', json=stale)
        self.assertEqual(response.status_code, 403)
        self.assertIn('account changed', response.json['error'])
        self.assertEqual(self.snapshot(), before)
        self.save(self.payload(current_owner))
        with site.app.app_context():
            attempt = dict(site.db().execute('SELECT * FROM attempt').fetchone())
        self.assertEqual(attempt['code'], current_owner)

    def test_owner_and_fen_binding_hold_before_idempotent_receipt_lookup(self):
        owner = self.open_practice()
        payload = self.payload(owner)
        accepted = self.save(payload)
        before = self.snapshot()
        retry = self.save(payload)
        self.assertEqual(retry.json, accepted.json)
        for wrong_fen in (None, '', site.BY_ID[0]['drill'][1]['fen']):
            with self.subTest(fen=wrong_fen):
                response = self.client.post('/api/answer', json={**payload, 'fen': wrong_fen})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(set(response.json), {'error'})
        self.assertEqual(self.snapshot(), before)
        other_client = site.app.test_client()
        other_owner = self.open_practice(other_client)
        before = self.snapshot()
        conflict = other_client.post('/api/answer', json={**payload, 'owner': other_owner})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(set(conflict.json), {'error'})
        self.assertEqual(self.snapshot(), before)

    def test_recovery_rejects_malformed_identity_fen_and_moves_without_writes(self):
        owner = self.open_practice()
        good = self.payload(owner)
        malformed = [None, [], 'answer',
            {**good, 'concept': True}, {**good, 'concept': '0'}, {**good, 'concept': 99},
            {**good, 'idx': True}, {**good, 'idx': -1}, {**good, 'idx': 36},
            {**good, 'request_id': None}, {**good, 'request_id': 'bad'},
            {**good, 'fen': None}, {**good, 'fen': site.BY_ID[0]['drill'][1]['fen']},
            {**good, 'picked': None}, {**good, 'picked': True}, {**good, 'picked': 'e2e9'},
            {**good, 'picked': '0000'}]
        before = self.snapshot()
        for request in malformed:
            with self.subTest(request=request):
                response = self.client.post('/api/answer/recover', json=request)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(set(response.json), {'error'})
                self.assertEqual(self.snapshot(), before)
        response = self.client.post('/api/answer/recover', data='{"broken"', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_bound_answers_never_create_attempts_or_receipts(self):
        owner = self.open_practice()
        good = self.payload(owner)
        before = self.snapshot()
        for request in ([], None, {**good, 'idx': False}, {**good, 'fen': ''},
                        {**good, 'picked': []}, {**good, 'picked': '0000'},
                        {**good, 'seconds': True}, {**good, 'seconds': -1},
                        {**good, 'seconds': float('inf')}, {**good, 'request_id': 'invalid'}):
            with self.subTest(request=request):
                response = self.client.post('/api/answer', json=request)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.snapshot(), before)

    def test_final_saved_answer_has_a_recovery_mount_even_when_fresh_queue_is_empty(self):
        owner = self.open_practice()
        size = len(site.BY_ID[0]['drill'])
        for index in range(size):
            payload = self.payload(owner, index=index)
            accepted = self.save(payload)
        before = self.snapshot()
        html = self.client.get('/pattern/0/drill').get_data(as_text=True)
        fresh = json.loads(re.search(r'const POS = (.*?), PIECES = ', html).group(1))
        all_positions = json.loads(re.search(r'allPositions:\s*(\[.*?\]),\s*pieces:', html, re.S).group(1))
        self.assertEqual(fresh, [])
        self.assertEqual([position['idx'] for position in all_positions], list(range(size)))
        self.assertEqual(all_positions[-1]['fen'], payload['fen'])
        self.assertIn(payload['picked'], all_positions[-1]['legal'])
        self.assertTrue(all('best' not in position for position in all_positions))
        elements = ElementsByID(html).elements
        self.assertIn('hidden', elements['practice-flow'][1])
        self.assertNotIn('hidden', elements['practice-empty'][1])
        for identifier in ('board', 'feedback', 'replay', 'lock', 'save-error'):
            self.assertIn(identifier, elements)
        self.assertIn('mountDrill({positions: POS, allPositions:', html)
        self.assertIn(f'const OWNER = {json.dumps(owner)};', html)
        recovered = self.client.post('/api/answer/recover', json=payload)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json, {'status': 'saved', 'result': accepted.json})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(before['attempt']), size)


if __name__ == '__main__':
    unittest.main()
