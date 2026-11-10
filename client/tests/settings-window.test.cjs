const {test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer');const load=require('./load-client.cjs');
const {MODELS_FIXTURE}=load('settings.tsx');

// 内存 localStorage：设置窗口读取主题与背景时使用。
function storageStub(){const map=new Map();return{getItem:k=>map.has(k)?map.get(k):null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k)};}
stubWindow();
function stubWindow(search=''){
  global.window={innerWidth:1024,innerHeight:768,opener:null,location:{search},addEventListener(){},removeEventListener(){},dispatchEvent(){}};
  global.document={documentElement:{classList:{toggle(){}}},body:{},querySelector:()=>null,querySelectorAll:()=>[]};
  global.localStorage=storageStub();
}

const panes={
  './accounts':{AccountsPane:() => null},
  './reminders':{ReminderSettings:() => null},
  './usage-center':{PersonalUsagePane:() => null},
  './release':{useReleaseIntro:()=>({open:false,show(){},close(){},daily:false,setDaily(){},preferenceError:''}),ReleaseSettings:() => null,ReleaseIntro:() => null},
  './model-network':{ModelNetworkSettings:() => null},
  './search-settings':{SearchSettings:() => null},
  './feishu':{FeishuPane:() => null,feishuLoggedIn:snap=>!!snap&&!!snap.logged_in,feishuWaiting:snap=>!!snap&&!!snap.login_busy},
  './feishu-agent':{FeishuAgentPane:() => null},
  './video':{VideoLogin:() => null,VideoSettings:() => null},
  './agent-debug':{AgentDebugDialog:() => null},
  './status':{StatusGrid:() => null,loadingStatuses:() => [],statusError:() => null,statusFromPayload:() => null,STATUS_KINDS:[]},
  './companion-ui':{readDeveloperMode:()=>false},
  './onboarding':{SetupGuide:() => null},
  './personalization':{PersonalizationPane:() => null},
};
function settingsApp({debugKind=null,rpc,backendInfo}={}){
  const calls=[];
  const rpcMock=async(_info,method)=>{calls.push(method);
    if(method==='load_models')return{ok:true,active:MODELS_FIXTURE.active,items:MODELS_FIXTURE.items};
    if(method==='load_persona')return{ok:true,persona:'tebb',max_steps:8,nudge_enabled:true};
    if(method==='load_onboarding')return{ok:true,show:false,configured:true,checks:{}};
    return{ok:true};};
  const apiMock={rpc:rpc||rpcMock,backendInfo:backendInfo||(async()=>({port:9,token:'isolated'}))};
  const debugMock={debugPane:()=>debugKind,installDeskDebug:()=>{},STATUS_FIXTURE:[]};
  const settingsModule=load('settings.tsx');
  const settingsState=load('settings-state.ts',{'./settings':settingsModule,'./api':apiMock,'./debug':debugMock,'./feishu':panes['./feishu']});
  const mocks={...panes,
    './api':apiMock,
    './settings':settingsModule,
    './settings-state':settingsState,
    '@tauri-apps/api/core':{invoke:async()=>({}),isTauri:()=>false},
    '@tauri-apps/api/event':{listen:async()=>()=>{}},
    './debug':debugMock,
  };
  return{SettingsApp:load('settings-app.tsx',mocks).SettingsApp,calls};
}
const text=node=>typeof node==='string'?node:(node.children||[]).map(text).join('');
const navItems=view=>view.root.findAll(node=>node.props['data-settings-nav-item']!==undefined&&node.type==='button');
const modelEntries=view=>view.root.findAll(node=>node.props['data-model-entry']!==undefined&&node.type==='button');
const searchBox=view=>view.root.findByProps({'aria-label':'搜索设置分类'});

test('分组导航覆盖现有分类并按大分组组织',()=>{
  const {SettingsApp}=settingsApp({debugKind:'settings'});
  let view;act(()=>{view=create(React.createElement(SettingsApp));});
  assert.equal(view.root.findByProps({'data-settings-shell':'1'}).props['data-settings-section'],'assistant');
  const groups=view.root.findAllByProps({className:'settings-nav-group-label'}).map(text);
  assert.deepEqual(groups,['通用','连接与数据','账号与关于']);
  assert.deepEqual(navItems(view).map(node=>node.props['data-settings-nav-item']),
    ['assistant','appearance','connections','usage','account','personalization','about']);
  act(()=>view.unmount());
});

test('搜索按分类与关键词过滤，清空恢复，无匹配给出状态',()=>{
  const {SettingsApp}=settingsApp({debugKind:'settings'});
  let view;act(()=>{view=create(React.createElement(SettingsApp));});
  act(()=>{searchBox(view).props.onChange({target:{value:'飞书'}});});
  assert.deepEqual(navItems(view).map(node=>node.props['data-settings-nav-item']),['connections']);
  act(()=>{searchBox(view).props.onChange({target:{value:'不存在的项'}});});
  assert.equal(navItems(view).length,0);
  assert(text(view.root).includes('没有匹配的分类'));
  act(()=>{searchBox(view).props.onChange({target:{value:''}});});
  assert.equal(navItems(view).length,7);
  act(()=>view.unmount());
});

test('点击导航切换分类并更新内容标题',()=>{
  const {SettingsApp}=settingsApp({debugKind:'settings'});
  let view;act(()=>{view=create(React.createElement(SettingsApp));});
  act(()=>{view.root.findAll(node=>node.props['data-settings-nav-item']==='about')[0].props.onClick();});
  assert.equal(view.root.findByProps({'data-settings-shell':'1'}).props['data-settings-section'],'about');
  assert(text(view.root).includes('版本与诊断'));
  act(()=>view.unmount());
});

test('外观分类渲染主题与背景卡片并隐藏模型表单',()=>{
  global.window.location.search='?debug=settings&section=appearance';
  const {SettingsApp}=settingsApp({debugKind:'settings'});
  let view;act(()=>{view=create(React.createElement(SettingsApp));});
  assert.equal(view.root.findByProps({'data-settings-shell':'1'}).props['data-settings-section'],'appearance');
  const rendered=text(view.root);
  assert(rendered.includes('外观'));
  assert.equal(view.root.findAll(node=>node.props['data-theme']!==undefined).length,1);
  assert.equal(view.root.findAllByProps({'data-bg-pick':true}).length,1);
  // 模型卡片仍挂载但通过 hidden 属性收起，切换分类不丢表单状态。
  const modelSection=view.root.findAllByType('section').find(node=>text(node).startsWith('模型'));
  assert.equal(modelSection.props.hidden,true);
  global.window.location.search='';
  act(()=>view.unmount());
});

test('连接后真实读取模型列表并渲染可选模型',async()=>{
  const {SettingsApp,calls}=settingsApp();
  let view;await act(async()=>{view=create(React.createElement(SettingsApp));});
  assert.ok(calls.includes('load_models'));
  const entries=modelEntries(view);
  assert.equal(entries.length,MODELS_FIXTURE.items.length);
  await act(async()=>{entries[1].props.onClick();});
  assert.deepEqual(modelEntries(view).map(node=>node.props['data-selected']),['0','1']);
  act(()=>view.unmount());
});

test('后端未连上时给出可读错误而不是空面板',async()=>{
  const offline=async()=>{throw Error('backend offline');};
  const {SettingsApp}=settingsApp({rpc:offline,backendInfo:offline});
  let view;await act(async()=>{view=create(React.createElement(SettingsApp));});
  assert(text(view.root).includes('连不上本地助手'));
  act(()=>view.unmount());
});
