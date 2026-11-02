const {test}=require('node:test');
const assert=require('node:assert/strict');
const React=require('react');
const {act,create}=require('react-test-renderer');
const load=require('./load-client.cjs');
test('switching experiments keeps unknown costs distinct from zero and surfaces a changed baseline',async()=>{
 const arm={status:'blocked',stage:'done',reason:'scope mismatch',timeline:[],checks:[],matched:true,calls:0,rework:0,supplements:0};
 const rows=['first','second'].map(id=>({id,title:id,version:10,base:'abc',arms:{direct:arm,workflow:{...arm,matched:id==='first'}}}));
 const {DevelopmentTeam}=load('development-team.tsx',{'./page-stack':{usePageActive:()=>true},'./api':{rpc:async(_info,method)=>{
  assert.equal(method,'development_team');return {experiments:rows};
 }}});
 let view;
 try {
  await act(async()=>{view=create(React.createElement(DevelopmentTeam,{info:{port:1,token:'fixture'}}));});
  assert.equal(view.root.findAllByType('article').length,2);
  assert.match(JSON.stringify(view.toJSON()),/未知/);
  await act(async()=>view.root.findByType('select').props.onChange({target:{value:'second'}}));
  assert.match(JSON.stringify(view.toJSON()),/实验条件已变化/);
 } finally { if(view)act(()=>view.unmount()); }
});
