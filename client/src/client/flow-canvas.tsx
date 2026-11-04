import "./development-flow.css";

export type FlowNode={id:string;title:string;state:string;summary:string;detail?:string};
export const flowLabel=(state:string)=>({running:"进行中",succeeded:"通过",completed:"执行结束",failed:"失败",timed_out:"超时",blocked:"阻塞",exhausted:"已停止",
 needs_input:"待补充",revise:"需修改",waiting:"等待前序",pending:"待执行",queued:"排队中",cancelling:"停止中",cancelled:"已停止",interrupted:"中断",unseen:"未开始"}[state]||state);
export const flowTone=(state:string)=>["succeeded","pass","accepted","aligned"].includes(state)?"green":
 ["failed","timed_out","blocked","exhausted","interrupted","fail"].includes(state)?"red":
 ["running","needs_input","revise","waiting","pending","queued","cancelling","completed"].includes(state)?"yellow":"gray";

export function FlowCanvas({nodes,current,selected,onSelect,returning=false}:{nodes:FlowNode[];current?:string;selected?:string;onSelect?:(id:string)=>void;returning?:boolean}){
 return <div className="flow-map" aria-label="动态阶段流程图">
  <div className="flow-map-nodes">{nodes.map((node,index)=><button key={node.id} type="button" disabled={!onSelect} aria-pressed={selected===node.id}
   data-stage={node.id} data-state={node.state} className={"flow-card tone-"+flowTone(node.state)+(node.id===current?" is-current":"")}
   onClick={()=>onSelect?.(node.id)}>
   <span className="flow-card-title"><strong>{String(index+1).padStart(2,'0')}　{node.title}</strong><span>{flowLabel(node.state)}</span></span>
   <p>{node.summary}</p>{node.detail&&<small>{node.detail}</small>}
  </button>)}</div>
  {returning&&<div className="flow-return">↶ 已返回前序阶段 · 修改后继续验证</div>}
  <div className="flow-legend"><span className="tone-green">● 通过</span><span className="tone-yellow">● 进行中 / 待处理</span><span className="tone-red">● 失败 / 阻塞</span><span>○ 未开始</span></div>
 </div>;
}
