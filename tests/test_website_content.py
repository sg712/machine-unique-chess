"""Public summaries distinguish saved research stages; demo never creates attempts."""
import copy
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_app import site


class TableRows(HTMLParser):
    def __init__(self, table_id):
        super().__init__()
        self.table_id, self.active, self.cell = table_id, False, None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table' and dict(attrs).get('id') == self.table_id:
            self.active = True
        if self.active and tag == 'tr':
            self.rows.append([])
        if self.active and tag in ('th', 'td'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.active and tag in ('th', 'td'):
            self.rows[-1].append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'table':
            self.active = False


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
        full['created_at'] = '2030-02-03T04:05:06+00:00'
        full['selection']['unique_representative_source_games_n'] = 3210
        full['counts'].update(checked_n=4345, engine_verified_n=987,
                              survives_candidate_criterion_n=654)
        for side, checked, stable, retained in [('white', 2106, 450, 300), ('black', 2239, 537, 354)]:
            full['groups']['by_side'][side]['outcomes'] = {
                'checked_n': checked, 'engine_verified_n': stable,
                'survives_candidate_criterion_n': retained, 'trainer_ready_n': 0}
        with patch.object(site, 'MINING_V3_FULL_DEEP', full):
            response = self.client.get('/research')
            self.assertEqual(response.status_code, 200)
            page = response.get_data(as_text=True)
        overview = page.split('id="current-status"', 1)[1].split('</section>', 1)[0]
        self.assertIn('654 retained the full selection criterion', overview)
        self.assertIn('need chess review and explanations', overview)
        self.assertNotIn('final results are not yet published here', overview)
        self.assertIn('href="#full-depth-checks"', overview)
        self.assertNotIn('href="#depth-checks"', overview)
        self.assertIn('The full checks are complete.', page)
        byline = page.split('class="research-byline"', 1)[1].split('</p>', 1)[0]
        self.assertIn('datetime="2030-02-03T04:05:06+00:00"', byline)
        self.assertIn('2030-02-03 at 04:05 UTC', byline)
        self.assertNotIn('9 September 2026', byline)
        table = TableRows('full-census-results')
        table.feed(page)
        self.assertEqual(table.rows, [
            ['Side to move', 'Checked', 'Stable acceptable set, no mate scores', 'Stable + selection criterion'],
            ['White', '2,106', '450', '300'],
            ['Black', '2,239', '537', '354'],
            ['All candidates', '4,345', '987', '654']])
        self.assertIn('4,345 positions / 3,210 source games', page)
        self.assertIn('no legal root move had a mate-valued score', page)
        self.assertIn('they have not been added to the trainer', page)
        self.assertIn('Verified full results, source groups and runtime', page)

    def test_incomplete_summary_withholds_full_census_outcomes(self):
        full = copy.deepcopy(site.MINING_V3_FULL_DEEP)
        full['complete'] = False
        # Even populated outcome fields must not be exposed before final validation.
        full['counts'].update(engine_verified_n=987654321, survives_candidate_criterion_n=123456789)
        with patch.object(site, 'MINING_V3_FULL_DEEP', full):
            response = self.client.get('/research')
            self.assertEqual(response.status_code, 200)
            page = response.get_data(as_text=True)
        self.assertIn('The full results have not yet been published.', page)
        self.assertIn('Published run snapshot', page)
        self.assertNotIn('id="full-census-results"', page)
        self.assertNotIn('987,654,321', page)
        self.assertNotIn('123,456,789', page)
        self.assertNotIn('>Full candidate depth checks</a>', page)
        overview = page.split('id="current-status"', 1)[1].split('</section>', 1)[0]
        self.assertIn('href="#depth-checks"', overview)
        byline = page.split('class="research-byline"', 1)[1].split('</p>', 1)[0]
        self.assertNotIn('Results updated', byline)

    def test_missing_optional_full_run_does_not_claim_it_started(self):
        with patch.object(site, 'MINING_V3_FULL_DEEP', None):
            page = self.client.get('/research').get_data(as_text=True)
        overview = page.split('id="current-status"', 1)[1].split('</section>', 1)[0]
        self.assertIn('first 200 candidates', overview)
        self.assertNotIn('has started', overview)
        self.assertNotIn('published snapshot dated', overview)
        self.assertNotIn('id="full-census-results"', page)
        self.assertNotIn('href="#full-depth-checks"', page)

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
