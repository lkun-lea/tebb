import json
import os
import tempfile
import unittest
from unittest.mock import patch
from desk_companion.evaluation.reference_judge import assess


class ReferenceJudgeTests(unittest.TestCase):
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
