import "./development-flow.css";

export type FlowNode={id:string;title:string;state:string;summary:string;detail?:string;role?:string;steps?:{label:string;state:string}[]};
export const toolStepName=(tool:string)=>({workspace_search:"定位源码",workspace_read_symbol:"读取函数",workspace_patch:"局部修改",workspace_run:"执行命令",workspace_list:"查看目录"}[tool]||tool);
export const flowLabel=(state:string)=>({running:"进行中",succeeded:"通过",completed:"执行结束",failed:"失败",timed_out:"超时",blocked:"阻塞",exhausted:"已停止",
 needs_input:"待补充",revise:"需修改",waiting:"等待前序",pending:"待执行",queued:"排队中",cancelling:"停止中",cancelled:"已停止",interrupted:"中断",unconfirmed:"未返回",unseen:"未开始"}[state]||state);
export const flowTone=(state:string)=>["succeeded","pass","accepted","aligned"].includes(state)?"green":
 ["failed","timed_out","blocked","exhausted","interrupted","fail"].includes(state)?"red":
 ["running","needs_input","revise","waiting","pending","queued","cancelling","completed","unconfirmed"].includes(state)?"yellow":"gray";

export function FlowCanvas({nodes,current,selected,onSelect,returning=false}:{nodes:FlowNode[];current?:string;selected?:string;onSelect?:(id:string)=>void;returning?:boolean}){
 return <div className="flow-map" aria-label="动态阶段流程图">
  <div className="flow-map-nodes">{nodes.map((node,index)=><button key={node.id} type="button" disabled={!onSelect} aria-pressed={selected===node.id}
   data-stage={node.id} data-state={node.state} className={"flow-card tone-"+flowTone(node.state)+(node.id===current?" is-current":"")}
   onClick={()=>onSelect?.(node.id)}>
   <span className="flow-card-head"><span className="flow-card-title"><strong><i className="flow-status-icon" aria-hidden="true">{flowTone(node.state)==="green"?"✓":flowTone(node.state)==="red"?"!":node.state==="running"?"◷":"○"}</i>{String(index+1).padStart(2,'0')}　{node.title}</strong><span className="flow-state-badge">{flowLabel(node.state)}</span></span>
    <span className="flow-card-role"><svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="10" cy="5" r="3"/><path d="M3 18v-2a7 7 0 0 1 14 0v2z"/></svg>{node.role||["负责人","编码伙伴","验证伙伴","负责人"][index]}</span></span>
   <span className="flow-card-body"><span className="flow-card-summary">{node.summary}</span>
    {!!node.steps?.length&&<span className="flow-step-list">{node.steps.slice(-3).map((step,i)=><span className={"flow-step tone-"+flowTone(step.state)} key={i}><small>{i+1}</small><i aria-hidden="true">{flowTone(step.state)==="green"?"✓":flowTone(step.state)==="red"?"!":"○"}</i><span>{step.label}</span><em>{step.state==="succeeded"?"已完成":step.state==="completed"?"已返回":flowLabel(step.state)}</em></span>)}</span>}
    {!node.steps?.length&&node.detail&&<small className="flow-card-note">{node.detail}</small>}
   </span>
  </button>)}</div>
  {returning&&<div className="flow-return"><span>未通过 →<br/>已返回修改</span></div>}
  <div className="flow-legend"><span className="tone-green">● 通过</span><span className="tone-yellow">● 进行中 / 待处理</span><span className="tone-red">● 失败 / 阻塞</span><span>○ 未开始</span></div>
 </div>;
}
