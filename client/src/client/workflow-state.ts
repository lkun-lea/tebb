import type {TaskBudget} from './task-budget';
export type NodeKind = 'trigger'|'search'|'read'|'ai'|'condition'|'document'|'base'|'message'|'video'|'feishu_read'|'news_sources'|'news_report';
export type NodeConfig = Record<string,string|number|Record<string,string>>;
export type GraphNode = {id:string;kind:NodeKind;config:NodeConfig;position:{x:number;y:number};capability?:{id:string;version:string;name:string}};
export type Capability = {id:string;version:string;revision:number;name:string;kind:NodeKind;parameters:Record<string,string>;template:NodeConfig;writes:boolean};
export type WorkflowTemplate = {id:string;name:string;description:string;graph:Graph};
export type Graph = {nodes:GraphNode[];edges:{source:string;target:string;branch:string}[]};
export type Definition = {id:string;name:string;revision:number;version:string;graph:Graph};
export type GraphPreview = {nodes:{id:string;kind:NodeKind;position:{x:number;y:number};label:string}[];edges:Graph['edges']};
export type WorkflowSummary = Omit<Definition,'graph'> & {updated:number;preview:GraphPreview;latest_run:RunSummary|null};
export type RunSummary = Pick<WorkflowRun,'id'|'workflow'|'version'|'name'|'state'|'mode'|'attempt'|'task_id'|'error'> & {created:number;updated:number};
export type Receipt = {node:string;kind:NodeKind;state:string;input:NodeConfig;output:Record<string,unknown>;error:string;receipt_key:string};
export type WorkflowRun = {id:string;workflow:string;version:string;name:string;state:string;mode:'step'|'full';attempt:number;task_id:string;error:string;approved:string[];graph:Graph;receipts:Record<string,Receipt>;task_budget?:TaskBudget};
export type CatalogNode = {kind:NodeKind;label:string;defaults:NodeConfig;outputs:string[];writes:boolean};
export const writeKinds = new Set<NodeKind>(['document','base','message']);
export const runLabels:Record<string,string> = {queued:'排队中',running:'执行中',paused:'步骤完成',waiting_approval:'待确认发布',completed:'已完成',failed:'失败',unknown:'结果待核对',interrupted:'已中断',cancelled:'已停止',confirmed:'已确认',pending:'执行中',skipped:'分支跳过'};
export const initialGraph = ():Graph => ({nodes:[{id:'trigger',kind:'trigger',config:{text:''},position:{x:70,y:70}}],edges:[]});
export function draftSnapshot(name:string,graph:Graph){
  return JSON.stringify({name,graph},(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b))):value);
}
export const newNodeId = (kind:NodeKind) => kind+'_'+crypto.randomUUID().replaceAll('-','').slice(0,8);
export function connectionError(graph:Graph,source:string|null,target:string|null,branch=''){
  const from=graph.nodes.find(n=>n.id===source),to=graph.nodes.find(n=>n.id===target);
  if(!from||!to)return '请选择有效的起点和终点。';
  if(source===target)return '节点不能连接自己。';
  if(to.kind==='trigger')return '触发节点只能作为起点。';
  if(from.kind==='condition'?!['true','false'].includes(branch):!!branch)return '条件出口须选择满足或不满足，普通节点不设置分支。';
  if(graph.edges.some(e=>e.source===source&&e.target===target&&e.branch===branch))return '这条连接已经存在。';
  const pending=[target],seen=new Set<string>();
  while(pending.length){const id=pending.pop()!;if(id===source)return '这条连接会形成循环。';if(seen.has(id))continue;seen.add(id);pending.push(...graph.edges.filter(e=>e.source===id).map(e=>e.target));}
  return '';
}
export function describeTarget(node:GraphNode){
  if(node.kind==='document')return String(node.config.parent_token||'当前用户云空间');
  if(node.kind==='base')return String(node.config.base_token)+' / '+String(node.config.table_id);
  if(node.kind==='message')return String(node.config.chat_id);
  return '';
}
export function resolvePreview(config:NodeConfig,receipts:Record<string,Pick<Receipt,'output'>>):NodeConfig{
  return Object.fromEntries(Object.entries(config).map(([key,value])=>[key,typeof value==='string'?value.replace(/\{\{\s*([A-Za-z][A-Za-z0-9_-]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g,(_all,node,field)=>{
    const output=receipts[node]?.output[field];return output===undefined?'（上游尚未取得）':typeof output==='string'?output:JSON.stringify(output);
  }):typeof value==='object'?resolvePreview(value,receipts) as Record<string,string>:value]));
}
export const editableRun = (run?:WorkflowRun|null) => !!run&&['paused','failed','interrupted','cancelled','waiting_approval'].includes(run.state);
