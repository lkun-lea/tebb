import {useEffect, useRef, useState} from "react";
import {rpc,type BackendInfo} from "./api";
import {CollaborationSync,loadCollaboration} from "./collaboration-sync";
import type {DemoState} from "./chat-prototype-state";
import {usePageActive} from "./page-stack";

const terminalState:Record<string,string>={succeeded:"已完成",failed:"失败",cancelled:"已停止",timed_out:"超时",interrupted:"中断",needs_input:"待补充"};

export function NativeDevelopmentTeam({info,onOpen}:{info:BackendInfo|null;onOpen?:(id:string)=>Promise<void>}) {
 const [state,setState]=useState<DemoState|null>(null);
 const [groupId,select]=useState("");
 const [goal,setGoal]=useState("");
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 const pending=useRef<{key:string;id:string}|null>(null), sending=useRef(false);
 const active=usePageActive();
 useEffect(()=>{
   if(!info||!active)return;
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
     setState(reply.state);setGoal("");pending.current=null;setNotice("已登记，可在项目群查看分工、补充需求或停止任务。");
   }catch(e){setNotice(String(e));}finally{sending.current=false;setBusy(false);}
 }
 const runs=(state?.runs??[]).filter(r=>r.conversation===group?.id);
 const root=[...runs].reverse().find(r=>!r.parent&&r.development_task);
 return <div className="my-4 rounded-lg border bg-card p-4">
   <h2 className="font-semibold">项目群开发</h2>
   {error&&<p role="alert">{error}</p>}
   {!state?<p>等待协作服务</p>:!group?<p>请在伙伴聊天中打开项目文件夹，创建项目群，并加入具备文件编辑和终端权限的编码伙伴。</p>:<>
   <label>项目群　<select disabled={busy} className="rounded border bg-card p-1" value={group.id} onChange={e=>{select(e.target.value);setNotice("");}}>
   {groups.map(c=><option key={c.id} value={c.id}>{state.projects?.find(p=>p.id===c.project_id)?.name} · {c.title}</option>)}</select></label>
   <p className="my-2 text-sm">参与伙伴 · {agents.map(a=>a.name+(a.id===group.coordinator?"（负责人）":"")).join("、")}</p>
   <textarea aria-label="项目开发需求" disabled={busy} className="block w-full rounded border bg-background p-2" value={goal} onChange={e=>setGoal(e.target.value)} placeholder="描述要完成的用户行为、涉及的模块和验收方式"/>
   {!capable&&<p>请在项目群加入具备文件编辑和终端权限的编码伙伴。</p>}
   <button className="mt-2 rounded bg-secondary px-3 py-2" disabled={busy||!capable||!goal.trim()} onClick={()=>void start()}>{busy?"登记中…":"开始团队开发"}</button>
   {onOpen&&<button className="ml-3" onClick={()=>void onOpen(group.id).catch(e=>setNotice(String(e)))}>打开项目群</button>}
   {root&&<div className="mt-3"><strong>{root.title}</strong>{[root,...runs.filter(r=>r.parent===root.id)].map(r=><p key={r.id}>{agents.find(a=>a.id===r.agent)?.name??r.agent} · {terminalState[r.state]||r.status||r.state} · {r.title}{r.error&&" · "+r.error}</p>)}</div>}
   </>}
   {notice&&<p role="status">{notice}</p>}
 </div>;
}
