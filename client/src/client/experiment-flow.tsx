import {useEffect,useState} from "react";
import {usePageActive} from "./page-stack";
import {FlowCanvas,flowLabel,flowTone,type FlowNode} from "./flow-canvas";

type Stage={stage:string;status:string;round:number;note:string;decision?:string;observations?:string[];proposals?:string[];validation_plan?:string[]};
export type Arm={status:string;stage:string;reason:string;matched:boolean;timeline:Stage[];gate:string|null;candidate:string|null;
 checks:{name:string;passed:boolean;observed?:boolean|null}[];calls:number;rework:number;supplements:number;cached:number|null;uncached:number|null;output:number|null;usage_complete:boolean;
 maintenance?:{id:string;status:string}[]};
export type Experiment={id:string;title:string;issue?:number;historical:boolean;version:number;base:string;error?:string;arms:{workflow:Arm;direct:Arm};accounting?:Record<string,{interventions:number;maintenance_tokens:number}>};
export type ReplayStep={stage:number|null;state:string;label:string;note:string;seconds?:number;returning?:boolean};
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
  return [{stage,state:"running",label:label+" · 开始",note:"第 "+s.round+" 轮",returning:arm.timeline.slice(0,index).some(p=>p.stage===s.stage)},
   {stage,state:stateOf(s.decision||s.status),label:label+" · "+flowLabel(stateOf(s.decision||s.status)),note}];
 }),{stage:arm.status==="accepted"?3:null,state:stateOf(arm.status),label:arm.status==="accepted"?"已交付":"流程结果",note:arm.reason||flowLabel(stateOf(arm.status))}];
}
export function replayNodes(steps:ReplayStep[],index:number):FlowNode[]{
 const nodes=titles.map((title,i)=>({id:String(i),title,state:"unseen",summary:"尚未进入"}));
 for(const step of steps.slice(0,index+1)){
  if(step.stage==null)continue;
  for(const node of nodes)if(node.state==="running"&&node.id!==String(step.stage))node.state="completed";
  const node=nodes[step.stage];if(node)Object.assign(node,{state:step.state,summary:step.label,detail:step.note});
 }
 return nodes;
}
export function FlowReplay({steps}:{steps:ReplayStep[]}){
 const [position,setPosition]=useState(steps.length-1),[playing,play]=useState(false),[selected,select]=useState("");
 const active=usePageActive();
 const index=Math.min(position,steps.length-1),step=steps[index];
 useEffect(()=>{if(!playing||!active)return;const timer=setTimeout(()=>{if(index>=steps.length-1){play(false);return;}setPosition(index+1);},1000);return()=>clearTimeout(timer);},[playing,active,index,steps.length]);
 const nodes=replayNodes(steps,index),node=nodes.find(n=>n.id===selected);
 const observed=steps.slice(0,index+1).filter(s=>s.stage!=null);
 const returning=observed.some((s,i)=>s.returning||(i>0&&s.stage!<observed[i-1].stage!));
 return <section aria-label="历史回放">
  <div className="flow-controls"><button disabled={!steps.length} onClick={()=>{if(index===steps.length-1)setPosition(0);play(!playing);}}>{playing?"暂停回放":"播放过程"}</button>
   <button disabled={index<=0} onClick={()=>{play(false);setPosition(Math.max(0,index-1));}}>上一步</button>
   <button disabled={index>=steps.length-1} onClick={()=>{play(false);setPosition(index+1);}}>下一步</button>
   <input aria-label="回放进度" type="range" min={0} max={Math.max(0,steps.length-1)} value={Math.max(0,index)} onChange={e=>{play(false);setPosition(Number(e.target.value));}}/>
   <small>{index+1} / {steps.length} 条记录</small></div>
  <small>历史回放 · 按记录顺序逐步展示，不是实时任务或原速录像。</small>
  <FlowCanvas nodes={nodes} current={step?.stage==null?undefined:String(step.stage)} selected={selected} onSelect={select} returning={returning}/>
  {step&&<div className={"flow-now tone-"+flowTone(step.state)} role="status"><strong>{step.label}</strong>{step.seconds!=null&&<small> · 原始用时 {step.seconds.toFixed(1)} 秒</small>}<p>{step.note||"此条未记录更多说明"}</p></div>}
  {node&&<div className="flow-view-detail"><strong>{node.title} · {flowLabel(node.state)}</strong><p>{node.detail||node.summary}</p><button onClick={()=>select("")}>收起节点详情</button></div>}
 </section>;
}
export function NativeTrialFlow({trial}:{trial:NativeTrial}){
 return <div className="team-history"><h3>#{trial.issue} · {trial.title}</h3><small>原生团队 · {trial.model}</small>
  <FlowReplay key={trial.id} steps={trial.steps}/>
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
