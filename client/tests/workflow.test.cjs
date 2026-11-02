const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript'),React=require('react');
const {act,create}=require('react-test-renderer');
function compile(file,imports={}){const filename=path.resolve(__dirname,'../src/client/'+file),mod=new Module(filename,module);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));const original=mod.require.bind(mod);mod.require=id=>{if(id in imports)return imports[id];if(id.endsWith('.css'))return{};const local=id.startsWith('./')&&['.tsx','.ts'].find(extension=>fs.existsSync(path.resolve(path.dirname(filename),id+extension)));return local?compile(id.slice(2)+local,imports):original(id);};mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);return mod.exports;}
const state=compile('workflow-state.ts');
const alignment=compile('workflow-alignment.ts');
const textOf=node=>typeof node==='string'?node:node.children?.map(textOf).join('')||'';
const summary=definition=>({...definition,updated:123,latest_run:null,preview:{nodes:definition.graph.nodes.map(n=>({id:n.id,kind:n.kind,position:n.position,label:n.capability?.name||''})),edges:definition.graph.edges}});
const scheduleState={jobs:[],loaded:true,error:'',busy:'',reload:async()=>{},toggle:async()=>{}};
const scheduleMock={WorkflowSchedules:()=>null,useWorkflowSchedules:()=>scheduleState};

async function draftEditor(){
  const graph={nodes:[{id:'trigger',kind:'trigger',config:{text:''},position:{x:70,y:70}},{id:'ai',kind:'ai',config:{prompt:'{{trigger.text}}',model_id:''},position:{x:350,y:70}}],edges:[{source:'trigger',target:'ai',branch:''}]};
  const templates=[{id:'one',name:'示例一',description:'one',graph},{id:'two',name:'示例二',description:'two',graph}];
  const definitions=[{id:'saved-one',name:'已保存一',revision:1,version:'a'.repeat(64),graph},{id:'saved-two',name:'已保存二',revision:1,version:'b'.repeat(64),graph}];
  const catalog=[{kind:'trigger',label:'触发',defaults:{text:''},outputs:['text'],writes:false},{kind:'ai',label:'AI处理',defaults:{prompt:'',model_id:''},outputs:['text'],writes:false},{kind:'base',label:'表格',defaults:{fields:{内容:'{{trigger.text}}'},base_token:'b',table_id:'t',key_field:'receipt',profile:''},outputs:['record_id'],writes:true}];
  const rpc=async(_info,_method,{operation,payload}={})=>operation==='catalog'?{ok:true,nodes:catalog}:operation==='list'?{ok:true,definitions:definitions.map(summary),runs:[]}:operation==='templates'?{ok:true,templates}:operation==='load'?{ok:true,definition:definitions.find(d=>d.id===payload.id)}:operation==='save'?{ok:true,definition:{...payload,id:'saved-copy',revision:1,version:'c'.repeat(64)}}:{ok:true};
  const {applyNodeChanges}=require('@xyflow/react');
  const flow={ReactFlow:props=>React.createElement('div',null,props.children),ViewportPortal:({children})=>children,ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,edge],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,changes=>set(current=>applyNodeChanges(changes,current))];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,getZoom:()=>1,fitView(){}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':scheduleMock,'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
  const previous=global.window,confirms=[];global.window={setInterval:()=>1,clearInterval(){},confirm:message=>{confirms.push(message);return false;}};let view;
  await act(async()=>{view=create(React.createElement(editor.WorkflowPane,{info:{port:1,token:'fixture'}}));});
  async function choose(label,value){
    if(label==='示例工作流'){
      await act(async()=>view.root.findByProps({'aria-label':'自动化工作流首页'}).findAllByType('button').find(n=>textOf(n)==='从示例创建').props.onClick());
      await act(async()=>view.root.findAllByType('button').find(n=>textOf(n).includes(templates.find(t=>t.id===value).name)&&n.props.onClick).props.onClick());
    }else if(label==='已保存工作流')await act(async()=>view.root.findByProps({'aria-label':'打开工作流：'+definitions.find(d=>d.id===value).name}).props.onClick());
    else await act(async()=>view.root.findByProps({'aria-label':label}).props.onChange({target:{value}}));
  }
  return {view,confirms,canvas:()=>view.root.findByType(flow.ReactFlow).props,choose,button:text=>view.root.findAllByType('button').find(n=>textOf(n)===text||n.children.includes(text)),close:()=>{act(()=>view.unmount());global.window=previous;}};
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

