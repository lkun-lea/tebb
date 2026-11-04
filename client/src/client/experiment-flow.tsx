import {useEffect,useState} from "react";
import {usePageActive} from "./page-stack";
import {FlowCanvas,flowLabel,flowTone,toolStepName,type FlowNode} from "./flow-canvas";

type Stage={stage:string;status:string;round:number;note:string;decision?:string;observations?:string[];proposals?:string[];validation_plan?:string[]};
export type Arm={status:string;stage:string;reason:string;matched:boolean;timeline:Stage[];gate:string|null;candidate:string|null;
 checks:{name:string;passed:boolean;observed?:boolean|null}[];calls:number;rework:number;supplements:number;cached:number|null;uncached:number|null;output:number|null;usage_complete:boolean;
 maintenance?:{id:string;status:string}[]};
export type Experiment={id:string;title:string;issue?:number;historical:boolean;version:number;base:string;error?:string;arms:{workflow:Arm;direct:Arm};accounting?:Record<string,{interventions:number;maintenance_tokens:number}>};
export type ReplayStep={stage:number|null;state:string;label:string;note:string;seconds?:number;returning?:boolean;kind?:string;round?:number};
export type NativeTrial={id:string;issue:number;title:string;model:string;status:string;steps:ReplayStep[];checks:{name:string;passed:boolean}[];input_tokens:number|null;output_tokens:number|null;elapsed_s:number;note:string};
const titles=["需求与分工","实现与自测","独立验收","总结与交付"];
const stages:Record<string,number>={requirements:0,scope_review:0,verification_plan:0,develop:1,diagnose:1,objective:2,verify:2,supplement:2,evaluator_repair:2,evaluator_review:2,supervise:3,reflect:3};
const names:Record<string,string>={requirements:"需求整理",scope_review:"范围审查",verification_plan:"验收计划",develop:"代码开发",objective:"固定测试",verify:"独立验收",supervise:"监督",reflect:"结束反思",diagnose:"故障诊断",supplement:"补交证据",evaluator_repair:"修复验收器",evaluator_review:"审查验收器"};
const stateOf=(value:string)=>({pass:"succeeded",accepted:"succeeded",aligned:"succeeded",fail:"failed"}[value]||value);
export const totalTokens=(arm:Arm)=>[arm.uncached,arm.cached,arm.output].every(v=>v!=null)?arm.uncached!+arm.cached!+arm.output!:null;
const number=(value:number|null|undefined)=>value==null?"未知":value.toLocaleString();
export function armSteps(arm:Arm):ReplayStep[]{
 return [...arm.timeline.flatMap((s,index)=>{
  const stage=stages[s.stage]??null,label=names[s.stage]||s.stage;
  const note=[s.note,...(s.observations||[]),...(s.proposals||[]).map(p=>"改进建议（不代表已采用）："+p),...(s.validation_plan||[])].filter(Boolean).join("\n");
  return [{stage,kind:s.stage,round:s.round,state:"running",label:label+" · 开始",note:"第 "+s.round+" 轮",returning:arm.timeline.slice(0,index).some(p=>p.stage===s.stage)},
   {stage,kind:s.stage,round:s.round,state:stateOf(s.decision||s.status),label:label+" · "+flowLabel(stateOf(s.decision||s.status)),note}];
 }),{stage:arm.status==="accepted"?3:null,state:stateOf(arm.status),label:arm.status==="accepted"?"已交付":"流程结果",note:arm.reason||flowLabel(stateOf(arm.status))}];
}
export function replayNodes(steps:ReplayStep[],index:number):FlowNode[]{
 const nodes=titles.map((title,i)=>({id:String(i),title,state:"unseen",summary:"尚未进入"}));
 for(const step of steps.slice(0,index+1)){
  if(step.stage==null)continue;
  for(const node of nodes)if(node.state==="running"&&node.id!==String(step.stage))node.state="completed";
  const node=nodes[step.stage];if(node)Object.assign(node,{state:step.state,summary:step.label,detail:step.note,round:step.round});
 }
 return nodes;
}
export function FlowReplay({steps,model}:{steps:ReplayStep[];model?:string}){
 const [position,setPosition]=useState(steps.length-1),[playing,play]=useState(false),[selected,select]=useState("");
 const [advanceMotion,setAdvanceMotion]=useState(false);
 const active=usePageActive();
 const index=Math.min(position,steps.length-1),step=steps[index];
 useEffect(()=>{if(!playing||!active)return;const timer=setTimeout(()=>{if(index>=steps.length-1){play(false);setAdvanceMotion(false);return;}setAdvanceMotion(true);setPosition(index+1);},1000);return()=>clearTimeout(timer);},[playing,active,index,steps.length]);
 const visible=steps.slice(0,index+1);
 const observed=visible.filter(s=>s.stage!=null);
 const current=observed.at(-1)?.stage;
 const nodes=replayNodes(steps,index).map(n=>{
  const rows:{label:string;state:string}[]=[];
  for(const s of visible.filter(s=>String(s.stage)===n.id&&s.label.startsWith("workspace_"))){
   const label=toolStepName(s.label.split(" · ")[0]);
   const returned=s.label.endsWith("返回"),state=s.state==="running"&&returned?"completed":s.state;
   if(returned&&rows.at(-1)?.label===label&&rows.at(-1)?.state==="running")rows[rows.length-1]={label,state};
   else rows.push({label,state});
  }
  return {...n,steps:rows.map(s=>({...s,state:s.state==="running"&&n.state!=="running"?"unconfirmed":s.state}))};
 });
 const node=nodes.find(n=>n.id===(selected||String(current)))||nodes[0];
 const receipt=visible.filter(s=>String(s.stage)===node.id).at(-1);
 const reflection=visible.filter(s=>["supervise","reflect"].includes(s.kind||"")&&s.state!=="running").at(-1);
 const returning=observed.some((s,i)=>s.stage===1&&i>0&&observed[i-1].stage===2);
 return <section aria-label="历史回放">
  <div className="flow-controls"><button disabled={!steps.length} onClick={()=>{setAdvanceMotion(false);if(index===steps.length-1)setPosition(0);play(!playing);}}>{playing?"暂停回放":"播放过程"}</button>
   <button disabled={index<=0} onClick={()=>{play(false);setAdvanceMotion(false);setPosition(Math.max(0,index-1));}}>上一步</button>
   <button disabled={index>=steps.length-1} onClick={()=>{play(false);setAdvanceMotion(true);setPosition(index+1);}}>下一步</button>
   <input aria-label="回放进度" type="range" min={0} max={Math.max(0,steps.length-1)} value={Math.max(0,index)} onChange={e=>{play(false);setAdvanceMotion(false);setPosition(Number(e.target.value));}}/>
   <small>{index+1} / {steps.length} 条记录</small></div>
  <div className="df-workbench">
   <div className="df-main">
    <div className="df-tabs"><span className="df-static-tab">流程图</span><small>历史回放 · 按记录顺序播放，非实时任务或原速录像</small></div>
    <div className="df-summary"><span>当前阶段 <b>{current==null?"未开始":titles[current]}</b></span><span className={"flow-state-badge tone-"+flowTone(step?.state||"unseen")}>{flowLabel(step?.state||"unseen")}</span><span>记录 {index+1} / {steps.length}</span>{step?.seconds!=null&&<span>原始用时 {step.seconds.toFixed(1)} 秒</span>}</div>
    <FlowCanvas nodes={nodes} current={current==null?undefined:String(current)} selected={node.id} onSelect={select} returning={returning}
     position={index} allowTransition={advanceMotion&&active} activity={playing&&active}/>
    <section className="df-observer"><h4>◎　监督与反思 <small>观察依据 · 改进建议</small></h4><p className="df-clamp">{reflection?.note||"当前已回放记录中尚无监督或反思回执。"}</p>{reflection?.note&&<details><summary>查看依据</summary><p>{reflection.note}</p></details>}</section>
    <section className="df-observer"><h4>☷　最近事件</h4>{visible.slice(-3).map((event,i)=><div className="df-recent-row" key={i}><span className={"df-event-dot tone-"+flowTone(event.state)}>●</span><time>{event.seconds==null?"时刻未记录":event.seconds.toFixed(1)+" 秒"}</time><strong>{event.label}</strong><span>{event.note}</span></div>)}</section>
   </div>
   <aside className="df-inspector" aria-label="节点详情"><h4 className="df-panel-title">▤　节点详情</h4>
    <div className="df-panel-subtitle"><strong>{node.title}</strong><span className={"flow-state-badge tone-"+flowTone(node.state)}>{flowLabel(node.state)}</span></div>
    <button className="df-follow" onClick={()=>select("")}>跟随当前节点</button>
    <dl><dt>执行者</dt><dd>{["负责人","编码伙伴","验证伙伴","负责人"][Number(node.id)]}{model&&" · "+model}</dd><dt>正在做什么</dt><dd>{node.summary}</dd></dl>
    <h4>最近节点记录</h4><div className={"df-receipt tone-"+flowTone(node.state)}><strong>{receipt?.label||"尚未进入"}</strong><p>{receipt?.note||"该节点尚无更多记录。"}</p></div>
    <h4>当前回放位置</h4>{step&&<div role="status"><strong>{step.label}</strong><p>{step.note||"此条未记录更多说明"}</p></div>}
    <h4>下一步</h4><p>点击播放或下一步查看后续记录。历史回放不会执行模型或修改项目。</p>
    <details><summary>查看该节点已回放记录</summary>{visible.filter(s=>String(s.stage)===node.id).map((s,i)=><p key={i}><strong>{s.label}</strong><br/>{s.note}</p>)}</details>
   </aside>
  </div>
 </section>;
}
export function NativeTrialFlow({trial}:{trial:NativeTrial}){
 return <div className="team-history"><h3>#{trial.issue} · {trial.title}</h3><small>原生团队 · {trial.model}</small>
  <FlowReplay key={trial.id} steps={trial.steps} model={trial.model}/>
  <details><summary>查看最终验收与用量</summary><p>最终状态：{flowLabel(trial.status)} · 用时 {trial.elapsed_s} 秒</p><p>输入 {number(trial.input_tokens)} · 输出 {number(trial.output_tokens)} token</p>
   <p>{trial.note}</p>{trial.checks.map(c=><p key={c.name}>{c.passed?"通过":"失败"} · {c.name}</p>)}</details></div>;
}
export function ExperimentFlow({item}:{item:Experiment}){
 const [armId,select]=useState<"workflow"|"direct">("workflow"),arm=item.arms[armId];
 return <div className="team-history"><h3>{item.issue?"#"+item.issue+" · ":""}{item.title}</h3>
  <div className="team-mode"><button aria-pressed={armId==="workflow"} onClick={()=>select("workflow")}>外部开发流程</button><button aria-pressed={armId==="direct"} onClick={()=>select("direct")}>单开发者对照</button></div>
  {!arm.matched&&<p role="alert">实验条件已变化，请分别解读两组结果。</p>}
  <FlowReplay key={item.id+armId} steps={armSteps(arm)}/>
  <details><summary>比较最终结果与 token</summary><p>流程 v{item.version} · 基线 {item.base?.slice(0,10)}。未完成组消耗较少，不代表更高效。</p>
   <table><thead><tr><th>结果</th><th>外部流程</th><th>单开发者</th></tr></thead><tbody>
   {([ ["交付",(a:Arm)=>flowLabel(stateOf(a.status))],["功能测试",(a:Arm)=>a.gate?flowLabel(stateOf(a.gate)):"未执行"],
    ["调用数",(a:Arm)=>number(a.calls)],["返工 / 补交",(a:Arm)=>a.rework+" / "+a.supplements],
    ["已记录 token",(a:Arm)=>number(totalTokens(a))],["用量记录",(a:Arm)=>a.usage_complete?"完整":"未齐"] ] as [string,(a:Arm)=>string][]).map(([name,value])=>
     <tr key={name}><th>{name}</th><td>{value(item.arms.workflow)}</td><td>{value(item.arms.direct)}</td></tr>)}
   </tbody></table><p>当前组候选：{arm.candidate||"无"}</p>{arm.checks.map(c=><p key={c.name}>{c.observed===false?"未观测":c.passed?"记录通过":"记录失败"} · {c.name}</p>)}
   {!!arm.maintenance?.length&&<p>维护回执：{arm.maintenance.map(m=>m.id+" · "+m.status).join("、")}</p>}
  </details></div>;
}
