import {useState} from 'react';
import {ArrowLeft,ArrowRight,Clock3,GitBranch,History,LayoutGrid,Plus,RefreshCw,Sparkles,X} from 'lucide-react';
import {runLabels,type CatalogNode,type GraphPreview,type RunSummary,type WorkflowSummary,type WorkflowTemplate} from './workflow-state';
import type {WorkflowScheduleState} from './workflow-schedules';

export function workflowTime(seconds?:number){return seconds?new Date(seconds*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'时间未提供';}

export function WorkflowThumbnail({graph,catalog}:{graph:GraphPreview;catalog:CatalogNode[]}){
  if(!graph.nodes.length)return <div className="workflow-thumbnail">没有节点</div>;
  const width=108,height=40,padding=22;
  const minX=Math.min(...graph.nodes.map(n=>n.position.x)),minY=Math.min(...graph.nodes.map(n=>n.position.y));
  const maxX=Math.max(...graph.nodes.map(n=>n.position.x))+width,maxY=Math.max(...graph.nodes.map(n=>n.position.y))+height;
  const positions=new Map(graph.nodes.map(n=>[n.id,{x:n.position.x-minX+padding,y:n.position.y-minY+padding}]));
  return <div className="workflow-thumbnail"><svg viewBox={`0 0 ${maxX-minX+padding*2} ${maxY-minY+padding*2}`} aria-hidden="true" preserveAspectRatio="xMidYMid meet">
    {graph.edges.map((edge,index)=>{const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)return null;const mid=(a.x+width+b.x)/2;return <path key={index} d={`M${a.x+width},${a.y+height/2} C${mid},${a.y+height/2} ${mid},${b.y+height/2} ${b.x},${b.y+height/2}`} data-branch={edge.branch}/>;})}
    {graph.nodes.map(n=>{const p=positions.get(n.id)!;const label=n.label||catalog.find(c=>c.kind===n.kind)?.label||n.kind;return <g key={n.id} data-kind={n.kind}><rect x={p.x} y={p.y} width={width} height={height} rx={9}/><circle cx={p.x+12} cy={p.y+height/2} r={3}/><text x={p.x+23} y={p.y+height/2+4}>{label.length>7?label.slice(0,7)+'…':label}</text></g>;})}
  </svg></div>;
}

