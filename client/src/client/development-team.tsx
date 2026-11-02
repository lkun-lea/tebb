import {useEffect, useState} from "react";
import {rpc, type BackendInfo} from "./api";
import {usePageActive} from "./page-stack";
import {NativeDevelopmentTeam} from "./native-development-team";

type Stage = {stage:string; status:string; round:number; note:string};
type Arm = {status:string; stage:string; reason:string; matched:boolean; timeline:Stage[]; maintenance?:{id:string;status:string}[]; gate:string|null;
  candidate:string|null; checks:{name:string;passed:boolean;observed:boolean}[]; calls:number; rework:number;
  supplements:number; cached:number|null; uncached:number|null; output:number|null; usage_complete:boolean};
type Experiment = {id:string; title:string; historical:boolean; version:number; base:string; error?:string;
 arms:{workflow:Arm;direct:Arm}; accounting?:Record<string,{interventions:number;maintenance_tokens:number}>};
const roles:Record<string,string>={requirements:"需求整理",scope_review:"范围审查",verification_plan:"验收计划",
 develop:"开发者",objective:"固定测试",verify:"独立验收",supervise:"监督与复盘",reflect:"结束反思",
 diagnose:"故障诊断",supplement:"证据补交",evaluator_repair:"验收器修复",evaluator_review:"验收器审查",done:"已结束"};
const states:Record<string,string>={ready:"待启动",running:"进行中",completed:"已完成",accepted:"已交付",blocked:"阻塞",
 exhausted:"额度用尽",needs_input:"等待输入",environment_blocked:"等待环境",cancelled:"已取消",failed:"失败",
 interrupted:"已中断",pass:"通过",fail:"未通过",unknown:"未知",finalizing:"收尾中"};
const label=(value:string)=>states[value]??value;
const number=(value:number|null|undefined)=>value==null?"未知":value.toLocaleString();

function RoleTrack({arm,direct}:{arm:Arm;direct:boolean}){
 const groups: [string,string[]][] = direct ? [["开发者",["develop"]],["固定测试",["objective"]]] :
   [["需求",["requirements","scope_review","verification_plan"]],["开发",["develop"]],
    ["验收",["objective","verify","supplement"]],["监督 / 复盘",["supervise","reflect"]]];
 return <ol aria-label="角色参与情况" className="my-4 flex flex-wrap gap-2">
   {groups.map(([name,stages])=>{
     const current=arm.status==="running"&&stages.includes(arm.stage);
     const seen=arm.timeline.some(a=>stages.includes(a.stage));
     return <li key={name} className={"rounded-lg border px-3 py-2 text-sm "+(current?"border-primary bg-secondary":seen?"bg-secondary":"text-muted-foreground")}>
       <strong>{name}</strong><small className="block">{current?"执行中":seen?"已参与":arm.stage==="done"?"未进入":"待进入"}</small>
     </li>;
   })}
 </ol>;
}

