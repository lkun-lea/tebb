import {Plus, Search} from 'lucide-react';
import {UiButton} from './ui-controls';
import {notifyReceipt} from './toast';
import {SavedNoteCard,type SavedNoteRow as Row} from './saved-note-card';
import type {NoteDraftPort} from './note-draft-port';
import {useEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {rpc,type BackendInfo} from './api';
import type {NotebookPage,NoteSession} from './note';
import type {LocalSource} from './local-sources';
import type {DemoState} from './chat-prototype-state';
import type {WorkPage} from './work-board-state';
import {recentFocus} from './recent-focus';
import {WorkspaceDialog} from './workspace-dialog';
import {usePageActive} from './page-stack';
import './saved-notes.css';

type Editor={id:string;row?:Row;title:string;body:string};

export function SavedNotes({info,sessions,error,accept,refresh,port,initialSession,onFile}:{
 info:BackendInfo|null;sessions:NoteSession[];error:string;accept:(page:NotebookPage)=>boolean;
 onFile:(action:'open'|'reveal',id:string,name:string,session:string)=>void;refresh:()=>void;port:NoteDraftPort;initialSession?:string|null
}){
 const active=usePageActive(),[query,setQuery]=useState(''),[opened,setOpened]=useState('');
 const [editor,setEditor]=useState<Editor|null>(null),[discard,setDiscard]=useState(false);
 const [adding,setAdding]=useState(''),[busy,setBusy]=useState(false),[problem,setProblem]=useState('');
 const [chat,setChat]=useState<DemoState|null>(null),[work,setWork]=useState<WorkPage['items']>([]);
 const submitting=useRef(false),mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false};},[]);
 const rows=useMemo(()=>sessions.flatMap(s=>s.notes.map(n=>({...n,session:s.id,group:s.title}))).sort((a,b)=>b.saved.localeCompare(a.saved)),[sessions]);
 const draft=useSyncExternalStore(port.subscribe,port.read);
 const [receipt,setReceipt]=useState<{key:string;conversation:string;title:string}|null>(null);
 useEffect(()=>{
   if(!receipt)return;
   if(draft?.id!==receipt.conversation){setReceipt(null);return;}
   if(draft.noteKeys.has(receipt.key)){
     notifyReceipt('已加入「'+receipt.title+'」的草稿，可在发送前移除。');
     setReceipt(null);
   }
 },[receipt,draft]);
 const initialId=initialSession?rows.find(r=>r.session===initialSession)?.id:'';
 useEffect(()=>{setOpened(initialId||'');},[initialSession,initialId]);
 useEffect(()=>{if(!info||!active)return;let live=true;
   void rpc<{state:DemoState}>(info,'load_collaboration',{}).then(p=>{if(live)setChat(p.state)}).catch(()=>{if(live)setChat(null)});
   void rpc<WorkPage>(info,'load_work_board',{}).then(p=>{if(live)setWork(p.items||[])}).catch(()=>{if(live)setWork([])});
   return ()=>{live=false};
 },[info,active]);
 const topics=useMemo(()=>recentFocus(sessions,chat,work),[sessions,chat,work]);
 const focusActivity=work.find(item=>!item.archived && item.state==='doing' && item.updated*1000<=Date.now() && item.updated*1000>=Date.now()-14*86400000 && topics.some(t=>item.title.includes(t)||item.project_name===t));
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
     setOpened(editor.id);setEditor(null);notifyReceipt('笔记已保存');
   }catch(e){setProblem(String(e));}finally{submitting.current=false;setBusy(false);}
 }
 async function attach(row:Row,key:string){
   const target=port.read();
   if(!info||!target||target.owner!==info.token||target.noteKeys.has(key)||submitting.current)return;
   submitting.current=true;setAdding(key);setProblem('');
   try{
     const response=await rpc<{ok:boolean;sources:LocalSource[];errors?:unknown[]}>(info,'prepare_notebook_source',{session_id:row.session,note_id:row.id});
     if(!mounted.current)return;
     if(!response.ok||!response.sources?.length||response.errors?.length)throw Error('笔记资料准备失败');
     const current=port.read();
     if(current?.id!==target.id||current.owner!==info.token)throw Error('当前会话已切换，请重新加入。');
     if(current.noteKeys.has(key))return;
     current.attach({...response.sources[0],name:'笔记 · '+row.question,noteKey:key});
     setReceipt({key,conversation:current.id,title:current.title});
   }catch(e){setProblem(String(e));}finally{submitting.current=false;setAdding('');}
 }
 const needle=query.trim().toLocaleLowerCase(),visible=rows.filter(r=>(r.question+' '+r.answer).toLocaleLowerCase().includes(needle));
 return <section className="saved-notes" aria-label="笔记">
 <header><h1>笔记</h1><UiButton variant="primary" onClick={()=>edit()} disabled={!info}><Plus size={16} aria-hidden="true"/>新建笔记</UiButton></header>
 {error&&<p role="alert">{error} <button onClick={refresh}>重新读取</button></p>}
 {problem&&!editor&&<p role="alert">{problem}</p>}
 <label className="sn-search"><Search size={17} aria-hidden="true"/><input type="search" aria-label="查找笔记" placeholder="查找标题或正文" value={query} onChange={e=>setQuery(e.target.value)}/></label>
 {!needle&&!!topics.length&&<aside className="sn-focus"><span>近期关注</span><p>{focusActivity ? `正在推进「${focusActivity.title}」。` : topics.join('、')}</p></aside>}
 <section className="sn-list" aria-label={needle?'查找结果':'保留的笔记'}>
 {visible.map(row=>{
   const key=JSON.stringify([row.session,row.id]);
   return <SavedNoteCard key={key} note={row} expanded={opened===row.id} added={!!draft?.noteKeys.has(key)} busy={adding===key}
     disabled={!info||!draft||draft.owner!==info.token||!!adding} onToggle={()=>setOpened(opened===row.id?'':row.id)}
     onAdd={()=>void attach(row,key)} onEdit={()=>edit(row)} onFile={onFile}/>;
 })}
 {!visible.length&&!error&&<p>{query?'没有匹配的笔记。':'还没有保留的笔记。'}</p>}</section>
 {editor&&<WorkspaceDialog title={editor.row?'编辑笔记':'新建笔记'} onClose={leave} closeDisabled={busy}><form onSubmit={e=>{e.preventDefault();void save()}}>
 <label>标题<input autoFocus required value={editor.title} onChange={e=>setEditor({...editor,title:e.target.value})}/></label><label>正文<textarea rows={10} required value={editor.body} onChange={e=>setEditor({...editor,body:e.target.value})}/></label>
 {problem&&<p role="alert">{problem}</p>}<footer><UiButton type="button" onClick={leave} disabled={busy}>取消</UiButton><UiButton type="submit" variant="primary" disabled={busy||!editor.title.trim()||!editor.body.trim()}>保存笔记</UiButton></footer></form></WorkspaceDialog>}
 {discard&&<WorkspaceDialog title="放弃未保存的修改？" onClose={()=>setDiscard(false)}><UiButton onClick={()=>setDiscard(false)}>继续编辑</UiButton><UiButton onClick={()=>{setEditor(null);setDiscard(false)}}>放弃修改</UiButton></WorkspaceDialog>}
 </section>;
}
