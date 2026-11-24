import {WorkspaceDialog} from './workspace-dialog';
import { ExecutionTree } from './run-progress';
import {ExecutionEntry} from './execution-entry';
import { usePageActive } from "./page-stack";
import { useEffect, useState } from "react";
import { rpc, type BackendInfo } from "./api";
import { RUN_LABELS, runActive, type DemoState } from "./chat-prototype-state";

export function WorkspaceRuns({ info, onOpen }: { info: BackendInfo | null; onOpen: (conversation: string) => void }) {
  const pageActive = usePageActive();
  const [state, setState] = useState<DemoState | null>(null), [error, setError] = useState("");
  useEffect(() => {
    if (!pageActive || !info) return; let live = true, loading = false;
    const load = async () => { if (loading) return; loading=true;
      try { const result = await rpc<{state:DemoState}>(info,'load_collaboration'); if(live) setState(result.state); }
      catch(e) { if(live) setError(String(e)); } finally { loading=false; }
    };
    void load(); const timer=window.setInterval(()=>void load(),1200);
    return()=>{live=false;window.clearInterval(timer);};
  },[pageActive,info?.port,info?.token]);
  async function cancel(id:string) {
    if(!info) return;
    try { const result=await rpc<{state:DemoState}>(info,'collaboration_action',{action:{type:'cancel',id,request_id:crypto.randomUUID()}}); setState(result.state); }
    catch(e){setError(String(e));}
  }
  const runs=(state?.runs || []).filter(r=>!r.parent&&(r.require_execution||r.state==='needs_input'||r.chain?.children.length||!['route','chat','compress'].includes(r.kind || ''))).slice().reverse();
  const [selected,setSelected]=useState("");
  const [limit,setLimit]=useState(12);
  const run=runs.find(item=>item.id===selected);
  function status(item:(typeof runs)[number]){
    const value=item.chain?.state||item.state;
    return ({running:'执行中',succeeded:'已完成',cancelled:'已停止'} as Record<string,string>)[value]||RUN_LABELS[value]||value;
  }
  return <section className="tebb-run-overview"><header className="channel-heading"><h2>协作任务</h2>{state&&<small>{runs.length} 项任务</small>}</header>
    {error&&<p role="alert">{error}</p>}{!state&&!error&&<p>正在读取协作任务…</p>}
    {state&&!runs.length&&<p>当前没有协作任务。</p>}
    <div className="collab-records">{runs.slice(0,limit).map(item=><button className="collab-record" key={item.id} onClick={()=>setSelected(item.id)}>
      <strong>{item.title}</strong><span data-state={item.chain?.state||item.state}>{status(item)}</span>
      <small>{[state?.agents.find(a=>a.id===item.agent)?.name,item.model].filter(Boolean).join(' · ')} · {item.chain?.calls??item.calls??0} 次模型调用</small>
    </button>)}</div>
    {runs.length>limit&&<button onClick={()=>setLimit(n=>n+12)}>显示更多任务</button>}
    {run&&<WorkspaceDialog title={run.title} onClose={()=>setSelected("")}><p>{status(run)} · {run.model}</p>
    {(run.clarification||run.chain?.error||run.error)&&<p>{run.clarification||run.chain?.error||run.error}</p>}
    <div><button onClick={()=>{setSelected("");onOpen(run.conversation)}}>回到对话</button>{(runActive(run)||run.state==='needs_input')&&<button onClick={()=>void cancel(run.id)}>停止</button>}</div>
    <ExecutionTree run={run} runs={state!.runs} agents={state!.agents}/><ExecutionEntry info={info} root={'collab:'+run.id}/>{!!run.changes?.length && <details><summary>改动文件 · {run.changes.length}</summary>{run.changes.map((c,i)=><div key={i}><strong>{c.path}</strong><pre>{c.diff}</pre></div>)}</details>}
    {!!run.checks?.length && <details><summary>实际命令回执</summary>{run.checks.map((c,i)=><div key={i}><code>{c.command}</code><p>{c.state} · 退出码 {c.exit_code ?? '无'}{c.stale?' · 此后文件发生修改':''}</p><pre>{c.output}</pre></div>)}</details>}</WorkspaceDialog>}
  </section>;
}