export function DevelopmentTeam({info,onOpen}:{info:BackendInfo|null;onOpen?:(id:string)=>Promise<void>}) {
 const active=usePageActive();
 const [items,setItems]=useState<Experiment[]|null>(null);
 const [historyOpen,setHistoryOpen]=useState(false);
 const [id,select]=useState("");
 const [error,setError]=useState("");
 useEffect(()=>{
   if(!historyOpen||!active||!info)return;
   let alive=true;
   let timer:ReturnType<typeof setTimeout>;
   async function refresh(){
     try {
       const result=await rpc<{experiments:Experiment[]}>(info!,"development_team",{});
       if(alive){setItems(result.experiments);setError("");}
     } catch(e){if(alive)setError(String(e));}
     if(alive)timer=setTimeout(refresh,5000);
   }
   void refresh();
   return ()=>{alive=false;clearTimeout(timer);};
 },[active,info,historyOpen]);
 const item=items?.find(x=>x.id===id)??items?.[0];
 return <section className="flex-1 overflow-auto px-8 py-6" data-page="development-team">
   <h1 className="text-2xl font-semibold">开发团队</h1>
   <NativeDevelopmentTeam info={info} onOpen={onOpen}/>
   <details onToggle={event=>setHistoryOpen(event.currentTarget.open)}><summary>外部开发流程实验记录</summary>
   {error&&<p role="alert">刷新失败 · {error}</p>}
   {!info?<p>等待桌面服务连接</p>:!items?<p>正在读取实验</p>:!items.length?<p className="mt-5">暂无已登记实验。通过项目的开发对照命令创建实验后，可在这里查看团队进度。</p>:<>
     <label className="mt-4 block">选择实验　<select className="max-w-full rounded-md border bg-card px-3 py-2 text-foreground" value={item?.id} onChange={e=>select(e.target.value)}>
       {items.map(x=><option key={x.id} value={x.id}>{x.title||x.id} · {x.id.slice(0,6)}</option>)}</select></label>
     {item?.error?<p role="alert">{item.error}</p>:item&&<>
       <p className="my-3 text-sm text-muted-foreground">{item.historical?"历史对照":"本次试点"} · 流程 v{item.version} · 基线 {item.base.slice(0,10)}</p>
       {Object.values(item.arms).some(a=>!a.matched)&&<p role="alert">实验条件已变化，请分别解读两组结果。</p>}
       <div className="grid gap-4 lg:grid-cols-2">{(["workflow","direct"] as const).map(key=>{
         const arm=item.arms[key];
         return <article key={key} className="min-w-0 rounded-xl border bg-card p-5 text-card-foreground">
           <h2 className="text-lg font-semibold">{key==="workflow"?"实验组 · 开发团队":"对照组 · 单开发者"}</h2>
           <p>{label(arm.status)} · {roles[arm.stage]??arm.stage}</p>
           <RoleTrack arm={arm} direct={key==="direct"}/>
           {arm.reason&&<p className="my-2 break-words">{arm.reason}</p>}
           <dl className="my-4 grid grid-cols-2 gap-2 text-sm">
             {Object.entries({"固定功能测试":arm.gate?label(arm.gate):"尚无结果","模型调用":number(arm.calls),
             "开发返工":number(arm.rework),"证据补交":number(arm.supplements),"未缓存输入":number(arm.uncached),
             "缓存输入":number(arm.cached),"输出 token":number(arm.output),"用量记录":arm.usage_complete?"完整":"未齐",
             "人工介入次数":number(item.accounting?.[key]?.interventions),"额外维护 token":number(item.accounting?.[key]?.maintenance_tokens)}).map(([k,v])=>
               <div key={k}><dt className="text-muted-foreground">{k}</dt><dd>{v}</dd></div>)}
           </dl>
           <h3 className="font-semibold">角色交接</h3>
           {arm.timeline.length?<ol className="my-2 border-l pl-4">{arm.timeline.map((a,i)=><li className="mb-2" key={i}>
             {i+1}. {roles[a.stage]??a.stage} · {label(a.status)}{a.round>0&&" · 第 "+a.round+" 轮"}
             {a.note&&<small className="block break-words">{a.note}</small>}</li>)}</ol>:<p>等待首个阶段启动</p>}
           {!!arm.maintenance?.length&&<p>流程维护 · {arm.maintenance.map(j=>j.id+" "+(j.status==="adopted"?"已采用":label(j.status))).join("、")}</p>}
           <details><summary>验收记录（{arm.checks.length}）</summary><p>候选 {arm.candidate?.slice(0,10)??"尚未生成"}</p>
           {arm.checks.map(c=><p key={c.name}>{c.observed?(c.passed?"通过":"失败"):"未观测"} · {c.name}</p>)}</details>
         </article>;
       })}</div>
     </>}
   </>}
   </details></section>;
}