type OverviewProps={definitions:WorkflowSummary[];history:RunSummary[];catalog:CatalogNode[];schedules:WorkflowScheduleState;loading:boolean;loaded:boolean;error:string;disabled:boolean;debug:boolean;draft:string;onOpen:(id:string)=>void;onResume:()=>void;onNew:()=>void;onTemplate:()=>void;onRun:(id:string)=>void;onRefresh:()=>void;onSchedules:()=>void};
export function WorkflowOverview({definitions,history,catalog,schedules,loading,loaded,error,disabled,debug,draft,onOpen,onResume,onNew,onTemplate,onRun,onRefresh,onSchedules}:OverviewProps){
  const [tab,setTab]=useState<'workflows'|'runs'>('workflows'),[query,setQuery]=useState('');
  const filtered=definitions.filter(d=>d.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const originalPlans=schedules.jobs.filter(j=>j.action!=='workflow'&&j.enabled).length;
  return <section className="workflow-overview" aria-label="自动化工作流首页">
    <header className="workflow-home-heading"><div><h2>自动化</h2></div><div className="workflow-home-actions"><button disabled={disabled||!loaded} onClick={onTemplate}><Sparkles size={15}/>从示例创建</button><button className="workflow-primary" disabled={disabled||!loaded} onClick={onNew}><Plus size={16}/>新建工作流</button></div></header>
    {debug&&<p className="workflow-info">设计预览不读取配置，也不会执行任务。真实工作流请在已连接的客户端中查看。</p>}
    {!!originalPlans&&<p className="workflow-info">还有 {originalPlans} 个原有计划仍启用。<button disabled={disabled} onClick={onSchedules}>查看触发计划</button></p>}
    {!!draft&&<div className="workflow-draft"><div><strong>继续编辑</strong><span>{draft}</span></div><button disabled={disabled} onClick={onResume}>返回当前画布<ArrowRight size={14}/></button></div>}
    <div className="workflow-home-toolbar"><div className="workflow-home-tabs" role="tablist" aria-label="自动化视图"><button role="tab" aria-selected={tab==='workflows'} onClick={()=>setTab('workflows')}><LayoutGrid size={15}/>我的工作流 <span>{definitions.length}</span></button><button role="tab" aria-selected={tab==='runs'} onClick={()=>setTab('runs')}><History size={15}/>运行记录</button></div><div className="workflow-home-actions">{tab==='workflows'&&<input aria-label="搜索工作流" type="search" placeholder="搜索工作流…" value={query} onChange={e=>setQuery(e.target.value)}/>}<button disabled={disabled} onClick={onSchedules}><Clock3 size={15}/>触发计划</button><button aria-label="刷新工作流" disabled={disabled||loading||debug} onClick={onRefresh}><RefreshCw size={15}/></button></div></div>
    {error&&<p className="workflow-error" role="alert">{error}；当前内容保留，可刷新重试。</p>}
    {loading&&!loaded&&<div className="workflow-home-empty" role="status">正在读取已有工作流…</div>}
    {!loading&&!loaded&&!error&&<div className="workflow-home-empty">连接桌面客户端后查看已有工作流。</div>}
    {tab==='workflows'?<div role="tabpanel" aria-label="我的工作流"><div className="workflow-card-grid">{filtered.map(def=>{
      const jobs=schedules.jobs.filter(j=>j.action==='workflow'&&j.workflow_id===def.id);
      const latest=def.latest_run;
      return <article className="workflow-home-card" key={def.id}>
        <button className="workflow-card-open" aria-label={'打开工作流：'+def.name} disabled={disabled} onClick={()=>onOpen(def.id)}><WorkflowThumbnail graph={def.preview} catalog={catalog}/><div className="workflow-card-title"><strong>{def.name}</strong><ArrowRight size={16}/></div><span className="workflow-card-meta"><GitBranch size={13}/>{def.preview.nodes.length} 个节点<span>版本 {def.version.slice(0,8)}</span></span></button>
        <div className="workflow-card-plans">{schedules.error?<span>计划状态读取失败</span>:!schedules.loaded?<span>正在读取触发计划…</span>:jobs.length?jobs.map(job=><div key={job.id}><span><Clock3 size={13}/>{job.schedule_text||job.name}{job.workflow_version!==def.version&&<small>绑定历史版本</small>}</span><button role="switch" aria-label={'启用计划：'+job.name} aria-checked={job.enabled} disabled={disabled||debug||!!schedules.busy||!!job.active} onClick={()=>void schedules.toggle(job)}><span/>{job.enabled?'已启用':'已停用'}</button></div>):<span><Clock3 size={13}/>手动触发</span>}</div>
        <footer><span className="workflow-result" data-state={latest?.state||'unrun'}><i/>{latest?runLabels[latest.state]||latest.state:'尚未运行'}</span>{latest?<button className="workflow-result-link" disabled={disabled} onClick={()=>onRun(latest.id)} aria-label={'查看最近执行：'+def.name}>{workflowTime(latest.created)}<ArrowRight size={12}/></button>:<span>可逐步调试</span>}</footer>
      </article>;
    })}</div>{loaded&&!filtered.length&&!loading&&<div className="workflow-home-empty"><GitBranch size={28}/><h3>{definitions.length?'没有找到匹配的工作流':'从第一个工作流开始'}</h3><p>{definitions.length?'换个关键词再试试。':'创建空白画布，或从资讯整理、视频笔记等示例开始。'}</p>{!definitions.length&&<button disabled={disabled} onClick={onTemplate}>浏览示例<ArrowRight size={14}/></button>}</div>}</div>:<section className="workflow-history" role="tabpanel" aria-label="运行记录">{history.map(item=><button disabled={disabled} key={item.id} onClick={()=>onRun(item.id)}><div><strong>{item.name}</strong><small>{workflowTime(item.created)} · {item.id.slice(0,8)}</small></div><span className="workflow-result" data-state={item.state}><i/>{runLabels[item.state]||item.state}</span><ArrowRight size={15}/></button>)}{loaded&&!history.length&&<div className="workflow-home-empty">还没有执行记录。保存工作流后，可先逐步调试。</div>}<p>显示最近 {history.length} 次执行；点击查看原版本与节点回执。</p></section>}
    <aside className="workflow-companion-tip"><Sparkles size={17}/><div><strong>通过 AI 伙伴创建工作流</strong><p>在「伙伴聊天」中允许使用「自动化工作流」，描述目标，即可创建草稿或复用原子能力；回到这里刷新查看。</p></div></aside>
  </section>;
}

export function WorkflowTemplates({templates,disabled,onChoose,onClose}:{templates:WorkflowTemplate[];disabled:boolean;onChoose:(template:WorkflowTemplate)=>void;onClose:()=>void}){
  return <section className="workflow-template-picker" aria-label="从示例创建"><header><button disabled={disabled} onClick={onClose}><ArrowLeft size={15}/>返回工作流</button><button aria-label="关闭示例" disabled={disabled} onClick={onClose}><X size={16}/></button></header><h2>示例工作流</h2><p>示例复制为独立草稿，填写配置并保存后再执行。</p><div className="workflow-template-grid">{templates.map(t=><button key={t.id} disabled={disabled} onClick={()=>onChoose(t)}><Sparkles size={20}/><strong>{t.name}</strong><span>{t.description}</span><small>{t.graph.nodes.length} 个节点 · 创建草稿 →</small></button>)}</div>{!templates.length&&<p>暂无可用示例。请返回首页刷新，或新建空白工作流。</p>}</section>;
}
