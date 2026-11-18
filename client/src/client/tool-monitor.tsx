import { useEffect, useRef, useState } from 'react';
import {rpc,type BackendInfo} from './api';
import {UiButton,UiFeedback,UiField} from './ui-controls';
import {ExecutionTrace,executionState} from './execution-trace';
import {EvaluationCaseEditor} from './evaluation-center';
type Definition={name:string;description:string;collection:string;source:string;version:string;parameters:unknown};
type Event={id:string;seq:number;tool:string;phase:string;state?:string;root:string;task:string;error_message?:string;error_kind?:string;attempt_id?:string};
type Result={definitions:Definition[];items:Event[];stats:Record<string,Record<string,number>>;timings?:Record<string,{samples:number;p50_ms:number|null;p95_ms:number|null;latest_error?:{error_message:string}}>;scope_status?:Record<string,unknown>;next_after:number|null;collections:string[]};
export function ToolMonitorPane({info}:{info:BackendInfo|null}){
 const [result,setResult]=useState<Result|null>(null),[query,setQuery]=useState(''),[tool,setTool]=useState(''),[root,setRoot]=useState(''),[error,setError]=useState(''),[pending,setPending]=useState(false);
 const [draftFilters,setDraftFilters]=useState({collection:'',state:'',model:'',task:'',session:'',root:'',period:'7'}),[filters,setFilters]=useState(draftFilters);
 const epoch=useRef(0);
 useEffect(()=>{setResult(null);setRoot('');},[info]);
 async function load(after=0){if(!info)return;const version=++epoch.current;setPending(true);const {period,...selected}=filters;try{const found=await rpc<Result>(info,'execution_inspect',{operation:'tools',payload:{filters:{...Object.fromEntries(Object.entries({...selected,tool}).filter(([,v])=>v)),...(period==='all'?{}:{since:Date.now()/1000-Number(period)*86400})},after}});if(version===epoch.current){setResult(old=>after&&old?{...found,items:[...old.items,...found.items]}:found);setError('');}}catch(e){if(version===epoch.current)setError(String(e));}finally{if(version===epoch.current)setPending(false);}}
 useEffect(()=>{void load();return()=>{epoch.current++;};},[info,tool,filters]);
 const definitions=result?.definitions.filter(d=>(d.name+' '+d.collection+' '+d.description).toLowerCase().includes(query.toLowerCase()))||[];
 return <section className="execution-center" aria-label="工具监控"><div className="execution-toolbar"><UiField label="搜索工具与集合"><input value={query} onChange={e=>setQuery(e.target.value)}/></UiField><UiButton busy={pending} disabled={!info} onClick={()=>void load()}>刷新工具记录</UiButton>{tool&&<UiButton onClick={()=>setTool('')}>显示全部调用</UiButton>}</div>
  <p className="ui-field-help">目录显示历史配置版本。当前账号、项目与任务的权限在实际调用前重新检查；加载不授予权限。缺少记录的可用性、加载状态与费用保持未知。</p>
  <UiField label="调用时间"><select value={draftFilters.period} onChange={e=>{setDraftFilters(v=>({...v,period:e.target.value}));setFilters(v=>({...v,period:e.target.value}));}}><option value="7">最近7天</option><option value="30">最近30天</option><option value="all">全部时间</option></select></UiField>
  <p className="ui-field-help">次数按工具名汇总，包含各版本；每条调用保留其实际版本。实际调用尝试指适配器调用，业务结果和外部写入另看原回执。</p>
  <details><summary>加载与缓存兼容性</summary><p>Pi 1.5.2 通过公开工具更新和应用侧发现实现按需加载；当前 Completions 请求按顺序重新发送已加载定义。原生 allowed_tools、tool_search、defer_loading 和 developer additional_tools 尚未启用。缓存收益仅采用 provider 实际回报，缺失保持未知。</p><p>目录中的登记与授权只描述当时的工具名称范围；连接配置、参数、目标和实际写入权限仍由原产品适配器检查。</p></details>
  <details><summary>调用与失败筛选</summary><div className="execution-toolbar"><UiField label="工具集合"><select value={draftFilters.collection} onChange={e=>setDraftFilters(v=>({...v,collection:e.target.value}))}><option value="">全部集合</option>{result?.collections?.map(c=><option key={c}>{c}</option>)}</select></UiField><UiField label="调用状态"><select value={draftFilters.state} onChange={e=>setDraftFilters(v=>({...v,state:e.target.value}))}><option value="">全部状态</option>{['returned','failed','rejected','timed_out','unknown','cancelled'].map(s=><option key={s} value={s}>{executionState[s]||s}</option>)}</select></UiField>{([['model','模型'],['task','物理任务'],['session','会话'],['root','根任务']]as const).map(([key,label])=><UiField key={key} label={label}><input value={draftFilters[key]} onChange={e=>setDraftFilters(v=>({...v,[key]:e.target.value}))}/></UiField>)}<UiButton disabled={!info} onClick={()=>setFilters({...draftFilters})}>应用调用筛选</UiButton></div></details>
  {error&&<UiFeedback state="error" title="工具记录读取失败">{error}，上次结果已保留。</UiFeedback>}
  {!result&&!error&&<UiFeedback state={info?'loading':'unconfirmed'} title={info?'正在读取工具记录':'尚未连接本地后端'}/>}
  {result&&!definitions.length&&<UiFeedback state={query?'no_results':'empty'} title={query?'没有匹配的工具':'还没有登记的工具；运行任务后可查看真实目录'}/>}
  <div className="tool-monitor-list">{definitions.map(d=><article key={d.version}><h2>{d.collection} · {d.name}</h2><p>{d.description}</p><p className="ui-field-help">来源：{d.source} · 版本：<code>{d.version}</code></p><p>{Object.entries(result?.stats[d.name]||{}).map(([k,v])=>`${k} ${v}`).join(' · ')||'尚无调用记录'}</p><UiButton aria-pressed={tool===d.name} onClick={()=>setTool(d.name)}>查看调用与失败</UiButton><details><summary>固定工具定义</summary><pre>{JSON.stringify(d.parameters,null,2)}</pre></details></article>)}</div>
  <details><summary>耗时、最近错误与所选任务加载状态</summary><pre>{JSON.stringify({timings:result?.timings,scope_status:result?.scope_status},null,2)}</pre></details>
  <ol aria-label="工具生命周期">{result?.items.map(e=><li key={e.id}><p><code>{e.tool}</code> · {e.phase} · {executionState[e.state||'']||e.state||'已记录'}</p>{e.error_message&&<><p role="status">{e.error_kind}：{e.error_message}</p><EvaluationCaseEditor info={info} sourceFailure={e.id}/></>}<p className="ui-field-help">{e.id} {e.attempt_id}</p>{e.root&&<UiButton onClick={()=>setRoot(e.root)}>查看所属任务执行图</UiButton>}</li>)}</ol>
  {result?.next_after!=null&&<UiButton busy={pending} onClick={()=>void load(result.next_after!)}>加载更多工具事件</UiButton>}
  {root&&<ExecutionTrace info={info} root={root}/>}
 </section>;
}
