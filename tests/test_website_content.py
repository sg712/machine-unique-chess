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

    def followup_fixtures(self):
        """Synthetic aggregates only: no frozen research evidence is modified."""
        context = {
            'status': 'complete', 'controls': {'passed': True},
            'counts': {'selected_n': 6, 'paired_completed_n': 6, 'pending_n': 0, 'failed_n': 0},
            'all_selected': {'n': 6, 'candidate_transitions': {'pass_to_pass': 4, 'pass_to_fail': 2},
                             'by_rating': {'1700': {'top_choice_changed_n': 1},
                                           '2000': {'top_choice_changed_n': 2}}},
            'by_side': {'white': {'n': 3, 'candidate_transitions': {'pass_to_pass': 3}},
                        'black': {'n': 3, 'candidate_transitions': {'pass_to_pass': 1, 'pass_to_fail': 2}}},
            'private_rows': [{'fen': 'PRIVATE_BOARD_MUST_NOT_RENDER'}],
        }
        prospective = {
            'status': 'running_engine', 'selected_n': 9, 'cohort_n': 20,
            'controls': {'passed': True},
            'fingerprints': {'evidence_inventory_sha256': 'a' * 64},
            'by_role': {
                'calibration_development': {
                    'selected_n': 3, 'policy_completed_n': 3, 'verified_calibration_n': 1,
                    'state_counts': {'incomplete_roots': 1, 'complete_stable_numeric': 1, 'unstable_acceptable_set': 1},
                    'root_status_counts': {'complete_numeric': 22, 'pending': 7, 'capped_or_interrupted': 2,
                                           'bound_score': 1, 'engine_error': 1},
                    'calibration': {'fen_only': {'n': 1, 'brier': 0.125, 'log_loss': 0.4567},
                                    'history': {'n': 1, 'brier': 0.0, 'log_loss': 0.0}},
                },
                'calibration_evaluation': {
                    'selected_n': 2, 'policy_completed_n': 1, 'verified_calibration_n': 0,
                    'state_counts': {'incomplete_roots': 1, 'mate_in_legal_root': 1},
                    'root_status_counts': {'complete_numeric': 11, 'pending': 5, 'mate_score': 2},
                    'calibration': {'fen_only': {'n': 0, 'brier': None, 'log_loss': None},
                                    'history': {'n': 0, 'brier': None, 'log_loss': None}},
                },
                'targeted_endgame': {
                    'selected_n': 4, 'policy_completed_n': 4, 'verified_calibration_n': 0,
                    'state_counts': {'approximate_targeted_screen': 3, 'incomplete_roots': 1},
                    'root_status_counts': {'complete_numeric': 33, 'pending': 9},
                },
            },
            'private_rows': [{'source': 'PRIVATE_SOURCE_MUST_NOT_RENDER'}],
        }
        return context, prospective

    def render_followups(self, context, prospective, extension=None):
        with patch.object(site, 'CONTEXT_AUDIT', context), patch.object(site, 'PROSPECTIVE_ANALYSIS', prospective), \
             patch.object(site, 'PROSPECTIVE_EXTENSION', extension):
            response = self.client.get('/research')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def table_rows(self, page, table_id):
        table = TableRows(table_id)
        table.feed(page)
        return table.rows

    def test_complete_context_uses_paired_aggregate_without_exposing_private_rows(self):
        context, prospective = self.followup_fixtures()
        page = self.render_followups(context, prospective)
        self.assertEqual(self.table_rows(page, 'context-audit-results'), [
            ['Side to move', 'Paired positions', 'Criterion retained', 'Criterion lost'],
            ['White', '3', '3', '0'], ['Black', '3', '1', '2']])
        self.assertIn('candidate criterion in <b>4/6</b>', page)
        self.assertIn('first choice changed in 1/6', page)
        self.assertNotIn('PRIVATE_BOARD_MUST_NOT_RENDER', page)
        self.assertNotIn('PRIVATE_SOURCE_MUST_NOT_RENDER', page)
        self.assertLess(page.index('id="full-depth-checks"'), page.index('id="context-checks"'))
        self.assertLess(page.index('id="fresh-data"'), page.index('id="learning"'))
        byline = page.split('class="research-byline"', 1)[1].split('</p>', 1)[0]
        self.assertNotIn('2026-09-29', byline)
        self.assertIn('Full-census snapshot', byline)

    def test_context_withholds_outcomes_when_status_coverage_or_controls_are_incomplete(self):
        context, _ = self.followup_fixtures()
        context['all_selected']['candidate_transitions']['pass_to_pass'] = 987654321
        mutations = [
            ('status', 'running'), ('counts', {'selected_n': 6, 'paired_completed_n': 5, 'pending_n': 1, 'failed_n': 0}),
            ('counts', {'selected_n': 6, 'paired_completed_n': 6, 'pending_n': 0, 'failed_n': 1}),
            ('controls', {'passed': False}), ('controls', {}),
        ]
        for key, value in mutations:
            with self.subTest(field=key, value=value):
                incomplete = copy.deepcopy(context)
                incomplete[key] = value
                page = self.render_followups(incomplete, None)
                self.assertNotIn('id="context-audit-results"', page)
                self.assertNotIn('987654321', page)
                self.assertNotIn('paired context audit is complete', page)

    def test_prospective_coverage_and_scores_keep_role_denominators_and_exclusions(self):
        context, prospective = self.followup_fixtures()
        page = self.render_followups(context, prospective)
        self.assertEqual(self.table_rows(page, 'prospective-coverage'), [
            ['Analysis role', 'Selected', 'Model predictions', 'Verified for calibration'],
            ['Calibration development', '3', '3/3', '1/3'],
            ['Calibration evaluation', '2', '1/2', '0/2'],
            ['Targeted endgames', '4', '4/4', 'Not a calibration sample']])
        self.assertEqual(self.table_rows(page, 'prospective-root-status')[1:], [
            ['Calibration development', '22', '7', '2', '1', '0', '1'],
            ['Calibration evaluation', '11', '5', '0', '0', '2', '0'],
            ['Targeted endgames', '33', '9', '0', '0', '0', '0']])
        self.assertEqual(self.table_rows(page, 'prospective-position-status')[1:], [
            ['Calibration development', '1', '0', '1', '0'],
            ['Calibration evaluation', '1', '1', '0', '0'],
            ['Targeted endgames', '1', '0', '0', '3']])
        self.assertEqual(self.table_rows(page, 'prospective-calibration_development-scores')[1:], [
            ['Current board only', '1/3', '0.1250', '0.4567'],
            ['Real move history', '1/3', '0.0000', '0.0000']])
        self.assertNotIn('id="prospective-calibration_evaluation-scores"', page)
        self.assertIn('Saved model predictions cover 8/9', page)
        self.assertIn('engine analysis is not complete in this snapshot', page)
        self.assertNotIn('planned engine searches are complete', page)

    def test_prospective_completion_requires_finished_searches_coverage_and_controls(self):
        _, prospective = self.followup_fixtures()
        prospective['status'] = 'searches_complete'
        for group in prospective['by_role'].values():
            group['policy_completed_n'] = group['selected_n']
            group['root_status_counts'] = {'complete_numeric': 50}
            group['state_counts'].pop('incomplete_roots', None)
        page = self.render_followups(None, prospective)
        self.assertIn('planned engine searches are complete', page)
        self.assertIn('1/3', page)  # Finishing searches does not make every selected row verified.
        cases = [('pending', 2), ('capped_or_interrupted', 2), ('bound_score', 1), ('engine_error', 1)]
        for field, value in cases:
            with self.subTest(root_status=field):
                incomplete = copy.deepcopy(prospective)
                incomplete['by_role']['calibration_development']['root_status_counts'][field] = value
                page = self.render_followups(None, incomplete)
                self.assertNotIn('planned engine searches are complete', page)
        for missing in ('controls', 'policies'):
            with self.subTest(missing=missing):
                incomplete = copy.deepcopy(prospective)
                if missing == 'controls':
                    incomplete['controls'] = None
                else:
                    incomplete['by_role']['calibration_evaluation']['policy_completed_n'] = 0
                page = self.render_followups(None, incomplete)
                self.assertNotIn('planned engine searches are complete', page)

    def test_followups_allow_missing_optional_aggregates_and_unavailable_scores(self):
        page = self.render_followups(None, None)
        for anchor in ('context-checks', 'fresh-data', 'supplemental-searches'):
            self.assertNotIn('id="' + anchor + '"', page)
            self.assertNotIn('href="#' + anchor + '"', page)
        _, prospective = self.followup_fixtures()
        group = prospective['by_role']['calibration_development']
        group['calibration']['fen_only']['brier'] = None
        del group['calibration']['fen_only']['log_loss']
        page = self.render_followups({'status': 'prepared'}, prospective)
        self.assertEqual(self.table_rows(page, 'prospective-calibration_development-scores')[1],
                         ['Current board only', '1/3', 'Not available', 'Not available'])
        prospective['controls'] = {'passed': False}
        page = self.render_followups(None, prospective)
        self.assertNotIn('id="prospective-calibration_development-scores"', page)

    def extension_fixture(self, baseline):
        extended = copy.deepcopy(baseline['by_role'])
        development = extended['calibration_development']
        development.update(verified_calibration_n=2,
                           state_counts={'complete_stable_numeric': 2, 'unstable_acceptable_set': 1},
                           calibration={'fen_only': {'n': 2, 'brier': 0.321, 'log_loss': 0.5432},
                                        'history': {'n': 2, 'brier': 0.123, 'log_loss': 0.4321}})
        return {'status': 'searches_complete', 'selected_roots_n': 2, 'completed_roots_n': 2,
                'incomplete_roots_n': 0, 'exhausted_roots_n': 0, 'controls': {'passed': True},
                'unresolved_reservations_n': 0,
                'base_fingerprints': {'evidence_content_sha256': baseline['fingerprints']['evidence_inventory_sha256']},
                'protocol': {'per_root_seconds': 120},
                'baseline_by_role': copy.deepcopy(baseline['by_role']), 'supplemented_by_role': extended,
                'private_rows': [{'fen': 'SUPPLEMENT_PRIVATE_BOARD_MUST_NOT_RENDER'}]}

    def test_stopped_baseline_keeps_numeric_mate_and_incomplete_root_denominators(self):
        context, baseline = self.followup_fixtures()
        for status in ('pass_complete_with_incomplete_roots', 'stopped_needs_review'):
            with self.subTest(status=status):
                baseline['status'] = status
                page = self.render_followups(context, baseline)
                section = page.split('id="fresh-data"', 1)[1].split('id="learning"', 1)[0]
                self.assertIn('The original bounded run stopped for review.', section)
                self.assertIn('25 root searches remain incomplete', section)
                self.assertIn('<b>68/93</b>', section)
                self.assertIn('66 exact numeric results', section)
                self.assertIn('2 mate-valued results', section)
                self.assertNotIn('engine analysis is not complete in this snapshot', section)
                self.assertNotIn('planned engine searches are complete', section)
                self.assertEqual(self.table_rows(page, 'prospective-coverage')[1],
                                 ['Calibration development', '3', '3/3', '1/3'])
                self.assertIn('datetime="2026-09-29"', section)

    def test_supplement_compares_development_without_replacing_baseline_or_pooling_roles(self):
        context, baseline = self.followup_fixtures()
        baseline['status'] = 'stopped_needs_review'
        extension = self.extension_fixture(baseline)
        page = self.render_followups(context, baseline, extension)
        self.assertIn('The original bounded run stopped for review.', page)
        self.assertIn('The supplemental searches are complete.', page)
        self.assertEqual(self.table_rows(page, 'prospective-calibration_development-scores')[1:], [
            ['Current board only', '1/3', '0.1250', '0.4567'],
            ['Real move history', '1/3', '0.0000', '0.0000']])
        self.assertEqual(self.table_rows(page, 'prospective-supplement-coverage')[1:], [
            ['Original bounded run', '1/3', '1', '0', '1'],
            ['With supplemental searches', '2/3', '0', '0', '1']])
        self.assertEqual(self.table_rows(page, 'prospective-supplement-scores')[1:], [
            ['Original bounded run', 'Current board only', '1/3', '0.1250', '0.4567'],
            ['Original bounded run', 'Real move history', '1/3', '0.0000', '0.0000'],
            ['With supplemental searches', 'Current board only', '2/3', '0.3210', '0.5432'],
            ['With supplemental searches', 'Real move history', '2/3', '0.1230', '0.4321']])
        self.assertLess(page.index('id="fresh-data"'), page.index('id="supplemental-searches"'))
        self.assertLess(page.index('id="supplemental-searches"'), page.index('id="learning"'))
        self.assertNotIn('SUPPLEMENT_PRIVATE_BOARD_MUST_NOT_RENDER', page)
        self.assertEqual(extension['baseline_by_role'], baseline['by_role'])

    def test_incomplete_or_unverified_supplement_withholds_comparison_results(self):
        _, baseline = self.followup_fixtures()
        extension = self.extension_fixture(baseline)
        cases = [('status', 'prepared'), ('status', 'paused_power'), ('status', 'running_engine'),
                 ('status', 'cap_exhausted'), ('completed_roots_n', 1), ('incomplete_roots_n', 1),
                 ('exhausted_roots_n', 1), ('controls', {'passed': False}), ('controls', None),
                 ('baseline_by_role', {}), ('supplemented_by_role', {}),
                 ('unresolved_reservations_n', 1), ('unresolved_reservations_n', None),
                 ('base_fingerprints', {'evidence_content_sha256': 'b' * 64}),
                 ('base_fingerprints', {}), ('base_fingerprints', None)]
        mutations = [{key: value} for key, value in cases]
        mutations.append({'selected_roots_n': 1, 'completed_roots_n': 1})
        for fields in mutations:
            with self.subTest(fields=fields):
                incomplete = copy.deepcopy(extension)
                incomplete.update(fields)
                page = self.render_followups(None, baseline, incomplete)
                self.assertNotIn('The supplemental searches are complete.', page)
                self.assertNotIn('id="prospective-supplement-scores"', page)
                self.assertNotIn('id="prospective-supplement-coverage"', page)
                self.assertNotIn('0.3210', page)
        for fingerprints in ({}, None, {'evidence_inventory_sha256': 'b' * 64}):
            with self.subTest(baseline_fingerprints=fingerprints):
                other_baseline = copy.deepcopy(baseline)
                other_baseline['fingerprints'] = fingerprints
                page = self.render_followups(None, other_baseline, extension)
                self.assertNotIn('The supplemental searches are complete.', page)
                self.assertNotIn('id="prospective-supplement-scores"', page)
        without_baseline = self.render_followups(None, None, extension)
        self.assertNotIn('The supplemental searches are complete.', without_baseline)
        self.assertNotIn('id="prospective-supplement-scores"', without_baseline)
        prepared = self.render_followups(None, None, {'status': 'prepared'})
        self.assertIn('The supplemental check is not complete in this snapshot.', prepared)
        self.assertNotIn('id="prospective-supplement-scores"', prepared)

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