test('card home opens the selected definition and returning preserves configuration, positions and unfinished JSON',async()=>{
  const ui=await draftEditor();
  try{
    const home=()=>ui.view.root.findByProps({'className':'workflow-home-surface'});
    const editor=()=>ui.view.root.findByProps({'className':'workflow-editor-surface'});
    assert.equal(home().props.hidden,false);assert.equal(editor().props.hidden,true);assert.equal(ui.view.root.findAllByProps({'aria-label':'工作流画布'}).length,0);
    await ui.choose('已保存工作流','saved-two');assert.equal(editor().props.hidden,false);
    act(()=>ui.canvas().onNodeClick({},ui.canvas().nodes[1]));
    act(()=>ui.view.root.findByType('textarea').props.onChange({target:{value:'保留我的提示词'}}));
    act(()=>ui.canvas().onNodesChange([{type:'position',id:'ai',position:{x:700,y:300},dragging:false}]));
    await act(async()=>ui.button('工作流').props.onClick());assert.equal(home().props.hidden,false);assert.equal(ui.confirms.length,0);
    await ui.choose('已保存工作流','saved-two');assert.equal(ui.confirms.length,0);assert.equal(ui.view.root.findByType('textarea').props.value,'保留我的提示词');assert.deepEqual(ui.canvas().nodes[1].position,{x:700,y:300});
    await act(async()=>ui.button('工作流').props.onClick());await ui.choose('已保存工作流','saved-one');
    assert.equal(ui.confirms.length,1);assert.equal(home().props.hidden,false);assert.equal(ui.canvas().nodes[1].data.config.prompt,'保留我的提示词');
    await act(async()=>ui.button('返回当前画布').props.onClick());assert.equal(editor().props.hidden,false);
    act(()=>ui.button('表格').props.onClick());act(()=>ui.view.root.findByProps({'aria-label':'普通文本字段 JSON'}).props.onChange({target:{value:'{"未完成":'}}));
    await act(async()=>ui.button('工作流').props.onClick());await act(async()=>ui.button('返回当前画布').props.onClick());
    assert.equal(ui.view.root.findByProps({'aria-label':'普通文本字段 JSON'}).props.value,'{"未完成":');assert.equal(ui.confirms.length,1);
  }finally{ui.close();}
});

