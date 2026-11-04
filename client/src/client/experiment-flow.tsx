import {useState} from "react";
import "./experiment-flow.css";

type Stage = {stage:string; status:string; round:number; note:string; decision?:string;
 observations?:string[];proposals?:string[];validation_plan?:string[]};
export type Arm = {status:string; stage:string; reason:string; matched:boolean; timeline:Stage[]; maintenance?:{id:string;status:string}[]; gate:string|null;
 candidate:string|null; checks:{name:string;passed:boolean;observed:boolean|null}[]; calls:number; rework:number;
 supplements:number; cached:number|null; uncached:number|null; output:number|null; usage_complete:boolean};
export type Experiment = {id:string; title:string; historical:boolean; version:number; base:string; error?:string;
 arms:{workflow:Arm;direct:Arm}; accounting?:Record<string,{interventions:number;maintenance_tokens:number}>};
const roles:Record<string,string>={requirements:"需求整理",scope_review:"范围审查",verification_plan:"验收计划",
 develop:"代码开发",objective:"固定测试",verify:"独立验收",supervise:"监督与复盘",reflect:"结束反思",
 diagnose:"故障诊断",supplement:"证据补交",evaluator_repair:"验收器修复",evaluator_review:"验收器审查",done:"结束"};
const labels:Record<string,string>={ready:"待启动",running:"进行中",completed:"执行结束",accepted:"已交付",blocked:"阻塞",
 exhausted:"额度用尽",needs_input:"待补充",environment_blocked:"等待环境",cancelled:"已取消",failed:"失败",
 interrupted:"已中断",timed_out:"超时",pass:"通过",fail:"未通过",unknown:"未知",finalizing:"收尾中",
 aligned:"范围对齐",revise:"要求修改",unseen:"未进入"};
export const label=(value:string)=>labels[value]??value;
const number=(value:number|null|undefined)=>value==null?"未知":value.toLocaleString();
const tone=(value:string)=>["pass","accepted","aligned"].includes(value)?"good":
 ["blocked","exhausted","failed","fail","timed_out","revise","needs_input","environment_blocked","interrupted"].includes(value)?"warn":value==="running"?"active":"neutral";
export function totalTokens(arm:Arm){return [arm.uncached,arm.cached,arm.output].every(v=>v!=null)?arm.uncached!+arm.cached!+arm.output!:null;}

function ArmFlow({arm,direct}:{arm:Arm;direct:boolean}){
 const [selected,select]=useState<number|null>(null);
 const index=selected??Math.max(0,arm.timeline.length-1);
 const step=arm.timeline[index];
 const phases=direct?[["开发",["develop"]],["测试",["objective"]]]:
 [["需求",["requirements","scope_review","verification_plan"]],["开发",["develop"]],["验收",["objective","verify"]],["监督",["supervise","reflect"]]];
 return <article className="ef-arm">
  <header><h3>{direct?"对照组 · 单开发者":"实验组 · 外部开发流程"}</h3><b className={"ef-status "+tone(arm.status)}>{label(arm.status)}</b></header>
  <p className="ef-outcome">固定测试 <strong>{arm.gate?label(arm.gate):"尚无结果"}</strong> · 开发返工 {arm.rework} · 补交 {arm.supplements}</p>
  <div className="ef-phases">{phases.map(([name,stages])=><span key={name as string}>{name} · {arm.timeline.some(s=>stages.includes(s.stage))?"已进入":"未进入"}</span>)}</div>
  <ol className="ef-chain" aria-label={direct?"单开发者执行链":"外部流程执行链"}>
   {arm.timeline.map((s,i)=>{
    const repeat=arm.timeline.slice(0,i).some(p=>p.stage===s.stage);
    const status=s.decision||s.status;
    return <li key={i}>
     {i>0&&<div className={"ef-edge"+(repeat?" ef-return":"")} aria-label={repeat?"返回节点":"下一步"}>{repeat?"↶ "+(s.stage==="develop"?"返回开发 · 返工":"再次进入 · "+(roles[s.stage]||s.stage)):"↓"}</div>}
     <button className={"ef-node "+tone(status)} aria-pressed={i===index} onClick={()=>select(i)}>
      <span className="ef-node-top"><strong>{i+1}. {roles[s.stage]||s.stage}</strong><span>{label(status)}</span></span>
      <small>{s.round>0?"第 "+s.round+" 轮":"准备 / 收尾"}{s.decision?" · "+label(s.status):""}</small>
      {s.note&&<span className="ef-excerpt">{s.note}</span>}
      {s.stage==="reflect"&&<small>已记录 {s.observations?.length??0} 条观察 · {s.proposals?.length??0} 条改进建议（节选）</small>}
     </button>
    </li>;
   })}
   {!arm.timeline.length&&<li className="ef-empty">尚无阶段执行记录</li>}
   <li><div className="ef-edge">↓</div><div className={"ef-result "+tone(arm.status)}><strong>{label(arm.status)}</strong>
    <p>{arm.reason||(arm.status==="accepted"?"本组已交付，查看固定测试与候选记录。":arm.status==="running"?"当前阶段："+(roles[arm.stage]||arm.stage):"未记录结束原因")}</p></div></li>
  </ol>
  {step&&<aside className="ef-detail" aria-label="阶段详情"><h4>节点详情 · {index+1}. {roles[step.stage]||step.stage}</h4>
   <p>执行状态：{label(step.status)}{step.decision&&" · 审查决定："+label(step.decision)}</p><p>{step.note||"该阶段未记录详细说明。"}</p>
   <small>执行结束仅表示该次调用结束；通过与否以审查决定和测试结果为准。</small>
   {step.stage==="reflect"&&<div>{([['observations','发现的问题'],['proposals','改进建议'],['validation_plan','后续验证']] as const).map(([key,title])=>
    !!step[key]?.length&&<div key={key}><h4>{title}（节选）</h4>{step[key]!.map((text,i)=><p key={i}>{text}</p>)}</div>)}
    <small>建议不代表已经实施；采用状态以流程维护回执为准。</small></div>}</aside>}
  {!!arm.maintenance?.length&&<p>流程维护 · {arm.maintenance.map(j=>j.id+" "+(j.status==="adopted"?"已采用":label(j.status))).join("、")}</p>}
  <details><summary>{arm.checks.length?"固定验收明细 · "+arm.checks.filter(c=>c.observed!==false&&c.passed).length+"/"+arm.checks.length+" 项记录通过":"尚无固定验收记录"}</summary>
   <p>候选 {arm.candidate?.slice(0,10)??"尚未生成"}</p>
   {arm.checks.map(c=><p key={c.name}>{c.observed===false?"未观测":c.passed?"记录通过":"记录失败"} · {c.name}{c.observed==null?"（未记录观测标记）":""}</p>)}
  </details>
 </article>;
}

