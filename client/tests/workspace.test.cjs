const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { act, create } = require('react-test-renderer');

function load(name, mocks = {}) {
  const base = path.resolve(__dirname, '../src/client', name);
  const filename = fs.existsSync(base + '.tsx') ? base + '.tsx' : base + '.ts';
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  const mod = new Module(filename, module); mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const original = mod.require.bind(mod);
  mod.require = id => mocks[id] || (id==='framer-motion'?require('./motion-fixture.cjs'):null) || (id.endsWith('.css') ? {} : id.startsWith('./') ? load(id.slice(2), mocks) : original(id));
  mod._compile(code, filename); return mod.exports;
}
function environment() {
  global.window = new EventTarget();
  global.ResizeObserver = class { observe() {} disconnect() {} };
}
const renderedText = node => typeof node === 'string' ? node : (node.children || []).map(renderedText).join('');
const button = (view, label) => view.root.findAllByType('button').find(b => renderedText(b) === label);
const source = { id: 's1', name: '技术.md', kind: 'file', path: 'E:/fixture/技术.md', chars: 12 };
const markdown = { Markdown: ({ text }) => React.createElement('article', { 'data-markdown': '' }, text), openableHref: url => /^https?:\/\//.test(url || '') ? url : null };
const mocks = rpc => ({ './api': { rpc }, './Markdown': markdown, './terminal': { TerminalPane: () => React.createElement('section', { 'data-terminal': '' }, '终端') }, '@tauri-apps/api/core': { isTauri: () => false }, '@tauri-apps/api/event': {} });
const workspaceProps = { info: { port: 1, token: 'test' }, enabled: true, attachments: [], onAttach() {}, onDetach() {}, onLink() {}, onRequest() {}, children: React.createElement('textarea', { defaultValue: '保留草稿' }) };

test('same quoted text from different source versions keeps separate preview identities', () => {
  const { quoteIdentity } = load('side-workspace', mocks(async () => ({ ok: true })));
  const quote = { n: 1, doc: 'doc', title: 'title', doc_id: 'doc', text: 'same text', source_id: 'a'.repeat(32), source_version: 'b'.repeat(64) };
  assert.notEqual(quoteIdentity(quote), quoteIdentity({ ...quote, source_version: 'c'.repeat(64) }));
  assert.equal(quoteIdentity(quote), quoteIdentity({ ...quote }));
});

test('file preview paginates without attaching, and preserves the conversation across collapse and tab switches', async () => {
  environment(); const calls = []; let attached = [];
  const { SideWorkspace, previewSource, previewQuote } = load('side-workspace', mocks(async (_i, method, args) => {
    calls.push({ method, args }); return { ok: true, source: { text: args.offset ? '第二页' : '# 第一页', chars: 12, next_offset: args.offset ? null : 5 } };
  }));
  let view; await act(async () => { view = create(React.createElement(SideWorkspace, { ...workspaceProps, onAttach: values => attached = values })); });
  const draft = view.root.findByType('textarea');
  await act(async () => previewSource(source)); assert.equal(attached.length, 0);
  assert.equal(view.root.findByProps({ 'data-markdown': '' }).children[0], '# 第一页');
  await act(async () => button(view, '继续读取').props.onClick());
  assert.equal(calls[1].args.offset, 5); assert.equal(view.root.findByProps({ 'data-markdown': '' }).children[0], '# 第一页第二页');
  await act(async () => button(view, '加入本轮资料').props.onClick()); assert.deepEqual(attached, [source]);
  await act(async () => button(view, '收起').props.onClick()); assert.equal(view.root.findByType('textarea'), draft);
  await act(async () => previewQuote({ n: 1, title: '来源', doc: '原文', doc_id: 'd', text: '摘要', context: '**完整片段**' }));
  assert.equal(view.root.findByProps({ 'data-markdown': '' }).children[0], '**完整片段**');
  assert.equal(view.root.findByType('textarea'), draft); await act(async () => view.unmount());
});

test('closing or stopping a pending preview ignores late data and never creates an attachment', async () => {
  environment(); let finish, attachments = 0;
  const { SideWorkspace, previewSource } = load('side-workspace', mocks(() => new Promise(resolve => finish = resolve)));
  let view; await act(async () => { view = create(React.createElement(SideWorkspace, { ...workspaceProps, onAttach: () => attachments++ })); previewSource(source); });
  // The listener is installed after mount.
  await act(async () => previewSource(source));
  await act(async () => button(view, '停止等待').props.onClick());
  await act(async () => finish({ ok: true, source: { text: '迟到内容', chars: 4, next_offset: null } }));
  assert(!renderedText(view.toJSON()).includes('迟到内容')); assert.equal(attachments, 0);
  await act(async () => button(view, '重试').props.onClick());
  await act(async () => view.root.findByProps({ 'aria-label': '关闭 技术.md' }).props.onClick());
  await act(async () => finish({ ok: true, source: { text: '关闭后的内容', chars: 6, next_offset: null } }));
  assert.equal(view.root.findByProps({'aria-label':'侧边工作区'}).props.hidden, true); assert.equal(view.root.findByType('textarea').props.defaultValue, '保留草稿');
  await act(async () => view.unmount());
});

test('browser is embedded, hides behind dialogs or collapsed panes, and inserts only an explicitly requested link', async () => {
  environment(); const calls = []; let linked = '', listener;
  const moduleMocks = mocks(async () => ({}));
  moduleMocks['@tauri-apps/api/core'] = { isTauri: () => true, invoke: async (name, args) => { calls.push({ name, args }); } };
  moduleMocks['@tauri-apps/api/event'] = { listen: async (_name, callback) => { listener = callback; return () => {}; } };
  const { SideWorkspace } = load('side-workspace', moduleMocks);
  let view; await act(async () => { view = create(React.createElement(SideWorkspace, { ...workspaceProps, onLink: url => linked = url }), {
    createNodeMock: () => ({ getBoundingClientRect: () => ({ left: 600, top: 90, width: 400, height: 450 }) }) }); });
  await act(async () => window.dispatchEvent(new CustomEvent('desk-open-preview', { detail: { kind: 'web', url: 'https://example.org' } })));
  assert(calls.some(c => c.name === 'open_side_browser')); assert.equal(linked, '');
  await act(async () => listener({ payload: { url: 'https://example.org/page', title: '网页标题', loading: false } }));
  await act(async () => button(view, '引用链接到草稿').props.onClick()); assert.equal(linked, 'https://example.org/page');
  await act(async () => view.update(React.createElement(SideWorkspace, { ...workspaceProps, suspended: true, onLink: url => linked = url })));
  assert.equal(calls.filter(c => c.name === 'side_browser_layout').at(-1).args.visible, false);
  await act(async () => view.root.findByProps({ 'aria-label': '关闭 网页' }).props.onClick());
  assert(calls.some(c => c.name === 'side_browser_action' && c.args.action === 'close')); await act(async () => view.unmount());
});

test('citations from different answers do not share stale source tabs', () => {
  const { quoteIdentity } = load('side-workspace', mocks());
  const cite = { n: 1, doc_id: 'same', title: 'same', doc: 'same', text: 'same', context: '# 原文A' };
  assert.notEqual(quoteIdentity(cite), quoteIdentity({ ...cite, context: '# 原文B' }));
  assert.equal(quoteIdentity(cite), quoteIdentity({ ...cite }));
});

test('sidebar reports toolbar state and never overlays the conversation with a reopen button', async()=>{
  environment();const states=[];
  const {SideWorkspace,openTerminal,togglePreview}=load('side-workspace',mocks());let view;
  await act(async()=>{view=create(React.createElement(SideWorkspace,{...workspaceProps,onVisibilityChange:value=>states.push(value)}));});
  assert.deepEqual(states.at(-1),{open:false,available:false});
  await act(async()=>openTerminal());assert.deepEqual(states.at(-1),{open:true,available:true});
  await act(async()=>togglePreview());assert.deepEqual(states.at(-1),{open:false,available:true});
  assert.equal(view.root.findAllByProps({className:'desk-menu-item workspace-reopen'}).length,0);
  assert.equal(view.root.findByProps({'aria-label':'侧边工作区'}).props.hidden,true);
  await act(async()=>togglePreview());assert.equal(view.root.findByProps({'aria-label':'侧边工作区'}).props.hidden,false);
  await act(async()=>view.unmount());
});

test('terminal opens in the shared sidebar, preserves chat draft, and can be reopened', async () => {
  environment(); let requests = 0;
  const { SideWorkspace, openTerminal, togglePreview } = load('side-workspace', mocks());
  let view; await act(async () => { view = create(React.createElement(SideWorkspace, { ...workspaceProps, onRequest: () => requests++ })); });
  const draft = view.root.findByType('textarea');
  await act(async () => openTerminal()); assert.equal(requests, 1); assert.equal(view.root.findAllByProps({ 'data-terminal': '' }).length, 1);
  await act(async () => openTerminal()); assert.equal(view.root.findAllByProps({ 'data-terminal': '' }).length, 1);
  await act(async () => button(view, '收起').props.onClick()); assert.equal(view.root.findByType('textarea'), draft);
  await act(async () => togglePreview()); assert.equal(view.root.findAllByProps({ 'data-terminal': '' }).length, 1);
  await act(async () => view.unmount());
});

test('slash menu picks the actual category in All and shows purpose, source and selection separately', async () => {
  global.window = { addEventListener() {}, removeEventListener() {} };
  const { SlashMenu } = load('slash-menu'); let selected;
  let view; await act(async () => { view = create(React.createElement(SlashMenu, { open: true, parent: 'all', repoPicking: false, active: 0,
    items: [{ id: 's', label: '摘要', description: '压缩重点', source: '本地技能', parent: 'skill', picked: true }],
    error: '', loading: false, onParent() {}, onClose() {}, onBack() {}, onRetry() {}, onPick: (...args) => selected = args })); });
  const item = view.root.findByProps({ 'data-slash-item': '' });
  await act(async () => item.props.onClick()); assert.deepEqual(selected, ['s', 'skill']);
  assert(renderedText(item).includes('本地技能')); assert(renderedText(item).includes('已加入')); await act(async () => view.unmount());
});

function sseResponse(frames) {
  const text = frames.map(value => 'data: ' + JSON.stringify(value) + '\n\n').join('');
  return new Response(text, {headers:{'Content-Type':'text/event-stream'}});
}
const settled = (state, answer = '', error = '') => ({type:'settled',data:{task:{state,answer,error}}});
const runId = 'a'.repeat(32);

test('HTTP RPC rejects disconnects, invalid replies and explicit timeouts without replaying writes', async () => {
  const {rpc}=load('api'), original=global.fetch, calls=[];
  try {
    global.fetch=async(...args)=>{calls.push(args);throw new TypeError('closed');};
    await assert.rejects(rpc({port:1,token:'test'},'write'),/连接已断开/);assert.equal(calls.length,1);
    global.fetch=async()=>new Response('{bad');await assert.rejects(rpc({port:1,token:'test'},'read'),/无法解析/);
    global.fetch=(_url,init)=>new Promise((_resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new Error('aborted'))));
    await assert.rejects(rpc({port:1,token:'test'},'read',{}, {timeoutMs:5}),/超时/);
    global.fetch=async(_url,init)=>{assert.equal(init.headers.Authorization,'Bearer test');return Response.json({ok:true,result:{value:42}});};
    assert.deepEqual(await rpc({port:1,token:'test'},'read'),{value:42});
  } finally {global.fetch=original;}
});

