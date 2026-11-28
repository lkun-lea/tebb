import {WorkspaceDialog} from './workspace-dialog';
import {notifyReceipt} from './toast';
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { ReactFlow, Controls, Position, useReactFlow, useNodesInitialized, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { rpc, type BackendInfo } from './api';
import { UiButton, UiFeedback } from './ui-controls';
import './execution-center.css';
import type {DebugDetail} from './agent-debug';
const CallInspector=lazy(()=>import('./agent-debug').then(module=>({default:module.AgentDebugDialog})));
const FailureCaseEditor=lazy(()=>import('./evaluation-center').then(module=>({default:module.EvaluationCaseEditor})));
const definitionEvent=(node:ExecutionNode)=>['tool_offer','tool_catalog','tool_definition_effective'].includes(node.kind);

function runTitle(node:ExecutionNode){
 for(const value of [node.title,node.prompt,node.text,node.label]){
  if(typeof value==='string' && value.trim() && !/^(?:(?:collab|task|operation):|[a-f0-9]{16,}$)/i.test(value))return value;
 }
 const kind=node.id.startsWith('collab:')?'协作任务':'任务';
 const date=node.created?new Date(node.created*1000).toLocaleString():'';
 const purpose=({route:'路由判断',plan:'任务规划',review:'结果审阅'} as Record<string,string>)[String(node.purpose)];
 const observed=[purpose,node.model].filter(Boolean).join(' · ');
 return [observed||kind+'（未记录标题）',date].filter(Boolean).join(' · ');
}
function traceLabel(node:ExecutionNode){
 if(node.kind==='task')return runTitle(node);
 const label=String(node.title||node.label);
 const names:Record<string,string>={request_received:'收到请求',attempt:'发起调用',outcome:'返回结果',offer:'提供工具',load:'加载工具'};
 if(/^[a-f0-9]{16,}$/i.test(label))return String(node.tool||node.agent||({task:'任务',operation:'调用',agent:'伙伴执行'} as Record<string,string>)[node.kind]||'执行记录');
 return label.split(' · ').map(part=>names[part]||part).join(' · ');
}
export type ExecutionNode = {note_refs?:{id:string;title:string}[];id:string;kind:string;label:string;state:string;started?:number;created?:number;ended?:number;[key:string]:unknown};
export type ExecutionGraph = {ok:boolean;root:string;nodes:ExecutionNode[];edges:{id:string;source:string;target:string;relation:string}[];timeline:string[];acceptance:{state:string;feedback_ok?:boolean};coverage:Record<string,unknown>};
export const executionState:Record<string,string>={queued:'排队中',running:'执行中',needs_input:'待补充',needs_confirmation:'待确认',succeeded:'执行完成',returned:'已返回',failed:'失败',rejected:'已拦截',timed_out:'超时',cancelled:'已停止',interrupted:'运行中断',unknown:'结果未知',loaded:'已加载',offered:'本次允许',effective:'定义已生效',recorded:'已记录',cached:'缓存命中',replayed:'已有回执',unverified:'待核验',checked:'已核验',incomplete:'核验未完成'};

export function graphLayout(graph:ExecutionGraph):{nodes:Node[];edges:Edge[]}{
 const children=new Map<string,string[]>(), positions=new Map<string,{x:number;y:number}>();
 const parents=new Set<string>();
 for(const edge of graph.edges){
   const siblings=children.get(edge.source)||[];
   siblings.push(edge.target);children.set(edge.source,siblings);parents.add(edge.target);
 }
 let lane=0;
 function place(id:string,depth:number):number{
   const existing=positions.get(id);
   if(existing)return existing.y;
   const position={x:depth*215,y:lane*82};positions.set(id,position);
   const childRows=(children.get(id)||[]).filter(child=>!positions.has(child)).map(child=>place(child,depth+1));
   position.y=childRows.length?(childRows[0]+childRows[childRows.length-1])/2:lane++*82;
   return position.y;
 }
 for(const n of graph.nodes)if(!parents.has(n.id))place(n.id,0);
 for(const n of graph.nodes)if(!positions.has(n.id))place(n.id,0);
 return {nodes:graph.nodes.map(n=>{return {id:n.id,position:positions.get(n.id)!,sourcePosition:Position.Right,targetPosition:Position.Left,data:{label:<><strong>{traceLabel(n)}</strong><small>{executionState[n.state]||n.state}</small></>},className:`execution-node is-${n.state}`,ariaLabel:`${n.label}，${executionState[n.state]||n.state}`,draggable:false};}),
 edges:graph.edges.map(e=>({...e,animated:false,ariaLabel:e.relation}))};
}

function FitExecutionGraph({element,signature,focusNode}:{element:HTMLDivElement|null;signature:string;focusNode?:string}){
 const flow=useReactFlow(),initialized=useNodesInitialized();
 useEffect(()=>{if(!element||!initialized||typeof ResizeObserver==='undefined')return;let frame=0;
  const observer=new ResizeObserver(()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{
    const node=focusNode?flow.getNode(focusNode):undefined;
    if(node)void flow.setCenter(node.position.x+(node.measured?.width||160)/2,node.position.y+(node.measured?.height||56)/2,{zoom:1});
    else void flow.fitView({padding:.18,duration:0});
  });});
  observer.observe(element);return()=>{observer.disconnect();cancelAnimationFrame(frame);};
 },[element,initialized,signature,flow,focusNode]);return null;
}