export function ExperimentFlow({item}:{item:Experiment}){
 const arms=(["workflow","direct"] as const);
 const totals=arms.map(k=>totalTokens(item.arms[k]));
 const max=Math.max(1,...totals.map(v=>v??0));
 return <section className="experiment-flow" aria-label="外部实验流程对照">
  <div className="ef-comparison"><h3>结果与成本对照</h3><p>先看功能与交付，再比较消耗；未完成的一组不能据此认定更省 token。</p>
   <div className="ef-table-wrap"><table><thead><tr><th>评估项</th><th>外部开发流程</th><th>单开发者</th></tr></thead><tbody>
    {([ ["交付状态",(a:Arm)=>label(a.status)], ["固定功能测试",(a:Arm)=>a.gate?label(a.gate):"尚无结果"],
     ["模型调用",(a:Arm)=>number(a.calls)],["开发返工 / 证据补交",(a:Arm)=>a.rework+" / "+a.supplements],
     ["未缓存输入",(a:Arm)=>number(a.uncached)],["缓存输入",(a:Arm)=>number(a.cached)],
     ["输出 token",(a:Arm)=>number(a.output)], ["用量记录",(a:Arm)=>a.usage_complete?"完整":"未齐"] ] as [string,(arm:Arm)=>string][]).map(([name,value])=>
      <tr key={name}><th>{name}</th>{arms.map(k=><td key={k}>{value(item.arms[k])}</td>)}</tr>)}
    <tr><th>人工介入 / 额外维护 token</th>{arms.map(k=><td key={k}>{number(item.accounting?.[k]?.interventions)} / {number(item.accounting?.[k]?.maintenance_tokens)}</td>)}</tr>
   </tbody></table></div>
   <div className="ef-token-bars">{arms.map((k,i)=><div key={k}><span>{k==="workflow"?"外部流程":"单开发者"} · {item.arms[k].usage_complete?"总":"已记录"} token {number(totals[i])}</span>
    {totals[i]!=null&&<div className="ef-bar-track"><div className="ef-bar" style={{width:100*totals[i]!/max+"%"}}/></div>}</div>)}</div>
  </div>
  <p className="ef-hint">下方按真实执行顺序连线。橙色表示问题或修改要求，绿色表示明确通过；点击节点查看原始说明。</p>
  <div className="ef-columns">{arms.map(k=><ArmFlow key={item.id+"-"+k} arm={item.arms[k]} direct={k==="direct"}/>)}</div>
 </section>;
}
