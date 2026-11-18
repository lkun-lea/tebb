import json
import os
import tempfile
import unittest
from unittest.mock import patch
from desk_companion.evaluation.reference_judge import assess


class ReferenceJudgeTests(unittest.TestCase):
    def test_review_transport_failure_cannot_pass_expected_unknown(self):
        from desk_companion.evaluation.agent_eval_judge import execute
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder),patch(
                'desk_companion.evaluation.agent_eval_judge.assess',side_effect=TimeoutError('transport failed')):
            result=execute(dict(prompt='x',reference='x',candidate='x',criterion='x',expected=dict(status='unknown')),{},timeout=20)
        self.assertEqual(result['outcome'],'incomplete')
        self.assertFalse(result['evidence']['verified'])
        self.assertTrue(result['task_id'])

    def test_calibration_requires_valid_assessment_even_for_expected_unknown(self):
        from desk_companion.evaluation.agent_eval_judge import verdict
        def assessment(status,**extra):
            return dict(goal_checks=[dict(status=status,checks=[dict(id='criterion',**extra)])])
        for status in ('pass','fail','unknown'):
            self.assertTrue(verdict(assessment(status),status)['verified'])
        wrong=verdict(assessment('pass'),'fail')
        self.assertTrue(wrong['false_accept']);self.assertFalse(wrong['verified'])
        self.assertTrue(verdict(assessment('fail'),'pass')['false_reject'])
        for invalid in (dict(goal_checks=[]),assessment('unknown',protocol_errors=['invalid JSON']),
                        assessment('unknown',invalid_evidence_ids=['missing']),
                        dict(goal_checks=[dict(status='unknown',checks=[dict(id='review_protocol')])])):
            self.assertFalse(verdict(invalid,'unknown')['verified'])

    def test_existing_reviewer_calibrated_positive_negative_and_invalid_evidence(self):
        spec=dict(prompt='Explain the given constant.',expected='Seven.',rubric=[dict(id='meaning',criterion='Must explain seven.',weight=2)])
        class Model:
            def __init__(self,*a,**kw):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def chat(self,messages,**kw):
                packet=json.loads(messages[1]['content'])['materials']
                return dict(message=dict(content=json.dumps(dict(requirements=[dict(requirement='meaning',dimension='task_acceptance',
                    status=status,reason='Controlled calibration sample.',evidence=['missing']if invalid else[packet[0]['excerpts'][0]['id']])]))))
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder),patch('desk_companion.pi_runtime.inference.PiInference',Model):
            for status,invalid,expected in [('supported',False,True),('contradicted',False,False),('supported',True,None),('unverified',False,None)]:
                result=assess(spec,'Seven.',dict(id='calibration',model='calibration'))
                self.assertIs(result['goal_checks'][0]['passed'],expected)
                self.assertTrue(result['prompt_version'])
