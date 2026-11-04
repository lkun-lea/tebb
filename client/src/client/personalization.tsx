import {useEffect,useMemo,useState} from 'react';
import {Brain,Check,Cloud,CloudOff,GitCompareArrows,Plus,RefreshCw,UserRound} from 'lucide-react';
import {rpc,type BackendInfo} from './api';
import {accountStorage} from './account-storage';
import {PersonalizationController,PERSONALIZATION_FIXTURE,type ProfileRecord} from './personalization-state';
import {UiButton,UiFeedback,UiField} from './ui-controls';
import './personalization.css';

const kinds:Record<string,string>={profile:'画像',preference:'偏好',memory:'长期记忆'};
const categories:Record<string,string>={communication:'沟通方式',knowledge:'知识背景',goal:'长期目标',project:'项目背景',other:'其他'};
const syncNames:Record<string,string>={queued:'等待同步',syncing:'正在同步',synced:'已同步',local_disabled:'仅本机停用',unconfirmed:'回执待核对',conflict:'版本冲突',conflict_delete:'删除待确认'};
const jobNames:Record<string,string>={queued:'等待开始',running:'正在同步',complete:'本轮已完成',paused:'本轮已暂停，可继续同步',needs_confirmation:'有资料需要处理',failed:'同步未完成',cancelled:'已取消',interrupted:'上次同步已中断'};
type Draft={id?:string;version?:number;kind:string;category:string;text:string;scope:string;scope_id:string;resolve?:boolean};
const blank=():Draft=>({kind:'preference',category:'communication',text:'',scope:'user',scope_id:''});
export function PersonalizationPane({info,debug=false,target}:{info:BackendInfo|null;debug?:boolean;target?:{id:string;nonce:number}|null}){
  const controller=useMemo(()=>new PersonalizationController((method,args)=>{
    if(debug)return Promise.resolve(structuredClone(PERSONALIZATION_FIXTURE));
    if(!info)return Promise.reject(Error('本地助手尚未连接。'));
    return rpc(info,method,args,{timeoutMs:30000});
  },accountStorage()),[info?.port,info?.token,debug]);
  const [,render]=useState(0),[filter,setFilter]=useState('all'),[draft,setDraft]=useState<Draft|null>(null);
  useEffect(()=>controller.subscribe(()=>render(n=>n+1)),[controller]);
  useEffect(()=>{void controller.read(true);},[controller]);
  const page=controller.page,active=!!page?.job&&['queued','running'].includes(page.job.state);
  useEffect(()=>{if(!active)return;const timer=window.setInterval(()=>{if(!controller.busy&&!controller.loading)void controller.read();},1200);return()=>window.clearInterval(timer);},[controller,active]);
  useEffect(()=>{if(target){setFilter('all');setDraft(null);window.setTimeout(()=>document.getElementById('profile-'+target.id)?.scrollIntoView({block:'center'}),50);}},[target]);
  function edit(row:ProfileRecord,resolve=false){setDraft({id:row.id,version:row.version,kind:row.kind,category:row.category,text:row.text,scope:row.scope,scope_id:row.scope_id,resolve});}
  async function save(){if(!draft)return;const {id,version,resolve,...payload}=draft;if(await controller.act(resolve?'resolve_local':'save',{id,version,payload}))setDraft(null);}
  function act(type:string,row:ProfileRecord){void controller.act(type,{id:row.id,version:row.version});}
  if(!page)return <UiFeedback state={controller.error?'error':'loading'} title={controller.error||'正在读取个人资料…'}><UiButton onClick={()=>void controller.read(true)}>重新读取</UiButton></UiFeedback>;
  const blocked=controller.busy||!!controller.unknown||controller.damaged||debug,local=page.mode==='local';
  const shown=page.records.filter(r=>filter==='deleted'?r.state==='deleted':r.state!=='deleted'&&(filter==='all'||r.kind===filter));
  const live=page.records.filter(r=>r.state==='active'&&!r.sync_state.startsWith('conflict'));
  const pending=page.records.filter(r=>!['synced','local_disabled'].includes(r.sync_state));
  const scopeLabel=(row:{scope:string;scope_id:string})=>page.scopes?.find(s=>s.scope===row.scope&&s.id===row.scope_id)?.label||({user:'所有对话',project:'项目',companion:'伙伴'}[row.scope]+' · '+row.scope_id);
  return <section className="profile-pane" aria-label="个人资料">
    <header><div><h2><UserRound size={23}/>个人资料</h2><p>已确认的画像、偏好与长期记忆，用于后续对话。</p></div><div className="profile-actions"><UiButton disabled={controller.busy||controller.loading} onClick={()=>void controller.read(true)}>刷新状态</UiButton><UiButton busy={active} busyLabel="正在同步…" disabled={blocked||local||active} onClick={()=>void controller.act('sync')}><RefreshCw size={15}/>立即同步</UiButton></div></header>
    {debug&&<UiFeedback state="unconfirmed" title="设计预览 · 合成资料，操作不写入账号"/>}
    {controller.unknown&&<UiFeedback state="unconfirmed" title="原操作结果待核对"><p>已保留操作编号 {controller.unknown.id}；不会自动重新提交。</p><UiButton disabled={controller.busy} onClick={()=>void controller.read()}>核对原操作</UiButton></UiFeedback>}
    {!draft&&controller.error&&<UiFeedback state="error" title={controller.error}/>}
    {controller.notice&&<UiFeedback state="success" title={controller.notice}/>}
    {local?<UiFeedback state="empty" title="当前为本机空间"><p>请在“账号与空间”登录并重启切换，再管理同步资料。本机记忆继续保留，登录不会自动上传。</p></UiFeedback>:<>
      <div className="profile-overview"><article><UserRound size={19}/><div><span>当前账号</span><strong>{page.account.email}</strong></div></article><article><Check size={19}/><div><span>可用于后续对话</span><strong>{live.length}<small> 条 · 按项目和伙伴范围选择</small></strong></div></article><article><Cloud size={19}/><div><span>待同步 / 待处理</span><strong>{pending.length}<small> 条</small></strong></div></article></div>
      {page.auto_paused&&<UiFeedback state="unconfirmed" title="自动同步已暂停"><p>点击“立即同步”恢复；资料继续保留在当前账号。</p></UiFeedback>}
      {page.job&&<div className={'profile-sync '+(['failed','needs_confirmation'].includes(page.job.state)?'has-warning':'')} role="status"><div><strong>{jobNames[page.job.state]||page.job.state}</strong><span>本轮已处理 {page.job.processed} 项{page.job.phase==='pull'?' · 正在读取云端变化':''}</span>{page.job.error&&<p>{page.job.error}</p>}</div>{active&&<UiButton disabled={blocked} onClick={()=>void controller.act('cancel')}>取消并暂停自动同步</UiButton>}<details><summary>同步编号</summary><code>{page.job.id}</code><p>本机游标 {page.cursor} / 已观察云端 {page.head}</p></details></div>}
      <nav className="profile-tabs" aria-label="个人资料分类">{[['all','全部资料'],...Object.entries(kinds),['deleted','已删除']].map(([id,label])=><button type="button" key={id} aria-pressed={filter===id} onClick={()=>setFilter(id)}>{label}<span>{page.records.filter(r=>id==='deleted'?r.state==='deleted':r.state!=='deleted'&&(id==='all'||r.kind===id)).length}</span></button>)}<UiButton variant="primary" disabled={blocked||!!draft} onClick={()=>setDraft(blank())}><Plus size={15}/>新增资料</UiButton></nav>
      {draft&&<form className="profile-editor" onSubmit={e=>{e.preventDefault();void save();}}><header><h3>{draft.resolve?'确认本机内容解决冲突':draft.id?'更正个人资料':'新增个人资料'}</h3><UiButton disabled={controller.busy} onClick={()=>setDraft(null)}>取消编辑</UiButton></header><div className="profile-editor-fields"><UiField label="资料类型"><select value={draft.kind} onChange={e=>setDraft({...draft,kind:e.target.value})}>{Object.entries(kinds).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></UiField><UiField label="内容类别"><select value={draft.category} onChange={e=>setDraft({...draft,category:e.target.value})}>{Object.entries(categories).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></UiField><UiField label="使用范围"><select value={JSON.stringify([draft.scope,draft.scope_id])} onChange={e=>{const [scope,scope_id]=JSON.parse(e.target.value);setDraft({...draft,scope,scope_id});}}>{!page.scopes?.some(s=>s.scope===draft.scope&&s.id===draft.scope_id)&&<option value={JSON.stringify([draft.scope,draft.scope_id])}>{scopeLabel(draft)}</option>}{page.scopes?.map(s=><option key={s.scope+':'+s.id} value={JSON.stringify([s.scope,s.id])}>{s.label}</option>)}</select></UiField></div><UiField label="确认内容" help="仅保存你明确确认的背景；停用、删除和版本冲突的资料不会用于后续对话。" error={controller.error||undefined}><textarea rows={4} maxLength={4000} value={draft.text} onChange={e=>setDraft({...draft,text:e.target.value})}/></UiField><footer><span>{draft.text.length} / 4000</span><UiButton variant="primary" type="submit" disabled={blocked||!draft.text.trim()} busy={controller.busy} busyLabel="正在保存…">确认并同步</UiButton></footer></form>}
      <div className="profile-cards">{shown.map(row=><article className={'profile-card '+(row.sync_state.startsWith('conflict')?'has-conflict':'')} key={row.id} id={'profile-'+row.id}><header><div className={'profile-kind kind-'+row.kind}><Brain size={17}/>{kinds[row.kind]}</div><span className={'profile-badge state-'+row.sync_state}>{row.sync_state==='synced'?<Check size={12}/>:row.sync_state.startsWith('conflict')?<GitCompareArrows size={12}/>:<CloudOff size={12}/>} {syncNames[row.sync_state]||row.sync_state}</span></header><div className="profile-card-tags"><span>{categories[row.category]}</span><span>{scopeLabel(row)}</span>{row.state!=='active'&&<span>{row.state==='deleted'?'已删除 · 正文已移除':'已停用'}</span>}</div><p className="profile-content">{row.text||'正文已从当前资料中移除。'}</p>
        {row.remote&&<section className="profile-remote"><strong>云端当前版本 · v{row.remote.version}</strong><p>{row.remote.text}</p><span>{row.remote.state==='disabled'?'云端已停用':'云端正在使用'}</span></section>}
        {row.error&&<p className="profile-error" role="alert">{row.error}</p>}
        <footer><small>本机 v{row.version} · 云端 v{row.cloud_version}</small><div className="profile-actions">{row.state==='deleted'?row.sync_state.startsWith('conflict')&&<UiButton disabled={blocked} onClick={()=>act('delete',row)}>确认删除云端当前版本</UiButton>:row.sync_state.startsWith('conflict')?<><UiButton disabled={blocked||!row.can_resolve} onClick={()=>edit(row,true)}>采用本机 / 更正</UiButton><UiButton disabled={blocked||!row.can_resolve} onClick={()=>act('resolve_remote',row)}>采用云端版本</UiButton></>:<><UiButton disabled={blocked||row.sync_state==='syncing'||row.sync_state==='unconfirmed'} onClick={()=>edit(row)}>{row.state==='disabled'?'确认恢复':'编辑'}</UiButton>{row.state==='active'&&<UiButton disabled={blocked} onClick={()=>act('disable',row)}>停用</UiButton>}</>}{row.can_retry&&<UiButton disabled={blocked} onClick={()=>act('retry',row)}>重试原编号</UiButton>}{row.state!=='deleted'&&<UiButton variant="danger" disabled={blocked} onClick={()=>act('delete',row)}>删除</UiButton>}</div></footer></article>)}</div>
      {!shown.length&&<UiFeedback state="empty" title={filter==='deleted'?'没有已删除资料':'当前分类暂无资料'}><p>新增内容前先选择使用范围，确认后才进入同步队列。</p></UiFeedback>}
      <p className="profile-footnote">同步仅包含这些确认资料；完整聊天、项目文件和凭据保留本机。删除立即停止本机使用，云端确认前保留状态；历史调用与摘要可能仍含原文。</p>
    </>}
  </section>;
}
