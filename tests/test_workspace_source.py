import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_companion import project_workspace, workspace_source


class SourceToolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.enterContext(patch.dict(os.environ, DESK_COMPANION_DATA_DIR=tmp.name))
        self.main = Path(tmp.name)/'project'
        self.ref = Path(tmp.name)/'reference'
        self.main.mkdir()
        self.ref.mkdir()
        self.config = project_workspace.save(str(self.main),[str(self.ref)],True)['workspace']
        self.file = self.main/'mod.py'
        self.raw = b'class Box:\r\n    @staticmethod\r\n    async def value():\r\n        return 1\r\n# after\r\n'
        self.file.write_bytes(self.raw)

    def test_search_slice_patch_round_trip_and_stale(self):
        hits = workspace_source.search('main','','value','symbol',config=self.config)
        self.assertEqual(hits,dict(ok=True,matches=[dict(path='mod.py',symbol='Box.value',start_line=2,end_line=4)],hit_count=1,limited=False))
        read = workspace_source.read_symbol('main','mod.py','Box.value',config=self.config)
        with self.assertRaisesRegex(ValueError,r'Box\.value \(2–4\)'):
            workspace_source.read_symbol('main','mod.py','Box.val',config=self.config)
        hit = hits['matches'][0]
        self.assertEqual(workspace_source.read_symbol('main',hit['path'],start_line=hit['start_line'],
                         end_line=hit['end_line'],config=self.config)['text'],read['text'])
        self.assertTrue(read['text'].startswith('    @staticmethod\r\n'))
        self.assertNotIn('# after',read['text'])
        exact=workspace_source.search('main','mod.py','value','symbol',config=self.config)
        self.assertEqual(exact['text'],read['text'])
        self.assertEqual(exact['revision'],read['revision'])
        receipt = workspace_source.patch('mod.py',exact['text'],exact['text'].replace('return 1','return 2'),exact['revision'],config=self.config)
        self.assertIn('+        return 2',receipt['diff'])
        self.assertEqual(self.file.read_bytes(),self.raw.replace(b'return 1',b'return 2'))
        with self.assertRaisesRegex(ValueError,'版本'):
            workspace_source.patch('mod.py','return 2','return 3',read['revision'],config=self.config)

    def test_filter_paths_and_readonly_grants(self):
        (self.main/'.env.py').write_bytes(self.raw)
        os.link(self.file,self.main/'hard.py')
        self.assertEqual(workspace_source.search('main','','Box','symbol',config=self.config)['matches'],[])
        (self.ref/'ref.ts').write_text('let value = 1','utf-8')
        self.assertEqual(workspace_source.search('ref-0','','value','text',config=self.config)['matches'][0]['path'],'ref.ts')
        with self.assertRaises(ValueError):
            workspace_source.read_symbol('main','../reference/ref.ts',start_line=1,config=self.config)
        with self.assertRaises(ValueError):
            workspace_source.patch('mod.py','1','2','new',config=self.config)

    def test_exact_preview_uses_the_same_paging_as_a_symbol_read(self):
        self.file.write_text('def long_body():\n'+'    pass\n'*130,'utf-8')
        exact=workspace_source.search('main','mod.py','long_body','symbol',config=self.config)
        page=workspace_source.read_symbol('main','mod.py','long_body',config=self.config)
        self.assertEqual(exact['text'],page['text'])
        self.assertEqual((exact['end_line'],exact['next_line']),(120,121))

    def test_pages_ambiguous_names_and_ambiguous_edits(self):
        self.file.write_text('class A:\n    def get(self): pass\nclass B:\n    def get(self): pass\n'+'# n\n'*130,'utf-8')
        for query,count in [('get',2),('ge',2),('missing',0),('A',2)]:
            result=workspace_source.search('main','mod.py',query,'symbol',config=self.config)
            self.assertEqual(result['hit_count'],count)
            self.assertNotIn('text',result)
        with self.assertRaisesRegex(ValueError,r'A\.get \(2–2\).*B\.get \(4–4\)'):
            workspace_source.read_symbol('main','mod.py','get',config=self.config)
        page = workspace_source.read_symbol('main','mod.py',start_line=1,config=self.config)
        self.assertEqual(page['next_line'],121)
        self.assertIsNone(workspace_source.read_symbol('main','mod.py',start_line=121,config=self.config)['next_line'])
        with self.assertRaisesRegex(ValueError,'不唯一'):
            workspace_source.patch('mod.py','pass','raise',page['revision'],config=self.config)
        project_workspace.save(str(self.main),[],False)
        with self.assertRaises(ValueError):
            workspace_source.patch('mod.py','class B','class C',page['revision'],config=self.config)
