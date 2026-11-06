import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desk_companion.evaluation.development_replay import native_replay
from desk_companion.evaluation.development_team import snapshot, register_native


class NativeReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'trial'
        self.folder.mkdir()
        self.result = dict(model='fixture', delivery='failed', elapsed_s=10,
                           runs=[dict(id='root', parent=None, agent='tebb', calls=1, state='failed', error='blocked'),
                                 dict(id='coder', parent='root', agent='coder', calls=2, state='failed', error='no progress'),
                                 dict(id='qa', parent='root', agent='tester', calls=0, state='failed')],
                           checks={'defect': False, 'regression': True})
        self.events = [dict(task=task, kind='llm_start', seconds=i, data={'model':'fixture'})
                       for i, task in enumerate(['owner-task', 'coder-task', 'coder-task'])]

    def write(self):
        (self.folder/'result.json').write_text(json.dumps(self.result), 'utf-8')
        (self.folder/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in self.events), 'utf-8')

    def test_failed_native_trial_reaches_history_without_inventing_verification(self):
        self.events.append(dict(task='coder-task', kind='tool_start', seconds=3,
                                data={'tool':'workspace_search', 'query':'urls', 'secret':'must not expose'}))
        self.write()
        before = (self.folder/'result.json').read_bytes()
        with patch.dict(os.environ, DESK_COMPANION_DATA_DIR=str(Path(self.temp.name)/'profile')):
            ident = register_native(self.folder, 208, 'cold start')
            row = snapshot()['native_trials'][0]
            self.assertEqual(row['id'], ident)
            self.assertEqual(row['issue'], 208)
            self.assertEqual(row['status'], 'failed')
            self.assertNotIn(2, [e['stage'] for e in row['steps']])
            self.assertEqual(row['steps'][0]['stage'], 0)
            self.assertEqual(row['steps'][1]['state'], 'succeeded')
            self.assertEqual(row['steps'][2]['stage'], 1)
            self.assertNotIn('must not expose', json.dumps(row))
            self.assertIsNone(row['input_tokens'])
            self.assertEqual(row['checks'], [{'name':'defect','passed':False},{'name':'regression','passed':True}])
        self.assertEqual(before, (self.folder/'result.json').read_bytes())

    def test_ambiguous_event_identity_remains_unassigned(self):
        self.result['runs'][1]['calls'] = 1
        self.write()
        self.assertTrue(all(s['stage'] is None for s in native_replay(self.folder)['steps'][:3]))

    def test_explicit_task_relation_overrides_call_count_and_unfinished_import_is_rejected(self):
        self.result['runs'][1]['task'] = 'coder-task'
        self.result['runs'][1]['calls'] = 1
        self.write()
        self.assertEqual(native_replay(self.folder)['steps'][2]['stage'], 1)
        self.result['delivery'] = 'running'
        self.write()
        with self.assertRaises(ValueError):
            native_replay(self.folder)
