const {test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer');
const {randomUUID}=require('node:crypto');
const load=require('./load-client.cjs');
const state=load('personalization-state.ts');
const {PersonalizationController,PERSONALIZATION_FIXTURE,PROFILE_MARKER}=state;
const page=extra=>({...structuredClone(PERSONALIZATION_FIXTURE),...extra});
const memory=()=>{const values=new Map();return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
const text=node=>typeof node==='string'?node:(node.children||[]).map(text).join('');

test('a lost mutation reply is resolved by its original receipt, never automatically replayed',async()=>{
  const storage=memory(),id=randomUUID();let writes=0,accepted=false;
  const wire=async(method,args)=>{
    if(method==='personalization_action'){writes++;accepted=true;throw Error('断连');}
    return page({receipt:accepted?{id,record_id:id,version:1}:null});
  };
  const controller=new PersonalizationController(wire,storage,()=>id);await controller.read();
  assert.equal(await controller.act('save',{payload:{text:'确认内容'}}),false);
  assert.equal(controller.unknown.id,id);assert.equal(await controller.act('save'),false);
  const restored=new PersonalizationController(wire,storage,randomUUID);await restored.read();
  assert.equal(restored.unknown,null);assert.equal(writes,1);
});

test('sync submission is reconciled by job ID and never starts a duplicate job on reload',async()=>{
  const storage=memory(),id=randomUUID();storage.setItem(PROFILE_MARKER,JSON.stringify({id,type:'sync'}));
  let writes=0;const controller=new PersonalizationController(async(method,args)=>{
    if(method!=='personalization_status')writes++;
    assert.equal(args.job_id,id);return page({job:{id,state:'running',processed:0,error:''}});
  },storage,randomUUID);
  await controller.read();assert.equal(controller.unknown,null);assert.equal(writes,0);
});

test('storage failure prevents submission and definite rejections clear only their marker',async()=>{
  let writes=0;const wire=async method=>{if(method==='personalization_action')writes++;return page({ok:false,accepted:false,error:'版本已变化'});};
  const failed=new PersonalizationController(wire,{getItem:()=>null,setItem(){throw Error();},removeItem(){}},randomUUID);
  await failed.read();await failed.act('save');assert.equal(writes,0);
  const rejected=new PersonalizationController(wire,memory(),randomUUID);await rejected.read();await rejected.act('save');
  assert.equal(rejected.unknown,null);assert.equal(rejected.error,'版本已变化');assert.equal(writes,1);
});

test('a lost cancellation reply is reconciled against the original job',async()=>{
  const storage=memory(),id=randomUUID(),job=randomUUID();let cancelled=false;
  const controller=new PersonalizationController(async(method,args)=>{
    if(method==='personalization_action'){assert.equal(args.payload.job_id,job);cancelled=true;throw Error('断连');}
    return page({job:{id:job,state:'running',processed:1,error:'',cancel_requested:cancelled}});
  },storage,()=>id);
  await controller.read();await controller.act('cancel');assert.equal(controller.unknown.job_id,job);
  await controller.read();assert.equal(controller.unknown,null);
});

test('late reads cannot replace a newer mutation or silently change the account binding',async()=>{
  let release,reads=0;const slow=new Promise(r=>release=r),id=randomUUID();
  const controller=new PersonalizationController(async method=>method==='personalization_action'?page({revision:4,receipt:{id}}):++reads===1?page({}):slow,memory(),()=>id);
  await controller.read(true);const read=controller.read();await controller.act('save');release(page({revision:2}));await read;
  assert.equal(controller.page.revision,4);assert.equal(controller.page.scopes.length,2);
  controller.wire=async()=>page({revision:5,account:{key:'b'.repeat(64)}});
  assert.equal(await controller.read(),false);assert.match(controller.error,/账号/);
});

test('profile cards show kinds, scope, both conflict versions and field-local errors',async()=>{
  const wire=async(_info,method)=>method==='personalization_status'?page({}):page({ok:false,accepted:false,error:'资料已变化，请重新读取'});
  const {PersonalizationPane}=load('personalization.tsx',{'./personalization-state':state,'./personalization.css':{},'./api':{rpc:wire}});
  const previous=global.localStorage;global.localStorage=memory();let ui;
  try{
    await act(async()=>{ui=create(React.createElement(PersonalizationPane,{info:{port:1,token:'synthetic'}}));});
    assert.equal(ui.root.findAll(n=>n.type==='button'&&n.props.className==='profile-domain').length,4);
    await act(async()=>ui.root.findAllByType('button').find(n=>text(n)==='已有资料').props.onClick());
    assert.equal(ui.root.findAll(n=>n.type==='article'&&n.props.className?.includes('profile-card')).length,3);
    assert.match(text(ui.toJSON()),/云端当前版本 · v3/);assert.match(text(ui.toJSON()),/项目 · tebb/);
    const add=ui.root.findAllByType('button').find(n=>text(n).includes('新增资料'));
    await act(async()=>add.props.onClick());
    const input=ui.root.findByType('textarea');await act(async()=>input.props.onChange({target:{value:'我的确认偏好'}}));
    await act(async()=>ui.root.findByType('form').props.onSubmit({preventDefault(){}}));
    assert.equal(ui.root.findByType('textarea').props.value,'我的确认偏好');
    const field=ui.root.findAll(n=>n.props['data-ui-control']==='field').find(n=>text(n).includes('确认内容'));
    assert.match(text(field),/资料已变化/);
  }finally{if(ui)await act(async()=>ui.unmount());global.localStorage=previous;}
});
