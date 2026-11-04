import {useEffect, useState} from "react";
import {rpc, type BackendInfo} from "./api";
import {usePageActive} from "./page-stack";
import {NativeDevelopmentTeam} from "./native-development-team";

import {ExperimentFlow,type Experiment} from "./experiment-flow";

export function DevelopmentTeam({info,onOpen,onSetup}:{info:BackendInfo|null;onOpen?:(id:string)=>Promise<void>;onSetup?:()=>void}) {
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
   <p className="mt-2 text-sm text-muted-foreground">原生团队在项目群执行；外部实验记录用于回看历史对照，两者分别保存。</p>
   <NativeDevelopmentTeam info={info} onOpen={onOpen} onSetup={onSetup}/>
   <details onToggle={event=>setHistoryOpen(event.currentTarget.open)}><summary>外部开发流程实验记录</summary>
   {error&&<p role="alert">刷新失败 · {error}</p>}
   {!info?<p>等待桌面服务连接</p>:!items?<p>正在读取实验</p>:!items.length?<p className="mt-5">暂无已登记实验。通过项目的开发对照命令创建实验后，可在这里查看团队进度。</p>:<>
     <label className="mt-4 block">选择实验　<select className="max-w-full rounded-md border bg-card px-3 py-2 text-foreground" value={item?.id} onChange={e=>select(e.target.value)}>
       {items.map(x=><option key={x.id} value={x.id}>{x.title||x.id} · {x.id.slice(0,6)}</option>)}</select></label>
     {item?.error?<p role="alert">{item.error}</p>:item&&<>
       <p className="my-3 text-sm text-muted-foreground">{item.historical?"历史对照":"本次试点"} · 流程 v{item.version} · 基线 {item.base.slice(0,10)}</p>
       {Object.values(item.arms).some(a=>!a.matched)&&<p role="alert">实验条件已变化，请分别解读两组结果。</p>}
       <ExperimentFlow key={item.id} item={item}/>
     </>}
   </>}
   </details></section>;
}