const failedStates = new Set(['failed','timed_out','rejected','interrupted']);
const eventNames:Record<string,string>={model:'模型',tool:'工具',physical:'任务阶段',task:'任务',diagnostic:'诊断'};
function Waterfall({graph,selected,onSelect}:{graph:ExecutionGraph;selected:string;onSelect:(id:string)=>void}){
 const [expanded,setExpanded]=useState(false);
 const nodes=useMemo(()=>{
   const index=new Map(graph.nodes.map(n=>[n.id,n]));
   return graph.timeline.map(id=>index.get(id)).filter((n):n is ExecutionNode=>!!n);
 },[graph]);
 const primaryKinds=new Set(['agent','model','tool','workflow_node']);
 const main=nodes.filter(n=>primaryKinds.has(n.kind));
 const receipts=nodes.filter(n=>!primaryKinds.has(n.kind));
 const [opened,setOpened]=useState<string[]>([]);
 const models=main.filter(n=>n.kind==='model');
 const phaseNames:Record<string,string>={route:'路由',plan:'规划'};
 const readTools=new Set(['workspace_read','workspace_read_symbol','workspace_search','workspace_list','web_search','web_fetch']);
 const buckets=new Map<string,ExecutionNode[]>();
 for(const n of main){
   const group=n.kind==='model'&&!phaseNames[String(n.purpose)]&&!failedStates.has(n.state)?'models:'+String(n.task||''):n.kind==='tool'&&readTools.has(String(n.tool))&&!failedStates.has(n.state)?'reads':n.id;
   const members=buckets.get(group)||[];
   members.push(n);buckets.set(group,members);
 }
 const times=nodes.flatMap(n=>[n.started||n.created,n.ended]).filter((v):v is number=>typeof v==='number'&&v>0);
 const start=times.reduce((a,b)=>Math.min(a,b),Infinity), end=times.reduce((a,b)=>Math.max(a,b),0);
 const span=end-start;
 function row(members:ExecutionNode[],key:string,child=false){
   const n=members[0],group=members.length>1, failure=failedStates.has(n.state);
   const label=group?(key.startsWith('models:')?'模型调用':'只读工具')+' × '+members.length:
     n.kind==='model'?(phaseNames[String(n.purpose)]||'第 '+(models.filter(m=>m.task===n.task).indexOf(n)+1)+' 次模型调用'):n.kind==='agent'&&n.agent==='coder'?'编码伙伴':traceLabel(n);
   return <li key={key}><button type="button" className={'trace-row'+(child?' trace-child':'')} aria-label={group?label:n.label+' · '+(executionState[n.state]||n.state)}
     aria-expanded={group?opened.includes(key):undefined} aria-pressed={!group&&selected===n.id}
     onClick={()=>group?setOpened(old=>old.includes(key)?old.filter(k=>k!==key):[...old,key]):onSelect(n.id)}>
     <span>{group&&(opened.includes(key)?'⌄ ':'› ')}{label}</span>
     <span className="trace-track">{members.map(m=>{const ts=m.started||m.created;if(!ts||!(span>0))return null;
       return <i key={m.id} title={((ts-start)).toFixed(2)+' s'+(m.ended?' – '+(m.ended-start).toFixed(2)+' s':'')} className={failedStates.has(m.state)?'trace-error':''}
         style={{left:Math.min(99,(ts-start)/span*100)+'%',width:Math.max(0,((m.ended||ts)-ts)/span*100)+'%'}}/>})}</span>
     <small>{failure?(executionState[n.state]||n.state):(!group&&n.ended&&n.started?(n.ended-n.started).toFixed(2)+' s':'')}</small>
   </button>{group&&opened.includes(key)&&<ol>{members.map(m=>row([m],m.id,true))}</ol>}</li>
 }
 return <section className="waterfall-panel"><h3>执行时间线</h3>
   <div className="time-axis"><span/ ><div>{[0,.25,.5,.75,1].map(f=><small key={f}>{span>0?Math.round(f*span)+'s':'—'}</small>)}</div><span/></div>
   <ol className="trace-waterfall" aria-label="执行时间线">{Array.from(buckets,([k,v])=>row(v,k))}</ol>
   {receipts.length>0&&<details open={expanded} onToggle={e=>setExpanded(e.currentTarget.open)}><summary>其他阶段与工具回执 · {receipts.length}</summary>{expanded&&<ol>{receipts.map(n=>row([n],n.id))}</ol>}</details>}
 </section>;
}

