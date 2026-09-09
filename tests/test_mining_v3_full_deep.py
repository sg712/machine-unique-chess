"""Checkpoint and reuse contracts; all engine responses are synthetic."""
import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import chess
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mining_v3_full_deep as full
from test_mining_v3_deep import fixture


def write_rows(path, records):
    path.write_text(''.join(json.dumps(r,separators=(',', ':'))+'\n' for r in records))


class FakeEngine:
    def __init__(self): self.closed=False; self.options=[]
    def configure(self, options): self.options.append(options)
    def close(self): self.closed=True


class CensusFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name)
        old=self.directory/'old';old.mkdir();current=self.directory/'census';current.mkdir()
        self.args=SimpleNamespace(input=current/'positions.jsonl',policies=current/'policies.jsonl',
            selection_manifest=current/'selection_manifest.json',run_dir=self.directory/'run',
            reuse_run_dir=old,reuse_input=old/'input.jsonl',reuse_policies=old/'policies.jsonl',
            reuse_selection_manifest=old/'selection.json',reuse_public_summary=old/'public.json',
            engine=self.directory/'engine',workers=1,repair_partial=False,discard_uncommitted=False)
        self.args.engine.write_bytes(b'synthetic engine identity')
        self.white,self.wp,self.wroots,_=fixture(chess.WHITE);self.black,self.bp,self.broots,_=fixture(chess.BLACK)
        # This full census deliberately admits the same source game and public/BOT material.
        self.black.update(game_id=self.white['game_id'],contains_bot=True,history_available=False,
                          known_public_game=True,analysis_role='public_exposed')
        self.bp['history_available']=False
        self.records=[self.white,self.black];self.policies=[self.wp,self.bp]
        write_rows(self.args.reuse_input,[self.white]);write_rows(self.args.reuse_policies,[self.wp])
        write_rows(old/'roots.jsonl',self.wroots)
        write_rows(old/'positions.jsonl',[full.original.summarize_position(self.white,self.wp,self.wroots)])
        sel={'complete':True,'selected_n':1,'selected_ids':[self.white['id']],
             'positions_sha256':full.digest(self.args.reuse_input),'policies_sha256':full.digest(self.args.reuse_policies)}
        self.args.reuse_selection_manifest.write_text(json.dumps(sel))
        fingerprints=full.scoring_fingerprints(self.args.engine)
        settings={**full.SCORE_SETTINGS,'python_chess_version':chess.__version__,
                  'runner_sha256':fingerprints['original_runner_sha256'],
                  **{k:fingerprints[k] for k in ['engine_sha256','search_and_metrics_sha256','canonicalization_sha256','io_sha256']},
                  'input_sha256':full.digest(self.args.reuse_input),'policy_sha256':full.digest(self.args.reuse_policies),
                  'selection_manifest_sha256':full.digest(self.args.reuse_selection_manifest)}
        oldrun={'complete':True,'settings':settings,'input_n':1,'completed_positions_n':1,
                'root_searches_n':len(self.wroots),'completed_root_searches_n':len(self.wroots),
                'roots_sha256':full.digest(old/'roots.jsonl'),'positions_sha256':full.digest(old/'positions.jsonl'),
                'roots_checkpoint_bytes':(old/'roots.jsonl').stat().st_size,'roots_checkpoint_sha256':full.digest(old/'roots.jsonl')}
        (old/'run.json').write_text(json.dumps(oldrun))
        self.args.reuse_public_summary.write_text(json.dumps({'complete':True,'fingerprints':{
            'run_manifest_sha256':full.digest(old/'run.json'),'roots_sha256':oldrun['roots_sha256'],'positions_sha256':oldrun['positions_sha256']}}))
        self.write_census()
        self.calls=[];self.engines=[]

    def write_census(self):
        write_rows(self.args.input,self.records);write_rows(self.args.policies,self.policies)
        legal={r['id']:chess.Board(r['fen']).legal_moves.count() for r in self.records}
        self.manifest={'complete':True,'selected_n':len(self.records),'selected_ids':[r['id'] for r in self.records],
            'positions_sha256':full.digest(self.args.input),'policies_sha256':full.digest(self.args.policies),
            'already_deep200_ids':[self.white['id']],'already_deep200_n':1,'new_n':len(self.records)-1,
            'old200_selection_manifest_sha256':full.digest(self.args.reuse_selection_manifest),
            'strata_by_id':{r['id']:full.classify_strata(r) for r in self.records},
            'legal_roots':{'total':sum(legal.values()),'by_id':legal}}
        self.args.selection_manifest.write_text(json.dumps(self.manifest))

    def engine(self,*args,**kwargs):
        result=FakeEngine();self.engines.append(result);return result

    def search(self,engine,board,depth,seconds,roots=None,**kwargs):
        self.assertFalse(board.move_stack);self.assertIsNone(seconds)
        self.calls.append((board.fen(),depth,roots[0].uci()))
        source=self.broots if board.turn==chess.BLACK else self.wroots
        result=copy.deepcopy(next(r for r in source if r['target_depth']==depth and r['uci']==roots[0].uci()))
        return [result]

    def execute(self,search=None,battery=False):
        with patch.object(full.original.base,'search',side_effect=search or self.search), \
             patch.object(full.chess.engine.SimpleEngine,'popen_uci',side_effect=self.engine), \
             patch.object(full.original,'battery_is_critical',return_value=battery), \
             contextlib.redirect_stdout(io.StringIO()):
            return full.run(self.args)

    def test_imported_evidence_is_reused_verbatim_and_new_strata_are_explicit(self):
        manifest=self.execute();self.assertTrue(manifest['complete'])
        self.assertEqual(len(self.calls),len(self.broots))
        self.assertTrue(all(chess.Board(fen).turn==chess.BLACK for fen,_,_ in self.calls))
        self.assertEqual((self.args.run_dir/'imported_roots.jsonl').read_bytes(),(self.args.reuse_run_dir/'roots.jsonl').read_bytes())
        outputs=[r for r,_,_ in full.strict_rows(self.args.run_dir/'positions.jsonl')]
        self.assertEqual(outputs[0]['evidence_origin'],'imported_deep200')
        self.assertEqual(outputs[0]['new_root_search_seconds_sum'],0)
        self.assertEqual(outputs[1]['strata'],{'bot_status':'bot_tagged','history_status':'unavailable','public_exposure':'known_public','analysis_role':'public_exposed'})
        self.assertEqual(outputs[1]['imported_root_search_seconds_sum'],0)
        self.assertTrue(all(r['trainer_ready'] is False for r in outputs))
        self.assertEqual(manifest['completed_root_searches_n'],len(self.wroots)+len(self.broots))
        self.assertEqual(manifest['completed_new_positions_n'],1)
        self.assertTrue(all(e.closed for e in self.engines))
        self.assertTrue(all(e.options==[{'Threads':1,'Hash':64,'UCI_ShowWDL':True}] for e in self.engines))
        self.assertGreaterEqual(manifest['attempts'][0]['monotonic_elapsed_seconds'],0)
        self.assertEqual(manifest['attempts'][0]['new_root_searches_after'],len(self.broots))

    def test_completed_resume_runs_no_search_and_does_not_append_an_attempt(self):
        first=self.execute();self.calls=[];again=self.execute()
        self.assertEqual(self.calls,[]);self.assertEqual(again,first);self.assertEqual(len(again['attempts']),1)

    def test_resume_after_worker_error_searches_only_missing_anchored_roots(self):
        def failing(*args,**kwargs):
            if len(self.calls)>=4:raise RuntimeError('synthetic interruption')
            return self.search(*args,**kwargs)
        with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):self.execute(failing)
        checkpoint=json.loads((self.args.run_dir/'checkpoint.json').read_text())
        done={r['id'] for r,_,_ in full.strict_rows(self.args.run_dir/'roots.jsonl')}
        self.assertEqual(len(done),checkpoint['root_searches_n']);self.assertGreater(len(done),0)
        self.calls=[];result=self.execute()
        self.assertTrue(result['complete']);self.assertEqual(len(self.calls),len(self.broots)-len(done))
        self.assertEqual(len(result['attempts']),2)
        for _,d,move in self.calls:self.assertNotIn(full.original.task_id(self.black['id'],d,move),done)

    def test_tampered_imported_evidence_fails_before_new_engine_launch(self):
        p=self.args.reuse_run_dir/'roots.jsonl';p.write_bytes(p.read_bytes().replace(b'"cp":0',b'"cp":1',1))
        with self.assertRaisesRegex(ValueError,'hash changed'):self.execute()
        self.assertEqual(self.engines,[])

    def test_tampered_original_outcome_fails_even_after_hashes_are_updated(self):
        p=self.args.reuse_run_dir/'positions.jsonl';values=[r for r,_,_ in full.strict_rows(p)];values[0]['survives']=False;write_rows(p,values)
        mpath=self.args.reuse_run_dir/'run.json';m=json.loads(mpath.read_text());m['positions_sha256']=full.digest(p);mpath.write_text(json.dumps(m))
        public=json.loads(self.args.reuse_public_summary.read_text());public['fingerprints'].update(positions_sha256=m['positions_sha256'],run_manifest_sha256=full.digest(mpath));self.args.reuse_public_summary.write_text(json.dumps(public))
        with self.assertRaisesRegex(ValueError,'outcomes do not match'):self.execute()
        self.assertEqual(self.engines,[])

    def test_source_bytes_and_policy_bytes_must_match_original_exports(self):
        for kind in ['source','policy']:
            with self.subTest(kind=kind):
                path=self.args.input if kind=='source' else self.args.policies
                original=path.read_bytes();path.write_bytes(original.replace(b':',b': ',1))
                key='positions_sha256' if kind=='source' else 'policies_sha256'
                self.manifest[key]=full.digest(path);self.args.selection_manifest.write_text(json.dumps(self.manifest))
                with self.assertRaisesRegex(ValueError,'bytes differ'):self.execute()
                path.write_bytes(original);self.write_census()

    def test_changed_checkpoint_prefix_cannot_be_repaired_or_discarded(self):
        self.execute();p=self.args.run_dir/'roots.jsonl';p.write_bytes(p.read_bytes().replace(b'"cp":0',b'"cp":1',1))
        self.args.repair_partial=True;self.args.discard_uncommitted=True
        with self.assertRaisesRegex(ValueError,'hash changed'):self.execute()

    def test_stratum_mismatch_fails_and_unknown_history_is_supported(self):
        self.black.update(contains_bot=None,history_available=None,known_public_game=None,analysis_role=None)
        self.bp['history_available']=None;self.write_census()
        self.assertEqual(full.load_census(self.args)[4][self.black['id']],{k:'unknown' for k in ['bot_status','history_status','public_exposure','analysis_role']})
        self.manifest['strata_by_id'][self.black['id']]['bot_status']='no_bot';self.args.selection_manifest.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError,'strata'):full.load_census(self.args)

    def test_invalid_or_terminal_board_is_rejected_not_silently_dropped(self):
        self.black['fen']='7k/6Q1/6K1/8/8/8/8/8 b - - 0 1';self.bp['fen']=self.black['fen'];self.write_census()
        with self.assertRaisesRegex(ValueError,'Invalid or terminal'):full.load_census(self.args)

    def test_duplicate_canonical_state_is_rejected(self):
        self.black['fen']=self.white['fen'];self.bp['fen']=self.white['fen'];self.write_census()
        with self.assertRaisesRegex(ValueError,'canonical state'):full.load_census(self.args)

    def test_battery_pause_records_reason_and_resume_clears_it(self):
        with self.assertRaisesRegex(RuntimeError,'battery'):self.execute(battery=True)
        paused=json.loads((self.args.run_dir/'run.json').read_text());self.assertEqual(paused['pause_reason'],'battery');self.assertFalse(paused['complete'])
        self.assertEqual(self.engines,[])
        result=self.execute();self.assertTrue(result['complete']);self.assertNotIn('pause_reason',result)

    def test_concurrent_writer_is_refused(self):
        with full.process_lock(self.args.run_dir):
            with self.assertRaisesRegex(RuntimeError,'Another process'):self.execute()
        self.assertEqual(self.engines,[])

    def test_output_directory_cannot_overwrite_frozen_source_or_original_evidence(self):
        for directory in [self.args.input.parent,self.args.reuse_run_dir]:
            with self.subTest(directory=directory):
                self.args.run_dir=directory
                with self.assertRaisesRegex(ValueError,'overwrite protected'):self.execute()
        self.assertEqual(self.engines,[])

    def test_worker_bounds_cannot_be_saved_as_exact_evidence(self):
        def bounded(*args,**kwargs):
            result=self.search(*args,**kwargs);result[0]['upperbound']=True;return result
        with self.assertRaisesRegex(ValueError,'exact target-depth'):self.execute(bounded)
        self.assertEqual((self.args.run_dir/'roots.jsonl').read_bytes(),b'')


