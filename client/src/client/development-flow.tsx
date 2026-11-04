import {useState} from "react";
import type {DemoRun,DemoAgent} from "./chat-prototype-state";
import "./development-flow.css";
import {FlowCanvas} from "./flow-canvas";

const labels:Record<string,string>={running:"执行中",waiting:"等待前序",pending:"待执行",queued:"排队中",cancelling:"正在停止",
 succeeded:"已完成",failed:"失败",timed_out:"超时",interrupted:"中断",cancelled:"已停止",needs_input:"待补充",unseen:"未开始"};
export const isOpen=(run:DemoRun)=>["running","waiting","pending","queued","cancelling","needs_input"].includes(run.state);

export function flowStages(root:DemoRun,runs:DemoRun[]){
 const children=runs.filter(r=>r.parent===root.id);
 const checks=children.filter(r=>r.integration_verification);
 const developers=children.filter(r=>!r.integration_verification);
 const latest=(items:DemoRun[])=>items[items.length-1];
 const routed=children.length>0;
 const ready=routed&&children.filter(r=>!r.rechecked_by&&r.id!==developers[0]?.id).every(r=>r.state==="succeeded")
   &&latest(developers)?.state==="succeeded";
 return [
  {id:"requirements",title:"需求与分工",role:"负责人",run:root,state:routed?"succeeded":root.state,
   summary:routed?"已产生真实任务分工":root.status||"正在确认执行路径"},
  {id:"develop",title:"实现与自测",role:"编码伙伴",run:latest(developers),state:latest(developers)?.state||"unseen",
   summary:latest(developers)?.status||"等待编码任务"},
  {id:"verify",title:"独立验收",role:"验证伙伴",run:latest(checks),state:latest(checks)?.state||"unseen",
   summary:latest(checks)?.status||"等待独立验收"},
  {id:"deliver",title:"交付",role:"负责人",run:ready||root.state==="succeeded"?root:undefined,
   state:root.state==="succeeded"?"succeeded":ready?root.state:"unseen",summary:ready?root.status||"整理交付结果":"等待前序任务完成"},
 ];
}

