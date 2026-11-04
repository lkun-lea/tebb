import {useEffect,useId,useLayoutEffect,useRef,useState} from "react";
import "./development-flow.css";

export type FlowStep={label:string;state:string};
export type FlowNode={id:string;title:string;state:string;summary:string;detail?:string;role?:string;round?:number;tool?:string;
 steps?:FlowStep[];facts?:{label:string;value:string}[]};
export const toolStepName=(tool:string)=>({workspace_search:"定位源码",workspace_read_symbol:"读取函数",workspace_patch:"局部修改",workspace_run:"执行命令",workspace_list:"查看目录"}[tool]||tool);
export const flowLabel=(state:string)=>({running:"进行中",succeeded:"通过",completed:"执行结束",failed:"失败",timed_out:"超时",blocked:"阻塞",exhausted:"已停止",
 needs_input:"待补充",revise:"需修改",waiting:"等待前序",pending:"待执行",queued:"排队中",cancelling:"停止中",cancelled:"已停止",interrupted:"中断",unconfirmed:"未返回",unseen:"未开始"}[state]||state);
export const flowTone=(state:string)=>["succeeded","pass","accepted","aligned"].includes(state)?"green":
 ["failed","timed_out","blocked","exhausted","interrupted","fail"].includes(state)?"red":
 ["running","needs_input","revise","waiting","pending","queued","cancelling","completed","unconfirmed"].includes(state)?"yellow":"gray";

type Snapshot={current?:string;position?:number};
// Only animate observed adjacent handoffs. Seeking and skipped stages do not invent travel.
export function flowHandoff(previous:Snapshot|undefined,next:Snapshot,nodes:FlowNode[],returning:boolean,allowTransition:boolean){
 if(!previous||!allowTransition||previous.current===next.current)return null;
 if(next.position!=null&&next.position!==((previous.position??-2)+1))return null;
 const from=nodes.findIndex(n=>n.id===previous.current),to=nodes.findIndex(n=>n.id===next.current);
 if(from<0||to<0||["unseen","waiting","pending","queued"].includes(nodes[to].state))return null;
 if(to===from+1)return `${from}-${to}`;
 if(from===2&&to===1&&returning)return "2-1";
 return null;
}

function StatusIcon({state,active=true}:{state:string;active?:boolean}){
 const spinning=state==="running"&&active;
 return <i className={"flow-status-icon"+(spinning?" flow-spinner":"")} aria-hidden="true">
  {spinning?null:flowTone(state)==="green"?"✓":flowTone(state)==="red"?"!":state==="running"?"◷":"○"}</i>;
}

