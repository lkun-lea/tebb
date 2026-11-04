import {useEffect, useRef, useState} from "react";
import {rpc,type BackendInfo} from "./api";
import {CollaborationSync,loadCollaboration} from "./collaboration-sync";
import type {DemoState} from "./chat-prototype-state";
import {usePageActive} from "./page-stack";
import {DevelopmentFlow} from "./development-flow";
import "./experiment-flow.css";

export function NativeDevelopmentTeam({info,onOpen,onSetup}:{info:BackendInfo|null;onOpen?:(id:string)=>Promise<void>;onSetup?:()=>void}) {
 const [state,setState]=useState<DemoState|null>(null);
 const [groupId,select]=useState("");
 const [goal,setGoal]=useState("");
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 const [runId,setRunId]=useState("");
 const pending=useRef<{key:string;id:string}|null>(null), sending=useRef(false);
 const active=usePageActive();
 useEffect(()=>{
   if(!info){setState(null);return;}
   if(!active)return;
   const sync=new CollaborationSync();
   let live=true,timer:ReturnType<typeof setTimeout>;
   async function refresh(){
     try {const reply=await loadCollaboration(info!,sync.sync);if(live){const next=sync.update(reply);if(next)setState(next);setError("");}}
     catch(e){if(live)setError(String(e));}
     if(live)timer=setTimeout(refresh,5000);
   }
   void refresh();return ()=>{live=false;clearTimeout(timer);};
 },[info,active]);
 const groups=state?.conversations.filter(c=>c.kind==="group"&&c.project_id)??[];
 const group=groups.find(c=>c.id===groupId)??groups[0];
 const agents=(state?.agents??[]).filter(a=>group?.members.includes(a.id));
 const capable=agents.some(a=>a.id!==group?.coordinator&&a.tools.includes("文件编辑")&&a.tools.includes("终端"));
 async function start(){
   if(!info||!group||!goal.trim()||sending.current)return;
   const key=JSON.stringify([group.id,goal.trim()]);
   if(pending.current?.key!==key)pending.current={key,id:crypto.randomUUID()};
   sending.current=true;setBusy(true);setNotice("");
   try {
     const reply=await rpc<{ok:boolean;state:DemoState;error?:string}>(info,"collaboration_action",{action:{
       type:"send",conversation:group.id,target:group.coordinator,text:goal.trim(),mode:"task",
       strategy:"delegate",development_task:true,request_id:pending.current.id}},{timeoutMs:15000});
     if(!reply.ok||!reply.state)throw Error(reply.error||"未取得任务登记回执");
     setState(reply.state);setRunId("");setGoal("");pending.current=null;setNotice("已登记，可在项目群查看分工、补充需求或停止任务。");
   }catch(e){setNotice(String(e));}finally{sending.current=false;setBusy(false);}
 }
 const runs=(state?.runs??[]).filter(r=>r.conversation===group?.id);
 const roots=[...runs].reverse().filter(r=>!r.parent&&r.development_task);
 const root=roots.find(r=>r.id===runId)??roots[0];
 async function stop(){
   if(!info||!root||busy)return;
   setBusy(true);
   try{
     const reply=await rpc<{ok:boolean;state:DemoState;error?:string}>(info,"collaboration_action",
       {action:{type:"cancel",id:root.id,request_id:crypto.randomUUID()}});
     if(!reply.ok)throw Error(reply.error||"未确认停止");
     setState(reply.state);setNotice("停止请求已登记，等待运行状态确认。");
   }catch(e){setNotice(String(e));}finally{setBusy(false);}
 }
 return <div className="my-4 rounded-lg border bg-card p-4">
   <h2 className="font-semibold">原生开发团队 · 项目群开发</h2>
   {error&&<p role="alert">{error}</p>}
   <div className="team-selectors">
    <label>项目群　<select aria-label="项目群" disabled={busy||!group} value={group?.id||""} onChange={e=>{select(e.target.value);setRunId("");setNotice("");}}>
     {!group&&<option value="">{state?"尚无项目群":"等待协作服务"}</option>}
     {groups.map(c=><option key={c.id} value={c.id}>{state?.projects?.find(p=>p.id===c.project_id)?.name} · {c.title}</option>)}</select></label>
    <label>运行记录　<select aria-label="运行记录" disabled={!root} value={root?.id||""} onChange={e=>setRunId(e.target.value)}>
     {!root&&<option value="">尚无原生开发记录</option>}
     {roots.map(r=><option key={r.id} value={r.id}>{r.title} · {r.id.slice(0,8)}</option>)}</select></label>
   </div>
   {!root&&<section className="team-empty-flow" aria-label="开发流程概览">
    <strong>开发流程 · 尚未运行</strong>
    <ol>{["需求与分工","实现与自测","独立验收","交付"].map(name=><li key={name}>{name}</li>)}</ol>
    <p>{!state?"连接协作服务后可选择项目群和历史运行。":!group?"先在伙伴聊天中打开项目文件夹，再创建项目群并加入编码伙伴。":
     "这个项目群还没有从本页发起的开发任务。填写下方需求并开始团队开发后，这里会展示真实节点进度。"}</p>
    <small>已有外部实验请展开下方“外部开发流程实验记录”。普通聊天任务不计入此处。</small>
    {!group&&onSetup&&<button className="mt-3 block rounded border px-3 py-2" onClick={onSetup}>前往伙伴聊天设置项目群</button>}
   </section>}
   {!state?<p>等待协作服务</p>:!group?<p>请在伙伴聊天中打开项目文件夹，创建项目群，并加入具备文件编辑和终端权限的编码伙伴。</p>:<>
   <p className="my-2 text-sm">参与伙伴 · {agents.map(a=>a.name+(a.id===group.coordinator?"（负责人）":"")).join("、")}</p>
   <textarea aria-label="项目开发需求" disabled={busy} className="block w-full rounded border bg-background p-2" value={goal} onChange={e=>setGoal(e.target.value)} placeholder="描述要完成的用户行为、涉及的模块和验收方式"/>
   {!capable&&<p>请在项目群加入具备文件编辑和终端权限的编码伙伴。</p>}
   <button className="mt-2 rounded bg-secondary px-3 py-2" disabled={busy||!capable||!goal.trim()} onClick={()=>void start()}>{busy?"登记中…":"开始团队开发"}</button>
   {onOpen&&<button className="ml-3" onClick={()=>void onOpen(group.id).catch(e=>setNotice(String(e)))}>打开项目群</button>}
   {root&&<>
     <DevelopmentFlow key={root.id} root={root} runs={runs} agents={agents} busy={busy} onStop={()=>void stop()}
       onOpen={onOpen?()=>void onOpen(group.id).catch(e=>setNotice(String(e))):undefined}/></>}
   </>}
   {notice&&<p role="status">{notice}</p>}
 </div>;
}
