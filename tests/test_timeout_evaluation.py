import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from desk_companion.observability.stream_progress import StreamProgress,validate
from desk_companion.observability.timeout_diagnostics import diagnose,report
from desk_companion.evaluation.golden_store import GoldenStore
from desk_companion.evaluation.coverage import coverage
from desk_companion.evaluation.quality_gate import gate


class TimeoutEvaluationTests(unittest.TestCase):
    def test_progress_distinguishes_reasoning_active_text_and_idle_without_retaining_text(self):
        now=[0.];clock=lambda:now[0]
        progress=StreamProgress(clock);progress.event('model_request',None);progress.event('http_status',{'status':200})
        now[0]=.1;progress.event('provider_frame',{})
        now[0]=1.4;progress.event('thinking_delta','private synthetic reasoning')
        now[0]=1.5;snapshot=progress.snapshot();validate(snapshot)
        row=dict(id='call',state='failed',error_kind='TimeoutError',stream_progress=snapshot)
        self.assertEqual(diagnose(row)['kind'],'reasoning_without_answer')
        self.assertNotIn('private',str(snapshot))
        now[0]=1.6;progress.event('text_delta','answer')
        self.assertEqual(diagnose({**row,'stream_progress':progress.snapshot()})['kind'],'text_unfinished')
        now[0]=4
        self.assertEqual(diagnose({**row,'stream_progress':progress.snapshot()})['kind'],'stream_gap')
        self.assertEqual(diagnose(dict(id='legacy',state='failed',error_kind='TimeoutError'))['kind'],'unknown')
        self.assertEqual(diagnose({**row,'stream_progress':StreamProgress(clock).snapshot()})['kind'],'before_model_send')
        startup_heavy={**snapshot,'elapsed_ms':3200,'first_frame_ms':1900,'last_frame_ms':1900,'last_reasoning_ms':1910}
        self.assertEqual(diagnose({**row,'stream_progress':startup_heavy})['kind'],'stream_gap')
        with self.assertRaises(ValueError):validate({**snapshot,'content':'secret'})
        with self.assertRaises(ValueError):validate({**snapshot,'frames':True})
        for malformed in ({'choices':None},{'choices':[{'delta':[]}]},{'choices':[{'delta':{'tool_calls':[{'function':None}]}}]}):
            progress.event('provider_frame',malformed)

    def test_coverage_separates_catalog_from_real_results_and_exposes_entry_gaps(self):
        with tempfile.TemporaryDirectory()as folder:
            cases=GoldenStore(Path(folder)/'memory/eval.sqlite3').cases()
        value=coverage(cases)
        self.assertEqual(value['canonical_cases'],65)
        self.assertEqual(value['splits'],dict(regression=61,holdout=4))
        self.assertEqual(len(value['suites']['timeout']),7)
        self.assertTrue(all(not a['missing']for a in value['areas']))
        self.assertFalse(value['unmapped_cases'])
        self.assertFalse(value['complete']);self.assertTrue(value['uncovered_entries'])
        self.assertTrue(all(c['live']is None for a in value['areas']for c in a['cases']))

    def test_gate_requires_same_standards_real_timeout_evidence_and_independent_holdout(self):
        base=dict(id='before',state='completed',case_manifest_hash='same',judge_contract='fixed',timeout=90,mode='fixture',code_version='code',model_config={'id':'fixed'},
            planned=[dict(case_id='a',sample=1)],cases=[dict(id='a',split='regression')],results=[dict(case_id='a',sample=1,outcome='incomplete',model_observations=[dict(id='call',state='failed',error_kind='TimeoutError')])])
        base['results'][0].update(call_ids=['original'],call_evidence_complete=True,model_observations_complete=True)
        candidate={**base,'id':'after','review_effort':'low','results':[dict(case_id='a',sample=1,outcome='success',call_ids=['candidate'],call_evidence_complete=True,model_observations_complete=True)]}
        self.assertFalse(gate(base,candidate)['ready_for_review'])
        held={**candidate,'id':'held','cases':[dict(id='new',split='holdout')],'planned':[dict(case_id='new',sample=1)],'results':[{**candidate['results'][0],'case_id':'new'}]}
        self.assertTrue(gate(base,candidate,held)['ready_for_review'])
        self.assertFalse(gate(base,candidate,{**held,'review_effort':'provider_default'})['ready_for_review'])
        self.assertFalse(gate(base,candidate,{**held,'tool_loading':'different'})['ready_for_review'])
        self.assertFalse(gate(base,candidate,{**held,'judge_limits':{'max_calls':99}})['ready_for_review'])
        self.assertFalse(gate(base,{**candidate,'results':[{**candidate['results'][0],'model_observations_complete':False}]},held)['ready_for_review'])
        with self.assertRaises(ValueError):gate(base,{**candidate,'judge_contract':'changed'},held)

    def test_new_public_operations_and_live_fault_injection_rejection(self):
        from desk_companion.evaluation.evaluation_center import EvaluationCenter
        from desk_companion.evaluation.artifacts import attempt_profile
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder):
            self.assertEqual(attempt_profile(folder),Path(folder)/'p')
            legacy=Path(folder)/'private-profile';legacy.mkdir()
            self.assertEqual(attempt_profile(folder),legacy)
            (Path(folder)/'p').mkdir()
            self.assertEqual(attempt_profile(folder),Path(folder)/'p')
            center=EvaluationCenter();value=center.operate('coverage')
            with self.assertRaises(ValueError):center.start('live-fault-denied',value['suites']['timeout'],mode='live',live_authorized=True)
