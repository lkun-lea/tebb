const {test}=require('node:test');
const assert=require('node:assert/strict');
const React=require('react');
const {act,create}=require('react-test-renderer');
const load=require('./load-client.cjs');
const flow=()=>load('development-flow.tsx',{'./development-flow.css':{}});
const experiment=()=>load('experiment-flow.tsx',{'./experiment-flow.css':{}});
const makeRun=(id,extra={})=>({id,conversation:'g',agent:'coder',title:id,state:'waiting',step:0,updates:[],events:[],applied:0,...extra});
test('repair tracks latest attempts without marking a pending recheck or delivery complete',()=>{
 const root=makeRun('root',{integration_repair:'repair'});
 const runs=[root,makeRun('dev',{parent:'root',state:'succeeded'}),makeRun('qa',{parent:'root',state:'failed',integration_verification:true,rechecked_by:'again'}),
 makeRun('repair',{parent:'root',state:'running'}),makeRun('again',{parent:'root',integration_verification:true})];
 const stages=flow().flowStages(root,runs);
 assert.equal(stages[1].run.id,'repair');assert.equal(stages[2].run.id,'again');
 assert.equal(stages[2].state,'waiting');assert.equal(stages[3].state,'unseen');
});
test('node inspector shows real errors, diffs, stale tests and preserves historical attempts',async()=>{
 const {DevelopmentFlow}=flow();
 const root=makeRun('root',{development_task:true});
 const old=makeRun('old',{parent:'root',state:'failed',error:'old_ambiguous',flow_events:[{seq:1,kind:'tool_end',data:{tool:'workspace_patch',status:'failed',error:'old_ambiguous'}}],
 changes:[{path:'mod.py',diff:'-a\n+b'}],checks:[{command:'pytest',state:'succeeded',exit_code:0,output:'PASS',stale:true}]});
 const fresh=makeRun('fresh',{parent:'root',state:'running'});
 let view;
 try{
  await act(async()=>{view=create(React.createElement(DevelopmentFlow,{root,runs:[root,old,fresh],agents:[],onStop:()=>{}}));});
  await act(async()=>view.root.findAllByProps({role:'tab'})[1].props.onClick());
  await act(async()=>view.root.findAllByType('button').find(b=>b.props.children?.some?.(x=>x?.props?.children==='workspace_patch')).props.onClick());
  const text=JSON.stringify(view.toJSON());
  assert.match(text,/old_ambiguous/);assert.match(text,/已失效/);assert.match(text,/mod.py/);
  assert.equal(view.root.findByProps({'aria-label':'执行轮次'}).props.value,'old');
 }finally{if(view)act(()=>view.unmount());}
});
test('switching experiments keeps unknown costs distinct from zero and surfaces a changed baseline',async()=>{
 const arm={status:'blocked',stage:'done',reason:'scope mismatch',timeline:[],checks:[],matched:true,calls:0,rework:0,supplements:0};
 const rows=['first','second'].map(id=>({id,title:id,version:10,base:'abc',arms:{direct:arm,workflow:{...arm,matched:id==='first'}}}));
 const {DevelopmentTeam}=load('development-team.tsx',{'./experiment-flow':experiment(),'./native-development-team':{NativeDevelopmentTeam:()=>null},'./page-stack':{usePageActive:()=>true},'./api':{rpc:async(_info,method)=>{
  assert.equal(method,'development_team');return {experiments:rows};
 }}});
 let view;
 try {
  await act(async()=>{view=create(React.createElement(DevelopmentTeam,{info:{port:1,token:'fixture'}}));});
  await act(async()=>view.root.findByType('details').props.onToggle({currentTarget:{open:true}}));
  assert.equal(view.root.findAllByType('article').length,2);
  assert.match(JSON.stringify(view.toJSON()),/未知/);
  await act(async()=>view.root.findByType('select').props.onChange({target:{value:'second'}}));
  assert.match(JSON.stringify(view.toJSON()),/实验条件已变化/);
 } finally { if(view)act(()=>view.unmount()); }
});

test('project team submits the actual native group request and keeps its retry identity',async()=>{
 const sent=[];
 const state={agents:[{id:'coder',name:'编码',tools:['终端','文件编辑']}],projects:[{id:'p',name:'测试项目'}],runs:[],
   conversations:[{kind:'group',project_id:'p',id:'g',title:'开发',coordinator:'tebb',members:['tebb','coder']}]};
 const {NativeDevelopmentTeam}=load('native-development-team.tsx',{
  './experiment-flow.css':{},
  './development-flow':{DevelopmentFlow:()=>null},
  './page-stack':{usePageActive:()=>true},'./collaboration-sync':{CollaborationSync:class{update(s){return s}},loadCollaboration:async()=>state},
  './api':{rpc:async(_info,method,{action})=>{assert.equal(method,'collaboration_action');sent.push(action);if(sent.length===1)throw Error('lost ack');return {ok:true,state}}}});
 let view;
 try{
  await act(async()=>{view=create(React.createElement(NativeDevelopmentTeam,{info:{port:1,token:'fixture'}}));});
  await act(async()=>view.root.findByType('textarea').props.onChange({target:{value:'实现恢复后的去重'}}));
  for(let i=0;i<2;i++)await act(async()=>view.root.findByType('button').props.onClick());
  assert.equal(sent.length,2);assert.deepEqual(sent[0],sent[1]);assert.equal(sent[0].development_task,true);
  assert.equal(sent[0].strategy,'delegate');assert.equal(sent[0].conversation,'g');assert.ok(sent[0].request_id);
 }finally{if(view)act(()=>view.unmount());}
});

