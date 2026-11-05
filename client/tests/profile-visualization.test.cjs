const {test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer'),load=require('./load-client.cjs');
const records=load('profile-records.ts'),state=load('personalization-state.ts');
const memory=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),values};};
const text=node=>typeof node==='string'?node:(node.children||[]).map(text).join('');
test('map summarizes confirmed records without fabricating scores, scopes or known sources',()=>{
 const rows=structuredClone(state.PERSONALIZATION_FIXTURE.records);rows.push({...rows[0],id:'disabled',state:'disabled'});rows.push({...rows[0],id:'deleted',state:'deleted'});
 assert.equal(records.profileGroup(rows,'communication').length,2);assert.equal(rows.filter(records.profileUsable).length,2);
 assert.equal(records.profileScopeLabel(state.PERSONALIZATION_FIXTURE,rows[0]),'所有对话');
});
test('static me marker keeps categories and shared edits without avatar controls or storage',async()=>{
 const storage=memory(),previous=global.localStorage;global.localStorage=storage;
 const edited=[],acted=[];let ui;
 const {ProfileOverview}=load('profile-overview.tsx');
 try{
  await act(async()=>{ui=create(React.createElement(ProfileOverview,{page:structuredClone(state.PERSONALIZATION_FIXTURE),blocked:false,scopeLabel:r=>records.profileScopeLabel(state.PERSONALIZATION_FIXTURE,r),onAdd:()=>{},onEdit:(...args)=>edited.push(args),onAct:(...args)=>acted.push(args)}));});
  assert.equal(ui.root.findAll(n=>n.type==='button'&&n.props.className==='profile-domain').length,4);
  assert.equal(text(ui.root.findByProps({'aria-label':'当前账号：我'})),'我');assert.equal(ui.root.findAllByType('img').length,0);assert.doesNotMatch(text(ui.toJSON()),/更换形象|角色动作|挥手|暂停动作/);assert.equal(storage.values.size,0);
  await act(async()=>ui.root.findByProps({'data-domain':'knowledge'}).props.onClick());assert.match(text(ui.toJSON()),/云端当前版本/);
  await act(async()=>ui.root.findAllByType('button').find(n=>text(n)==='采用本机 / 更正').props.onClick());assert.equal(edited[0][0].category,'knowledge');assert.equal(edited[0][1],true);
  await act(async()=>ui.root.findAllByType('button').find(n=>text(n)==='采用云端版本').props.onClick());assert.equal(acted[0][0],'resolve_remote');
  await act(async()=>ui.root.findByProps({'data-domain':'goal'}).props.onClick());assert.match(text(ui.toJSON()),/这里尚未补充/);
 }finally{if(ui)await act(async()=>ui.unmount());global.localStorage=previous;}
});
test('record deletion requires explicit confirmation and shows real provenance metadata',async()=>{
 const {ProfileRecordCard}=load('profile-record-card.tsx');const actions=[];let ui;
 try{
  await act(async()=>ui=create(React.createElement(ProfileRecordCard,{row:{...state.PERSONALIZATION_FIXTURE.records[0],source_ref:'manual:synthetic',source_device_id:'test-device'},blocked:false,scopeLabel:()=> '所有对话',onEdit:()=>{},onAct:(...args)=>actions.push(args)})));
  assert.match(text(ui.toJSON()),/你手动确认/);assert.match(text(ui.toJSON()),/test-device/);
  await act(async()=>ui.root.findAllByType('button').find(n=>text(n)==='删除').props.onClick());assert.equal(actions.length,0);
  await act(async()=>ui.root.findAllByType('button').find(n=>text(n)==='确认删除').props.onClick());assert.equal(actions.length,1);assert.equal(actions[0][0],'delete');
 }finally{if(ui)await act(async()=>ui.unmount());}
});
