const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript'),React=require('react');
const {act,create}=require('react-test-renderer');
function compile(file,imports={}){const filename=path.resolve(__dirname,'../src/client/'+file),mod=new Module(filename,module);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));const original=mod.require.bind(mod);mod.require=id=>id in imports?imports[id]:id.endsWith('.css')?{}:original(id);mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);return mod.exports;}
const state=compile('workflow-state.ts');
test('manual connection validation rejects cycles, self links, duplicate edges and invalid branch handles',()=>{
  const graph={nodes:[{id:'trigger',kind:'trigger'},{id:'a',kind:'condition'},{id:'b',kind:'ai'},{id:'c',kind:'ai'}],edges:[{source:'trigger',target:'a',branch:''},{source:'a',target:'b',branch:'true'}]};
  assert.match(state.connectionError(graph,'b','a'),/循环/);
  assert.match(state.connectionError(graph,'b','b'),/自己/);
  assert.match(state.connectionError(graph,'b','trigger'),/触发/);
  assert.match(state.connectionError(graph,'a','b','true'),/存在/);
  assert.match(state.connectionError(graph,'a','c'),/条件/);
  assert.equal(state.connectionError(graph,'a','c','false'),'');
  assert.equal(state.connectionError(graph,'b','c'),'');
});
test('workflow input preview preserves unknown values and never evaluates commands',()=>{
  const receipts={a:{output:{text:'$(do-not-run)',urls:['https://example.org']}}};
  assert.equal(state.resolvePreview({text:'{{a.text}}'},receipts).text,'$(do-not-run)');
  assert.equal(state.resolvePreview({text:'{{missing.text}}'},receipts).text,'（上游尚未取得）');
  assert.equal(state.describeTarget({kind:'base',config:{base_token:'b',table_id:'t'}}),'b / t');
  assert.equal(state.editableRun({state:'unknown'}),false);
  assert.equal(state.editableRun({state:'failed'}),true);
});

test('the designer connection form and canvas both update the graph and reject a back edge',async()=>{
  const graph={nodes:[{id:'trigger',kind:'trigger',config:{text:''},position:{x:0,y:0}},{id:'first',kind:'ai',config:{prompt:'one',model_id:''},position:{x:300,y:0}}],edges:[{source:'trigger',target:'first',branch:''}]};
  const definition={id:'saved',name:'编辑',revision:1,version:'a'.repeat(64),graph};
  const catalog=[{kind:'trigger',label:'触发',defaults:{text:''},outputs:['text'],writes:false},{kind:'ai',label:'AI处理',defaults:{prompt:'',model_id:''},outputs:['text'],writes:false}];
  const rpc=async(_info,_method,{operation}={})=>operation==='catalog'?{ok:true,nodes:catalog}:operation==='list'?{ok:true,definitions:[definition],runs:[]}:operation==='load'?{ok:true,definition}:{ok:true,templates:[]};
  const flow={ReactFlow:props=>React.createElement('div',null,props.children),ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,{...edge,id:'added'}],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,fitView(){}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':{WorkflowSchedules:()=>null},'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
  const previous=global.window;global.window={setInterval:()=>1,clearInterval(){},confirm:()=>true};let view;
  try{
    await act(async()=>{view=create(React.createElement(editor.WorkflowPane,{info:{port:1,token:'fixture'}}));});
    await act(async()=>view.root.findByProps({'aria-label':'已保存工作流'}).props.onChange({target:{value:'saved'}}));
    const button=text=>view.root.findAllByType('button').find(n=>n.children[0]===text);
    await act(async()=>button('AI处理').props.onClick());
    let canvas=()=>view.root.findByType(flow.ReactFlow).props;
    const added=canvas().nodes.find(n=>!['trigger','first'].includes(n.id)).id;
    act(()=>view.root.findByProps({'aria-label':'连接起点'}).props.onChange({target:{value:'first'}}));
    act(()=>view.root.findByProps({'aria-label':'连接终点'}).props.onChange({target:{value:added}}));
    act(()=>button('连接节点').props.onClick());
    assert.equal(canvas().edges.length,2);assert.equal(canvas().edges[1].target,added);
    act(()=>canvas().onConnect({source:added,target:'first',sourceHandle:null,targetHandle:null}));
    assert.equal(canvas().edges.length,2);assert.match(JSON.stringify(view.toJSON()),/形成循环/);
    assert.equal(canvas().connectOnClick,true);assert.equal(canvas().connectionRadius,28);
    act(()=>canvas().onEdgeClick({},canvas().edges[1]));act(()=>button('删除所选连线').props.onClick());assert.equal(canvas().edges.length,1);
  }finally{act(()=>view?.unmount());global.window=previous;}
});

