"""One real worker/fixture-model roundtrip, including isolated trial persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class MemoryEvaluationTests(unittest.TestCase):
    def test_cli_uses_product_queues_and_verifies_actual_trial_without_production_mutations(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'report'
            env={**os.environ,'PYTHONUTF8':'1','DESK_COMPANION_DATA_DIR':str(Path(folder)/'bootstrap')}
            result=subprocess.run([sys.executable,str(root/'scripts/eval_agent.py'),'--output',str(output),
                '--case','memory_trial','--limit','1','--samples','1','--timeout','90'],cwd=root,env=env,
                capture_output=True,text=True,encoding='utf-8',timeout=130)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=json.loads((output/'report.json').read_text('utf-8'))
            self.assertEqual(report['summary']['success'],1)
            case=report['cases'][0]
            self.assertEqual(len(case['call_ids']),2)
            self.assertTrue(case['evidence']['verification']['original_memory_unchanged'])
            self.assertTrue(report['cleanup']['observed_workers_exited'])
            self.assertTrue(report['cleanup']['model_credential_removed'])
            self.assertEqual(report['attempts'],1)