type Wire={id:string;d:string;state:string};
export function FlowCanvas({nodes,current,selected,onSelect,returning=false,position,allowTransition=true,activity=true}:{
 nodes:FlowNode[];current?:string;selected?:string;onSelect?:(id:string)=>void;returning?:boolean;
 position?:number;allowTransition?:boolean;activity?:boolean;
}){
 const map=useRef<HTMLDivElement>(null),previous=useRef<Snapshot>();
 const [wires,setWires]=useState<Wire[]>([]),[transfer,setTransfer]=useState<{edge:string;to:string;serial:number}|null>(null);
 const sequence=useRef(0),dot=useRef<SVGCircleElement>(null),serial=transfer?.serial;
 const marker="flow-arrow-"+useId().replace(/:/g,"");
 const signature=nodes.map(n=>n.id+":"+n.state).join("|");

 useLayoutEffect(()=>{
  const host=map.current;if(!host)return;
  const measure=()=>{
   const parent=host.getBoundingClientRect(),cards=Array.from(host.querySelectorAll<HTMLButtonElement>(".flow-card"));
   const boxes=cards.map(card=>{const r=card.getBoundingClientRect();return {x:r.left-parent.left,y:r.top-parent.top,w:r.width,h:r.height};});
   const result:Wire[]=[];
   for(let i=0;i<Math.min(3,boxes.length-1);i++){
    const a=boxes[i],b=boxes[i+1],vertical=Math.abs(a.x-b.x)<2;
    const d=vertical?`M ${a.x+a.w/2} ${a.y+a.h} L ${b.x+b.w/2} ${b.y-3}`:
     `M ${a.x<b.x?a.x+a.w:a.x} ${a.y+a.h/2} L ${a.x<b.x?b.x-3:b.x+b.w+3} ${a.y+a.h/2}`;
    result.push({id:`${i}-${i+1}`,d,state:cards[i].dataset.state||"unseen"});
   }
   if(returning&&boxes.length>=3){
    const a=boxes[2],b=boxes[1],x=parent.width-17,ay=a.y+a.h/2,by=b.y+b.h/2;
    result.push({id:"2-1",state:"failed",d:`M ${a.x+a.w} ${ay} L ${x-8} ${ay} Q ${x} ${ay} ${x} ${ay-8} L ${x} ${by+8} Q ${x} ${by} ${x-8} ${by} L ${b.x+b.w+3} ${by}`});
   }
   setWires(old=>JSON.stringify(old)===JSON.stringify(result)?old:result);
  };
  measure();const observer=new ResizeObserver(measure);observer.observe(host);
  host.querySelectorAll(".flow-card").forEach(card=>observer.observe(card));
  return()=>observer.disconnect();
 },[signature,returning]);

 useEffect(()=>{
  const next={current,position},edge=flowHandoff(previous.current,next,nodes,returning,allowTransition);
  if(!allowTransition){previous.current=next;setTransfer(null);return;}
  if(["unseen","waiting","pending","queued"].includes(nodes.find(n=>n.id===current)?.state||"unseen")){
   if(previous.current)previous.current={...previous.current,position};
   setTransfer(null);return;
  }
  previous.current=next;
  if(!edge){setTransfer(null);return;}
  if(typeof matchMedia!=="undefined"&&matchMedia("(prefers-reduced-motion: reduce)").matches)return;
  setTransfer({edge,to:current!,serial:++sequence.current});
  // Node state changes alone must not replay the same handoff.
 },[current,position,allowTransition,returning,signature]);

 useLayoutEffect(()=>{
  if(!transfer||!map.current||!dot.current)return;
  const path=map.current.querySelector<SVGPathElement>(`[data-wire="${transfer.edge}"]`);
  if(!path)return;
  const circle=dot.current,length=path.getTotalLength(),start=performance.now();let frame=0;
  const move=(now:number)=>{
   const progress=Math.min(1,(now-start)/850),point=path.getPointAtLength(length*progress);
   circle.setAttribute("cx",String(point.x));circle.setAttribute("cy",String(point.y));circle.style.visibility="visible";
   if(progress<1)frame=requestAnimationFrame(move);else setTransfer(null);
  };
  frame=requestAnimationFrame(move);return()=>cancelAnimationFrame(frame);
 },[serial,wires]);

 return <div ref={map} className={"flow-map"+(!activity?" is-motion-paused":"")} aria-label="动态阶段流程图">
  <svg className="flow-wires" aria-hidden="true"><defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10Z" fill="context-stroke"/></marker></defs>
   {wires.map(wire=><path key={wire.id} data-wire={wire.id} d={wire.d} className={"flow-wire tone-"+flowTone(wire.state)+(wire.id==="2-1"?" is-return":"")} markerEnd={`url(#${marker})`}/>)}
   {transfer&&<circle key={transfer.serial} ref={dot} data-transfer={transfer.edge} className={"flow-transfer-dot tone-"+(transfer.edge==="2-1"?"red":"yellow")} r="4.5" style={{visibility:"hidden"}}/>}
  </svg>
  <div className="flow-map-nodes">{nodes.map((node,index)=><button key={node.id} type="button" disabled={!onSelect} aria-pressed={selected===node.id}
   data-stage={node.id} data-state={node.state} aria-current={node.id===current?"step":undefined}
   className={"flow-card tone-"+flowTone(node.state)+(node.id===current?" is-current":"")+(node.state==="running"&&activity?" is-executing":"")+(transfer?.to===node.id?" is-arriving":"")}
   onClick={()=>onSelect?.(node.id)}>
   <span className="flow-card-head"><span className="flow-card-title"><strong><StatusIcon state={node.state} active={activity}/>{String(index+1).padStart(2,'0')}　{node.title}</strong><span className="flow-state-badge">{node.round!=null?`第 ${node.round} 轮 · `:""}{flowLabel(node.state)}</span></span>
    <span className="flow-card-role"><svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="10" cy="5" r="3"/><path d="M3 18v-2a7 7 0 0 1 14 0v2z"/></svg>{node.role||["负责人","编码伙伴","验证伙伴","负责人"][index]}</span></span>
   <span className="flow-card-body"><span className="flow-card-summary">{node.summary}</span>
    {node.tool&&<span className="flow-card-tool">工具 <code>{node.tool}</code></span>}
    {!!node.steps?.length&&<span className="flow-step-list" aria-label="最近工具步骤">{node.steps.slice(-4).map((step,i)=><span className={"flow-step tone-"+flowTone(step.state)+(step.state==="running"&&node.state==="running"?" is-active-step":"")} key={i}>
     <small>{Math.max(0,node.steps!.length-4)+i+1}</small><StatusIcon state={step.state} active={activity&&node.state==="running"}/><span>{step.label}</span><em>{step.state==="succeeded"?"已完成":step.state==="completed"?"已返回":flowLabel(step.state)}</em></span>)}</span>}
    {!!node.facts?.length&&<span className="flow-card-facts">{node.facts.map(f=><span key={f.label}><span>{f.label}</span><b>{f.value}</b></span>)}</span>}
    {node.detail&&<small className="flow-card-note">{node.detail}</small>}
   </span>
  </button>)}</div>
  {returning&&<div className="flow-return-label">返工路径 · 返回修改</div>}
  <div className="flow-legend"><span className="tone-green">● 通过</span><span className="tone-yellow">◉ 进行中 / 待处理</span><span className="tone-red">● 失败 / 阻塞</span><span>○ 未开始</span></div>
 </div>;
}
