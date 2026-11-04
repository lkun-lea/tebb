import {useState} from 'react';
import {Brain,Check,CloudOff,GitCompareArrows} from 'lucide-react';
import {UiButton} from './ui-controls';
import type {ProfileRecord} from './personalization-state';
import {profileKinds,profileCategories,profileSyncNames} from './profile-records';
export type ProfileRecordActions={blocked:boolean;scopeLabel:(row:ProfileRecord)=>string;onEdit:(row:ProfileRecord,resolve?:boolean)=>void;onAct:(type:string,row:ProfileRecord)=>void};
export function ProfileRecordCard({row,blocked,scopeLabel,onEdit,onAct}:ProfileRecordActions&{row:ProfileRecord}){
  const [deleting,setDeleting]=useState(false);
  const conflict=row.sync_state.startsWith('conflict'),source=row.source_ref?.startsWith('manual:')?'你手动确认':row.source_ref?'已确认来源':'来源未记录';
  const date=new Date(row.updated),updated=Number.isFinite(date.getTime())?date.toLocaleString('zh-CN'):'未记录';
  return <article className={'profile-card '+(conflict?'has-conflict':'')} id={'profile-'+row.id}>
    <header><div className={'profile-kind kind-'+row.kind}><Brain size={17}/>{profileKinds[row.kind]}</div><span className={'profile-badge state-'+row.sync_state}>{row.sync_state==='synced'?<Check size={12}/>:conflict?<GitCompareArrows size={12}/>:<CloudOff size={12}/>} {profileSyncNames[row.sync_state]||row.sync_state}</span></header>
    <div className="profile-card-tags"><span>{profileCategories[row.category]}</span><span>{scopeLabel(row)}</span>{row.state!=='active'&&<span>{row.state==='deleted'?'已删除 · 正文已移除':'已停用'}</span>}</div>
    <p className="profile-content">{row.text||'正文已从当前资料中移除。'}</p>
    {row.remote&&<section className="profile-remote"><strong>云端当前版本 · v{row.remote.version}</strong><p>{row.remote.text}</p><span>{row.remote.state==='disabled'?'云端已停用':row.remote.state==='deleted'?'云端已删除':'云端正在使用'}</span></section>}
    <dl className="profile-record-meta"><dt>来源</dt><dd>{source}</dd><dt>资料更新</dt><dd>{updated}</dd><dt>使用范围</dt><dd>{scopeLabel(row)}</dd></dl>
    {row.error&&<p className="profile-error" role="alert">{row.error}</p>}
    <footer><small>本机 v{row.version} · 云端 v{row.cloud_version}</small><div className="profile-actions">
      {row.state==='deleted'?conflict&&<UiButton disabled={blocked} onClick={()=>onAct('delete',row)}>确认删除云端当前版本</UiButton>:conflict?<><UiButton disabled={blocked||!row.can_resolve} onClick={()=>onEdit(row,true)}>采用本机 / 更正</UiButton><UiButton disabled={blocked||!row.can_resolve} onClick={()=>onAct('resolve_remote',row)}>采用云端版本</UiButton></>:<><UiButton disabled={blocked||row.sync_state==='syncing'||row.sync_state==='unconfirmed'} onClick={()=>onEdit(row)}>{row.state==='disabled'?'确认恢复':'更正'}</UiButton>{row.state==='active'&&<UiButton disabled={blocked} onClick={()=>onAct('disable',row)}>停用</UiButton>}</>}
      {row.can_retry&&<UiButton disabled={blocked} onClick={()=>onAct('retry',row)}>重试原编号</UiButton>}
      {row.state!=='deleted'&&!deleting&&<UiButton variant="danger" disabled={blocked} onClick={()=>setDeleting(true)}>删除</UiButton>}
    </div></footer>
    {deleting&&<div className="profile-delete-confirm"><p>确认移除这条资料？删除会停止后续使用，历史调用保留原快照。</p><UiButton disabled={blocked} onClick={()=>setDeleting(false)}>取消</UiButton><UiButton variant="danger" disabled={blocked} onClick={()=>{onAct('delete',row);setDeleting(false);}}>确认删除</UiButton></div>}
    <details className="profile-source-reference"><summary>来源与版本编号</summary><dl className="profile-record-meta"><dt>来源编号</dt><dd>{row.source_ref||'未记录'}</dd><dt>来源设备</dt><dd>{row.source_device_id||'未记录'}</dd><dt>条目编号</dt><dd>{row.id}</dd></dl></details>
  </article>;
}
