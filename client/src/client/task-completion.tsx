import {useEffect,useState}from'react';
import {rpc,type BackendInfo}from'./api';
import type{BoardTask}from'./board';
import './reminders.css';

export type CompletionReceipt={ok:boolean;request_id?:string;guid?:string;summary?:string;identity?:{user_name?:string;open_id?:string};state?:string;stage?:string;remote_state?:string;execution_result?:string;observed_state?:string;cache_state?:string;already_completed?:boolean;error?:string;operations?:CompletionReceipt[]};
export type CompletionTransport=(method:string,args:Record<string,unknown>)=>Promise<CompletionReceipt>;
const stateLabel:Record<string,string>={prepared:'待确认',preparing:'核对中',calling:'提交中',unconfirmed:'结果待核对',confirmed:'已完成',observed_done:'查询到完成',not_started:'未提交'};
type Props={info:BackendInfo|null;debug:boolean;tasks:BoardTask[];onRefresh:()=>void;deleting?:boolean;taskErrors?:Record<string,string>;onDeleteTask?:(guid:string)=>void;transport?:CompletionTransport};

export function TaskCompletionPanel(props:Props){
  const [active,setActive]=useState<CompletionReceipt|null>(null),[history,setHistory]=useState<CompletionReceipt[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const available=!!props.transport||!!props.info&&!props.debug;
  const call:CompletionTransport=props.transport||((method,args)=>rpc<CompletionReceipt>(props.info!,method,args,{timeoutMs:120000}));
  async function load(){
    if(!available)return;
    try{const result=await call('task_completion_status',{});if(!result.ok)throw Error(result.error||'完成回执未读取。');setHistory(result.operations||[]);}
    catch(error){setError(String(error));}
  }
  useEffect(()=>{void load();},[props.info?.port,props.info?.token,props.transport,props.debug]);
  async function action(method:string,args:Record<string,unknown>,prior:CompletionReceipt){
    if(busy||!available)return;setBusy(true);setError('');setActive(prior);
    try{
      const result=await call(method,args);const receipt={...prior,...result};setActive(receipt);
      if(['confirmed','observed_done'].includes(receipt.state||''))props.onRefresh();
      await load();
    }catch(error){setActive({...prior,ok:false,state:'client_unconfirmed',error:'回执未返回，请核对原操作，勿直接重复提交。'});setError(String(error));}
    finally{setBusy(false);}
  }
  function prepare(guid:string){
    const request_id=crypto.randomUUID();void action('task_completion_prepare',{guid,request_id},{ok:false,guid,request_id,state:'preparing'});
  }
  const pending=active&&['client_unconfirmed','unconfirmed','calling','preparing'].includes(active.state||'');
  return <div>
    {props.tasks.map(task=><section className="sw-sync-row" key={task.guid||task.title}><strong>{task.title}</strong><span>{task.when}</span>
      {task.guid&&<><button type="button" disabled={!available||busy||props.deleting} onClick={()=>prepare(task.guid)}>完成待办</button>
        <button type="button" disabled={busy||props.deleting} onClick={()=>{if(window.confirm('真实删除此飞书待办？这不是标记完成。'))props.onDeleteTask?.(task.guid);}}>删除待办</button></>}
      {props.taskErrors?.[task.guid]&&<p role="alert">{props.taskErrors[task.guid]}</p>}
    </section>)}
    {active&&<fieldset className="task-completion-confirm" disabled={busy}><legend>{active.state==='prepared'?'确认完成待办':'完成操作结果'}</legend>
      <p><strong>{active.summary||props.tasks.find(task=>task.guid===active.guid)?.title||'原待办'}</strong></p>
      {active.identity&&<p>账号：{active.identity.user_name||'飞书用户'} · {active.identity.open_id?.slice(-6)}</p>}
      {active.state==='prepared'&&<><p>将此飞书待办标记为已完成。</p><button type="button" onClick={()=>void action('task_completion_confirm',{request_id:active.request_id},active)}>确认完成</button><button type="button" onClick={()=>setActive(null)}>取消</button></>}
      {pending&&<><p>原操作结果待核对。核对只读取状态。</p><button type="button" onClick={()=>void action('task_completion_inspect',{request_id:active.request_id},active)}>核对原结果</button></>}
      {active.state==='confirmed'&&<p role="status">{active.already_completed?'飞书原已完成。':'飞书已完成。'}</p>}
      {active.state==='observed_done'&&<p role="status">查询到已完成；原写入回执仍未知。</p>}
      {active.error&&<p role={active.cache_state==='unconfirmed'?'alert':'status'}>{active.error}</p>}
      {active.request_id&&<details><summary>操作编号</summary><code>{active.request_id}</code></details>}
      {!pending&&active.state!=='prepared'&&<button type="button" onClick={()=>setActive(null)}>关闭结果</button>}
    </fieldset>}
    <details className="task-completion-history"><summary>完成回执与待核对操作</summary><button type="button" disabled={busy||!available} onClick={()=>void load()}>读取原回执</button>
      {history.slice(0,100).map(row=><button type="button" key={row.request_id} disabled={busy} onClick={()=>setActive(row)}>{row.summary||'待办'} · {stateLabel[row.state||'']||'待核对'}</button>)}
    </details>
    {busy&&<p role="status">正在核对当前账号与原操作…</p>}{error&&<p role="alert">{error}</p>}
    {props.debug&&!props.transport&&<p>隔离演示不能完成真实飞书待办。</p>}
  </div>;
}
