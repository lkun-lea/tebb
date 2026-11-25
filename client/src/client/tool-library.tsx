import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ChevronRight, Cloud, Plus, Search, Sparkles } from 'lucide-react';
import { editToolLibrary, fetchCloudTools, fetchToolLibrary, rpc, type BackendInfo, type CatalogDefinition, type LibraryEntry } from './api';
import { toolPresentation } from './tool-presentation';
import { UiButton, UiFeedback, UiField } from './ui-controls';
import { WorkspaceDialog } from './workspace-dialog';
import './tool-library.css';

import {CapabilityDefinitionForm,type Capability,type Adapter} from './capability-definition-form';
type Catalog = {ok:boolean;error?:string;capabilities:Capability[];nodes:Adapter[]};
type Props = {info:BackendInfo|null; definitions:CatalogDefinition[]; onActivity:(name:string)=>void; onRefresh:()=>Promise<void>; onChat?:(conversation:string)=>void};
const keyOf = (d:CatalogDefinition) => d.capabilityId ? 'cap-'+d.capabilityId : d.name;

export function ToolLibrary({info,definitions,onActivity,onRefresh,onChat}:Props) {
  const [page,setPage] = useState<'mine'|'cloud'|'removed'>('mine');
  const [queries,setQueries] = useState({mine:'',cloud:'',removed:''});
  const query=queries[page];
  function setQuery(value:string) { setQueries(old=>({...old,[page]:value})); }
  const [cloud,setCloud] = useState<CatalogDefinition[]|null>(null);
  const [preferencesReady,setPreferencesReady]=useState(false);
  const [source,setSource] = useState<Catalog|null>(null);
  const [caps,setCaps] = useState<CatalogDefinition[]>([]);
  const [prefs,setPrefs] = useState<Record<string,LibraryEntry>>({});
  const [detail,setDetail] = useState<CatalogDefinition|null>(null);
  const [editing,setEditing] = useState(false), [archiving,setArchiving] = useState(false);
  const [title,setTitle] = useState(''), [summary,setSummary] = useState('');
  const [author,setAuthor] = useState<CatalogDefinition|'new'|null>(null);
  const [instructions,setInstructions] = useState(''), [conversation,setConversation] = useState('');
  const [busy,setBusy] = useState(false), [error,setError] = useState('');
  const locked = useRef(false);
  const receipt = useRef<{text:string; id:string; conversation:string}>();
  const local = new Map([...definitions,...caps].map(d=>[keyOf(d),d]));
  async function readLocal() {
    if (!info) return;
    const saved=await fetchToolLibrary(info);
    setPrefs(Object.fromEntries(saved.entries.map(row=>[row.name,row])));
    setPreferencesReady(true);
    const catalog=await rpc<Catalog>(info,'automation_workflow',{operation:'catalog',payload:{}});
    if (catalog.ok === false) throw Error(catalog.error || '读取自定义能力失败');
    setSource(catalog);
    setCaps(catalog.capabilities.map(c=>({name:c.name,capabilityId:c.id,revision:c.revision,version:c.version,source:'工作流能力',collection:'自定义能力',
      description:(catalog.nodes.find(n=>n.kind===c.kind)?.label || c.kind)+' · '+(Object.keys(c.parameters).join('、') || '无需参数'),parameters:c.parameters})));
  }
  useEffect(()=>{void readLocal().catch(e=>setError(String(e)));},[info]);
  async function run(work:()=>Promise<void>) {
    if (locked.current) return;
    locked.current=true;setBusy(true);setError('');
    try { await work(); } catch(e) { setError(String(e)); } finally { locked.current=false;setBusy(false); }
  }
  function navigate(next:typeof page) {setPage(next);setError('');}
  function browse() {
    navigate('cloud');
    if (info) void run(async()=>setCloud((await fetchCloudTools(info)).tools));
  }
  function describe(d:CatalogDefinition) {
    const base=toolPresentation(d), pref=prefs[keyOf(d)];
    return {...base,title:pref?.title || base.title,summary:pref?.summary || base.summary};
  }
  function change(d:CatalogDefinition, values:Partial<LibraryEntry> & {add?:boolean}) {
    if (!info || !preferencesReady) return;
    void run(async()=>{
      const name=keyOf(d);
      await editToolLibrary(info,{name,...values});
      setPrefs(old=>({...old,[name]:{...old[name],name,...values,...(values.add?{hidden:false}:{})}}));
      if (values.add) await onRefresh();
      setEditing(false);
      if (values.hidden!==undefined) setDetail(null);
    });
  }
  function openAuthor(d:CatalogDefinition|'new') {
    setDetail(null);setAuthor(d);setInstructions('');setConversation('');setError('');receipt.current=undefined;
  }
  function submitRequest() {
    if (!info || !instructions.trim() || !author) return;
    const goal=author==='new' ? '创建一项自定义工作流能力' : author.capabilityId ?
      '修改自定义能力 '+author.name+'，编号 '+author.capabilityId+'，先读取当前版本' :
      '基于内置工具 '+author.name+' 设计一项可复用的自定义能力';
    const text=goal+'。请使用自动化工作流工具核对目录，按需求保存能力定义，返回名称和版本。仅保存定义。\n'+instructions.trim();
    void run(async()=>{
      if (receipt.current?.text!==text) receipt.current={text,id:crypto.randomUUID(),conversation:'dm-'+crypto.randomUUID().replaceAll('-','')};
      const attempt=receipt.current;
      const result=await rpc<{ok:boolean;error?:string}>(info,'collaboration_action',{action:{type:'send',new_chat:{agent_id:'tebb',project_id:''},conversation:attempt.conversation,target:'tebb',mode:'task',text,request_id:attempt.id}});
      if (!result.ok) throw Error(result.error || '任务未登记');
      setConversation(attempt.conversation);
    });
  }
  const isCloud=page==='cloud';
  const rows=(isCloud ? cloud||[] : [...local.values()].filter(d=>Boolean(prefs[keyOf(d)]?.hidden)===(page==='removed')))
    .filter(d=>{const view=describe(d);return [d.name,d.collection,view.group,view.title,view.summary].join(' ').toLowerCase().includes(query.trim().toLowerCase());});
  const groups=[...new Set(rows.map(d=>describe(d).group))];
  const selected=detail && describe(detail);
  const errorView=error && <UiFeedback state="error" title="操作未完成">{error}</UiFeedback>;
  return <section className="tool-library">
    <header className="library-head"><div>{page!=='mine'&&<UiButton disabled={busy} onClick={()=>navigate('mine')}><ArrowLeft size={16}/>我的工具</UiButton>}
      <h2>{isCloud?'云端工具':page==='removed'?'已移除的工具':'我的工具'}</h2></div>
      <div className="library-actions">{page==='mine'?<>
        <UiButton disabled={!info||busy} onClick={browse}><Cloud size={18}/>浏览云端工具</UiButton>
        <UiButton disabled={!info||busy} variant="primary" onClick={()=>openAuthor('new')}><Plus size={17}/>创建工具</UiButton>
      </>:isCloud&&<UiButton busy={busy} onClick={browse}>重新拉取</UiButton>}</div></header>
    <div className="library-toolbar"><label><Search size={17}/><input aria-label="查找工具" placeholder="搜索工具名称或用途" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      {page==='mine'&&<UiButton onClick={()=>navigate('removed')}>已移除</UiButton>}
      {page==='mine'&&<UiButton disabled={!info||busy} onClick={()=>void run(async()=>{await readLocal();await onRefresh();})}>刷新本机</UiButton>}</div>
    {!detail&&!author&&errorView}
    {isCloud&&busy&&!cloud&&<p role="status">正在读取云端目录…</p>}
    {!rows.length&&!busy&&!error&&<p className="library-empty">{query?'没有找到匹配的工具':page==='mine'?'还没有工具，可以从云端挑选。':page==='removed'?'没有已移除的工具':'云端目录为空'}</p>}
    <div className="library-groups">{groups.map(group=><section key={group} className="library-group" data-group={group}><h3>{group}</h3><div className="library-list">{rows.filter(d=>describe(d).group===group).map(d=>{
      const {title,summary,Icon}=describe(d), key=keyOf(d), exists=local.has(key)&&!prefs[key]?.hidden;
      return <div className="library-row" key={key}><button className="library-item" onClick={()=>{setError('');setEditing(false);setArchiving(false);setDetail(d);}}>
        <span className="library-icon"><Icon aria-hidden size={21}/></span><span><strong>{title}</strong><small>{summary}</small></span><ChevronRight size={16} aria-hidden/></button>
        {isCloud?<UiButton disabled={busy||!preferencesReady||exists||!d.compatible} onClick={()=>change(d,{add:true})}>{exists?'已添加':d.compatible?'添加':'本机不支持'}</UiButton>:
          page==='removed'?<UiButton disabled={busy} onClick={()=>change(d,{hidden:false})}>恢复</UiButton>:prefs[key]?.disabled?<small>已停用</small>:null}</div>;
    })}</div></section>)}</div>
    {detail&&selected&&<WorkspaceDialog title={selected.title} closeDisabled={busy} onClose={()=>setDetail(null)}>
      {editing?<form className="library-form" onSubmit={e=>{e.preventDefault();change(detail,{title:title.trim(),summary:summary.trim()});}}>
        <UiField label="显示名称"><input value={title} maxLength={60} required onChange={e=>setTitle(e.target.value)}/></UiField>
        <UiField label="一句话用途"><textarea value={summary} maxLength={160} required onChange={e=>setSummary(e.target.value)}/></UiField>
        <UiButton variant="primary" busy={busy} type="submit">保存</UiButton></form>:<>
        <p>{selected.summary}</p><details><summary>技术说明与参数</summary><code>{detail.name}</code><p>{detail.description}</p><pre>{JSON.stringify(detail.parameters,null,2)}</pre>{detail.version&&<small>{detail.version}</small>}</details>
        {!isCloud&&<div className="library-actions">
          <UiButton onClick={()=>{setTitle(selected.title);setSummary(selected.summary);setEditing(true);}}>编辑显示信息</UiButton>
          <UiButton disabled={busy} onClick={()=>change(detail,{disabled:!prefs[keyOf(detail)]?.disabled})}>{prefs[keyOf(detail)]?.disabled?'启用本机调用':'停用本机调用'}</UiButton>
          <UiButton disabled={busy} onClick={()=>change(detail,{hidden:!prefs[keyOf(detail)]?.hidden})}>{prefs[keyOf(detail)]?.hidden?'恢复到目录':'从目录移除'}</UiButton>
          <UiButton disabled={busy} onClick={()=>openAuthor(detail)}><Sparkles size={16}/>{detail.capabilityId?'让 tebb 修改能力':'让 tebb 定制能力'}</UiButton>
          {detail.capabilityId&&<UiButton disabled={busy} variant="danger" onClick={()=>setArchiving(true)}>删除自定义能力</UiButton>}
          {!detail.capabilityId&&<UiButton onClick={()=>onActivity(detail.name)}>查看调用记录</UiButton>}</div>}
        {archiving&&<div><p>从可复用能力中删除「{detail.name}」？已有工作流保留原版本。</p><UiButton disabled={busy} onClick={()=>setArchiving(false)}>取消</UiButton>
          <UiButton busy={busy} variant="danger" onClick={()=>{if(info) void run(async()=>{
            const result=await rpc<{ok:boolean;error?:string}>(info,'automation_workflow',{operation:'capability_archive',payload:{id:detail.capabilityId,version:detail.version}});
            if (!result.ok) throw Error(result.error);
            setDetail(null);await readLocal();
          });}}>确认删除</UiButton></div>}</>}{errorView}</WorkspaceDialog>}
    {author&&<WorkspaceDialog title={author==='new'?'让 tebb 创建工具':'让 tebb 调整工具'} closeDisabled={busy} onClose={()=>setAuthor(null)}>
      {conversation?<><p role="status">需求已交给 tebb。能力保存后可在「我的工具」刷新查看。</p>{onChat&&<UiButton disabled={busy} onClick={()=>void run(async()=>{await onChat(conversation);})}>查看任务会话</UiButton>}</>:
      <form className="library-form" onSubmit={e=>{e.preventDefault();submitRequest();}}><UiField label="你想让工具做什么？"><textarea required maxLength={3000} placeholder="例如，从会议记录中提取负责人和截止日期" value={instructions} onChange={e=>setInstructions(e.target.value)}/></UiField><UiButton variant="primary" busy={busy} disabled={!instructions.trim()} type="submit">交给 tebb</UiButton></form>}
      {!conversation&&source&&info&&(author==='new'||author.capabilityId)&&<CapabilityDefinitionForm info={info} adapters={source.nodes}
        existing={author==='new'?undefined:source.capabilities.find(c=>c.id===author.capabilityId)}
        onSaved={async()=>{await readLocal();setAuthor(null);}}/>}{errorView}</WorkspaceDialog>}
  </section>;
}