test('overview uses real graph layout, per-definition latest receipts and actual schedule state; actions remain separate',async()=>{
  const {WorkflowOverview}=compile('workflow-overview.tsx');
  const definition=summary({id:'w',name:'资讯流程',revision:1,version:'c'.repeat(64),graph:{nodes:[{id:'t',kind:'trigger',config:{text:'private'},position:{x:-30,y:40}},{id:'a',kind:'ai',config:{prompt:'private'},position:{x:300,y:240}}],edges:[{source:'t',target:'a',branch:''}]}});
  definition.latest_run={id:'older-than-100',workflow:'w',name:'资讯流程',state:'unknown',created:1700000000};
  const job={id:'original',name:'每天整理',action:'workflow',workflow_id:'w',workflow_version:'b'.repeat(64),enabled:false,schedule_text:'每天 09:00'};
  const calls=[],props={definitions:[definition],history:[],catalog:[{kind:'trigger',label:'触发'},{kind:'ai',label:'AI处理'}],schedules:{...scheduleState,jobs:[job],toggle:async value=>calls.push(['toggle',value])},loading:false,loaded:true,error:'',disabled:false,debug:false,draft:'',onOpen:id=>calls.push(['open',id]),onResume(){},onNew:()=>calls.push(['new']),onTemplate:()=>calls.push(['template']),onRun:id=>calls.push(['run',id]),onRefresh(){},onSchedules:()=>calls.push(['schedules'])};let view;
  try{
    await act(async()=>{view=create(React.createElement(WorkflowOverview,props));});
    assert.equal(view.root.findAllByType('path').filter(n=>n.props['data-branch']==='').length,1);
    assert.equal(view.root.findByProps({className:'workflow-thumbnail'}).findAllByType('rect').length,2);assert.match(textOf(view.root),/结果待核对/);assert.match(textOf(view.root),/绑定历史版本/);assert.doesNotMatch(JSON.stringify(view.toJSON()),/private/);
    const button=text=>view.root.findAllByType('button').find(n=>textOf(n)===text);
    await act(async()=>view.root.findByProps({'aria-label':'打开工作流：资讯流程'}).props.onClick());await act(async()=>view.root.findByProps({'aria-label':'查看最近执行：资讯流程'}).props.onClick());
    const toggle=view.root.findByProps({role:'switch'});assert.equal(toggle.props['aria-checked'],false);await act(async()=>toggle.props.onClick());assert.strictEqual(calls[2][1],job);
    act(()=>button('新建工作流').props.onClick());act(()=>button('从示例创建').props.onClick());act(()=>button('触发计划').props.onClick());
    assert.deepEqual(calls.slice(0,2),[['open','w'],['run','older-than-100']]);assert.deepEqual(calls.slice(3),[['new'],['template'],['schedules']]);
    act(()=>view.root.findByProps({'aria-label':'搜索工作流'}).props.onChange({target:{value:'不存在'}}));assert.equal(view.root.findAllByType('article').length,0);assert.match(textOf(view.root),/没有找到/);
    await act(async()=>view.update(React.createElement(WorkflowOverview,{...props,definitions:[],schedules:{...scheduleState,loaded:false,error:'权限失败'},error:'连接失败'})));assert.match(textOf(view.root),/连接失败/);assert.doesNotMatch(textOf(view.root),/已完成/);
  }finally{act(()=>view?.unmount());}
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

test('focus uses the native modal and a stable portal container, preserving child state through Escape and repeated toggles',async()=>{
  const old={document:global.document,window:global.window,CustomEvent:global.CustomEvent};let view,mounts=0,shows=0,closes=0;const targets=[];
  const host=()=>({children:[],appendChild(child){if(child.parentNode)child.parentNode.children=child.parentNode.children.filter(c=>c!==child);this.children.push(child);child.parentNode=this;},showModal(){this.open=true;shows++;},close(){this.open=false;closes++;}});
  global.document={createElement:host,activeElement:{isConnected:true,focus(){}}};global.window={dispatchEvent(){}};global.CustomEvent=class{constructor(type,options){this.type=type;this.detail=options.detail;}};
  const {WorkflowSurface}=compile('workflow-surface.tsx',{'react-dom':{createPortal:(children,target)=>{targets.push(target);return children;}},'./page-stack':{usePageActive:()=>true}});
  function Child(){const[text,setText]=React.useState('');React.useEffect(()=>{mounts++;},[]);return React.createElement('input',{value:text,onChange:e=>setText(e.target.value)});}
  function App(){const[focused,setFocused]=React.useState(false);return React.createElement(React.Fragment,null,React.createElement('button',{onClick:()=>setFocused(true)},'focus'),React.createElement(WorkflowSurface,{focused,onClose:()=>setFocused(false)},React.createElement(Child)));}
  try{
    await act(async()=>{view=create(React.createElement(App),{createNodeMock:host});});act(()=>view.root.findByType('input').props.onChange({target:{value:'未保存的内容'}}));
    await act(async()=>view.root.findByType('button').props.onClick());assert.equal(shows,1);assert.equal(view.root.findByType('dialog').props['aria-label'],'工作流专注画布');assert.equal(view.root.findByType('input').props.value,'未保存的内容');
    let prevented=false;await act(async()=>view.root.findByType('dialog').props.onCancel({preventDefault(){prevented=true;}}));assert.equal(prevented,true);assert.equal(closes,1);assert.equal(view.root.findByType('input').props.value,'未保存的内容');
    await act(async()=>view.root.findByType('button').props.onClick());assert.equal(shows,2);assert.equal(mounts,1);assert.ok(targets.every(target=>target===targets[0]));
  }finally{act(()=>view?.unmount());for(const[key,value]of Object.entries(old))if(value===undefined)delete global[key];else global[key]=value;}
});

test('actual edits require confirmation even for a single trigger; cancelling preserves text and reverting removes the prompt',async()=>{
  const ui=await draftEditor();
  try{
    act(()=>ui.button('新建工作流').props.onClick());
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
  const rpc=async(_info,_method,{operation}={})=>operation==='catalog'?{ok:true,nodes:catalog}:operation==='list'?{ok:true,definitions:[summary(definition)],runs:[]}:operation==='load'?{ok:true,definition}:{ok:true,templates:[]};
  const flow={ReactFlow:props=>React.createElement('div',null,props.children),ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,{...edge,id:'added'}],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,fitView(){}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':scheduleMock,'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
  const previous=global.window;global.window={setInterval:()=>1,clearInterval(){},confirm:()=>true};let view;
  try{
    await act(async()=>{view=create(React.createElement(editor.WorkflowPane,{info:{port:1,token:'fixture'}}));});
    await act(async()=>view.root.findByProps({'aria-label':'打开工作流：编辑'}).props.onClick());
    const button=text=>view.root.findAllByType('button').find(n=>textOf(n)===text||n.children.includes(text));
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
  const rpc=async(_info,method,{operation,payload}={})=>{calls.push([method,operation,payload]);if(operation==='catalog')return{ok:true,nodes:catalog};if(operation==='list')return{ok:true,definitions:[summary(definition)],runs:[]};if(operation==='load')return{ok:true,definition};if(operation==='check_targets')return{ok:true,targets:[{node:'send',target:'oc_target',name:'目标群'}]};if(operation==='start'){if(failures-- >0)throw Error('WebSocket disconnected');return{ok:true,run};}return{ok:true};};
  const flow={ReactFlow:props=>React.createElement('div',{'data-canvas':true},props.children),ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,edge],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,fitView:()=>{}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':scheduleMock,'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
  const previous=global.window;global.window={setInterval:()=>1,clearInterval(){},confirm:()=>true};
  let renderer;
  try{
    await act(async()=>{renderer=create(React.createElement(editor.WorkflowPane,{info:{port:1,token:'test'}}));});
    await act(async()=>renderer.root.findByProps({'aria-label':'打开工作流：日报'}).props.onClick());
    const button=text=>renderer.root.findAllByType('button').find(node=>textOf(node)===text);
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
  const rpc=async(_info,method,args={})=>{calls.push([method,args]);if(method==='save_automation_job')return{ok:true,job_id:job.id};if(args.operation==='catalog')return{ok:true,nodes:catalog};if(args.operation==='list')return{ok:true,definitions:[summary(definition)],runs:[]};if(args.operation==='load')return{ok:true,definition};return{ok:true,templates:[]};};
  const Schedules=()=>null;
  const flow={ReactFlow:props=>React.createElement('div',null,props.children),ReactFlowProvider:({children})=>children,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Top:'top',Bottom:'bottom'},addEdge:(edge,edges)=>[...edges,edge],useNodesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useEdgesState:initial=>{const[v,set]=React.useState(initial);return[v,set,()=>{}];},useNodesInitialized:()=>true,useReactFlow:()=>({screenToFlowPosition:value=>value,fitView(){}})};
  const editor=compile('workflow-editor.tsx',{'./api':{rpc},'./page-stack':{usePageActive:()=>true},'./workflow-state':state,'./workflow-schedules':{...scheduleMock,WorkflowSchedules:Schedules},'./task-budget':compile('task-budget.tsx'),'@xyflow/react':flow});
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
