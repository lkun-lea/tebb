"""The shared eval must verify real graph artifacts over authenticated worker RPC."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class WorkflowAuthoringEvaluationTests(unittest.TestCase):
    def test_cli_checks_saved_capability_graph_and_complete_cleanup(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);output=folder/'result'
            env={**os.environ,'PYTHONUTF8':'1','DESK_COMPANION_DATA_DIR':str(folder/'bootstrap')}
            result=subprocess.run([sys.executable,str(root/'scripts/eval_agent.py'),'--case','workflow_authoring','--limit','1','--samples','1','--timeout','120','--output',str(output)],cwd=root,env=env,capture_output=True)
            report=json.loads((output/'report.json').read_text('utf-8'))
            self.assertEqual(result.returncode,0,report['cases'])
            self.assertEqual(report['summary']['success'],1)
            self.assertLessEqual(report['totals']['model_calls'],8)
            case=report['cases'][0];self.assertEqual(case['outcome'],'success')
            proof=case['evidence']['verification']
            self.assertTrue(proof['layout_and_reference_verified']);self.assertTrue(proof['draft_only'])
            self.assertTrue(proof['authenticated_parent_stopped']);self.assertEqual(len(case['artifacts']),2)
            for key in ('model_credential_removed','network_policy_removed','observed_workers_exited','call_evidence_complete'):self.assertTrue(report['cleanup'][key],key)