function defaultStep(graph:ExecutionGraph){
 const failures=new Set(graph.nodes.filter(n=>failedStates.has(n.state)&&['model','tool'].includes(n.kind)).map(n=>n.id));
 return graph.timeline.find(id=>failures.has(id))||graph.root;
}

export function ExecutionTrace({info,root,task,evaluation}:{info:BackendInfo|null;root?:string;task?:string;evaluation?:{ident:string;case_id:string;sample:number}}){
 const [snapshots,setSnapshots]=useState<{backend:BackendInfo|null; entries:Map<string,ExecutionGraph>}>({backend:info,entries:new Map()});
 const traceKey=JSON.stringify([root,task,evaluation?.ident,evaluation?.case_id,evaluation?.sample]);
 const graph=snapshots.backend===info?snapshots.entries.get(traceKey):undefined;
 const [error,setError]=useState(''),[selected,select]=useState('');
 const [callId,setCallId]=useState('');
 const [callSnapshot,setCallSnapshot]=useState<DebugDetail|undefined>(undefined);
 useEffect(()=>{if(error)notifyReceipt(error.replace(/^(?:Error: |ValueError: )+/g,''));},[error]);
 const [unlinkedKey,setUnlinkedKey]=useState('');
 const [expandedGraph,setExpandedGraph]=useState(false);
 const [canvas,setCanvas]=useState<HTMLDivElement|null>(null);
 const [showDefinitions,setShowDefinitions]=useState(false),[dependency,setDependency]=useState(false);
 const generation=useRef(0), manualSelection=useRef(false);
 const choose=(id:string)=>{manualSelection.current=true;select(id)};
 useEffect(()=>{const epoch=++generation.current;let busy=false;
  manualSelection.current=false;setError('');select('');setCallId('');setCallSnapshot(undefined);
  async function refresh(){if(!info||busy)return;busy=true;try{const found=await rpc<ExecutionGraph|{ok:true;state:'unlinked'}>(info,evaluation?'agent_evaluation':'execution_inspect',{operation:evaluation?'trace':root?'trace':'locate',payload:evaluation|| (root?{root}:{task})});if(epoch===generation.current){if('state' in found){setUnlinkedKey(traceKey);setError('');return;}setUnlinkedKey('');if(!found.ok)throw Error('读取执行过程失败。');setSnapshots(previous=>{
     const entries=new Map(previous.backend===info?previous.entries:[]);
     entries.delete(traceKey);
     entries.set(traceKey,found);
     if(entries.size>12)entries.delete(entries.keys().next().value!);
     return {backend:info,entries};
    });if(!manualSelection.current)select(defaultStep(found));setError('');}}
   catch(e){if(epoch===generation.current)setError(String(e));}finally{busy=false;}}
  void refresh();const timer=setInterval(()=>void refresh(),2000);return()=>{generation.current++;clearInterval(timer);};
 },[info,root,task,evaluation?.ident,evaluation?.case_id,evaluation?.sample]);
 async function inspectCall(id:string){if(!info)return;const version=generation.current;try{if(evaluation){const snapshot=await rpc<DebugDetail>(info,'agent_evaluation',{operation:'debug_call',payload:{...evaluation,call_id:id}});if(version!==generation.current)return;setCallSnapshot(snapshot);}else setCallSnapshot(undefined);setCallId(id);}catch(e){if(version===generation.current)setError(String(e));}}
 const visibleGraph=useMemo(()=>{if(!graph||showDefinitions)return graph;const nodes=graph.nodes.filter(n=>!definitionEvent(n)),ids=new Set(nodes.map(n=>n.id));return {...graph,nodes,edges:graph.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)),timeline:graph.timeline.filter(id=>ids.has(id))};},[graph,showDefinitions]);
 const layout=useMemo(()=>dependency&&visibleGraph?graphLayout(visibleGraph):null,[dependency,visibleGraph]);
 const selectedStep=graph && (graph.nodes.some(n=>n.id===selected)?selected:defaultStep(graph));
 const detail=graph?.nodes.find(n=>n.id===selectedStep);
 const rootNode=graph?.nodes.find(n=>n.id===graph.root);
 const lastEnd=graph?.nodes.reduce((end,n)=>Math.max(end,n.ended||0),0)||0;
 const dependencyCanvas=layout&&(<div className="execution-canvas" ref={setCanvas}><ReactFlow nodes={layout.nodes.map(node=>({...node,selected:node.id===selectedStep}))} edges={layout.edges} fitView nodesDraggable={false} nodesConnectable={false} deleteKeyCode={null} onNodeClick={(_,node)=>choose(node.id)} onNodesChange={changes=>{for(const change of changes)if(change.type==='select'&&change.selected)select(change.id);}}><Controls showInteractive={false}/><FitExecutionGraph element={canvas} focusNode={expandedGraph?graph?.root:undefined} signature={visibleGraph!.nodes.map(n=>n.id).join('|')}/></ReactFlow></div>);
 return <section className="execution-trace" aria-label="真实执行过程">

  {!graph&&unlinkedKey===traceKey&&<UiFeedback state="empty" title="这项任务暂无执行记录"/>}
  {!graph&&unlinkedKey!==traceKey&&!error&&<UiFeedback state={info?'loading':'unconfirmed'} title={info?'正在读取真实执行过程':'尚未连接本地后端'}/>}
  {graph&&<><header className="run-heading" data-failed={failedStates.has(graph.nodes.find(n=>n.id===graph.root)?.state||'')}><h2>{runTitle(rootNode||{id:graph.root,label:graph.root,kind:'task',state:'unknown'})}</h2><span className="run-badge">{executionState[graph.nodes.find(n=>n.id===graph.root)?.state||'unknown']}</span></header>
   {rootNode?.note_refs?.map(ref=><p key={ref.id}>引用笔记：{ref.title}</p>)}
   <p className="run-meta">开始 {graph.nodes[0]?.created?new Date(graph.nodes[0].created*1000).toLocaleTimeString():'—'}　·　{rootNode?.created&&lastEnd>=rootNode.created&&<>记录跨度 {(lastEnd-rootNode.created).toFixed(2)} s　·　</>}验收 {executionState[graph.acceptance.state]||graph.acceptance.state}</p>
   {dependency&&graph.nodes.some(definitionEvent)&&<UiButton aria-pressed={showDefinitions} onClick={()=>setShowDefinitions(v=>!v)}>{showDefinitions?'收起请求工具定义事件':'展开请求工具定义事件'}</UiButton>}
   <div className="execution-toolbar"><UiButton aria-pressed={!dependency} onClick={()=>setDependency(false)}>时间瀑布</UiButton><UiButton aria-pressed={dependency} onClick={()=>setDependency(true)}>依赖图</UiButton></div>
   {dependency&&layout&&<><UiButton onClick={()=>setExpandedGraph(true)}>放大依赖图</UiButton>{expandedGraph?<WorkspaceDialog className="dependency-dialog" title="运行依赖图" onClose={()=>setExpandedGraph(false)}>{dependencyCanvas}</WorkspaceDialog>:dependencyCanvas}</>}
   <div className="execution-details">{!dependency&&<Waterfall graph={visibleGraph!} selected={selectedStep||''} onSelect={choose}/>}
    <div className="span-inspector">{detail?<><header><small>{eventNames[detail.kind]||'执行步骤'}</small><h3>{detail.kind==='model'?'第 '+(graph.timeline.filter(id=>graph.nodes.some(n=>n.id===id&&n.kind==='model'&&n.task===detail.task)).indexOf(detail.id)+1)+' 次模型调用':traceLabel(detail)}</h3>{detail.kind==='model'&&<small>{detail.label}</small>}<p className={failedStates.has(detail.state)?'span-failure':''}>{executionState[detail.state]||detail.state}　{String(detail.error_kind||detail.error||'')}</p></header>
     {Array.isArray(detail.network_spans)&&detail.network_spans.map((s:{label:string;duration_ms:number;state:string},i:number)=><div className="span-phase" key={i}><span>{s.label}</span><strong>{s.duration_ms>=1000?(s.duration_ms/1000).toFixed(2)+' s':s.duration_ms.toFixed(0)+' ms'}</strong><small className={s.state==='failed'?'span-failure':''}>{s.state==='failed'?(/timeout/i.test(String(detail.error_kind))?'超时':'失败'):s.state==='complete'?'已完成':'未结束'}</small></div>)}
     {typeof detail.debug_call==='string'&&<UiButton onClick={()=>void inspectCall(detail.debug_call as string)}>查看模型请求与响应</UiButton>}
      {Array.isArray(detail.network_spans)&&detail.network_spans.some(s=>s.phase==='start_tls'&&s.state==='failed')&&!detail.network_spans.some(s=>s.phase==='receive_response_headers')&&<div className="span-phase"><span>HTTP 响应头</span><strong>未记录</strong></div>}
     <details><summary>原始回执</summary><pre tabIndex={0}>{JSON.stringify(detail,null,2)}</pre></details></>:<p className="ui-field-help">选择图中节点或时间线查看原编号、真实状态与记录证据。</p>}
     {detail&&!evaluation&&['failed','rejected','timed_out','cancelled','unknown'].includes(detail.state)&&(detail.kind==='model'||detail.kind==='tool'||detail.kind.startsWith('tool_'))&&<Suspense fallback={null}><FailureCaseEditor key={detail.id} info={info} sourceFailure={detail.id.replace(/^tool-event:/,'')}/></Suspense>}

    </div></div><footer className="run-footer">工具调用 {graph.nodes.filter(n=>n.kind==='tool').length}　·　工作区写入调用 {graph.nodes.filter(n=>n.kind==='tool'&&['workspace_write','workspace_patch'].includes(String(n.tool))).length}　·　命令执行 {graph.nodes.filter(n=>n.kind==='tool'&&n.tool==='workspace_run').length}</footer></>}
  {callId&&<Suspense fallback={<UiFeedback state="loading" title="正在打开调用详情"/>}><CallInspector key={callId} info={info} callId={callId} debug={!!callSnapshot} snapshot={callSnapshot} onClose={()=>setCallId('')}/></Suspense>}
 </section>;
}

