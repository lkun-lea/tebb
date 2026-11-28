const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const ts = require('typescript'), React = require('react');
const { act, create } = require('react-test-renderer');
function load(name, mocks={}) {
  const base=path.resolve(__dirname,'../src/client',name);const filename=fs.existsSync(base+'.tsx')?base+'.tsx':base+'.ts';
  const mod=new Module(filename,module);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));
  const original=mod.require.bind(mod);mod.require=id=>mocks[id]||(id==='framer-motion'?require('./motion-fixture.cjs'):null)||(id.endsWith('.css')?{}:id.startsWith('./')?load(id.slice(2),mocks):original(id));
  mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);return mod.exports;
}
const text=n=>typeof n==='string'?n:(n.children||[]).map(text).join('');

test('pet retains real progress after chat closes, reports failure, and respects dismissal for descendants',()=>{
  const filename=path.resolve(__dirname,'../src/pet-feedback.ts');const mod=new Module(filename,module);
  mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
  const {PetFeedback}=mod.exports;const feedback=new PetFeedback();const progress={enabled:true};
  const old={id:'old',state:'failed',error:'上次启动前的失败'};
  assert.equal(feedback.update(progress,[old],false),null);
  const run={id:'new',state:'running',kind:'chat',title:'hello',events:['正在调用模型']};
  assert.equal(feedback.update(progress,[old,run],true),null);
  assert.match(feedback.update(progress,[old,run],false).text,/正在调用模型/);
  run.answer='你好，';assert.match(feedback.update(progress,[old,run],false).text,/正在调用模型/);
  run.state='succeeded';run.answer='你好，有什么可以帮你？';
  assert.match(feedback.update(progress,[old,run],false).text,/hello\n已完成\n你好/);
  feedback.dismiss();assert.equal(feedback.update(progress,[old,run],false),null);
  const child={id:'child',parent:'new',state:'running'};
  assert.equal(feedback.update(progress,[old,run,child],false),null);
  const next={id:'next',state:'running',kind:'route',answer:'{"mode":"task","instructions":"raw JSON"}'};
  assert(!feedback.update(progress,[old,run,child,next],false).text.includes('raw JSON'));
  next.state='timed_out';next.error='模型调用超时';child.state='succeeded';
  assert.equal(feedback.update(progress,[old,run,child,next],false).error,true);
  assert.match(feedback.current.text,/模型调用超时/);
  assert.equal(feedback.update({enabled:false},[old,run,child,next],false),null);
  const concurrent=new PetFeedback();const ongoing={id:'ongoing',created:1,state:'running'};
  concurrent.update(progress,[ongoing],false);
  const failed={id:'fresh',created:2,state:'failed',error:'新消息调用失败'};
  assert.match(concurrent.update(progress,[ongoing,failed],false).text,/新消息调用失败/);
  assert.match(concurrent.update(progress,[ongoing,failed],true) || '',/^$/);
  assert.match(concurrent.update(progress,[ongoing,failed],false).text,/新消息调用失败/);
});

test('visited pages preserve inputs, and their activity context pauses while hidden',async()=>{
  const {PageStack,usePageActive}=load('page-stack');let mounts=0;
  function Page(){const [draft,setDraft]=React.useState('');const active=usePageActive();React.useEffect(()=>{mounts++;},[]);return React.createElement('input',{value:draft,'data-active':active,onChange:e=>setDraft(e.target.value)});}
  let view;await act(async()=>{view=create(React.createElement(PageStack,{active:'one'},React.createElement(Page)));});
  const input=view.root.findByType('input');await act(async()=>input.props.onChange({target:{value:'保留输入'}}));
  await act(async()=>view.update(React.createElement(PageStack,{active:'two'},React.createElement('p',null,'第二页'))));
  assert.equal(input.props['data-active'],false);assert.equal(input.props.value,'保留输入');
  await act(async()=>view.update(React.createElement(PageStack,{active:'one'},React.createElement(Page))));
  assert.equal(input.props['data-active'],true);assert.equal(input.props.value,'保留输入');assert.equal(mounts,1);
  await act(async()=>view.unmount());
});

test('streaming passes complete Markdown and an appended reveal range, then retains output without a timer',()=>{
  const {StreamText}=load('stream-text',{'./Markdown':{loosenQuotedEmphasis:text=>text,Markdown:({text,reveal})=>React.createElement('article',{'data-reveal':reveal},text)}});let view;
  act(()=>{view=create(React.createElement(StreamText,{text:'第一段',active:true}));});
  act(()=>view.update(React.createElement(StreamText,{text:'第一段，新增',active:true})));
  assert.equal(text(view.root.findByType('article')),'第一段，新增');
  assert.equal(view.root.findByType('article').props['data-reveal'][0].offset,'第一段'.length);
  act(()=>view.update(React.createElement(StreamText,{text:'第一段，新增',active:false})));
  assert.equal(text(view.root.findByType('article')),'第一段，新增');assert.equal(view.root.findByType('article').props['data-reveal'],undefined);act(()=>view.unmount());
});

test('newer root keeps priority over a late older failure and replaces its own stage with its reason',()=>{
 const file=path.resolve(__dirname,'../src/pet-feedback.ts'),mod=new Module(file,module);
 mod._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,file);
 const f=new mod.exports.PetFeedback(),p={enabled:true};
 const a={id:'a',state:'running',created:12},b={id:'b',title:'验收日程',state:'running',created:12,events:['调用模型：test-local','正在读取日程']};
 assert.match(f.update(p,[a,b],false).text,/test-local/);a.state='failed';a.error='旧轮失败';
 assert.equal(f.update(p,[a,b],false).key,'collab:b');b.state='failed';b.error='日程连接断开';b.answer='旧输出';
 const end=f.update(p,[a,b],false);assert.equal(end.working,false);assert.match(end.text,/日程连接断开/);assert(!end.text.includes('旧输出'));
});

test('pet board ranks pending answer, near appointment and selected project, deduplicating task identities',()=>{
 const {petRows}=load('pet-board');const now=new Date('2026-11-29T10:00:00');
 const pref={time:'20:00',focus:'both',keywords:'评审'};
 const b={day:'2026-11-29',preferences:{morning:pref,evening:pref,project:'p'},projects:[{id:'p',name:'研发'}],questions:[{run:'q',title:'时长',prompt:'评审时长？'}],events:[{source:'q',time:+now/1000,title:'重复'},{source:'r',time:+now/1000,title:'准备议程'}]};
 const e={calendar_id:'c',event_id:'e',summary:'评审',start:'2026-11-29T11:00:00',end:'2026-11-29T12:00:00'};
 assert.deepEqual(petRows(b,[e],now).map(r=>r.id),['q','calendar:c:e','r']);b.preferences.project='';
 assert.equal(petRows(b,[e],now).length,2);b.questions=[];assert.deepEqual(petRows(b,[],now),[]);
});
