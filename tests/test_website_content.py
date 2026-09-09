"""Public summaries distinguish saved research stages; demo never creates attempts."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_app import site


class WebsiteContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="muc-content-tests-")
        self.previous_db = site.DB
        site.DB = Path(self.tmp.name) / "test.db"
        site.app.config.update(TESTING=True)
        site.init_db()
        self.client = site.app.test_client()

    def tearDown(self):
        site.DB = self.previous_db
        self.tmp.cleanup()

    def test_home_demo_does_not_create_progress_and_has_legal_saved_lines(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        with site.app.app_context():
            self.assertEqual(site.db().execute('SELECT COUNT(*) FROM player').fetchone()[0], 0)
            self.assertEqual(site.db().execute('SELECT COUNT(*) FROM attempt').fetchone()[0], 0)
        pos = site.RESEARCH_EXAMPLES['examples'][0]['primary']
        for pv in (pos['pv'], pos['human']['pv']):
            line = site.frames_of(pos['fen'], pv)
            board = site.chess.Board(pos['fen'])
            self.assertEqual(line['frames'][0]['fen'], board.fen())
            for i, step in enumerate(pv):
                move = site.chess.Move.from_uci(step['uci'])
                self.assertIn(move, board.legal_moves)
                self.assertEqual(line['sans'][i], board.san(move))
                board.push(move)
                self.assertEqual(line['frames'][i + 1]['fen'], board.fen())

    def test_research_overview_separates_trainer_screen_and_incomplete_full_run(self):
        page = self.client.get('/research').get_data(as_text=True)
        overview = page.split('id="current-status"', 1)[1].split('</section>', 1)[0]
        self.assertIn('320 positions from the original collection', overview)
        self.assertIn('248,810 observations', overview)
        self.assertIn('4,345 distinct candidate positions', overview)
        self.assertIn('not a live progress feed', overview)
        if not site.MINING_V3_FULL_DEEP['complete']:
            self.assertIn('final results are not yet published here', overview)
            self.assertNotIn('checked at depths 20 and 24 in all', overview)
        self.assertIn('need chess review and explanations', overview)

    def test_complete_summary_uses_full_results_without_calling_them_trainer_ready(self):
        # Synthetic rendering fixture only; never written to any research output.
        full = copy.deepcopy(site.MINING_V3_FULL_DEEP)
        full['complete'] = True
        full['counts'].update(checked_n=4345, engine_verified_n=987,
                              survives_candidate_criterion_n=654)
        with patch.object(site, 'MINING_V3_FULL_DEEP', full):
            page = self.client.get('/research').get_data(as_text=True)
        overview = page.split('id="current-status"', 1)[1].split('</section>', 1)[0]
        self.assertIn('654 retained the full selection criterion', overview)
        self.assertIn('need chess review and explanations', overview)
        self.assertNotIn('final results are not yet published here', overview)
        self.assertIn('The full checks are complete.', page)

    def test_missing_optional_full_run_does_not_claim_it_started(self):
        with patch.object(site, 'MINING_V3_FULL_DEEP', None):
            page = self.client.get('/research').get_data(as_text=True)
        overview = page.split('id="current-status"', 1)[1].split('</section>', 1)[0]
        self.assertIn('first 200 candidates', overview)
        self.assertNotIn('has started', overview)
        self.assertNotIn('published snapshot dated', overview)

    def test_practice_notes_arrive_after_answer_and_remain_tied_to_the_position(self):
        import uuid
        self.assertTrue(site.PRACTICE_NOTES)
        for note in site.PRACTICE_NOTES.values():
            cid, index = note['concept_id'], note['drill_index']
            with self.subTest(note=note['id']):
                page = self.client.get(f'/pattern/{cid}/drill?mode=restart').get_data(as_text=True)
                self.assertNotIn(note['title'], page)
                request_id = str(uuid.uuid4())
                payload = {'concept': cid, 'idx': index, 'picked': note['best'],
                           'seconds': 1, 'request_id': request_id}
                response = self.client.post('/api/answer', json=payload)
                self.assertEqual(response.status_code, 200)
                line = response.json['line']
                self.assertEqual(line['note']['title'], note['title'])
                self.assertEqual(line['frames'][0]['fen'], note['fen'])
                self.assertEqual(line['frames'][1]['last'], note['best'])
                self.assertEqual(bool(line.get('comparison')), bool(note.get('comparison')))
                self.assertEqual(self.client.post('/api/answer', json=payload).json, response.json)
        with site.app.app_context():
            self.assertEqual(site.db().execute('SELECT COUNT(*) FROM attempt').fetchone()[0],
                             len(site.PRACTICE_NOTES))


if __name__ == '__main__':
    unittest.main()
