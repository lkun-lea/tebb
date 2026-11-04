import {useEffect,useState} from "react";
import {rpc,type BackendInfo} from "./api";
import {usePageActive} from "./page-stack";
import {NativeDevelopmentTeam} from "./native-development-team";
import {ExperimentFlow,NativeTrialFlow,type Experiment,type NativeTrial} from "./experiment-flow";

type History={experiments:Experiment[];native_trials:NativeTrial[]};
export function DevelopmentTeam({info,onOpen,onSetup}:{info:BackendInfo|null;onOpen?:(id:string)=>Promise<void>;onSetup?:()=>void}){
 const active=usePageActive();
 const [mode,setMode]=useState("start"),[history,setHistory]=useState<History|null>(null),[id,select]=useState(""),[error,setError]=useState("");
 useEffect(()=>{setHistory(null);select("");setError("");},[info]);
 useEffect(()=>{
  if(!active||!info||mode!=="history")return;
  let live=true,timer:ReturnType<typeof setTimeout>;
  async function refresh(){try{const result=await rpc<History>(info!,"development_team",{});if(live){setHistory(result);setError("");}}
   catch(e){if(live)setError(String(e));}if(live)timer=setTimeout(refresh,5000);}
  void refresh();return()=>{live=false;clearTimeout(timer);};
 },[active,info,mode]);
 const choices=[...(history?.native_trials||[]).map(trial=>({id:trial.id,label:"#"+trial.issue+" · "+trial.title,trial,item:undefined as Experiment|undefined})),
  ...(history?.experiments||[]).map(item=>({id:item.id,label:(item.issue?"#"+item.issue+" · ":"")+"外部对照 · "+(item.title||item.id),item,trial:undefined as NativeTrial|undefined}))];
 const chosen=choices.find(c=>c.id===id)||choices.find(c=>c.trial?.issue===208)||choices[0];
 return <section className="development-team-page flex-1 overflow-auto px-6 py-5" data-page="development-team">
  <h1 className="text-2xl font-semibold">开发团队</h1><p className="mt-2 text-sm text-muted-foreground">选项目，说清想改什么，点击开始。进度会直接显示在流程图上。</p>
  <nav className="team-mode" aria-label="开发方式"><button aria-pressed={mode==="start"} onClick={()=>setMode("start")}>开始开发</button>
   <button aria-pressed={mode==="history"} onClick={()=>setMode("history")}>历史回放 · 含 #208</button></nav>
  <div hidden={mode!=="start"}><NativeDevelopmentTeam info={mode==="start"?info:null} onOpen={onOpen} onSetup={onSetup}/></div>
  {mode==="history"&&<section className="team-history">
   {error&&<p role="alert">读取失败 · {error}</p>}
   {!info?<p>等待桌面服务连接</p>:!history?<p>正在读取历史记录…</p>:!choices.length?<p>当前账号尚未登记实验。历史记录按账号保存。</p>:<>
    <label>选择记录　<select aria-label="历史记录" value={chosen?.id} onChange={e=>select(e.target.value)}>{choices.map(c=><option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
    {chosen?.trial?<NativeTrialFlow key={chosen.id} trial={chosen.trial}/>:chosen?.item?.error?<p role="alert">{chosen.item.error}</p>:chosen?.item&&<ExperimentFlow key={chosen.id} item={chosen.item}/>}
   </>}
  </section>}
 </section>;
}
