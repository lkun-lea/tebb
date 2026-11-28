const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { act, create } = require('react-test-renderer');
global.window = new EventTarget();
function load(name, mocks) {
  const filename = path.resolve(__dirname, '../src/client', name + '.tsx');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  const mod = new Module(filename, module); mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const original = mod.require.bind(mod);
  mod.require = id => id.endsWith('.css') ? {} : mocks[id] || (id==='framer-motion'?require('./motion-fixture.cjs'):null) || (['./copy-button','./toast'].includes(id) ? load(id.slice(2),mocks) : original(id));
  mod._compile(code, filename); return mod.exports;
}
const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');
const button = (view, label) => view.root.findAllByType('button').find(b => text(b) === label);
const info = { port: 1, token: 'test' };

test('unknown create archive requires confirmation and retries only the original receipt id',async(t)=>{
  const calls=[];let failed=false,archived=false;
  const environment={id:'old-environment',repository:'https://github.com/example/demo',ref:'',commit:'',state:'unknown',sandbox_id:'',prepare_operation:'original-prepare',active_operation:'original-prepare'};
  const {ProjectRuntimePane}=load('project-runtime',{'./api':{rpc:async(_info,method,args)=>{
    calls.push({method,args});const operation=args.operation;
    const env=archived?{...environment,active_operation:'',creation_archive:{operation:'original-prepare',request:'archive-receipt',at:1}}:environment;
    if(operation==='list')return{ok:true,environments:[env]};
    if(operation==='status')return{ok:true,environment:env,service_ready:false,recovery_required:true,
      archive_status:{eligible:!archived,operation:'original-prepare',local_active:false,archived}};
    if(operation==='log')return{ok:true,base64:'',offset:0,size:0,done:true};
    if(operation==='archive_create'){if(!failed){failed=true;throw Error('ack lost');}archived=true;return{ok:true};}
    throw Error('unexpected operation '+operation);
  }}});
  let view;t.after(async()=>{if(view)await act(async()=>view.unmount());});
  await act(async()=>{view=create(React.createElement(ProjectRuntimePane,{info,environment:environment.id}));});
  assert.equal(calls.filter(c=>c.args.operation==='archive_create').length,0);
  await act(async()=>button(view,'放弃原创建请求').props.onClick());
  assert.equal(calls.filter(c=>c.args.operation==='archive_create').length,0);
  assert(text(view.toJSON()).includes('创建结果仍未知'));
  await act(async()=>button(view,'确认释放应用准入').props.onClick());
  assert(text(view.toJSON()).includes('ack lost'));
  await act(async()=>button(view,'确认释放应用准入').props.onClick());
  const sent=calls.filter(c=>c.args.operation==='archive_create').map(c=>c.args.payload);
  assert.equal(sent.length,2);assert(sent[0].request_id);assert.equal(sent[0].request_id,sent[1].request_id);
  assert.equal(sent[0].expected_operation,'original-prepare');assert.equal(sent[0].confirm,true);
  assert(text(view.toJSON()).includes('请求已归档；创建结果仍未知'));
  assert(!calls.some(c=>['stop','prepare','create'].includes(c.args.operation)));
});