test('SSE reconnect uses the original run and cursor, deduplicates events and settles once',async()=>{
  const {streamNotebook}=load('api'),original=global.fetch,tokens=[],done=[],calls=[];
  let subscription=0;
  try {
    global.fetch=async(url,init)=>{
      calls.push([url,init]);
      if(url.endsWith('/v1/runs'))return Response.json({run_id:runId});
      subscription++;
      if(subscription===1)return new Response('id: 1\ndata: '+JSON.stringify({type:'token',data:'partial'})+'\n\n',{headers:{'Content-Type':'text/event-stream'}});
      assert.match(url,/after=1$/);
      return new Response('id: 1\ndata: '+JSON.stringify({type:'token',data:'partial'})+'\n\n'+'id: 2\ndata: '+JSON.stringify({type:'token',data:' complete'})+'\n\n'+'data: '+JSON.stringify(settled('succeeded',JSON.stringify({answer:'partial complete',cites:[]})))+'\n\n',{headers:{'Content-Type':'text/event-stream'}});
    };
    await new Promise((resolve,reject)=>streamNotebook({port:1,token:'test'},'s','q',['d'],{}, {
      onToken:text=>tokens.push(text),onStatus(){},onDone:result=>{done.push(result);resolve();},onError:reject,
    }));
    assert.deepEqual(tokens,['partial',' complete']);assert.equal(done.length,1);
    assert.equal(calls.filter(([url])=>url.endsWith('/v1/runs')).length,1);
  }finally{global.fetch=original;}
});

