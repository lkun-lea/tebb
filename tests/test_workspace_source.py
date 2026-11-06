import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_companion.projects import project_workspace
from desk_companion.projects import workspace_source


class SourceToolTests(unittest.TestCase):
    def test_search_reports_unsearched_and_skipped_scope_and_can_be_narrowed(self):
        for i in range(40):(self.main/f'f{i:02}.txt.md').write_text('needle\n','utf-8')
        (self.main/'bad.py').write_bytes(b'\xffbad encoding')
        found=workspace_source.search('main','','needle','text',config=self.config)
        self.assertTrue(found['limited'])
        self.assertIn('result_limit',found['coverage']['stop_reasons'])
        self.assertEqual(found['coverage']['skipped']['encoding'],1)
        self.assertFalse(found['coverage']['complete'])
        narrowed=workspace_source.search('main','f39.txt.md','needle','text',config=self.config)
        self.assertFalse(narrowed['limited']);self.assertTrue(narrowed['coverage']['complete'])
        self.assertEqual(narrowed['matches'][0]['path'],'f39.txt.md')

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
        self.assertEqual({k:v for k,v in hits.items()if k!='coverage'},dict(ok=True,matches=[dict(path='mod.py',symbol='Box.value',start_line=2,end_line=4)],hit_count=1,limited=False))
        self.assertTrue(hits['coverage']['complete'])
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

    def test_patch_retries_only_unique_uniform_newline_mismatch(self):
        def apply(raw,old,new,revision=None):
            self.file.write_bytes(raw)
            rev=revision or project_workspace.read('main','mod.py',config=self.config)['revision']
            return workspace_source.patch('mod.py',old,new,rev,config=self.config)
        for target,supplied in [('\r\n','\n'),('\n','\r\n'),('\r','\n')]:
            raw=target.join(['# 前','first','second','# 后','']).encode()
            apply(raw,'first'+supplied+'second','one'+supplied+'two')
            self.assertEqual(self.file.read_bytes(),raw.replace(b'first',b'one').replace(b'second',b'two'))
        for raw,old,new,rev in [
                (b'a\r\nb\r\na\r\nb','a\nb','x',None),
                (b'a\r\nb\nc','a\nb','x',None),
                (b'a\r\nb','a\nb','x\ny\r\nz',None),
                (b'a\r\nb','a\nb','x','stale')]:
            with self.assertRaises(ValueError):apply(raw,old,new,rev)
            self.assertEqual(self.file.read_bytes(),raw)
        apply(b'a\r\nb\nc','a\r\nb','x')
        self.assertEqual(self.file.read_bytes(),b'x\nc')

    def test_exact_preview_uses_the_same_paging_as_a_symbol_read(self):
        self.file.write_text('def long_body():\n'+'    pass\n'*130,'utf-8')
        exact=workspace_source.search('main','mod.py','long_body','symbol',config=self.config)
        page=workspace_source.read_symbol('main','mod.py','long_body',config=self.config)
        self.assertEqual(exact['text'],page['text'])
        self.assertEqual((exact['end_line'],exact['next_line']),(120,121))

    def test_scoped_edits_report_recoverable_errors_and_preserve_other_bytes(self):
        raw = b'class A:\r\n def f(self):\r\n  return 1\r\nclass B:\r\n def f(self):\r\n  x="aaa"\r\n  return 1\r\n'
        self.file.write_bytes(raw)
        page = workspace_source.read_symbol('main','mod.py','B.f',config=self.config)
        self.assertEqual(page['symbol'],'B.f')
        self.assertEqual(workspace_source.search('main','mod.py','B.f','symbol',config=self.config)['symbol'],'B.f')
        def edit(old,new):
            return workspace_source.patch('mod.py',old,new,page['revision'],symbol=page['symbol'],config=self.config)
        with self.assertRaisesRegex(ValueError,r'old_ambiguous.*2 处.*L6:.*L6:'):
            edit('aa','b')
        with self.assertRaisesRegex(ValueError,r'old_not_found.*L7 +return 1'):
            edit('return 2','return 3')
        with self.assertRaisesRegex(ValueError,'old_not_found'):
            edit('class A','class C')
        self.assertEqual(self.file.read_bytes(),raw)
        edit('  x="aaa"\n  return 1','  return 2')
        self.assertEqual(self.file.read_bytes(),raw.replace(b'  x="aaa"\r\n  return 1',b'  return 2'))
        with self.assertRaisesRegex(ValueError,'stale_revision'):
            edit('return 2','return 3')

    def test_text_search_keeps_line_matches_and_only_previews_unique_identifiers(self):
        self.file.write_bytes(b'def urls(): return 1\nlink=urls()\n')
        def search(query='urls',path='mod.py'):
            return workspace_source.search('main',path,query,'text',config=self.config)
        found=search()
        self.assertEqual(found['matches'],search(path='')['matches'])
        self.assertEqual(found['hit_count'],2)
        self.assertEqual(found['text'],'def urls(): return 1\n')
        self.assertNotIn('revision',search('urls()'))
        self.assertNotIn('revision',search(path=''))
        self.file.write_text('class A:\n def urls(self): pass\nclass B:\n def urls(self): pass\n','utf-8')
        self.assertNotIn('revision',search())
        self.file.write_text('def urls(:\n','utf-8')
        broken=search()
        self.assertEqual(broken['hit_count'],1)
        self.assertNotIn('revision',broken)

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
