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

export type ExecutionNode = {id:string;kind:string;label:string;state:string;started?:number;created?:number;ended?:number;[key:string]:unknown};
export type ExecutionGraph = {ok:boolean;root:string;nodes:ExecutionNode[];edges:{id:string;source:string;target:string;relation:string}[];timeline:string[];acceptance:{state:string;feedback_ok?:boolean};coverage:Record<string,unknown>};
export const executionState:Record<string,string>={queued:'排队中',running:'执行中',needs_input:'待补充',needs_confirmation:'待确认',succeeded:'执行完成',returned:'已返回',failed:'失败',rejected:'已拦截',timed_out:'超时',cancelled:'已停止',interrupted:'运行中断',unknown:'结果未知',loaded:'已加载',offered:'本次允许',effective:'定义已生效',recorded:'已记录',cached:'缓存命中',replayed:'已有回执',unverified:'待核验',checked:'已核验',incomplete:'核验未完成'};

export function graphLayout(graph:ExecutionGraph):{nodes:Node[];edges:Edge[]}{
 const parents=new Map(graph.edges.map(e=>[e.target,e.source])),depths=new Map<string,number>();
 function depth(id:string,seen=new Set<string>()):number{if(depths.has(id))return depths.get(id)!;if(seen.has(id))return 0;seen.add(id);const p=parents.get(id),value=p?1+depth(p,seen):0;depths.set(id,value);return value;}
 const rows=new Map<number,number>();
 return {nodes:graph.nodes.map(n=>{const d=depth(n.id),row=rows.get(d)||0;rows.set(d,row+1);return {id:n.id,position:{x:d*250,y:row*95},sourcePosition:Position.Right,targetPosition:Position.Left,data:{label:<><strong>{n.label}</strong><small>{executionState[n.state]||n.state}</small></>},className:`execution-node is-${n.state}`,ariaLabel:`${n.label}，${executionState[n.state]||n.state}`,draggable:false};}),
 edges:graph.edges.map(e=>({...e,animated:false,ariaLabel:e.relation}))};
}

function FitExecutionGraph({element,signature}:{element:HTMLDivElement|null;signature:string}){
 const flow=useReactFlow(),initialized=useNodesInitialized();
 useEffect(()=>{if(!element||!initialized||typeof ResizeObserver==='undefined')return;let frame=0;
  const observer=new ResizeObserver(()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>void flow.fitView({padding:.18,duration:0}));});
  observer.observe(element);return()=>{observer.disconnect();cancelAnimationFrame(frame);};
 },[element,initialized,signature,flow]);return null;
}

