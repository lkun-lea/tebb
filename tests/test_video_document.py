import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from desk_companion.content.video import sources as video
from desk_companion.content.video.document import render_note, embed_video, separate_diagrams, embed_diagrams
from tests.test_video import SOURCE, URL


class PresentationTests(unittest.TestCase):
    def test_video_references_become_labels_and_external_sources_remain_links(self):
        note = f'[00:30]({URL}&t=30) [原视频]({URL}) [规范](https://example.org/spec)'
        result, count = render_note(SOURCE, note)
        self.assertEqual(result, '00:30 原视频 [规范](https://example.org/spec)')
        self.assertEqual(count, 0)

    def test_one_flowchart_becomes_native_whiteboard_and_xml_is_escaped(self):
        note = '```mermaid\nflowchart LR\n A[信息] --> B[模型]\n```'
        result, count = render_note(SOURCE, note + '\n\n' + note)
        self.assertEqual(count, 1)
        self.assertIn('<whiteboard type="mermaid">flowchart LR', result)
        self.assertIn('--&gt;', result)
        self.assertEqual(result.count('<whiteboard'), 1)
        bad = '```mermaid\nflowchart LR\nclick A "https://example.org"\n```'
        self.assertEqual(render_note(SOURCE, bad), (bad, 0))

    def test_embed_uses_native_iframe_and_idempotent_request_then_verifies(self):
        source = {**SOURCE, 'url': 'https://www.bilibili.com/video/BV1ojfDBSEPv?p=2'}
        component = {'iframe_type': 1, 'url': ''}
        calls = []
        def cli(cfg, args, **kwargs):
            calls.append((args, kwargs))
            if args[1] == 'POST':
                payload = json.loads(kwargs['stdin'])
                self.assertEqual(payload['index'], 1)
                self.assertEqual(payload['children'][1]['block_type'], 26)
                component.update(payload['children'][1]['iframe']['component'])
                self.assertEqual(unquote(component['url']), source['url'])
                return {'children': [{'block_type': 26, 'block_id': 'embed'}]}
            return {'block': {'iframe': {'component': component}}}
        with patch('desk_companion.integrations.feishu.wiki_connection.cli', side_effect=cli):
            self.assertEqual(embed_video({}, 'doc123', source), 'embed')
            embed_video({}, 'doc123', source)
        self.assertEqual(calls[0][0], calls[2][0])
        with patch('desk_companion.integrations.feishu.wiki_connection.cli') as tool:
            with self.assertRaises(ValueError): embed_video({}, '../foreign', source)
            tool.assert_not_called()

    def test_embed_failure_preserves_saved_receipt_and_does_not_create_twice(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DESK_COMPANION_DATA_DIR': root}), \
                patch.object(video, 'extract', return_value=dict(SOURCE)):
            source = video.read_video('note', URL)
            with patch('desk_companion.integrations.feishu.feishu_auth.create_markdown_doc', return_value={'url': 'https://example.feishu.cn/docx/doc', 'document_id': 'doc'} ) as create, \
                    patch('desk_companion.content.video.document.embed_video', side_effect=RuntimeError('secret')) as embed:
                first = video.export_summary('note', source['source_id'], '简洁笔记')
                again = video.export_summary('note', source['source_id'], '简洁笔记')
            self.assertTrue(first['ok'] and again['already_saved'])
            self.assertEqual(create.call_count, 1)
            self.assertEqual(embed.call_count, 1)
            self.assertNotIn('secret', str(first))
            self.assertTrue(first['presentation_warnings'])
            receipt = next(iter(video.get_source('note', source['source_id'])['exports'].values()))
            self.assertEqual(receipt['state'], 'saved')
            self.assertEqual(receipt['embed_state'], 'unknown')

    def test_saved_receipt_exists_before_embed_and_success_clears_warning(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DESK_COMPANION_DATA_DIR': root}), \
                patch.object(video, 'extract', return_value=dict(SOURCE)):
            source = video.read_video('note', URL)
            def embedded(cfg, document_id, value):
                receipt = next(iter(video.get_source('note', source['source_id'])['exports'].values()))
                self.assertEqual(receipt['state'], 'saved')
                self.assertEqual(receipt['embed_state'], 'pending')
                return 'embed'
            with patch('desk_companion.integrations.feishu.feishu_auth.create_markdown_doc', return_value={'url': 'saved', 'document_id': 'doc'}), \
                    patch('desk_companion.content.video.document.embed_video', side_effect=embedded):
                result = video.export_summary('note', source['source_id'], '笔记')
            self.assertEqual(result['presentation_warnings'], [])

    def test_markdown_import_and_native_diagram_write_are_separate(self):
        note = '机制\n\n```mermaid\nflowchart LR\n A[用户] --> B[模型]\n```'
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DESK_COMPANION_DATA_DIR': root}), \
                patch.object(video, 'extract', return_value=dict(SOURCE)):
            source = video.read_video('note', URL)
            calls = []
            def cli(cfg, args, **kwargs):
                calls.append((args, kwargs))
                self.assertIn('<whiteboard type="mermaid">', kwargs['stdin'])
                return {'result': 'success', 'warnings': [], 'document': {'new_blocks': [
                    {'block_type': 'whiteboard', 'block_id': 'boardBlock', 'block_token': 'boardToken'}]}}
            with patch('desk_companion.integrations.feishu.feishu_auth.create_markdown_doc', return_value={'url': 'saved', 'document_id': 'doc'}) as create, \
                    patch('desk_companion.integrations.feishu.wiki_connection.cli', side_effect=cli), \
                    patch('desk_companion.content.video.document.embed_video', return_value='embed'):
                video.export_summary('note', source['source_id'], note)
            self.assertNotIn('<whiteboard', create.call_args.args[1])
            self.assertEqual(len(calls), 1)
            receipt = next(iter(video.get_source('note', source['source_id'])['exports'].values()))
            self.assertEqual(receipt['diagram_state'], 'saved')
            self.assertEqual(receipt['diagram_count'], 1)
            self.assertEqual(receipt['presentation_warnings'], [])

    def test_diagram_failure_does_not_duplicate_doc_or_hide_warning(self):
        note = '```mermaid\nflowchart LR\n A --> B\n```'
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DESK_COMPANION_DATA_DIR': root}), \
                patch.object(video, 'extract', return_value=dict(SOURCE)):
            source = video.read_video('note', URL)
            with patch('desk_companion.integrations.feishu.feishu_auth.create_markdown_doc', return_value={'url': 'saved', 'document_id': 'doc'}) as create, \
                    patch('desk_companion.content.video.document.embed_diagrams', side_effect=RuntimeError('secret')) as board, \
                    patch('desk_companion.content.video.document.embed_video', return_value='embed'):
                result = video.export_summary('note', source['source_id'], note)
                video.export_summary('note', source['source_id'], note)
            self.assertEqual(create.call_count, 1)
            self.assertEqual(board.call_count, 1)
            self.assertNotIn('secret', str(result))
            receipt = next(iter(video.get_source('note', source['source_id'])['exports'].values()))
            self.assertEqual(receipt['diagram_count'], 0)
            self.assertEqual(receipt['diagram_state'], 'unknown')
            self.assertEqual(receipt['embed_state'], 'saved')
            self.assertTrue(result['presentation_warnings'])

    def test_native_diagram_requires_confirmed_board_block(self):
        text, diagrams = separate_diagrams(render_note(SOURCE, '文字\n```mermaid\nflowchart LR\n A --> B\n```')[0])
        self.assertEqual(text, '文字')
        with patch('desk_companion.integrations.feishu.wiki_connection.cli', return_value={'result': 'success', 'document': {'new_blocks': []}}):
            with self.assertRaises(RuntimeError): embed_diagrams({}, 'doc', diagrams)


if __name__ == '__main__':
    unittest.main()
