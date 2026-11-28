import {useEffect,useMemo,useRef,useState,type MutableRefObject} from 'react';
import {rpc,type BackendInfo} from './api';
import type {NotebookPage,NoteSession,NoteItem} from './note';
import type {LocalSource} from './local-sources';
import type {DemoState} from './chat-prototype-state';
import type {WorkPage} from './work-board-state';
import {recentFocus} from './recent-focus';
import {WorkspaceDialog} from './workspace-dialog';
import {Markdown} from './Markdown';
import {usePageActive} from './page-stack';
import './saved-notes.css';

export type NoteDraftTarget={id:string;title:string};
export type NoteDraftPort=MutableRefObject<{
  owner:string;targets:NoteDraftTarget[];current:string;attach:(id:string,file:LocalSource)=>void
}|null>;
type Row=NoteItem&{session:string;group:string};
type Editor={id:string;row?:Row;title:string;body:string};

export function SavedNotes({info,sessions,error,accept,refresh,port,initialSession,onFile}:{
 info:BackendInfo|null;sessions:NoteSession[];error:string;accept:(page:NotebookPage)=>boolean;
 onFile:(action:'open'|'reveal',id:string,name:string,session:string)=>void;refresh:()=>void;port:NoteDraftPort;initialSession?:string|null
}){
 const active=usePageActive(),[query,setQuery]=useState(''),[opened,setOpened]=useState('');
 const [editor,setEditor]=useState<Editor|null>(null),[discard,setDiscard]=useState(false),[share,setShare]=useState<Row|null>(null);
 const [target,setTarget]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[problem,setProblem]=useState('');
 const [chat,setChat]=useState<DemoState|null>(null),[work,setWork]=useState<WorkPage['items']>([]);
 const submitting=useRef(false),mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false};},[]);
 const rows=useMemo(()=>sessions.flatMap(s=>s.notes.map(n=>({...n,session:s.id,group:s.title}))).sort((a,b)=>b.saved.localeCompare(a.saved)),[sessions]);
 const selected=rows.find(r=>r.id===opened);
 const initialId=initialSession?rows.find(r=>r.session===initialSession)?.id:'';
 useEffect(()=>{setOpened(initialId||'');},[initialSession,initialId]);
 useEffect(()=>{if(!info||!active)return;let live=true;
   void rpc<{state:DemoState}>(info,'load_collaboration',{}).then(p=>{if(live)setChat(p.state)}).catch(()=>{if(live)setChat(null)});
   void rpc<WorkPage>(info,'load_work_board',{}).then(p=>{if(live)setWork(p.items||[])}).catch(()=>{if(live)setWork([])});
   return ()=>{live=false};
 },[info,active]);
 const topics=useMemo(()=>recentFocus(sessions,chat,work),[sessions,chat,work]);
 function edit(row?:Row){setProblem('');setEditor({id:row?.id||crypto.randomUUID().replaceAll('-',''),row,title:row?.question||'',body:row?.answer||''});}
 function leave(){if(editor&&(editor.title!==(editor.row?.question||'')||editor.body!==(editor.row?.answer||'')))setDiscard(true);else setEditor(null);}
 async function save(){
   if(!info||!editor||submitting.current)return;
   submitting.current=true;setBusy(true);setProblem('');
   try{
     const r=editor.row;
     const page=await rpc<NotebookPage>(info,'write_personal_note',{session_id:r?.session||'',note_id:editor.id,title:editor.title,body:editor.body,previous:r?{title:r.question,body:r.answer}:null});
     if(!mounted.current)return;
     if(!accept(page))throw Error(page.error||'保存结果待核对');
     setOpened(editor.id);setEditor(null);setNotice('笔记已保存');
   }catch(e){setProblem(String(e));}finally{submitting.current=false;setBusy(false);}
 }
 function choose(row:Row){setProblem('');setTarget(port.current?.current||'');setShare(row);}
 async function attach(){
   if(!share||!info||!target||submitting.current)return;
   submitting.current=true;setBusy(true);setProblem('');
   try{
     const response=await rpc<{ok:boolean;sources:LocalSource[];errors?:unknown[]}>(info,'prepare_notebook_source',{session_id:share.session,note_id:share.id});
     if(!mounted.current)return;
     const dest=port.current?.targets.find(t=>t.id===target);
     if(!response.ok||!response.sources?.length||response.errors?.length)throw Error('笔记资料准备失败');
     if(!dest||!port.current||port.current.owner!==info.token)throw Error('会话已发生变化，请重新选择。');
     port.current.attach(target,{...response.sources[0],name:'笔记 · '+share.question,noteKey:JSON.stringify([share.session,share.id])});
     setShare(null);setNotice('已加入「'+dest.title+'」的草稿，可在发送前移除。');
   }catch(e){setProblem(String(e));}finally{submitting.current=false;setBusy(false);}
 }
 const needle=query.trim().toLocaleLowerCase(),visible=rows.filter(r=>(r.question+' '+r.answer).toLocaleLowerCase().includes(needle));
 return <section className="saved-notes" aria-label="笔记">
 <header><h1>笔记</h1><button className="sn-primary" onClick={()=>edit()} disabled={!info}>＋ 新建笔记</button></header>
 {error&&<p role="alert">{error} <button onClick={refresh}>重新读取</button></p>}
 {notice&&<p role="status">{notice}</p>}
 {selected?<article><button onClick={()=>setOpened('')}>‹ 全部笔记</button><h2>{selected.question}</h2><small>{selected.group} · {selected.saved.slice(0,10)}</small><Markdown text={selected.answer}/>
 {!!selected.cites.length&&<details><summary>来源 · {selected.cites.length}</summary>{selected.cites.map((c,i)=><blockquote key={i}><strong>{c.doc} · {c.title}</strong><p>{c.text}</p></blockquote>)}</details>}
 {!!selected.files.length&&<details><summary>关联文件 · {selected.files.length}</summary>{selected.files.map(f=><p key={f.name}>{f.name} <button onClick={()=>onFile('open',selected.id,f.name,selected.session)}>预览</button> <button onClick={()=>onFile('reveal',selected.id,f.name,selected.session)}>所在文件夹</button></p>)}</details>}
 <footer><button onClick={()=>edit(selected)}>编辑笔记</button><button onClick={()=>choose(selected)}>加入会话</button></footer></article>:<>
 <input aria-label="查找笔记" placeholder="查找标题或正文" value={query} onChange={e=>setQuery(e.target.value)}/>
 {!query&&!!topics.length&&<aside><small>近期关注 · 最近 14 天</small><h2>{topics.join('、')}</h2></aside>}
 <div className="sn-list"><h2>{query?'查找结果':'保留的笔记'}</h2>{visible.map(r=><button className="sn-row" key={r.id} onClick={()=>{setOpened(r.id);setNotice('')}}><strong>{r.question}</strong><span>{r.answer.slice(0,90)}</span><small>{r.saved.slice(0,10)} · {r.group}</small></button>)}
 {!visible.length&&!error&&<p>{query?'没有匹配的笔记。':'还没有保留的笔记。'}</p>}</div></>}
 {editor&&<WorkspaceDialog title={editor.row?'编辑笔记':'新建笔记'} onClose={leave} closeDisabled={busy}><form onSubmit={e=>{e.preventDefault();void save()}}>
 <label>标题<input autoFocus required value={editor.title} onChange={e=>setEditor({...editor,title:e.target.value})}/></label><label>正文<textarea rows={10} required value={editor.body} onChange={e=>setEditor({...editor,body:e.target.value})}/></label>
 {problem&&<p role="alert">{problem}</p>}<footer><button type="button" onClick={leave} disabled={busy}>取消</button><button className="sn-primary" disabled={busy||!editor.title.trim()||!editor.body.trim()}>保存笔记</button></footer></form></WorkspaceDialog>}
 {discard&&<WorkspaceDialog title="放弃未保存的修改？" onClose={()=>setDiscard(false)}><button onClick={()=>setDiscard(false)}>继续编辑</button><button onClick={()=>{setEditor(null);setDiscard(false)}}>放弃修改</button></WorkspaceDialog>}
 {share&&<WorkspaceDialog title="加入会话" onClose={()=>setShare(null)} closeDisabled={busy}><strong>{share.question}</strong><p>将笔记正文及其引用作为本地附件加入所选草稿，由你决定何时发送。</p><label>目标会话<select value={target} onChange={e=>setTarget(e.target.value)}>{!target&&<option value="">请选择会话</option>}{port.current?.targets.map(t=><option key={t.id} value={t.id}>{t.title}{t.id===port.current?.current?'（当前）':''}</option>)}</select></label>
 {problem&&<p role="alert">{problem}</p>}<footer><button disabled={busy} onClick={()=>setShare(null)}>取消</button><button disabled={!target||busy} className="sn-primary" onClick={()=>void attach()}>加入草稿</button></footer></WorkspaceDialog>}
 </section>;
}
