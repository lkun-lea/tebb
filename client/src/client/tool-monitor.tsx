import {WorkspaceDialog} from './workspace-dialog';
import { useEffect, useRef, useState } from 'react';
import {ToolLibrary} from './tool-library';
import {rpc,type BackendInfo} from './api';
import {UiButton,UiFeedback,UiField} from './ui-controls';
import {executionState} from './execution-trace';
import {EvaluationCaseEditor} from './evaluation-center';
type Definition={name:string;description:string;collection:string;source:string;version:string;parameters:unknown};
type Event={id:string;seq:number;tool:string;phase:string;state?:string;root:string;task:string;error_message?:string;error_kind?:string;attempt_id?:string};
type Result={definitions:Definition[];items:Event[];stats:Record<string,Record<string,number>>;timings?:Record<string,{trend?:number[];samples:number;p50_ms:number|null;p95_ms:number|null;latest_error?:{id:string;root?:string;error_message:string}}>;scope_status?:Record<string,unknown>;next_after:number|null;collections:string[]};
const phaseLabels:Record<string,string>={offer:"提供",attempt:"开始调用",outcome:"调用结果",load:"加载"};
export function ToolMonitorPane({info,onTrace,onConnections,onChat}:{onChat?:(id:string)=>void;onConnections?:()=>void;info:BackendInfo|null;onTrace:(root:string)=>void}){
 const [result,setResult]=useState<Result|null>(null),[query,setQuery]=useState(''),[tool,setTool]=useState(''),[error,setError]=useState(''),[pending,setPending]=useState(false);
 const [draftFilters,setDraftFilters]=useState({collection:'',state:'',model:'',task:'',session:'',root:'',period:'7'}),[filters,setFilters]=useState(draftFilters);
 const epoch=useRef(0);
 useEffect(()=>{setResult(null);},[info]);
 async function load(after=0){if(!info)return;const version=++epoch.current;setPending(true);const {period,...selected}=filters;try{const found=await rpc<Result>(info,'execution_inspect',{operation:'tools',payload:{filters:{...Object.fromEntries(Object.entries(selected).filter(([,v])=>v)),...(period==='all'?{}:{since:Date.now()/1000-Number(period)*86400})},after}});if(version===epoch.current){setResult(old=>after&&old?{...found,items:[...old.items,...found.items]}:found);setError('');}}catch(e){if(version===epoch.current)setError(String(e));}finally{if(version===epoch.current)setPending(false);}}
 useEffect(()=>{void load();return()=>{epoch.current++;};},[info,filters]);
 const [tab,setTab]=useState<'activity'|'catalog'>('catalog');
 const [sort,setSort]=useState("errors");
 const rows=Object.entries(result?.stats||{}).map(([name,v])=>({name,ok:v.returned||0,fail:v.failed||0,timeout:v.timed_out||0,rejected:v.rejected||0,unknown:v.unknown||0,offers:v.offer||0,attempts:v.attempt||0,loads:v.load||0})).filter(r=>r.name.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>sort==="calls"?b.attempts-a.attempts:sort==="name"?a.name.localeCompare(b.name):(b.fail+b.timeout)-(a.fail+a.timeout)||b.ok-a.ok);
 const ok=rows.reduce((n,r)=>n+r.ok,0),bad=rows.reduce((n,r)=>n+r.fail+r.timeout,0);
 const active=tool?rows.find(r=>r.name===tool)||{name:tool,loads:0,offers:0,attempts:0}:undefined;
 const [inspectTool,setInspectTool]=useState(false);
 const timing=active&&result?.timings?.[active.name];
 const failure=timing?.latest_error;
 return <section className="execution-center tool-dashboard" aria-label="工具监控">
  <div className="design-tabs"><UiButton aria-pressed={tab==='activity'} onClick={()=>setTab('activity')}>调用概览</UiButton><UiButton aria-pressed={tab==='catalog'} onClick={()=>setTab('catalog')}>工具目录</UiButton>{tab==="activity"&&<label><select aria-label="调用时间" value={draftFilters.period} onChange={e=>{setDraftFilters(v=>({...v,period:e.target.value}));setFilters(v=>({...v,period:e.target.value}));}}><option value="7">最近7天</option><option value="30">最近30天</option><option value="all">全部时间</option></select></label>}</div>
  {tab==="activity"&&<details className="tool-filters"><summary>搜索与筛选</summary><div className="execution-toolbar"><UiField label="搜索工具与集合"><input value={query} onChange={e=>setQuery(e.target.value)}/></UiField><UiField label="工具集合"><select value={draftFilters.collection} onChange={e=>setDraftFilters(v=>({...v,collection:e.target.value}))}><option value="">全部集合</option>{result?.collections?.map(c=><option key={c}>{c}</option>)}</select></UiField><UiField label="调用状态"><select value={draftFilters.state} onChange={e=>setDraftFilters(v=>({...v,state:e.target.value}))}><option value="">全部状态</option>{['returned','failed','rejected','timed_out','unknown','cancelled'].map(s=><option key={s} value={s}>{executionState[s]||s}</option>)}</select></UiField>{([['model','模型'],['task','物理任务'],['session','会话'],['root','根任务']]as const).map(([key,label])=><UiField key={key} label={label}><input value={draftFilters[key]} onChange={e=>setDraftFilters(v=>({...v,[key]:e.target.value}))}/></UiField>)}<UiButton disabled={!info} onClick={()=>setFilters({...draftFilters})}>应用调用筛选</UiButton><UiButton busy={pending} onClick={()=>void load()}>刷新</UiButton></div></details>}
  {error&&<UiFeedback state="error" title="工具记录读取失败">{error}，上次结果已保留。</UiFeedback>}
  {!result&&!error&&<UiFeedback state={info?'loading':'unconfirmed'} title={info?'正在读取工具记录':'尚未连接本地后端'}/>}
  {tab==='activity'?<>
    <div className="tool-metrics"><span>已知结果调用<b>{ok+bad}</b></span><span>已返回<b>{ok}</b></span><span>失败及超时<b>{bad}</b></span><span>返回率<b>{ok+bad?(ok/(ok+bad)*100).toFixed(1)+'%':'—'}</b></span></div>
    <div className="tool-columns"><section className="design-card"><header><h3>工具调用</h3><select aria-label="排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="errors">失败优先</option><option value="calls">调用最多</option><option value="name">按名称</option></select></header>
    <table><thead><tr>{['工具','已返回','失败','P50','调用趋势'].map(k=><th key={k}>{k}</th>)}</tr></thead><tbody>{rows.filter(r=>r.attempts||r.ok||r.fail||r.timeout||r.rejected||r.unknown).map(r=>{
      const measured=result?.timings?.[r.name],series=measured?.trend||[];
      return <tr key={r.name} onClick={()=>{setTool(r.name);setInspectTool(true)}} data-selected={r.name===active?.name}><td><button onClick={()=>{setTool(r.name);setInspectTool(true)}}>{r.name}</button></td><td>{r.ok}</td><td>{r.fail+r.timeout}</td><td>{measured?.p50_ms==null?'—':measured.p50_ms+' ms'}</td>
       <td>{series.some(Boolean)?<svg role="img" aria-label={'各时段调用次数 '+series.join('、')} viewBox="0 0 100 26"><polyline fill="none" stroke="currentColor" strokeWidth="2" points={series.map((v,i)=>i*100/Math.max(1,series.length-1)+','+(24-22*v/Math.max(...series))).join(' ')}/></svg>:'—'}</td></tr>;
    })}</tbody></table></section>{inspectTool&&active&&<WorkspaceDialog title="工具调用记录" onClose={()=>setInspectTool(false)}><p>{active.name}</p><h3>最近失败</h3><p>{failure?.error_message||'当前范围内没有失败回执'}</p>{failure?.root&&<UiButton onClick={()=>onTrace(failure.root!)}>查看关联运行 →</UiButton>}
    {active&&<dl className="tool-counts">{[['加载',active.loads],['提供',active.offers],['调用',active.attempts]].map(([label,n])=><div key={label}><dt>{label}</dt><dd>{n}</dd></div>)}</dl>}
    {active&&/^(feishu|github|connection_|video_)/i.test(active.name)&&onConnections&&<UiButton onClick={onConnections}>管理外部连接 →</UiButton>}
    {failure&&<EvaluationCaseEditor info={info} sourceFailure={failure.id}/>}</WorkspaceDialog>}</div>
    <small>返回率按已返回、失败和超时计算。趋势按所选时段等分统计。</small>
  </>:<ToolLibrary key={info?.port} onChat={onChat} onRefresh={load} info={info} definitions={result?.definitions || []} onActivity={name=>{
    setTool(name);setTab('activity');setInspectTool(true);
  }}/>}

  {tab==='activity'&&<><details><summary>最近错误与耗时分布</summary>
    <table className="tool-timing"><thead><tr><th>工具</th><th>耗时样本</th><th>P95</th><th>最近错误</th></tr></thead><tbody>{rows.map(r=>{const t=result?.timings?.[r.name];return t&&(t.samples>0||t.latest_error)?<tr key={r.name}><td>{r.name}</td><td>{t.samples}</td><td>{t.p95_ms==null?'—':t.p95_ms+' ms'}</td><td>{t.latest_error?.root?<button onClick={()=>onTrace(t.latest_error!.root!)}>定位失败任务</button>:t.latest_error?.error_message||'—'}</td></tr>:null})}</tbody></table>
    <small>P95 仅在耗时样本足够时显示。</small></details>
  <details><summary>全部工具 · 调用明细</summary><ol aria-label="工具生命周期">{result?.items.map(e=><li key={e.id}><details className="tool-entry"><summary><strong>{e.tool}</strong><small>{phaseLabels[e.phase]||e.phase} · {executionState[e.state||'']||e.state||'已记录'}</small></summary>{e.error_message&&<><p>{e.error_kind}：{e.error_message}</p><EvaluationCaseEditor info={info} sourceFailure={e.id}/></>}<p className="ui-field-help">记录编号 <code>{e.id}</code></p>{e.attempt_id&&<p>尝试编号 <code>{e.attempt_id}</code></p>}{e.root&&<UiButton onClick={()=>onTrace(e.root)}>查看所属任务执行图</UiButton>}</details></li>)}</ol></details></>}
  {tab==="activity"&&result?.next_after!=null&&<UiButton busy={pending} onClick={()=>void load(result.next_after!)}>加载更多工具事件</UiButton>}

 </section>;
}