test('notebook SSE rejects malformed completion and preserves structured partial failure',async()=>{
  const {streamNotebook}=load('api'),original=global.fetch;
  try {
    for (const answer of ['{bad',JSON.stringify({answer:'',cites:[]})]) {
      global.fetch=async url=>url.endsWith('/v1/runs')?Response.json({run_id:runId}):sseResponse([settled('succeeded',answer)]);
      await new Promise(resolve=>streamNotebook({port:1,token:'test'},'s','q',[],{}, {onToken(){},onStatus(){},onDone(){assert.fail();},onError:message=>{assert.match(message,/无法解析/);resolve();}}));
    }
    global.fetch=async url=>url.endsWith('/v1/runs')?Response.json({run_id:runId}):sseResponse([
      {type:'notebook_result',data:{answer:'full body',answer_complete:true,cites:[]}},settled('failed','','save unconfirmed')]);
    await new Promise(resolve=>streamNotebook({port:1,token:'test'},'s','q',[],{}, {onToken(){},onStatus(){},onDone(){assert.fail();},onError:(message,result)=>{assert.equal(message,'save unconfirmed');assert.equal(result.answer,'full body');resolve();}}));
  }finally{global.fetch=original;}
});

test('lost HTTP submit acknowledgement reuses its ID and expired cursor replaces visible text',async()=>{
  const {streamChat}=load('api'),original=global.fetch,submitted=[],snapshots=[],tokens=[];
  try{
    global.fetch=async(url,init)=>{
      if(url.endsWith('/v1/runs')){
        submitted.push(JSON.parse(init.body));
        if(submitted.length===1)throw new TypeError('lost acknowledgement');
        return Response.json({run_id:runId});
      }
      return new Response('id: 600\ndata: '+JSON.stringify({type:'snapshot',data:{task:{answer:'restored'},events:[]}})+'\n\n'
        +'id: 601\ndata: '+JSON.stringify({type:'token',data:' tail'})+'\n\n'
        +'data: '+JSON.stringify(settled('succeeded','restored tail'))+'\n\n',{headers:{'Content-Type':'text/event-stream'}});
    };
    await new Promise((resolve,reject)=>streamChat({port:1,token:'test'},'question',{}, {},'',{
      onToken:text=>tokens.push(text),onSnapshot:text=>snapshots.push(text),onThink(){},onStatus(){},onDone:resolve,onError:reject,
    }));
    assert.equal(submitted.length,2);assert.deepEqual(submitted[0],submitted[1]);
    assert.deepEqual(snapshots,['restored']);assert.deepEqual(tokens,[' tail']);
  }finally{global.fetch=original;}
});

