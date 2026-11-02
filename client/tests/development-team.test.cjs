const {test}=require('node:test');
const assert=require('node:assert/strict');
const React=require('react');
const {act,create}=require('react-test-renderer');
const load=require('./load-client.cjs');
test('switching experiments keeps unknown costs distinct from zero and surfaces a changed baseline',async()=>{
 const arm={status:'blocked',stage:'done',reason:'scope mismatch',timeline:[],checks:[],matched:true,calls:0,rework:0,supplements:0};
 const rows=['first','second'].map(id=>({id,title:id,version:10,base:'abc',arms:{direct:arm,workflow:{...arm,matched:id==='first'}}}));
 const {DevelopmentTeam}=load('development-team.tsx',{'./native-development-team':{NativeDevelopmentTeam:()=>null},'./page-stack':{usePageActive:()=>true},'./api':{rpc:async(_info,method)=>{
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
