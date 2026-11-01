const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript'),React=require('react');
const {act,create}=require('react-test-renderer');
function compile(file,imports={}){const filename=path.resolve(__dirname,'../src/client/'+file),mod=new Module(filename,module);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));const original=mod.require.bind(mod);mod.require=id=>{if(id in imports)return imports[id];if(id.endsWith('.css'))return{};const local=id.startsWith('./')&&['.tsx','.ts'].find(extension=>fs.existsSync(path.resolve(path.dirname(filename),id+extension)));return local?compile(id.slice(2)+local,imports):original(id);};mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);return mod.exports;}
const state=compile('workflow-state.ts');
const alignment=compile('workflow-alignment.ts');

async function draftEditor(){
  const graph={nodes:[{id:'trigger',kind:'trigger',config:{text:''},position:{x:70,y:70}},{id:'ai',kind:'ai',config:{prompt:'{{trigger.text}}',model_id:''},position:{x:350,y:70}}],edges:[{source:'trigger',target:'ai',branch:''}]};
  const templates=[{id:'one',name:'示例一',description:'one',graph},{id:'two',name:'示例二',description:'two',graph}];
  const definitions=[{id:'saved-one',name:'已保存一',revision:1,version:'a'.repeat(64),graph},{id:'saved-two',name:'已保存二',revision:1,version:'b'.repeat(64),graph}];
  const catalog=[{kind:'trigger',label:'触发',defaults:{text:''},outputs:['text'],writes:false},{kind:'ai',label:'AI处理',defaults:{prompt:'',model_id:''},outputs:['text'],writes:false},{kind:'base',label:'表格',defaults:{fields:{内容:'{{trigger.text}}'},base_token:'b',table_id:'t',key_field:'receipt',profile:''},outputs:['record_id'],writes:true}];
  const rpc=async(_info,_method,{operation,payload}={})=>operation==='catalog'?{ok:true,nodes:catalog}:operation==='list'?{ok:true,definitions,runs:[]}:operation==='templates'?{ok:true,templates}:operation==='load'?{ok:true,definition:definitions.find(d=>d.id===payload.id)}:operation==='save'?{ok:true,definition:{...payload,id:'saved-copy',revision:1,version:'c'.repeat(64)}}:{ok:true};
  const {applyNodeChanges}=require('@xyflow/react');
  const flow={ReactFlow:props=>React.createElement('div',null,props.children),ViewportPortal:({children})=>children,ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,edge],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,changes=>set(current=>applyNodeChanges(changes,current))];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,getZoom:()=>1,fitView(){}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':{WorkflowSchedules:()=>null},'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
  const previous=global.window,confirms=[];global.window={setInterval:()=>1,clearInterval(){},confirm:message=>{confirms.push(message);return false;}};let view;
  await act(async()=>{view=create(React.createElement(editor.WorkflowPane,{info:{port:1,token:'fixture'}}));});
  return {view,confirms,canvas:()=>view.root.findByType(flow.ReactFlow).props,choose:async(label,value)=>act(async()=>view.root.findByProps({'aria-label':label}).props.onChange({target:{value}})),button:text=>view.root.findAllByType('button').find(n=>n.children[0]===text),close:()=>{act(()=>view.unmount());global.window=previous;}};
}

test('untouched examples and saved workflows switch without a discard prompt, including unchanged canvas notifications',async()=>{
  const ui=await draftEditor();
  try{
    await ui.choose('示例工作流','one');await ui.choose('示例工作流','two');
    assert.match(ui.view.root.findByProps({'aria-label':'工作流名称'}).props.value,/示例二/);assert.equal(ui.confirms.length,0);
    act(()=>ui.canvas().onNodesChange([{type:'position',id:'trigger',position:{x:70,y:70},dragging:false}]));
    act(()=>ui.canvas().onNodesChange([{type:'select',id:'ai',selected:true},{type:'dimensions',id:'ai',dimensions:{width:180,height:80}}]));
    await ui.choose('已保存工作流','saved-one');await ui.choose('已保存工作流','saved-two');
    assert.equal(ui.view.root.findByProps({'aria-label':'工作流名称'}).props.value,'已保存二');assert.equal(ui.confirms.length,0);
    await ui.choose('示例工作流','one');await act(async()=>ui.button('保存工作流').props.onClick());
    await ui.choose('示例工作流','two');assert.equal(ui.confirms.length,0);
  }finally{ui.close();}
});

test('alignment snaps closest measured edges and centers within screen pixels, and excludes a selected group',()=>{
  const anchor={id:'anchor',position:{x:300,y:100},measured:{width:200,height:80}};
  const moving={id:'moving',position:{x:307,y:105},measured:{width:100,height:60}};
  const snapped=alignment.snapAlignment(moving,[anchor]);assert.equal(snapped.position.x,300);assert.equal(snapped.position.y,100);assert.equal(snapped.guides.length,2);
  assert.equal(alignment.snapAlignment({...moving,position:{x:316,y:500}},[anchor],.5).position.x,300);
  assert.equal(alignment.snapAlignment({...moving,position:{x:307,y:500}},[anchor],2).position.x,307);
  assert.deepEqual(alignment.snapAlignment(moving,[{...anchor,selected:true}]).position,moving.position);
  const nodes=[{...anchor,selected:true},{...moving,selected:true},{id:'fixed',position:{x:900,y:800}}];
  const horizontal=alignment.alignSelection(nodes,'horizontal');assert.equal(horizontal[0].position.y+40,horizontal[1].position.y+30);assert.equal(horizontal[0].position.x,300);assert.strictEqual(horizontal[2],nodes[2]);
  const vertical=alignment.alignSelection(nodes,'vertical');assert.equal(vertical[0].position.x+100,vertical[1].position.x+50);assert.equal(vertical[1].position.y,105);
  assert.strictEqual(alignment.alignSelection([anchor],'vertical')[0],anchor);
});