export function ExecutionCenterPane({info,onInspectCalls,initialTrace,onSelectRun}:{onSelectRun?:(id:string)=>void;info:BackendInfo|null;onInspectCalls:()=>void;initialTrace?:string}){
 const [items,setItems]=useState<ExecutionNode[]>([]),[root,setRoot]=useState(''),[query,setQuery]=useState(''),[error,setError]=useState(''),[pending,setPending]=useState(false);
 const [filters,setFilters]=useState({kind:'task',model:'',agent:'',role:'',purpose:'',channel:'',state:'',configuration_version:'',code_version:'',period:'7'});
 const [next,setNext]=useState<number|null>(null),[kinds,setKinds]=useState<Record<string,number>>({}),[states,setStates]=useState<Record<string,number>>({});
 const epoch=useRef(0);
 const [visibleRuns,setVisibleRuns]=useState(8);
 const reading=useRef(false),pages=useRef(1);
 const [loaded,setLoaded]=useState(false),[acceptance,setAcceptance]=useState<{passed:number;known:number;total:number;unknown:number}|null>(null);
 useEffect(()=>{setRoot(initialTrace||'');},[initialTrace,info]);
 async function refresh(offset=0){if(!info||reading.current)return;reading.current=true;const version=++epoch.current;setPending(true);const {period,...selected}=filters;try{const value=await rpc<{ok:boolean;items:ExecutionNode[];next_offset:number|null;kinds:Record<string,number>;task_states:Record<string,number>;acceptance:{passed:number;known:number;total:number;unknown:number}}>(info,'execution_inspect',{operation:'list',payload:{filters:{...Object.fromEntries(Object.entries({root:query,...selected}).filter(([,v])=>v)),...(period==='all'?{}:{since:Date.now()/1000-Number(period)*86400})},offset}});if(version===epoch.current){setItems(old=>offset?[...old,...value.items.filter(v=>!old.some(r=>r.id===v.id))]:[...value.items,...old.filter(v=>!value.items.some(r=>r.id===v.id))]);setKinds(value.kinds);setStates(value.task_states);setAcceptance(value.acceptance);setLoaded(true);if(!offset)setRoot(old=>old||value.items[0]?.id||'');if(offset||pages.current===1)setNext(value.next_offset);if(offset)pages.current++;setError('');}}catch(e){if(version===epoch.current)setError(String(e));}finally{reading.current=false;if(version===epoch.current)setPending(false);}}
 useEffect(()=>{setItems([]);setVisibleRuns(8);setRoot(initialTrace||'');setLoaded(false);pages.current=1;setNext(null);void refresh();const timer=setInterval(()=>void refresh(),3000);return()=>{epoch.current++;clearInterval(timer);};},[info,query,filters]);
 return <div className="execution-center"><details className="run-filters"><summary>筛选运行记录</summary><div className="execution-toolbar"><label>记录类型 <select value={filters.kind} onChange={e=>setFilters(v=>({...v,kind:e.target.value}))}><option value="task">任务运行</option><option value="operation">独立调用</option><option value="">全部</option></select></label><label>根任务编号 <input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void refresh();}}/></label><UiButton busy={pending} disabled={!info} onClick={()=>void refresh()}>查询任务</UiButton><UiButton onClick={onInspectCalls}>模型调用详情</UiButton></div>
  <details><summary>Agent 与执行筛选</summary><div className="execution-toolbar">{([['model','模型'],['agent','Agent 编号'],['role','角色编号'],['purpose','任务类型（purpose）'],['channel','渠道'],['state','任务状态'],['configuration_version','配置版本'],['code_version','运行代码版本']]as const).map(([key,label])=><label key={key}>{label}<input value={filters[key]} onChange={e=>setFilters(v=>({...v,[key]:e.target.value}))}/></label>)}</div></details>
  <label>任务提交时间 <select value={filters.period} onChange={e=>setFilters(v=>({...v,period:e.target.value}))}><option value="7">最近7天</option><option value="30">最近30天</option><option value="all">全部时间</option></select></label>
  {loaded&&<details><summary>运行统计与验收覆盖</summary><p className="ui-field-help">根任务 {kinds.task||0} · 独立调用 {kinds.operation||0} · 诊断 {kinds.diagnostic||0}；子任务不重复计入根任务次数。</p><p className="ui-field-help">{Object.entries(states||{}).map(([state,count])=>`${executionState[state]||state} ${count}`).join(' · ')}</p>{acceptance&&<p className="ui-field-help">原任务验收通过 {acceptance.passed}/{acceptance.known} 个已记录判断 · 覆盖 {acceptance.known}/{acceptance.total} · {acceptance.unknown} 项待核验</p>}</details>}
  </details>{error&&<UiFeedback state="error" title="任务读取失败">{error}</UiFeedback>}
  {!loaded&&!error&&<UiFeedback state={info?'loading':'unconfirmed'} title={info?'正在读取任务记录':'尚未连接本地后端'}/>}
  {loaded&&!pending&&!items.length&&!error&&<UiFeedback state={query?'no_results':'empty'} title={query?'没有匹配的任务':'还没有执行记录'}/>}
  {root&&<div className="run-browser"><nav className="execution-roots" aria-label="最近运行"><h3>最近运行</h3>{items.slice(0,visibleRuns).map(row=><UiButton key={row.id} aria-pressed={root===row.id} onClick={()=>{setRoot(row.id);onSelectRun?.(row.id)}}><span>{runTitle(row)}</span><small>{executionState[row.state]||row.state}</small></UiButton>)}
  {items.length>visibleRuns?<UiButton onClick={()=>setVisibleRuns(n=>n+8)}>显示更多运行</UiButton>:next!=null&&<UiButton busy={pending} onClick={()=>void refresh(next)}>加载更早执行</UiButton>}</nav><ExecutionTrace info={info} {...(root.startsWith('@')?{task:root.slice(1)}:{root})}/></div>}
 </div>;
}
