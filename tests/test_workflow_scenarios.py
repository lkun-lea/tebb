import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import verify_workflow_scenarios as scenarios
from desk_companion.workflow_templates import templates


class ScenarioAcceptanceTests(unittest.TestCase):
    def test_scenarios_copy_the_example_and_use_only_explicit_targets(self):
        examples=templates();before=json.dumps(examples,sort_keys=True)
        graph=scenarios.scenario(examples,'feishu-base',dict(base_token='test-base',table_id='test-table',key_field='验收编号',content_field='正文'), '')['graph']
        self.assertEqual(graph['nodes'][0]['config']['text'],scenarios.TEXT)
        self.assertEqual(graph['nodes'][-1]['config']['fields'],dict(正文='{{trigger.text}}'))
        self.assertEqual(json.dumps(examples,sort_keys=True),before)
        with self.assertRaises(KeyError):scenarios.scenario(examples,'feishu-message',{},'')
        with self.assertRaises(ValueError):scenarios.scenario(examples,'video-notes',{},'')

    def test_news_requires_five_unique_rows_bound_to_actual_sources(self):
        candidates=[dict(id=str(i),url='https://example.com/'+str(i)) for i in range(5)]
        receipts=dict(sources=dict(state='confirmed',output=dict(candidates=candidates)),report=dict(state='confirmed',output=dict(text='实际报告',report=dict(items=candidates.copy()))))
        self.assertTrue(all(scenarios.verify_outputs('tech-news',dict(receipts=receipts)).values()))
        receipts['report']['output']['report']['items']=[candidates[0]]*5
        self.assertFalse(scenarios.verify_outputs('tech-news',dict(receipts=receipts))['five_unique_sources'])
        receipts['report']['output']['report']['items']=[dict(id=str(i),url='https://unrelated.test') for i in range(5)]
        self.assertFalse(scenarios.verify_outputs('tech-news',dict(receipts=receipts))['actual_source_binding'])

    def test_video_does_not_pass_empty_subtitles_or_undisclosed_partial_coverage(self):
        receipts=dict(video=dict(state='confirmed',output=dict(text='',complete=False)),note=dict(state='confirmed',output=dict(text='00:01 学习笔记')))
        proof=scenarios.verify_outputs('video-notes',dict(receipts=receipts))
        self.assertFalse(proof['actual_subtitles']);self.assertFalse(proof['coverage_disclosed'])
        receipts['video']['output']['text']='[0:01] 实际字幕'
        receipts['note']['output']['text']='00:01 仅依据部分字幕的笔记，存在覆盖缺口'
        self.assertTrue(all(scenarios.verify_outputs('video-notes',dict(receipts=receipts)).values()))

    def test_bootstrap_failure_removes_credentials_and_restores_original_profile(self):
        from tests.test_collaboration import MODEL
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);original=root/'source';original.mkdir();output=root/'case'
            (original/'model-network.json').write_text('{}','utf-8')
            args=['verify','--live','--case','tech-news','--output',str(output)]
            with patch.dict(os.environ,DESK_COMPANION_DATA_DIR=str(original)),patch('sys.argv',args),patch('desk_companion.model_catalog.require_active',return_value=MODEL),patch.object(scenarios.subprocess,'check_output',return_value=b'0'*40),patch.object(scenarios.subprocess,'Popen',side_effect=RuntimeError('start failed')):
                with self.assertRaisesRegex(RuntimeError,'start failed'):scenarios.main()
                self.assertEqual(os.environ['DESK_COMPANION_DATA_DIR'],str(original))
            report=json.loads((output/'report.json').read_text('utf-8'))
            self.assertTrue(report['cleanup']['credentials_removed']);self.assertFalse((output/'private-profile/models.json').exists())
            self.assertTrue((original/'model-network.json').exists())

    def test_partial_configuration_copy_failure_does_not_leave_credentials(self):
        from tests.test_collaboration import MODEL
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir();output=root/'case'
            (source/'model-network.json').write_text('{}','utf-8')
            def fail_copy(_source,target):target.write_text('partial-private-setting','utf-8');raise OSError('copy interrupted')
            with patch.dict(os.environ,DESK_COMPANION_DATA_DIR=str(source)),patch('sys.argv',['verify','--live','--case','tech-news','--output',str(output)]),patch('desk_companion.model_catalog.require_active',return_value=MODEL),patch.object(scenarios.subprocess,'check_output',return_value=b'0'*40),patch.object(scenarios.shutil,'copyfile',side_effect=fail_copy):
                with self.assertRaisesRegex(OSError,'copy interrupted'):scenarios.main()
            self.assertFalse((output/'private-profile/models.json').exists());self.assertFalse((output/'private-profile/model-network.json').exists())