export function ExecutionTrace({info,root,task,evaluation}:{info:BackendInfo|null;root?:string;task?:string;evaluation?:{ident:string;case_id:string;sample:number}}){
 const [graph,setGraph]=useState<ExecutionGraph|null>(null),[error,setError]=useState(''),[selected,select]=useState('');
 const [callId,setCallId]=useState('');
 const [callSnapshot,setCallSnapshot]=useState<DebugDetail|undefined>(undefined);
 const [canvas,setCanvas]=useState<HTMLDivElement|null>(null);
 const [showDefinitions,setShowDefinitions]=useState(false);
 const generation=useRef(0);
 useEffect(()=>{const epoch=++generation.current;let busy=false;
  setGraph(null);setError('');select('');setCallId('');setCallSnapshot(undefined);
  async function refresh(){if(!info||busy)return;busy=true;try{const found=await rpc<ExecutionGraph>(info,evaluation?'agent_evaluation':'execution_inspect',{operation:evaluation?'trace':root?'trace':'locate',payload:evaluation|| (root?{root}:{task})});if(epoch===generation.current){if(!found.ok)throw Error('读取执行过程失败。');setGraph(found);setError('');}}
   catch(e){if(epoch===generation.current)setError(String(e));}finally{busy=false;}}
  void refresh();const timer=setInterval(()=>void refresh(),2000);return()=>{generation.current++;clearInterval(timer);};
 },[info,root,task,evaluation?.ident,evaluation?.case_id,evaluation?.sample]);
 async function inspectCall(id:string){if(!info)return;const version=generation.current;try{if(evaluation){const snapshot=await rpc<DebugDetail>(info,'agent_evaluation',{operation:'debug_call',payload:{...evaluation,call_id:id}});if(version!==generation.current)return;setCallSnapshot(snapshot);}else setCallSnapshot(undefined);setCallId(id);}catch(e){if(version===generation.current)setError(String(e));}}
 const visibleGraph=useMemo(()=>{if(!graph||showDefinitions)return graph;const nodes=graph.nodes.filter(n=>!definitionEvent(n)),ids=new Set(nodes.map(n=>n.id));return {...graph,nodes,edges:graph.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)),timeline:graph.timeline.filter(id=>ids.has(id))};},[graph,showDefinitions]);
 const layout=useMemo(()=>visibleGraph?graphLayout(visibleGraph):null,[visibleGraph]);
 const detail=graph?.nodes.find(n=>n.id===selected);
 return <section className="execution-trace" aria-label="真实执行过程">
  {error&&<UiFeedback state="error" title="执行过程读取失败">{error}，保留上次记录，稍后自动重试。</UiFeedback>}
  {!graph&&!error&&<UiFeedback state={info?'loading':'unconfirmed'} title={info?'正在读取真实执行过程':'尚未连接本地后端'}/>}
  {graph&&layout&&<><p className="ui-field-help">{graph.root} · 执行状态与验收分开显示 · 验收：{executionState[graph.acceptance.state]||graph.acceptance.state}</p>
   {graph.nodes.some(definitionEvent)&&<UiButton aria-pressed={showDefinitions} onClick={()=>setShowDefinitions(v=>!v)}>{showDefinitions?'收起请求工具定义事件':'展开请求工具定义事件'}</UiButton>}
   <div className="execution-canvas" ref={setCanvas}><ReactFlow nodes={layout.nodes.map(node=>({...node,selected:node.id===selected}))} edges={layout.edges} fitView nodesDraggable={false} nodesConnectable={false} deleteKeyCode={null} onNodeClick={(_,node)=>select(node.id)} onNodesChange={changes=>{for(const change of changes)if(change.type==='select'&&change.selected)select(change.id);}}><Controls showInteractive={false}/><FitExecutionGraph element={canvas} signature={visibleGraph!.nodes.map(n=>n.id).join('|')}/></ReactFlow></div>
   <div className="execution-details"><ol aria-label="执行时间线">{visibleGraph!.timeline.map(id=>{const n=graph.nodes.find(n=>n.id===id)!;return <li key={id}><button className="desk-btn" aria-pressed={selected===id} onClick={()=>select(id)}>{n.label} · {executionState[n.state]||n.state}</button></li>;})}</ol>
    <div>{detail?<><h3>{detail.label}</h3><p>调用编号：<code>{detail.id}</code></p>{typeof detail.debug_call==='string'&&<UiButton onClick={()=>void inspectCall(detail.debug_call as string)}>查看原模型调用与来源证据</UiButton>}<pre tabIndex={0}>{JSON.stringify(detail,null,2)}</pre></>:<p className="ui-field-help">选择图中节点或时间线查看原编号、真实状态与记录证据。</p>}
     {detail&&!evaluation&&['failed','rejected','timed_out','cancelled','unknown'].includes(detail.state)&&(detail.kind==='model'||detail.kind==='tool'||detail.kind.startsWith('tool_'))&&<Suspense fallback={null}><FailureCaseEditor key={detail.id} info={info} sourceFailure={detail.id.replace(/^tool-event:/,'')}/></Suspense>}
     <p className="ui-field-help">没有记录的版本、用量与费用保持未知；工具返回不代表整项任务已验收。停止、补充与继续使用原任务操作。</p>
    </div></div></>}
  {callId&&<Suspense fallback={<UiFeedback state="loading" title="正在打开调用详情"/>}><CallInspector key={callId} info={info} callId={callId} debug={!!callSnapshot} snapshot={callSnapshot} onClose={()=>setCallId('')}/></Suspense>}
 </section>;
}

