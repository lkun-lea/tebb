const {test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer');
const {randomUUID}=require('node:crypto');
const load=require('./load-client.cjs');
const {AccountController,ACCOUNT_FIXTURE,ACCOUNT_MARKER_KEY}=load('account-state.ts');
const memory=()=>{const values=new Map();return {values,getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
const page=extra=>({...structuredClone(ACCOUNT_FIXTURE),...extra});
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:value=>resolve(value)};};
const text=node=>typeof node==='string'?node:(node.children||[]).map(text).join('');

test('browser preferences and pending receipts are isolated and a live webview cannot change its binding',()=>{
  const raw=memory(),a=load('account-storage.ts'),b=load('account-storage.ts'),local=load('account-storage.ts');
  raw.setItem('tebb.theme','local preference');a.initializeAccountStorage('a'.repeat(64));b.initializeAccountStorage('b'.repeat(64));local.initializeAccountStorage('local');
  const first=a.accountStorage(raw),second=b.accountStorage(raw);
  first.setItem('tebb.theme','A');second.setItem('tebb.theme','B');first.setItem(ACCOUNT_MARKER_KEY,'original A operation');
  assert.equal(first.getItem('tebb.theme'),'A');assert.equal(second.getItem('tebb.theme'),'B');assert.equal(second.getItem(ACCOUNT_MARKER_KEY),null);
  assert.equal(local.accountStorage(raw).getItem('tebb.theme'),'local preference');
  assert.throws(()=>a.initializeAccountStorage('b'.repeat(64)),/重启/);assert.equal(first.getItem('tebb.theme'),'A');
  assert.throws(()=>load('account-storage.ts').initializeAccountStorage('../other'),/标识/);
});

test('account requests persist only an operation marker, and disconnected verification is reconciled without resend',async()=>{
  const storage=memory(),calls=[],id=randomUUID();let failed=true;
  const controller=new AccountController(async(method,args)=>{
    calls.push([method,args]);
    if(method==='account_action')throw Error('connection closed');
    return page(failed?{}:{version:2,selected:'a'.repeat(64),restart_required:true,operation:{id,type:'verify_code',state:'complete'}});
  },storage,()=>id);
  await controller.read();await controller.act('verify_code',{code:'123456',challenge_id:randomUUID()});
  assert.ok(controller.unknown);assert.doesNotMatch(storage.getItem(ACCOUNT_MARKER_KEY),/123456|challenge/);
  assert.equal(await controller.act('verify_code',{code:'123456'}),false);assert.equal(calls.filter(([method])=>method==='account_action').length,1);
  failed=false;await controller.read();assert.equal(controller.unknown,null);assert.equal(controller.page.restart_required,true);
  assert.equal(storage.getItem(ACCOUNT_MARKER_KEY),null);
});

test('an interrupted acknowledgement preserves the original request across reloads and rejected acknowledgements',async()=>{
  const storage=memory(),original=randomUUID(),ack=randomUUID();storage.setItem(ACCOUNT_MARKER_KEY,JSON.stringify({id:original,type:'send_code'}));
  const calls=[];const controller=new AccountController(async(method,args)=>{
    if(method==='account_session')return page({version:3});
    calls.push(args.payload);throw Error('unknown acknowledgement');
  },storage,()=>ack);
  await controller.read();await controller.act('acknowledge');
  const marker=JSON.parse(storage.getItem(ACCOUNT_MARKER_KEY));assert.equal(marker.original_id,original);assert.equal(marker.id,ack);
  const restored=new AccountController(async(method,args)=>{
    if(method==='account_session')return page({version:5});
    calls.push(args.payload);return page({ok:false,code:'version_conflict',version:6});
  },storage,randomUUID);
  await restored.read();await restored.act('acknowledge');assert.equal(calls.at(-1).operation_id,original);
  assert.equal(restored.unknown.original_id,original);assert.equal(restored.unknown.id,ack);
});

test('reconciliation of a failed code keeps its error associated with verification rather than reporting success',async()=>{
  const storage=memory(),id=randomUUID();storage.setItem(ACCOUNT_MARKER_KEY,JSON.stringify({id,type:'verify_code'}));
  const controller=new AccountController(async()=>page({version:2,operation:{id,type:'verify_code',state:'failed',error:'验证码无效'}}),storage,randomUUID);
  await controller.read();assert.equal(controller.unknown,null);assert.equal(controller.error,'验证码无效');
  assert.equal(controller.errorType,'verify_code');assert.equal(controller.notice,'');
});

test('definite rejections clear only their marker and retain failure text and current account',async()=>{
  const storage=memory(),controller=new AccountController(async method=>method==='account_session'?page({}):page({ok:false,accepted:false,code:'invalid_config',error:'公开密钥无效'}),storage,randomUUID);
  await controller.read();assert.equal(await controller.act('configure',{publishable_key:'wrong'}),false);
  assert.equal(controller.unknown,null);assert.equal(controller.error,'公开密钥无效');assert.equal(controller.page.runtime.key,'local');
});

test('a late read cannot overwrite newer account state or change the frozen binding',async()=>{
  const slow=deferred(),storage=memory();let reads=0;
  const controller=new AccountController(async method=>{
    if(method==='account_session')return ++reads===1?page({version:0}):slow.promise;
    return page({version:2,selected:'a'.repeat(64),restart_required:true,operation:{id:'op',type:'send_code',state:'complete'}});
  },storage,()=> 'op');
  await controller.read();const read=controller.read();await controller.act('send_code',{email:'a@tebb.invalid'});
  slow.resolve(page({version:0}));await read;assert.equal(controller.page.version,2);assert.equal(controller.page.restart_required,true);
  const other=new AccountController(async()=>page({runtime:{key:'a'.repeat(64),mode:'account',email:'a@tebb.invalid'}}),storage,randomUUID);
  await other.read();other['wire']=async()=>page({runtime:{key:'b'.repeat(64),mode:'account',email:'b@tebb.invalid'}});
  assert.equal(await other.read(),false);assert.match(other.error,/绑定/);assert.equal(other.page.runtime.key,'a'.repeat(64));
});

test('failure to save a request ID prevents any mutation from being submitted',async()=>{
  let writes=0;const storage={getItem:()=>null,setItem(){throw Error('denied');},removeItem(){}};
  const controller=new AccountController(async method=>{if(method==='account_action')writes++;return page({});},storage,randomUUID);
  await controller.read();assert.equal(await controller.act('send_code',{email:'a@tebb.invalid'}),false);assert.equal(writes,0);
});

test('the workspace stays unmounted until its backend account is verified and cache partitioned',async()=>{
  const response=deferred(),initialized=[],progress=[];let mounts=0;
  function Workspace(){React.useEffect(()=>{mounts++;},[]);return React.createElement('div',{},'private workspace');}
  const {AccountBootstrap}=load('account-bootstrap.tsx',{'./api':{backendInfo:async()=>({port:1,token:'synthetic'}),rpc:()=>response.promise},'./debug':{debugPane:()=>null},
    './account-storage':{initializeAccountStorage:key=>initialized.push(key)},'./startup':{startupStatus:text=>progress.push(text),startupFailed(){}}});
  let view;await act(async()=>{view=create(React.createElement(AccountBootstrap,{},React.createElement(Workspace)));});assert.equal(mounts,0);
  await act(async()=>response.resolve({runtime:{key:'a'.repeat(64)}}));assert.equal(mounts,1);assert.deepEqual(initialized,['a'.repeat(64)]);
  await act(async()=>view.unmount());
});

test('failed account initialization never mounts workspace or reads another account cache',async()=>{
  let mounts=0,failures=0;
  const {AccountBootstrap}=load('account-bootstrap.tsx',{'./api':{backendInfo:async()=>{throw Error('offline');}},'./debug':{debugPane:()=>null},
    './account-storage':{initializeAccountStorage:()=>{mounts++;}},'./startup':{startupStatus(){},startupFailed(){failures++;}}});
  let view;await act(async()=>{view=create(React.createElement(AccountBootstrap,{},React.createElement('div',{},'private workspace')));});
  assert.equal(mounts,0);assert.equal(failures,1);assert.doesNotMatch(text(view.root),/private workspace/);await act(async()=>view.unmount());
});

test('unconfigured account UI exposes configuration state, disables email sends and never restarts automatically',async()=>{
  const calls=[];global.localStorage=memory();global.crypto=require('node:crypto').webcrypto;
  const state=load('account-state.ts');
  const {AccountsPane}=load('accounts.tsx',{'./account-state':state,'./api':{rpc:async(_info,method)=>{calls.push(method);return page({});}},
    '@tauri-apps/api/core':{invoke:async()=>{throw Error('no automatic restart');}},'./accounts.css':{}});
  let view;await act(async()=>{view=create(React.createElement(AccountsPane,{info:{port:1,token:'synthetic'}}));});
  assert.match(text(view.root),/账号服务尚未配置/);assert.equal(view.root.findAllByType('button').find(n=>text(n)==='获取验证码').props.disabled,true);
  assert.deepEqual(calls,['account_session']);await act(async()=>view.unmount());delete global.localStorage;
});

test('a rejected code is explained beside the invalid field and the same login step can be corrected',async()=>{
  global.localStorage=memory();global.crypto=require('node:crypto').webcrypto;
  const challenge={id:randomUUID(),email:'a@tebb.invalid',expires_at:Date.now()/1000+600};
  const initial=page({configured:true,config_managed:true,challenge}),calls=[];let focused=0,scrolled=0;
  const state=load('account-state.ts');
  const {AccountsPane}=load('accounts.tsx',{'./account-state':state,'./api':{rpc:async(_info,method,args)=>{
    if(method==='account_session')return initial;
    const payload=args.payload;calls.push(payload);
    return payload.code==='000000'?{...initial,version:2,ok:false,error:'验证码已过期或无效，请重新获取。',
      operation:{id:payload.request_id,type:'verify_code',state:'failed',code:'invalid_otp'}}:
      page({configured:true,config_managed:true,version:4,selected:'a'.repeat(64),restart_required:true,
        operation:{id:payload.request_id,type:'verify_code',state:'complete'}});
  }},'@tauri-apps/api/core':{invoke:async()=>{throw Error('no automatic restart');}},'./accounts.css':{}});
  let view;await act(async()=>{view=create(React.createElement(AccountsPane,{info:{port:1,token:'synthetic'}}),{
    createNodeMock:element=>element.props.autoComplete==='one-time-code'?{focus(){focused++;},parentElement:{scrollIntoView(){scrolled++;}}}:null,
  });});
  await act(async()=>view.root.findByProps({autoComplete:'email'}).props.onChange({target:{value:challenge.email}}));
  await act(async()=>view.root.findByProps({autoComplete:'one-time-code'}).props.onChange({target:{value:'000000'}}));
  const verifyForm=()=>view.root.findAllByType('form').find(n=>n.findAllByProps({autoComplete:'one-time-code'}).length);
  await act(async()=>verifyForm().props.onSubmit({preventDefault(){}}));
  const code=view.root.findByProps({autoComplete:'one-time-code'}),field=code.parent;
  assert.equal(code.props['aria-invalid'],true);assert.equal(code.props.value,'');
  assert.match(text(field),/验证码已过期或无效/);assert.equal(field.findByProps({role:'alert'}).type,'span');
  assert.equal(view.root.findAllByProps({'data-ui-feedback':'error'}).length,0);
  assert.equal(view.root.findByProps({autoComplete:'email'}).props.value,challenge.email);
  assert.equal(focused,1);assert.equal(scrolled,1);
  await act(async()=>view.root.findByProps({autoComplete:'one-time-code'}).props.onChange({target:{value:'123456'}}));
  await act(async()=>verifyForm().props.onSubmit({preventDefault(){}}));
  assert.equal(calls.length,2);assert.equal(calls[1].challenge_id,challenge.id);
  assert.match(text(view.root),/待重启切换空间/);assert.doesNotMatch(text(view.root),/验证码已过期或无效/);
  await act(async()=>view.unmount());delete global.localStorage;
});