test('disposing old-account SSE subscriptions ignores late frames and never cancels a task',async()=>{
  const {watchWorkBoard}=load('api'),original=global.fetch;
  let controller,signal,refreshes=0;const calls=[];
  try{
    global.fetch=async(url,init)=>{calls.push(url);signal=init.signal;return new Response(new ReadableStream({start(value){controller=value;}}),{headers:{'Content-Type':'text/event-stream'}});};
    const stop=watchWorkBoard({port:1,token:'old-account'},()=>refreshes++);
    await new Promise(resolve=>setImmediate(resolve));stop();
    controller.enqueue(new TextEncoder().encode('data: {"type":"work_board_changed"}\n\n'));
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(refreshes,0);assert(signal.aborted);assert.equal(calls.length,1);assert(!calls.some(url=>url.includes('/cancel')));
  }finally{global.fetch=original;}
});

test('a snapshot retains an unconsumed answer reset until the replacement token arrives',async()=>{
  const {streamChat}=load('api'),original=global.fetch,snapshots=[],tokens=[];
  try{
    global.fetch=async url=>url.endsWith('/v1/runs')?Response.json({run_id:runId}):sseResponse([
      {type:'snapshot',data:{task:{answer:'previous draft'},events:[],replace_pending:true}},
      {type:'token',data:'replacement'},settled('succeeded','replacement')]);
    await new Promise((resolve,reject)=>streamChat({port:1,token:'test'},'q',{}, {},'',{
      onToken:piece=>tokens.push(piece),onSnapshot:text=>snapshots.push(text),onThink(){},onStatus(){},onDone:resolve,onError:reject,
    }));
    assert.deepEqual(snapshots,['previous draft','replacement']);assert.deepEqual(tokens,[]);
  }finally{global.fetch=original;}
});