test('project selection isolates runs and stopping targets the selected real root',async()=>{
 const sent=[];
 const state={agents:[{id:'coder',name:'编码',tools:['文件编辑','终端']}],projects:[],
  conversations:['a','b'].map(id=>({id,kind:'group',project_id:id,title:id,coordinator:'tebb',members:['coder']})),
  runs:['a','b'].flatMap(id=>[makeRun(id,{conversation:id,development_task:true,state:'running'}),makeRun(id+'-child',{conversation:id,parent:id})])};
 const {NativeDevelopmentTeam}=load('native-development-team.tsx',{
  './experiment-flow.css':{},
  './development-flow':{DevelopmentFlow:props=>React.createElement('div',{'data-root':props.root.id},React.createElement('button',{onClick:props.onStop},'停止'))},
  './page-stack':{usePageActive:()=>true},'./collaboration-sync':{CollaborationSync:class{update(s){return s}},loadCollaboration:async()=>state},
  './api':{rpc:async(_info,_method,{action})=>{sent.push(action);return {ok:true,state};}}});
 let view;
 try{
  await act(async()=>{view=create(React.createElement(NativeDevelopmentTeam,{info:{port:1,token:'fixture'}}));});
  assert.equal(view.root.findAllByProps({'data-root':'a'}).length,1);
  await act(async()=>view.root.findAllByType('select')[0].props.onChange({target:{value:'b'}}));
  assert.equal(view.root.findAllByProps({'data-root':'a'}).length,0);
  await act(async()=>view.root.findByProps({'data-root':'b'}).findByType('button').props.onClick());
  assert.equal(sent[0].id,'b');assert.equal(sent[0].type,'cancel');
 }finally{if(view)act(()=>view.unmount());}
});

test('external flow separates completed calls from revise verdicts and retains repeat evidence',async()=>{
 const {ExperimentFlow,totalTokens}=experiment();
 const arm={status:'blocked',stage:'done',reason:'验收计划未细化',timeline:[
  {stage:'scope_review',status:'completed',round:0,decision:'revise',note:'第一轮缺少计划'},
  {stage:'scope_review',status:'completed',round:0,decision:'revise',note:'第二轮仍需细化'},
  {stage:'reflect',status:'completed',round:0,note:''}],checks:[],matched:true,calls:3,rework:0,supplements:0};
 assert.equal(totalTokens(arm),null);assert.equal(totalTokens({...arm,uncached:0,cached:0,output:0}),0);
 const item={id:'case',arms:{workflow:arm,direct:{...arm,status:'accepted',gate:'pass',timeline:[{stage:'develop',status:'completed',round:1,note:''}]}}};
 let view;
 try{
  await act(async()=>{view=create(React.createElement(ExperimentFlow,{item}));});
  const chain=view.root.findByProps({'aria-label':'外部流程执行链'});
  assert.equal(chain.findAllByProps({'aria-label':'返回节点'}).length,1);
  assert.equal(chain.findAllByType('button').filter(b=>b.props.className.includes('warn')).length,2);
  await act(async()=>chain.findAllByType('button')[0].props.onClick());
  assert.equal(view.root.findAllByProps({'aria-label':'阶段详情'})[0].findAllByType('p')[1].children.join(''),'第一轮缺少计划');
  assert.match(JSON.stringify(view.toJSON()),/未进入/);
  assert.match(JSON.stringify(view.toJSON()),/未知/);
 }finally{if(view)act(()=>view.unmount());}
});

test('native team without runs keeps selectors and a truthful flow overview visible',async()=>{
 const {NativeDevelopmentTeam}=load('native-development-team.tsx',{
  './api':{},'./experiment-flow.css':{},'./development-flow':{DevelopmentFlow:()=>{throw Error('must not fabricate a run')}},
  './page-stack':{usePageActive:()=>true},'./collaboration-sync':{CollaborationSync:class{update(s){return s}},
   loadCollaboration:async()=>({agents:[],projects:[],conversations:[],runs:[]})}});
 let view,opened=false;
 try{
  await act(async()=>{view=create(React.createElement(NativeDevelopmentTeam,{info:{port:1,token:'fixture'},onSetup:()=>{opened=true}}));});
  assert.equal(view.root.findByProps({'aria-label':'项目群'}).props.disabled,true);
  assert.equal(view.root.findByProps({'aria-label':'运行记录'}).props.disabled,true);
  assert.match(view.root.findByProps({'aria-label':'开发流程概览'}).findByType('strong').children.join(''),/尚未运行/);
  await act(async()=>view.root.findByType('button').props.onClick());assert.equal(opened,true);
 }finally{if(view)act(()=>view.unmount());}
});
