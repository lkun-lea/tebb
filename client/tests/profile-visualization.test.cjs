const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const React=require('react'),{act,create}=require('react-test-renderer'),load=require('./load-client.cjs');
const appearance=load('profile-appearance.ts'),motion=load('profile-character-motion.ts'),records=load('profile-records.ts');
const state=load('personalization-state.ts');
const memory=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k),values};};
const text=node=>typeof node==='string'?node:(node.children||[]).map(text).join('');
test('all three choices persist as display preferences without semantic memory writes',()=>{
 const storage=memory();
 for(const character of ['comic','robot','rabbit']){
  assert.equal(appearance.saveAppearance(storage,{version:1,character,motion:false}),'');
  assert.equal(appearance.loadAppearance(storage).value.character,character);
 }
 assert.equal(storage.values.size,1);assert.equal(appearance.loadAppearance(storage).value.motion,false);
 const failed=appearance.saveAppearance({getItem:()=>null,setItem(){throw Error('full');}},{version:1,character:'comic',motion:true});assert.match(failed,/未能保存/);
 const invalid=memory();invalid.setItem(appearance.APPEARANCE_KEY,'{"character":"https://example.invalid/avatar"}');const read=appearance.loadAppearance(invalid);assert.equal(read.value.character,'comic');assert.match(read.error,/未覆盖/);assert.match(invalid.getItem(appearance.APPEARANCE_KEY),/https/);
});
test('appearance follows existing account isolation including local space',()=>{
 const storage=memory(),a=load('account-storage.ts'),b=load('account-storage.ts'),local=load('account-storage.ts');
 a.initializeAccountStorage('a'.repeat(64));b.initializeAccountStorage('b'.repeat(64));local.initializeAccountStorage('local');
 appearance.saveAppearance(a.accountStorage(storage),{version:1,character:'rabbit',motion:true});
 appearance.saveAppearance(b.accountStorage(storage),{version:1,character:'robot',motion:false});
 assert.equal(appearance.loadAppearance(a.accountStorage(storage)).value.character,'rabbit');assert.equal(appearance.loadAppearance(b.accountStorage(storage)).value.character,'robot');assert.equal(appearance.loadAppearance(local.accountStorage(storage)).value.character,'comic');
});
test('every gesture interpolates the current transforms and has preparation and return phases',()=>{
 for(const character of ['comic','robot','rabbit'])for(const kind of ['idle','wave','nod','point'])for(const direction of ['left','right']){
  const plan=motion.characterMotionPlan(kind,character,direction);assert.equal(plan.length,7);
  for(const bone of plan){for(const key of ['rotate','y','x','scaleY'])if(bone[key]){assert.equal(bone[key][0],null,'action must start from current pose');assert(bone[key].length>=3);if(bone.times)assert.equal(bone[key].length,bone.times.length);}assert(bone.duration>=1);}
 }
 const left=motion.characterMotionPlan('point','robot','left').find(p=>p.bone==='left');const right=motion.characterMotionPlan('point','robot','right').find(p=>p.bone==='right');assert(left.rotate[1]>0);assert(right.rotate[1]<0);
  for(const kind of ['idle','wave','point'])assert.equal(motion.characterMotionPlan(kind,'comic').find(p=>p.bone==='head').y.at(-1),0,'interrupting a nod must return the head to its resting height');
});
test('map summarizes confirmed records without fabricating scores, scopes or known sources',()=>{
 const rows=structuredClone(state.PERSONALIZATION_FIXTURE.records);rows.push({...rows[0],id:'disabled',state:'disabled'});rows.push({...rows[0],id:'deleted',state:'deleted'});
 assert.equal(records.profileGroup(rows,'communication').length,2);assert.equal(rows.filter(records.profileUsable).length,2);
 assert.equal(records.profileScopeLabel(state.PERSONALIZATION_FIXTURE,rows[0]),'所有对话');
});
test('map category, record selection, shared edits and debug appearance remain isolated',async()=>{
 const storage=memory(),previous=global.localStorage;global.localStorage=storage;
 const edited=[],acted=[];let ui;
 const {ProfileOverview}=load('profile-overview.tsx');
 try{
  await act(async()=>{ui=create(React.createElement(ProfileOverview,{page:structuredClone(state.PERSONALIZATION_FIXTURE),debug:true,blocked:false,scopeLabel:r=>records.profileScopeLabel(state.PERSONALIZATION_FIXTURE,r),onAdd:()=>{},onEdit:(...args)=>edited.push(args),onAct:(...args)=>acted.push(args)}));});
  assert.equal(ui.root.findAll(n=>n.type==='button'&&n.props.className==='profile-domain').length,4);
  await act(async()=>ui.root.findAllByType('button').find(n=>text(n)==='几何小机器人').props.onClick());assert.equal(ui.root.findByProps({'data-character':'robot'}).props['data-character'],'robot');assert.equal(storage.values.size,0);
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
test('bundled PNG parts match the retained original atlases and optimized manifest',()=>{
 const crypto=require('node:crypto');const root=path.resolve(__dirname,'../public/profile-avatars');const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));assert.equal(manifest.length,24);
 for(const row of manifest){const bytes=fs.readFileSync(path.join(root,row.character,row.part+'.png'));assert.equal(bytes.toString('hex',0,8),'89504e470d0a1a0a');assert.equal(bytes.readUInt32BE(16),row.width);assert.equal(bytes.readUInt32BE(20),row.height);assert.equal(bytes[25],6,'assets must retain alpha');assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),row.sha256);}
});

