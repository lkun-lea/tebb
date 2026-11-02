import {useCallback,useEffect,useRef,useState} from 'react';
import {rpc,type BackendInfo} from './api';
import {usePageActive} from './page-stack';

export type WorkflowSchedule={id:string;name:string;action:string;enabled:boolean;active?:boolean;schedule_text?:string;last_result?:string;last_error?:string;workflow_id?:string;workflow_version?:string;cadence:string;hour:number;minute:number;date?:string;weekdays:number[];[key:string]:unknown};
// One owner for schedule status on both the overview and the design page.
export function useWorkflowSchedules(info:BackendInfo|null,debug=false,disabled=false){
  const active=usePageActive(),[jobs,setJobs]=useState<WorkflowSchedule[]>([]),[loaded,setLoaded]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState('');
  const generation=useRef(0),reading=useRef(false),saving=useRef(false);
  const reload=useCallback(async()=>{
    if(!info||debug||reading.current)return;
    const current=generation.current;reading.current=true;
    try{const value=await rpc<{ok:boolean;items:WorkflowSchedule[];error?:string}>(info,'list_automation_jobs');if(!value.ok)throw Error(value.error||'触发计划读取失败');if(current===generation.current){setJobs(value.items);setLoaded(true);setError('');}}
    catch(e){if(current===generation.current)setError(String(e));}
    finally{reading.current=false;}
  },[info?.port,info?.token,debug]);
  useEffect(()=>{setJobs([]);setLoaded(false);setError('');},[info?.port,info?.token,debug]);
  useEffect(()=>{if(!active||!info||debug)return;void reload();const timer=window.setInterval(()=>void reload(),2500);return()=>{generation.current++;window.clearInterval(timer);};},[active,reload]);
  async function toggle(job:WorkflowSchedule){
    if(!info||saving.current||disabled||debug||job.active||(!job.enabled&&job.action!=='workflow'))return;
    saving.current=true;setBusy(job.id);setError('');
    try{const value=await rpc<{ok:boolean;error?:string}>(info,'save_automation_job',{payload:{...job,enabled:!job.enabled}});if(!value.ok)throw Error(value.error||'计划未保存');await reload();}
    catch(e){setError(String(e)+'；结果不明先刷新核对原计划。');}
    finally{saving.current=false;setBusy('');}
  }
  return {jobs,loaded,error,busy,reload,toggle};
}
export type WorkflowScheduleState=ReturnType<typeof useWorkflowSchedules>;

export function WorkflowSchedules({state,debug=false,disabled=false,onEdit}:{state:WorkflowScheduleState;debug?:boolean;disabled?:boolean;onEdit?:(job:WorkflowSchedule)=>void}){
  const {jobs,error,busy,reload,toggle}=state;
  return <section className="workflow-trigger-list" aria-label="触发计划管理"><h3>触发计划与原有计划 <small>{jobs.length}</small></h3><p>计划绑定保存时的版本。原有计划仍按原规则运行，可明确停用；新建计划请在已保存工作流中配置。</p>{!state.loaded&&!error&&<p>正在读取触发计划…</p>}{state.loaded&&!jobs.length&&<p>尚未配置触发计划。工作流仍可手动运行。</p>}{jobs.map(job=><div key={job.id}><strong>{job.name}</strong><span>{job.action==='workflow'?'工作流版本 '+job.workflow_version?.slice(0,8):'原有 '+job.action} · {job.schedule_text} · {job.enabled?'启用':'停用'} · {job.last_result||'未执行'}</span>{job.last_error&&<p>{job.last_error}</p>}<button disabled={disabled||!!busy||debug||!!job.active||(!job.enabled&&job.action!=='workflow')} onClick={()=>void toggle(job)}>{job.enabled?'停用计划':'启用此工作流版本'}</button>{job.action==='workflow'&&onEdit&&<button disabled={disabled||!!busy||debug||!!job.active} onClick={()=>onEdit(job)}>编辑原计划</button>}<details><summary>原计划与执行回执</summary><pre>{JSON.stringify(job,null,2)}</pre></details></div>)}{error&&<p role="alert">{error}</p>}<button disabled={disabled||!!busy||debug} onClick={()=>void reload()}>刷新核对计划</button></section>;
}
