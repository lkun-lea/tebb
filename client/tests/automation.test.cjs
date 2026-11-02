const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript'),React=require('react');
const {act,create}=require('react-test-renderer');
function component(file,imports){const filename=path.resolve(__dirname,'../src/client/'+file),m=new Module(filename,module);m.filename=filename;m.paths=Module._nodeModulePaths(path.dirname(filename));const original=m.require.bind(m);m.require=id=>id in imports?imports[id]:original(id);m._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);return m.exports;}

test('automation has one workflow workspace and never mounts the old news or job creation UI',async()=>{
  const Workflow=()=>React.createElement('div',{'data-design-page':true});
  const module=component('automation.tsx',{react:{...React,lazy:()=>Workflow}});
  let view;await act(async()=>{view=create(React.createElement(module.AutomationPane,{info:{port:1,token:'fixture'}}));});
  assert.equal(view.root.findAllByProps({'data-design-page':true}).length,1);
  assert.doesNotMatch(JSON.stringify(view.toJSON()),/已有自动化|生成今日预览|发布这份日报/);
  act(()=>view.unmount());
});

test('old schedules remain visible and are only disabled explicitly; active jobs and legacy re-enabling are blocked',async()=>{
  let refresh,fail=false;const calls=[];
  let job={id:'original',name:'原资讯计划',action:'ai_news',enabled:true,active:false,last_result:'ok'};
  const rpc=async(_info,method,args)=>{calls.push([method,args]);if(method==='list_automation_jobs')return{ok:true,items:[{...job}]};if(fail)return{ok:false,error:'已保存，但列表读取失败'};job={...job,enabled:args.payload.enabled};return{ok:true};};
  const {WorkflowSchedules,useWorkflowSchedules}=component('workflow-schedules.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true}});
  function Schedules(){const state=useWorkflowSchedules({port:1,token:'fixture'});return React.createElement(WorkflowSchedules,{state});}
  const previous=global.window;global.window={setInterval:fn=>{refresh=fn;return 1;},clearInterval(){}};let view;
  try{
    await act(async()=>{view=create(React.createElement(Schedules));});
    const button=text=>view.root.findAllByType('button').find(n=>n.children.join('')===text);
    assert.match(JSON.stringify(view.toJSON()),/原有计划仍按原规则运行/);assert.equal(calls.filter(c=>c[0]==='save_automation_job').length,0);
    fail=true;await act(async()=>button('停用计划').props.onClick());assert.match(JSON.stringify(view.toJSON()),/先刷新核对/);
    assert.equal(calls.at(-1)[1].payload.id,'original');
    fail=false;job.active=true;await act(async()=>refresh());assert.equal(button('停用计划').props.disabled,true);
    job.active=false;await act(async()=>refresh());await act(async()=>button('停用计划').props.onClick());
    assert.equal(job.enabled,false);assert.equal(button('启用此工作流版本').props.disabled,true);
    assert.equal(calls.some(c=>c[0]==='run_automation_job'),false);
  }finally{act(()=>view?.unmount());global.window=previous;}
});