export function DevelopmentFlow({root,runs,agents,onStop,onOpen,busy=false}:{
 root:DemoRun;runs:DemoRun[];agents:DemoAgent[];onStop:()=>void;onOpen?:()=>void;busy?:boolean;
}){
 const [selected,select]=useState<string>("");
 const [attempt,setAttempt]=useState("");
 const [tab,setTab]=useState("flow");
 const [detailOpen,showDetail]=useState(false);
 const stages=flowStages(root,runs);
 const family=[root,...runs.filter(r=>r.parent===root.id)];
 const current=stages.find(s=>s.state==="running")||stages.find(s=>["needs_input","failed","timed_out"].includes(s.state))||stages.find(s=>s.state!=="succeeded")||stages[3];
 const node=stages.find(s=>s.id===selected)||current;
 const attempts=node.id==="develop"?familyFor("develop"):node.id==="verify"?familyFor("verify"):[root];
 function familyFor(stage:string){return runs.filter(r=>r.parent===root.id&&Boolean(r.integration_verification)===(stage==="verify"));}
 const run=attempts.find(r=>r.id===attempt)||node.run;
 const events=family.flatMap(r=>(r.flow_events||[]).map(e=>({...e,run:r}))).sort((a,b)=>(a.ts||0)-(b.ts||0)||a.seq-b.seq);
 const calls=run?.flow_events?.filter(e=>e.kind==="tool_start"||e.kind==="tool_end")||[];
 const latest=calls[calls.length-1];
 const input=[...calls].reverse().find(e=>e.kind==="tool_start"&&e.data.tool===latest?.data.tool)?.data;
 const checks=run?.checks||[];
 const report=family.filter(r=>r.feedback_check).at(-1)?.feedback_check;
 const tokens=family.every(r=>r.input_tokens!=null&&r.output_tokens!=null)
  ?family.reduce((total,r)=>total+r.input_tokens!+r.output_tokens!,0).toLocaleString():"未知";
 const last=events.at(-1);
 const seconds=root.created?Math.max(0,Math.floor((root.finished||Date.now()/1000)-root.created)):null;
 const clock=(ts?:number)=>ts?new Date(ts*1000).toLocaleTimeString():"时间未记录";
 return <section className="dev-flow" aria-label="开发流程">
  <header className="df-heading"><div><h3>{root.title}</h3><small>运行 {root.id.slice(0,8)} · {labels[root.state]}</small></div>
   <div>{onOpen&&<button onClick={onOpen}>打开项目群 / 补充说明</button>}
    {isOpen(root)&&<button disabled={busy||root.state==="cancelling"} onClick={onStop}>停止任务</button>}</div></header>
  <div className="df-summary" role="status"><span>当前阶段 <b>{current.title}</b></span><span>{labels[current.state]}</span>
   <span>最近回执 {clock(last?.ts)}</span><span>耗时 {seconds==null?"未知":Math.floor(seconds/60)+" 分 "+seconds%60+" 秒"}</span><span>Token {tokens}</span></div>
  <FlowCanvas nodes={stages.map(s=>({...s,detail:s.run?.flow_events?.at(-1)?.data.tool}))} current={current.id} selected={selected}
   onSelect={id=>{select(id);setAttempt("");showDetail(true);}} returning={!!root.integration_repair}/>
  <p role="status">{root.error||current.summary} · 每 5 秒同步真实运行状态</p>
  <details open={detailOpen} onToggle={e=>showDetail(e.currentTarget.open)}><summary>查看节点详情与执行记录</summary>
  <div className="df-tabs" role="tablist" aria-label="开发视图">{[["flow","流程图"],["events","事件记录"]].map(([id,name])=>
   <button key={id} role="tab" aria-selected={tab===id} onClick={()=>setTab(id)}>{name}</button>)}</div>
  <button onClick={()=>{select("");setAttempt("");}}>跟随当前节点</button>
  <div className="df-layout">
   <div>{tab==="flow"?null:<div className="df-event-list"><h4>执行事件</h4>{events.length?events.map(e=>
    <button key={e.run.id+"-"+e.seq} onClick={()=>{select(e.run.id===root.id?"requirements":e.run.integration_verification?"verify":"develop");setAttempt(e.run.id);}}>
     <time>{clock(e.ts)}</time> <strong>{e.data.tool||e.kind}</strong> {e.data.status||e.data.state} {e.data.error||e.data.query||e.data.path}
    </button>):<p>尚未记录结构化工具事件。</p>}<small>每个任务显示最近 80 条结构化事件。</small></div>}
   <section className="df-observer"><h4>监督与反思</h4>
    {report?<><p>{report.ok?"检查通过":"检查发现问题"} · {report.scope}</p>{report.checks.map(c=><p key={c.id}>{c.status} · {c.message}<small>{c.basis}</small></p>)}</>:<p>尚未产生监督检查回执。</p>}
    {root.integration_repair&&<p>独立验收失败，已派发修复任务 {root.integration_repair.slice(0,8)}。</p>}
    <details><summary>调度记录与结束反馈</summary>{root.events.map((e,i)=><p key={i}>{e}</p>)}<p>{root.error||root.answer||"尚无结束反馈"}</p></details>
   </section>
   {tab==="flow"&&<section className="df-observer"><h4>最近事件</h4>{events.slice(-3).map(e=><p key={e.run.id+"-"+e.seq}>
    <time>{clock(e.ts)}</time>　{e.data.tool||e.kind} · {e.data.error||e.data.status||e.data.path||e.data.command}</p>)}
    {!events.length&&<p>等待首条工具回执。</p>}</section>}
   </div>
   <aside className="df-inspector" aria-label="节点详情"><h4>节点详情 · {node.title}</h4><span className={"df-badge state-"+node.state}>{labels[attempt?run?.state||node.state:node.state]}</span>
    {attempts.length>1&&<label>执行轮次 <select aria-label="执行轮次" value={run?.id||""} onChange={e=>setAttempt(e.target.value)}>
     {attempts.map((r,i)=><option key={r.id} value={r.id}>第 {i+1} 次 · {labels[r.state]}</option>)}</select></label>}
    <dl><dt>执行者</dt><dd>{run?agents.find(a=>a.id===run.agent)?.name||run.agent:node.role}</dd>
     <dt>正在做什么</dt><dd>{node.summary}</dd><dt>任务输入</dt><dd>{run?.title||"尚未派发"}</dd>
     <dt>模型</dt><dd>{run?.model||"未记录"}</dd></dl>
    {input&&<dl><dt>操作目标</dt><dd>{input.query||"未记录"}</dd>
     {input.symbol&&<><dt>函数</dt><dd>{input.symbol}</dd></>}
     {input.revision&&<><dt>文件版本</dt><dd>{input.revision}</dd></>}</dl>}
    {run?.error&&<p className="df-error" role="alert">{run.error}</p>}
    <h4>最近工具回执</h4>{latest?<><p>{latest.data.tool} · {latest.kind==="tool_start"?"等待返回":latest.data.status==="failed"?"调用失败":"已返回"}</p>
     <pre>{latest.data.error||latest.data.query||latest.data.path||"工具已返回"}</pre>
     <details><summary>查看已记录的调用摘要</summary>{calls.map(e=><pre key={e.seq}>{JSON.stringify(e,null,2)}</pre>)}</details></>:<p>尚无工具调用记录</p>}
    <h4>下一步</h4><p>{run?.state==="needs_input"?"在项目群补充说明。":latest?.data.error||run?.error||"等待执行者提交下一条实际回执。"}</p>
    <details><summary>代码差异（{run?.changes?.length||0}）</summary>{run?.changes?.map((c,i)=><div key={i}><b>{c.path}</b><pre>{c.diff}</pre></div>)}</details>
    <details><summary>验收记录（{checks.length}）</summary>{checks.map((c,i)=><div key={i}><b>{c.command}</b><p>{c.stale?"已失效 · 修改后需重跑":c.state} · 退出码 {c.exit_code??"未知"}</p><pre>{c.output}</pre></div>)}</details>
    <small>模型调用 {run?.calls??"未知"} 次 · {run?.created?"开始于 "+clock(run.created):"尚未开始"}</small>
   </aside>
  </div></details>
 </section>;
}