test('notebook titles are reading links, citations use complete stored Markdown, and batch/delete actions are explicit', async () => {
  let quoted, deleted = [], merged;
  const cite = { n: 1, doc: '来源', title: '原文', doc_id: 'd', text: '摘要', context: '# 完整片段\n**要点**' };
  const note = { id: 'n1', question: '技术要点', answer: '答案[1]', cites: [cite], saved: '2026-10-10', files: [{ name: '资料.md', path: 'fixture/资料.md' }] };
  const motion = new Proxy({}, { get: (_, tag) => React.forwardRef(({ children, initial, animate, transition, ...props }, ref) => React.createElement(tag, { ...props, ref }, children)) });
  const { NoteMode } = load('note', { 'framer-motion': { motion }, './side-workspace': { previewQuote: c => quoted = c },
    './Markdown': { Markdown: ({ text, onCite }) => React.createElement('article', {}, text, React.createElement('button', { onClick: () => onCite?.(1) }, '引用1')) } });
  let shared='';let view; await act(async () => { view = create(React.createElement(NoteMode, { sessionId: 'session', onCollaborate:id=>shared=id, book: { docs: [], turns: [], notes: [note] },
    checked: [], error: '', status: '', busy: false, saveStatus: '', saveBad: false, docUrl: '', onCheck() {}, onSave() {}, onDelete() {},
    onMarkdown() {}, onFeishu() {}, onOpenFile() {}, onRevealFile() {}, onDeleteFile: (...args) => deleted.push(args), onSummarize: ids => merged = ids })); });
  const title = view.root.findByProps({ 'data-note-answer-toggle': 'n1' }); assert.equal(title.type, 'a');
  assert.equal(view.root.findAllByProps({ 'data-note-summarize': '' }).length, 0);
  await act(async () => title.props.onClick({ preventDefault() {} }));
  assert.equal(view.root.findByProps({ 'data-note-reader': 'n1' }).type, 'article');
  await act(async()=>button(view,'作为资料交给伙伴').props.onClick());assert.equal(shared,'n1');
  await act(async () => button(view, '引用1').props.onClick()); assert.deepEqual(quoted, cite);
  await act(async () => view.root.findByProps({ 'data-note-answer-toggle': 'n1' }).props.onClick({preventDefault(){}}));
  await act(async () => button(view, '删除文件').props.onClick()); assert.equal(deleted.length, 0);
  const fileDialog = view.root.findByProps({role:'alertdialog', 'aria-label':'删除关联文件？'});
  await act(async () => fileDialog.props.onCancel({preventDefault(){},stopPropagation(){}}));
  assert.equal(deleted.length, 0);
  assert.equal(view.root.findByProps({'data-note-reader':'n1'}).type, 'article');
  await act(async () => button(view, '删除文件').props.onClick());
  await act(async () => button(view, '确认删除文件').props.onClick()); assert.deepEqual(deleted, [['n1', '资料.md']]);
  await act(async () => button(view, '多选').props.onClick());
  await act(async () => view.root.findAllByType('input').find(i => i.props.type === 'checkbox').props.onChange({ target: { checked: true } }));
  await act(async () => view.root.findByProps({ 'data-note-summarize': '' }).props.onClick()); assert.deepEqual(merged, ['n1']);
  await act(async () => view.unmount());
});

test('only trusted local webviews have capabilities, even when remote content shares the main window', () => {
  const capability = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../src-tauri/capabilities/default.json'), 'utf8'));
  assert.deepEqual(capability.webviews, ['pet', 'main', 'pet-chat', 'settings']); assert(!capability.windows?.length); assert(!capability.remote);
});


test('open folder intent reaches project panel once and closing the tab clears it',async()=>{
 environment();const requests=[];
 const {SideWorkspace,openProject,openProjectFolder}=load('side-workspace',{
  ...mocks(async()=>{throw Error('Unexpected RPC');}),
  './project-panel':{ProjectPanel:props=>{requests.push(props.folderRequest);return React.createElement('div',{'data-project-panel':''},'项目目录');}}
 });
 let view;await act(async()=>{view=create(React.createElement(SideWorkspace,workspaceProps));});
 await act(async()=>openProjectFolder());assert.equal(requests.at(-1),1);
 await act(async()=>view.root.findByProps({'aria-label':'关闭 项目文件'}).props.onClick());
 await act(async()=>openProject());assert.equal(requests.at(-1),0);
 assert.equal(view.root.findByType('textarea').props.defaultValue,'保留草稿');
 await act(async()=>view.unmount());
});
