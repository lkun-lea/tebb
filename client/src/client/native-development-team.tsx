import {useEffect, useRef, useState} from "react";
import {rpc,type BackendInfo} from "./api";
import {CollaborationSync,loadCollaboration} from "./collaboration-sync";
import type {DemoState} from "./chat-prototype-state";
import {usePageActive} from "./page-stack";
import {DevelopmentFlow} from "./development-flow";
import {FlowCanvas} from "./flow-canvas";

export function NativeDevelopmentTeam({info,onOpen,onSetup}:{info:BackendInfo|null;onOpen?:(id:string)=>Promise<void>;onSetup?:()=>void}) {
 const [state,setState]=useState<DemoState|null>(null);
 const [groupId,select]=useState("");
 const [goal,setGoal]=useState("");
 const [notice,setNotice]=useState("");
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 const [runId,setRunId]=useState("");
 const [composing,setComposing]=useState(false);
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
     setState(reply.state);setRunId("");setGoal("");setComposing(false);pending.current=null;setNotice("已开始，下面的卡片会随实际进度更新。");
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
 return <div>
  <div className="team-start">
   {error&&<p role="alert">{error}</p>}
   <label>1. 选择项目　<select aria-label="项目群" disabled={busy||!group} value={group?.id||""} onChange={e=>{select(e.target.value);setRunId("");setNotice("");}}>
    {!group&&<option value="">{state?"请先打开项目文件夹":"正在连接…"}</option>}
    {groups.map(c=><option key={c.id} value={c.id}>{state?.projects?.find(p=>p.id===c.project_id)?.name||c.title} · {c.title}</option>)}</select></label>
   {!group&&state&&<><p>先打开项目文件夹并创建项目群，加入编码伙伴。文件编辑与终端权限在项目中设置。</p>
    {onSetup&&<button onClick={onSetup}>打开项目设置</button>}</>}
   {group&&(!root||composing)?<>
    <label>2. 想改什么？<textarea aria-label="项目开发需求" disabled={busy} value={goal} onChange={e=>setGoal(e.target.value)}
     placeholder="例如：新建事项后，让它立即出现在周视图旁边；切换日期、重启后也能看到。"/></label>
    <small>写出现象和希望的结果，或粘贴 issue 正文。团队会自行定位代码、修改和测试。</small>
    <button disabled={busy||!!goal.trim()} onClick={()=>setGoal("新建事项后，让它立即出现在周视图旁边；切换日期、重启后也能看到。请修复并验证这些操作。")}>填入示例</button>
    <button className="team-primary ml-3" disabled={busy||!capable||!goal.trim()} onClick={()=>void start()}>{busy?"正在提交…":"3. 开始开发"}</button>
    {!capable&&<p role="status">还缺具备“文件编辑、终端”权限的编码伙伴。{onOpen&&<button onClick={()=>void onOpen(group.id).catch(e=>setNotice(String(e)))}>去项目群设置</button>}</p>}
   </>:group&&<button onClick={()=>setComposing(true)}>开始新需求</button>}
   {root&&<label>本项目运行　<select aria-label="运行记录" value={root.id} onChange={e=>setRunId(e.target.value)}>
    {roots.map(r=><option key={r.id} value={r.id}>{r.title} · {r.id.slice(0,8)}</option>)}</select></label>}
   {notice&&<p role="status">{notice}</p>}
  </div>
  {root?<DevelopmentFlow key={root.id} root={root} runs={runs} agents={agents} busy={busy} onStop={()=>void stop()}
   onOpen={onOpen?()=>void onOpen(group!.id).catch(e=>setNotice(String(e))):undefined}/>:
   <section aria-label="开发流程概览"><small>填写需求并点击“开始开发”，下方卡片将显示真实阶段变化。</small>
    <FlowCanvas nodes={["需求与分工","实现与自测","独立验收","交付"].map((title,i)=>({id:String(i),title,state:"unseen",summary:"尚未开始"}))}/></section>}
 </div>;
}