test('canvas drag guides snap while dragging and on release; alignment toggle and group controls keep drafts valid',async()=>{
  const ui=await draftEditor();
  try{
    await ui.choose('示例工作流','one');
    act(()=>ui.canvas().onNodesChange([{type:'position',id:'trigger',position:{x:347,y:75},dragging:true}]));
    assert.deepEqual(ui.canvas().nodes[0].position,{x:350,y:70});assert.equal(ui.view.root.findAllByType('line').length,2);
    act(()=>ui.canvas().onNodesChange([{type:'position',id:'trigger',position:{x:348,y:74},dragging:false}]));
    assert.deepEqual(ui.canvas().nodes[0].position,{x:350,y:70});assert.equal(ui.view.root.findAllByType('line').length,0);
    const checkbox=ui.view.root.findAllByType('input').find(n=>n.props.type==='checkbox');act(()=>checkbox.props.onChange({target:{checked:false}}));
    act(()=>ui.canvas().onNodesChange([{type:'position',id:'trigger',position:{x:347,y:75},dragging:true}]));assert.deepEqual(ui.canvas().nodes[0].position,{x:347,y:75});
    act(()=>ui.canvas().onNodesChange([{type:'select',id:'trigger',selected:true},{type:'select',id:'ai',selected:true}]));
    assert.equal(ui.button('水平对齐').props.disabled,false);act(()=>ui.button('水平对齐').props.onClick());
    assert.equal(ui.canvas().nodes[0].position.y,ui.canvas().nodes[1].position.y);assert.equal(ui.canvas().edges.length,1);assert.equal(ui.canvas().nodes[1].data.config.prompt,'{{trigger.text}}');
    act(()=>ui.button('竖直对齐').props.onClick());assert.equal(ui.canvas().nodes[0].position.x,ui.canvas().nodes[1].position.x);
    await act(async()=>ui.button('保存工作流').props.onClick());await ui.choose('示例工作流','two');assert.equal(ui.confirms.length,0);
  }finally{ui.close();}
});

test('actual edits require confirmation even for a single trigger; cancelling preserves text and reverting removes the prompt',async()=>{
  const ui=await draftEditor();
  try{
    const text=()=>ui.view.root.findByType('textarea');
    act(()=>text().props.onChange({target:{value:'尚未保存的输入'}}));
    await ui.choose('已保存工作流','saved-one');assert.equal(ui.confirms.length,1);assert.equal(text().props.value,'尚未保存的输入');assert.equal(ui.canvas().nodes.length,1);
    act(()=>text().props.onChange({target:{value:''}}));await ui.choose('示例工作流','one');assert.equal(ui.confirms.length,1);
    const original=ui.view.root.findByProps({'aria-label':'工作流名称'}).props.value;
    await ui.choose('工作流名称','临时改名');await ui.choose('示例工作流','two');assert.equal(ui.confirms.length,2);assert.equal(ui.view.root.findByProps({'aria-label':'工作流名称'}).props.value,'临时改名');
    await ui.choose('工作流名称',original);await ui.choose('示例工作流','two');assert.equal(ui.confirms.length,2);assert.match(ui.view.root.findByProps({'aria-label':'工作流名称'}).props.value,/示例二/);
    act(()=>ui.button('表格').props.onClick());act(()=>ui.canvas().onConnect({source:'trigger',target:ui.canvas().nodes.find(n=>n.data.kind==='base').id}));await act(async()=>ui.button('保存工作流').props.onClick());
    act(()=>ui.view.root.findByProps({'aria-label':'普通文本字段 JSON'}).props.onChange({target:{value:'未完成的 JSON'}}));
    await ui.choose('示例工作流','one');assert.equal(ui.confirms.length,3);assert.equal(ui.view.root.findByProps({'aria-label':'普通文本字段 JSON'}).props.value,'未完成的 JSON');
  }finally{ui.close();}
});

test('moving a node is an actual draft edit, and moving it back restores direct example switching',async()=>{
  const ui=await draftEditor();
  try{
    await ui.choose('示例工作流','one');
    act(()=>ui.canvas().onNodesChange([{type:'position',id:'trigger',position:{x:90,y:70},dragging:false}]));
    await ui.choose('示例工作流','two');assert.equal(ui.confirms.length,1);assert.equal(ui.canvas().nodes[0].position.x,90);
    act(()=>ui.canvas().onNodesChange([{type:'position',id:'trigger',position:{x:70,y:70},dragging:false}]));
    await ui.choose('示例工作流','two');assert.equal(ui.confirms.length,1);assert.match(ui.view.root.findByProps({'aria-label':'工作流名称'}).props.value,/示例二/);
  }finally{ui.close();}
});
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