export function ExecutionCenterPane({info,onInspectCalls}:{info:BackendInfo|null;onInspectCalls:()=>void}){
 const [items,setItems]=useState<ExecutionNode[]>([]),[root,setRoot]=useState(''),[query,setQuery]=useState(''),[error,setError]=useState(''),[pending,setPending]=useState(false);
 const [filters,setFilters]=useState({model:'',agent:'',role:'',purpose:'',channel:'',state:'',configuration_version:'',code_version:'',period:'7'});
 const [next,setNext]=useState<number|null>(null),[kinds,setKinds]=useState<Record<string,number>>({}),[states,setStates]=useState<Record<string,number>>({});
 const epoch=useRef(0);
 const reading=useRef(false),pages=useRef(1);
 const [loaded,setLoaded]=useState(false),[acceptance,setAcceptance]=useState<{passed:number;known:number;total:number;unknown:number}|null>(null);
 useEffect(()=>{setItems([]);setRoot('');},[info]);
 async function refresh(offset=0){if(!info||reading.current)return;reading.current=true;const version=++epoch.current;setPending(true);const {period,...selected}=filters;try{const value=await rpc<{ok:boolean;items:ExecutionNode[];next_offset:number|null;kinds:Record<string,number>;task_states:Record<string,number>;acceptance:{passed:number;known:number;total:number;unknown:number}}>(info,'execution_inspect',{operation:'list',payload:{filters:{...Object.fromEntries(Object.entries({root:query,...selected}).filter(([,v])=>v)),...(period==='all'?{}:{since:Date.now()/1000-Number(period)*86400})},offset}});if(version===epoch.current){setItems(old=>offset?[...old,...value.items.filter(v=>!old.some(r=>r.id===v.id))]:[...value.items,...old.filter(v=>!value.items.some(r=>r.id===v.id))]);setKinds(value.kinds);setStates(value.task_states);setAcceptance(value.acceptance);setLoaded(true);if(offset||pages.current===1)setNext(value.next_offset);if(offset)pages.current++;setError('');}}catch(e){if(version===epoch.current)setError(String(e));}finally{reading.current=false;if(version===epoch.current)setPending(false);}}
 useEffect(()=>{setItems([]);setLoaded(false);pages.current=1;setNext(null);void refresh();const timer=setInterval(()=>void refresh(),3000);return()=>{epoch.current++;clearInterval(timer);};},[info,query,filters]);
 return <div className="execution-center"><div className="execution-toolbar"><label>根任务编号 <input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void refresh();}}/></label><UiButton busy={pending} disabled={!info} onClick={()=>void refresh()}>查询任务</UiButton><UiButton onClick={onInspectCalls}>模型调用详情</UiButton></div>
  <details><summary>Agent 与执行筛选</summary><div className="execution-toolbar">{([['model','模型'],['agent','Agent 编号'],['role','角色编号'],['purpose','任务类型（purpose）'],['channel','渠道'],['state','任务状态'],['configuration_version','配置版本'],['code_version','运行代码版本']]as const).map(([key,label])=><label key={key}>{label}<input value={filters[key]} onChange={e=>setFilters(v=>({...v,[key]:e.target.value}))}/></label>)}</div></details>
  <label>任务提交时间 <select value={filters.period} onChange={e=>setFilters(v=>({...v,period:e.target.value}))}><option value="7">最近7天</option><option value="30">最近30天</option><option value="all">全部时间</option></select></label>
  {loaded&&<><p className="ui-field-help">根任务 {kinds.task||0} · 独立调用 {kinds.operation||0} · 诊断 {kinds.diagnostic||0}；子任务不重复计入根任务次数。</p><p className="ui-field-help">{Object.entries(states||{}).map(([state,count])=>`${executionState[state]||state} ${count}`).join(' · ')}</p>{acceptance&&<p className="ui-field-help">原任务验收通过 {acceptance.passed}/{acceptance.known} 个已记录判断 · 覆盖 {acceptance.known}/{acceptance.total} · {acceptance.unknown} 项待核验</p>}</>}
  {error&&<UiFeedback state="error" title="任务读取失败">{error}</UiFeedback>}
  {!loaded&&!error&&<UiFeedback state={info?'loading':'unconfirmed'} title={info?'正在读取任务记录':'尚未连接本地后端'}/>}
  {loaded&&!pending&&!items.length&&!error&&<UiFeedback state={query?'no_results':'empty'} title={query?'没有匹配的任务':'还没有执行记录'}/>}
  <div className="execution-roots">{items.map(row=><UiButton key={row.id} aria-pressed={root===row.id} onClick={()=>setRoot(row.id)}>{row.id} · {executionState[row.state]||row.state}</UiButton>)}</div>
  {next!=null&&<UiButton busy={pending} onClick={()=>void refresh(next)}>加载更早执行</UiButton>}
  {root&&<ExecutionTrace info={info} root={root}/>}
 </div>;
}