test('workflow publishing previews the fixed target before sending, and a lost response retains the submission key',async()=>{
  const calls=[];let failures=1;
  const graph={nodes:[{id:'trigger',kind:'trigger',config:{text:''},position:{x:0,y:0}},{id:'send',kind:'message',config:{chat_id:'oc_target',text:'{{trigger.text}}',profile:''},position:{x:0,y:100}}],edges:[{source:'trigger',target:'send',branch:''}]};
  const definition={id:'workflow',name:'日报',revision:1,version:'a'.repeat(64),graph};
  const catalog=[{kind:'trigger',label:'触发',defaults:{text:''},outputs:['text'],writes:false},{kind:'message',label:'发送群消息',defaults:{chat_id:'',text:'',profile:''},outputs:['message_id'],writes:true}];
  const run={id:'run',workflow:'workflow',version:definition.version,name:'日报',mode:'full',state:'running',receipts:{},approved:['send'],graph};
  const rpc=async(_info,method,{operation,payload}={})=>{calls.push([method,operation,payload]);if(operation==='catalog')return{ok:true,nodes:catalog};if(operation==='list')return{ok:true,definitions:[definition],runs:[]};if(operation==='load')return{ok:true,definition};if(operation==='check_targets')return{ok:true,targets:[{node:'send',target:'oc_target',name:'目标群'}]};if(operation==='start'){if(failures-- >0)throw Error('WebSocket disconnected');return{ok:true,run};}return{ok:true};};
  const flow={ReactFlow:props=>React.createElement('div',{'data-canvas':true},props.children),ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,edge],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,fitView:()=>{}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':{WorkflowSchedules:()=>null},'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
  const previous=global.window;global.window={setInterval:()=>1,clearInterval(){},confirm:()=>true};
  let renderer;
  try{
    await act(async()=>{renderer=create(React.createElement(editor.WorkflowPane,{info:{port:1,token:'test'}}));});
    await act(async()=>renderer.root.findByProps({'aria-label':'已保存工作流'}).props.onChange({target:{value:'workflow'}}));
    const button=text=>renderer.root.findAllByType('button').find(node=>node.children.join('')===text);
    act(()=>renderer.root.findByProps({'aria-label':'工作流触发输入'}).props.onChange({target:{value:'已确认的正文'}}));
    await act(async()=>button('运行工作流').props.onClick());
    assert.equal(calls.filter(c=>c[1]==='start').length,0);
    assert.match(JSON.stringify(renderer.toJSON()),/oc_target/);
    assert.match(JSON.stringify(renderer.toJSON()),/已确认的正文/);
    assert.equal(renderer.root.findByProps({'aria-label':'工作流执行记录'}).props.disabled,true);
    assert.equal(renderer.root.findByProps({'aria-label':'工作流触发输入'}).props.disabled,true);
    await act(async()=>renderer.root.findByProps({'aria-label':'工作流执行记录'}).props.onChange({target:{value:'foreign-run'}}));
    assert.equal(calls.some(c=>c[1]==='get'),false);
    await act(async()=>button('确认目标并继续执行').props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()),/WebSocket disconnected/);
    act(()=>renderer.root.findByProps({'aria-label':'工作流触发输入'}).props.onChange({target:{value:'未确认的新输入'}}));
    await act(async()=>button('确认目标并继续执行').props.onClick());
    assert.equal(calls.filter(c=>c[1]==='start').length,1);
    assert.match(JSON.stringify(renderer.toJSON()),/重新核对目标与内容/);
    act(()=>renderer.root.findByProps({'aria-label':'工作流触发输入'}).props.onChange({target:{value:'已确认的正文'}}));
    await act(async()=>button('运行工作流').props.onClick());
    await act(async()=>button('确认目标并继续执行').props.onClick());
    const submitted=calls.filter(c=>c[1]==='start');assert.equal(submitted.length,2);
    assert.equal(submitted[0][2].request_id,submitted[1][2].request_id);
    assert.equal(submitted[1][2].confirm_writes,true);
    assert.equal(submitted[1][2].version,definition.version);
  }finally{act(()=>renderer?.unmount());global.window=previous;}
});

test('editing an existing schedule keeps its ID, name, disabled state and frozen workflow version',async()=>{
  const calls=[],graph=state.initialGraph(),definition={id:'w',name:'工作流当前名称',revision:4,version:'b'.repeat(64),graph};
  const job={id:'original-job',name:'自定义计划名称',action:'workflow',enabled:false,cadence:'daily',hour:9,minute:0,weekdays:[],workflow_id:'w',workflow_version:definition.version};
  const catalog=[{kind:'trigger',label:'触发',defaults:{text:''},outputs:['text'],writes:false}];
  const rpc=async(_info,method,args={})=>{calls.push([method,args]);if(method==='save_automation_job')return{ok:true,job_id:job.id};if(args.operation==='catalog')return{ok:true,nodes:catalog};if(args.operation==='list')return{ok:true,definitions:[definition],runs:[]};if(args.operation==='load')return{ok:true,definition};return{ok:true,templates:[]};};
  const Schedules=()=>null;
  const flow={ReactFlow:props=>React.createElement('div',null,props.children),ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,edge],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,fitView(){}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':{WorkflowSchedules:Schedules},'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
  const previous=global.window;global.window={setInterval:()=>1,clearInterval(){},confirm:()=>true};let view;
  try{
    await act(async()=>{view=create(React.createElement(editor.WorkflowPane,{info:{port:1,token:'fixture'}}));});
    await act(async()=>view.root.findByType(Schedules).props.onEdit(job));
    const load=calls.find(c=>c[1].operation==='load')[1];assert.equal(load.payload.version,job.workflow_version);
    act(()=>view.root.findAllByType('input').find(n=>n.props.type==='time').props.onChange({target:{value:'10:00'}}));
    await act(async()=>view.root.findAllByType('button').find(n=>n.children[0]==='保存触发计划').props.onClick());
    const saved=calls.find(c=>c[0]==='save_automation_job')[1].payload;
    assert.equal(saved.id,job.id);assert.equal(saved.name,job.name);assert.equal(saved.enabled,false);assert.equal(saved.hour,10);assert.equal(saved.minute,0);assert.equal(saved.workflow_version,job.workflow_version);
  }finally{act(()=>view?.unmount());global.window=previous;}
});