class PrefixBoundaryTests(unittest.TestCase):
    def test_unanchored_complete_rows_need_explicit_discard_and_are_never_reused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roots.jsonl';cp=Path(d)/'checkpoint.json'
            full.load_new_checkpoint(p,cp,'settings')
            p.write_bytes(b'{"id":"uncommitted"}\n')
            with self.assertRaisesRegex(ValueError,'Unanchored'):full.load_new_checkpoint(p,cp,'settings',repair_partial=True)
            checkpoint,_=full.load_new_checkpoint(p,cp,'settings',discard_uncommitted=True)
            self.assertEqual(p.read_bytes(),b'');self.assertEqual(checkpoint['root_searches_n'],0)

    def test_partial_tail_can_be_discarded_without_touching_anchored_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roots.jsonl';cp=Path(d)/'checkpoint.json';prefix=b'{"id":"saved"}\n';p.write_bytes(prefix)
            full.durable_json(cp,{'settings_sha256':'s','bytes':len(prefix),'sha256':hashlib.sha256(prefix).hexdigest(),'root_searches_n':1})
            p.write_bytes(prefix+b'{"id":')
            with self.assertRaisesRegex(ValueError,'Unanchored'):full.load_new_checkpoint(p,cp,'s')
            full.load_new_checkpoint(p,cp,'s',repair_partial=True);self.assertEqual(p.read_bytes(),prefix)
            p.write_bytes(prefix.replace(b'saved',b'other'))
            with self.assertRaisesRegex(ValueError,'prefix hash changed'):full.load_new_checkpoint(p,cp,'s',discard_uncommitted=True)

    def test_missing_checkpoint_never_adopts_existing_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roots.jsonl';p.write_bytes(b'{"id":"unanchored"}\n')
            with self.assertRaisesRegex(ValueError,'without an authenticated'):full.load_new_checkpoint(p,Path(d)/'checkpoint.json','s')


if __name__=='__main__':unittest.main()