test('avatar stops replaced actions and stale completions cannot restart a paused or unmounted avatar',async()=>{
 const scope={current:null},calls=[];
 const animate=(selector,keyframes,options)=>{const c={selector,keyframes,options,stopped:0,paused:0,stop(){this.stopped++;},pause(){this.paused++;},play(){},then(callback){this.complete=callback;}};calls.push(c);return c;};
 const {ProfileAvatar}=load('profile-avatar.tsx',{'framer-motion':{useAnimate:()=>[scope,animate],useReducedMotion:()=>false}});
 let ui;try{
  await act(async()=>ui=create(React.createElement(ProfileAvatar,{character:'robot',request:{kind:'idle',nonce:0}}),{createNodeMock:()=>({})}));assert.equal(calls.length,7);const idle=calls.slice();
  await act(async()=>ui.update(React.createElement(ProfileAvatar,{character:'robot',request:{kind:'wave',nonce:1}})));assert(idle.every(c=>c.stopped));const wave=calls.slice(7);assert.equal(wave.length,7);
  await act(async()=>ui.update(React.createElement(ProfileAvatar,{character:'robot',request:{kind:'wave',nonce:1},paused:true})));const pausedCount=calls.length;
  await act(async()=>wave[0].complete());assert.equal(calls.length,pausedCount,'late completion cannot restart idle');
  await act(async()=>ui.update(React.createElement(ProfileAvatar,{character:'robot',request:{kind:'point',nonce:2}})));assert.equal(calls.length,pausedCount+7);const point=calls.slice(-7);
  await act(async()=>ui.unmount());ui=null;assert(point.every(c=>c.stopped));await act(async()=>point[0].complete());assert.equal(calls.length,pausedCount+7);
 }finally{if(ui)await act(async()=>ui.unmount());}
});

test('system reduced motion keeps all three characters static',async()=>{
 let writes=0;const scope={current:null};const {ProfileAvatar}=load('profile-avatar.tsx',{'framer-motion':{useAnimate:()=>[scope,()=>{writes++;}],useReducedMotion:()=>true}});
 for(const character of ['comic','robot','rabbit']){let ui;await act(async()=>ui=create(React.createElement(ProfileAvatar,{character,request:{kind:'wave',nonce:1}}),{createNodeMock:()=>({})}));await act(async()=>ui.unmount());}
 assert.equal(writes,0);
});
