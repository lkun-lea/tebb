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

    def test_code_search_prefers_implementation_and_preserves_doc_scope(self):
        (self.main/'README.md').write_text('while (true) {}\n' * 32, 'utf-8')
        (self.main/'docs').mkdir()
        (self.main/'docs'/'guide.ts').write_text('while (true) {}\n', 'utf-8')
        (self.main/'runtime').mkdir()
        (self.main/'runtime'/'loop.ts').write_text('while (true) {}\n', 'utf-8')
        def search(path):
            return workspace_source.search('main', path, 'while (true)', 'text', config=self.config)
        result = search('')
        self.assertEqual(result['matches'][0]['path'], 'runtime/loop.ts')
        self.assertTrue(result['limited'])
        self.assertEqual(search('README.md')['matches'][0]['path'], 'README.md')
        self.assertEqual(search('docs')['matches'][0]['path'], 'docs/guide.ts')

    def test_missing_field_offers_local_lines_without_claiming_a_match(self):
        (self.main/'loop.ts').write_text('// steering input\nawait config.getSteeringMessages();\n', 'utf-8')
        result = workspace_source.search('main', 'loop.ts', 'steeringQueue', 'text', config=self.config)
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['hit_count'], 0)
        self.assertEqual(result['related_lines'], [dict(path='loop.ts', start_line=2,
                                                     text='await config.getSteeringMessages();')])
        (self.main/'wrapper.ts').write_text('/** Owns state. */\nexport class Wrapper {}', 'utf-8')
        hits = workspace_source.search('main', 'wrapper.ts', 'Wrapper', 'symbol', config=self.config)
        view = workspace_source.overview_receipt('workspace_search', {}, hits, set())
        self.assertEqual(view['matches'][0]['declaration_doc']['citation'], 'wrapper.ts:L1-L1')
        self.assertIn('text', hits['matches'][0]['declaration_doc'])

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

    def test_source_windows_reach_eof_and_keep_navigation(self):
        lines = ['// package'] * 42 + ['// Drain pending work', 'while (active) {', '  break;', '}']
        (self.main/'run.ts').write_text('\n'.join(lines), 'utf-8')
        page = workspace_source.read_symbol('main', 'run.ts', start_line=1, end_line=120, config=self.config)
        self.assertEqual(page['end_line'], len(lines))
        preview = workspace_source.excerpt_for_question(page)
        self.assertEqual(preview['next_line'], 41)
        self.assertEqual(preview['locations'], [dict(line=44, text='while (active) {', comment=lines[42])])
        with self.assertRaises(ValueError):
            workspace_source.read_symbol('main', 'run.ts', start_line=47, config=self.config)
        from desk_companion.projects.workspace_feedback import read_error
        with self.assertRaises(ValueError) as exc:
            project_workspace.resolve('project', '', self.config)
        self.assertEqual(read_error(exc.exception)['reason'], 'invalid_root')

    def test_distant_loop_exit_preserves_line_numbers(self):
        lines = ['while (running) {'] + ['    process();'] * 52 + ['    break;', '}']
        (self.main/'loop.js').write_text('\n'.join(lines), 'utf-8')
        page = workspace_source.read_symbol('main', 'loop.js', start_line=1, end_line=100, config=self.config)
        preview = workspace_source.excerpt_for_question(page)
        tail = preview['closing_excerpt']
        self.assertGreater(tail['start_line'], preview['end_line'])
        self.assertEqual(tail['text'].splitlines(), lines[tail['start_line']-1:tail['end_line']])
        nearby = workspace_source.read_symbol('main', 'loop.js', start_line=1, end_line=45, config=self.config)
        self.assertEqual(nearby['end_line'], 45)
        self.assertEqual(nearby['closing_excerpt']['end_line'], len(lines))
        self.assertEqual(nearby['closing_excerpt']['text'].splitlines()[-2:], ['    break;', '}'])
        short = workspace_source.read_symbol('main', 'loop.js', start_line=1, end_line=10, config=self.config)
        self.assertNotIn('closing_excerpt', short)

    def test_path_only_read_pages_and_typescript_declaration_locations(self):
        path = self.main/'core.mts'
        path.write_text('export async function runLoop() {}\n' + 'const item = 1;\n' * 48
                        + 'export interface Client {}\n', 'utf-8')
        page = workspace_source.read_symbol('main', path.name, config=self.config)
        self.assertEqual((page['start_line'], page['end_line'], page['next_line']), (1, 40, 41))
        last = workspace_source.read_symbol('main', path.name, start_line=41, config=self.config)
        self.assertEqual((last['end_line'], last['next_line']), (50, None))
        result = workspace_source.search('main', '', 'runLoop', 'symbol', config=self.config)
        self.assertEqual(result['matches'], [dict(path=path.name, symbol='runLoop', start_line=1, end_line=1)])
        for phrase in ('interface Client', 'export interface'):
            found = workspace_source.search('main', path.name, phrase, 'symbol', config=self.config)
            self.assertEqual([m['symbol'] for m in found['matches']], ['Client'])
        call = workspace_source.search('main', path.name, 'interface Client', 'text', config=self.config)
        self.assertEqual(call['matches'][0]['start_line'], 50)
        call = workspace_source.search('main', path.name, 'runLoop(', 'symbol', config=self.config)
        self.assertEqual((call['effective_mode'], call['matches'][0]['start_line']), ('text', 1))

    def test_ts_class_hit_supplies_only_its_own_adjacent_documentation(self):
        (self.main/'wrapper.ts').write_text('/** Owns the queue. */\nexport class Wrapper {}\n'
                                           '\nexport class Other {}\n', 'utf-8', newline='\n')
        found = workspace_source.search('main', 'wrapper.ts', 'class', 'symbol', config=self.config)
        wrapper, other = found['matches']
        self.assertEqual(wrapper['declaration_doc'], dict(start_line=1, end_line=1, text='/** Owns the queue. */\n'))
        self.assertNotIn('declaration_doc', other)

    def test_overview_numbers_body_and_noncontiguous_tail_independently(self):
        receipt = dict(ok=True, path='a.ts', start_line=17, end_line=19, text='first\r\n\r\nlast',
                       closing_excerpt=dict(start_line=208, end_line=209, text='break;\n}'))
        view = workspace_source.overview_receipt('workspace_read_symbol', {}, receipt, set())
        self.assertEqual(view['citation'], 'a.ts:L17-L19')
        self.assertEqual(view['closing_excerpt']['citation'], 'a.ts:L208-L209')
        self.assertEqual(view['numbered_text'], '17|first\r\n18|\r\n19|last')
        self.assertEqual(view['closing_excerpt']['numbered_text'], '208|break;\n209|}')
        self.assertIn('a.ts:L17-L19、a.ts:L208-L209', view['next_action'])
        self.assertIn('解释 break 时引 a.ts:L208；', view['next_action'])
        self.assertNotIn('a.ts:L17-L209', view['next_action'])
        self.assertEqual(receipt['closing_excerpt']['text'], 'break;\n}')
        self.assertNotIn('text', view)

    def test_overview_evidence_depends_on_returned_source(self):
        def guide(path, lines, *, implementation=False):
            receipt = dict(ok=True, path=path, start_line=30, end_line=29+len(lines),
                           text='\n'.join(lines))
            return workspace_source.overview_receipt('workspace_read_symbol', {}, receipt, set(),
                                                    implementation=implementation)['next_action']

        self.assertNotIn('符号词 State', guide('README.md', ['# Static site'], implementation=True))
        self.assertNotIn('符号词 State', guide('README.md', ['Stateful engine']))
        self.assertIn('符号词 State', guide('README.md', ['Stateful engine'], implementation=True))
        ordinary = guide('prices.py', ['def total(items):', '    return sum(items)'])
        self.assertNotIn('循环', ordinary)
        self.assertNotIn('setter', ordinary)
        accessors = guide('collection.ts', ['get items() { return this.data.slice(); }',
                                             'set items(next) { this.data = next; }'])
        self.assertIn('getter 实际 return 哪个对象', accessors)
        self.assertNotIn('getter 直接返回原数组', accessors)

    def test_tail_identifies_two_different_loop_scopes(self):
        lines = ['while (running) {', '  while (active) {'] + ['    tick();'] * 50
        lines += ['    const a = await input.next();', '  }', '  const b = await tasks.next();',
                  '  if (b) continue;', '  break;', '}']
        path = self.main / 'consumer.ts'
        path.write_text('\n'.join(lines), encoding='utf8')
        page = workspace_source.read_symbol('main', path.name, start_line=1, end_line=43, config=self.config)
        view = workspace_source.overview_receipt('workspace_read_symbol', {}, page, set())
        self.assertIn('L53 的 next 在 L2 循环体内', view['next_action'])
        self.assertIn('L55 的 next 在 L1 循环体内', view['next_action'])
        self.assertIn('consumer.ts:L57', view['next_action'])

    def test_initializer_context_is_opt_in_and_from_same_file(self):
        path = self.main / 'invoice.ts'
        factory = ['function createLines() {', '    return [];', '}']
        lines = factory + [''] * 60 + ['this.lines = createLines();'] + [''] * 50
        path.write_text('\n'.join(lines), encoding='utf8')
        def read(**kwargs):
            return workspace_source.read_symbol('main', path.name, start_line=62, end_line=110,
                                                config=self.config, **kwargs)
        self.assertNotIn('initializer_excerpt', read())
        page = read(include_initializer=True)
        self.assertEqual(page['initializer_excerpt']['text'].splitlines(), factory)
        self.assertEqual(page['initializer_excerpt']['start_line'], 1)
        result = workspace_source.overview_receipt('workspace_read_symbol', {}, page, set(), implementation=True)
        self.assertEqual(result['initializer_excerpt']['citation'], 'invoice.ts:L1-L3')

    def test_overview_compacts_navigation_without_losing_source(self):
        seen = set()
        receipt = dict(ok=True, path='module.ts', revision='a', text='body', locations=[{'line': 1}])
        def view(args, source):
            return workspace_source.overview_receipt('workspace_read_symbol', args, source, seen)
        self.assertIn('locations', view({}, receipt))
        explicit = view({'start_line': 1, 'end_line': 30}, receipt)
        self.assertNotIn('locations', explicit)
        self.assertEqual(explicit['text'], 'body')
        again = view({'root':'main'}, receipt)
        self.assertEqual(again['text'], 'body')
        self.assertNotIn('locations', again)
        self.assertIn('locations', view({}, {**receipt, 'revision':'b'}))
        self.assertIn('locations', view({'root':'ref-0'}, receipt))
        self.assertIn('locations', receipt)
        hits = dict(ok=True, matches=list(range(10)), hit_count=10)
        compact = workspace_source.overview_receipt('workspace_search', {}, hits, seen)
        self.assertEqual(compact['matches'], hits['matches'][:6])
        self.assertTrue(compact['more_matches'])
        self.assertEqual(compact['hit_count'], 10)

    def test_empty_results_identify_coverage_and_path_type(self):
        from desk_companion.projects.workspace_feedback import read_error
        cfg = self.config
        self.assertEqual(project_workspace.tree('ref-0', '', cfg)['reason'], 'empty_directory')
        (self.ref/'empty.md').touch()
        self.assertEqual(project_workspace.read('ref-0', 'empty.md', cfg)['reason'], 'empty_file')
        self.assertEqual(workspace_source.search('main', '', 'absent', 'text', config=cfg)['reason'], 'no_matches')
        (self.main/'opaque.bin').touch()
        self.assertEqual(workspace_source.search('main', '', 'absent', 'text', config=cfg)['reason'], 'incomplete_search')
        for path, reason in [('missing', 'path_not_found'), ('', 'wrong_path_type'), ('../x', 'access_denied')]:
            with self.assertRaises(ValueError) as exc:
                project_workspace.read('main', path, cfg)
            self.assertEqual(read_error(exc.exception)['reason'], reason)

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
