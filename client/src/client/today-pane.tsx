import {useEffect, useState} from 'react';
import {CalendarDays, CornerUpRight, Flag, MessageCircle, SlidersHorizontal} from 'lucide-react';
import {rpc, type BackendInfo} from './api';
import {UiButton, UiFeedback} from './ui-controls';
import './today-pane.css';

type Period = {time:string; focus:string; keywords?:string; frequency?:string};
type Preferences = {version:number; project:string; morning:Period; evening:Period};
type Source = {title:string; conversation:string; source:string; time?:number};
type Board = {
  preferences:Preferences; projects:{id:string; name:string}[];
  questions:{run:string; title:string; prompt:string; conversation:string}[];
  events:Source[]; reports:{slot:string; date:string; generated:number; rows:Source[]}[];
};
const slots = {morning:'早报', evening:'晚报'} as const;
const periods = ['morning','evening'] as const;
const formatTime = (seconds:number) => new Date(seconds*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});

export function TodayPane({info,onOpen,onProfiles}:{info:BackendInfo|null; onOpen:(id:string)=>Promise<void>; onProfiles:()=>void}) {
  const [board,setBoard]=useState<Board|null>(null);
  const [draft,setDraft]=useState<Preferences|null>(null);
  const [busy,setBusy]=useState(false);
  const [actionError,setActionError]=useState('');
  const [error,setError]=useState('');
  useEffect(()=>{
    if (!info || busy) return;
    let active=true;
    let timer:number;
    async function load() {
      try {
        const value=await rpc<Board>(info!, 'today_board', {}, {timeoutMs:12000});
        if(active){setBoard(value);setError('');}
      } catch(e) {if(active)setError(String(e));}
      if(active) timer=window.setTimeout(load,3000);
    }
    void load();
    return ()=>{active=false;window.clearTimeout(timer);};
  },[info,busy]);
  async function save(){
    if(!info || !draft) return;
    setBusy(true);setActionError('');
    try {
      setBoard(await rpc<Board>(info,'today_board',{preferences:draft}));
      setDraft(null); setError('');
    } catch(e){setActionError(String(e));}
    finally{setBusy(false);}
  }
  function open(id:string){void onOpen(id).catch(e=>setActionError(String(e)));}
  function sourceRow(row:Source,index:number){
    return <button className="today-source" key={row.source+index} onClick={()=>open(row.conversation)}>
      {row.time&&<small>{formatTime(row.time)}</small>}<span>{row.title}</span><CornerUpRight size={16}/></button>;
  }
  return <section className="today-pane">
    <header><time>{new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})}</time>
      <div><UiButton onClick={onProfiles}>个人资料</UiButton><UiButton disabled={!board} onClick={()=>setDraft(board!.preferences)}><SlidersHorizontal size={16}/>定制看板</UiButton></div></header>
    {(actionError||error)&&<p role="alert">{actionError||error}</p>}
    {!board&&<UiFeedback state={info?'loading':'unconfirmed'} title={info?'正在读取今日看板…':'等待本地助手连接'}/>}
    {draft&&<form onSubmit={event=>{event.preventDefault();void save();}}>
      <label>关注项目<select value={draft.project} onChange={e=>setDraft({...draft,project:e.target.value})}><option value="">选择项目</option>{board?.projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      {periods.map(slot=><fieldset key={slot}><legend>{slots[slot]}</legend>
        <label>周期<select value={draft[slot].frequency||'daily'} onChange={e=>setDraft({...draft,[slot]:{...draft[slot],frequency:e.target.value}})}><option value="daily">每天</option><option value="weekdays">工作日</option><option value="weekends">周末</option><option value="off">关闭</option></select></label>
        <label>生成时间<input type="time" required value={draft[slot].time} onChange={e=>setDraft({...draft,[slot]:{...draft[slot],time:e.target.value}})}/></label>
        <label>关注内容<select value={draft[slot].focus} onChange={e=>setDraft({...draft,[slot]:{...draft[slot],focus:e.target.value}})}><option value="questions">待答任务</option><option value="project">项目进展</option><option value="both">任务与项目</option></select></label>
        <label>关注词（选填）<input value={draft[slot].keywords||''} maxLength={120} placeholder="多个词用空格分开" onChange={e=>setDraft({...draft,[slot]:{...draft[slot],keywords:e.target.value}})}/></label>
      </fieldset>)}
      <small>新偏好用于下一份简报。</small><div><UiButton type="button" onClick={()=>setDraft(null)}>取消</UiButton><UiButton type="submit" disabled={busy}>保存</UiButton></div>
    </form>}
    {board&&<>
      <article className="today-questions"><h3><MessageCircle/>等你决定</h3>{board.questions.length?board.questions.map(q=><button className="today-source" key={q.run} onClick={()=>open(q.conversation)}><small>{q.title}</small><strong>{q.prompt}</strong><CornerUpRight size={16}/></button>):<p>当前没有待答任务。</p>}</article>
      <article className="today-timeline"><h3><Flag/>{board.projects.find(p=>p.id===board.preferences.project)?.name || '关注的项目'}</h3>{board.events.length?board.events.map(sourceRow):<p>{board.preferences.project?'这个项目还没有任务记录。':'在「定制看板」中选择要跟进的项目。'}</p>}</article>
      <article><h3><CalendarDays/>今日简报</h3>{board.reports.length?board.reports.map(r=><section key={r.slot}><h4>{r.slot==='morning'?'早报':'晚报'} <small>{formatTime(r.generated)}</small></h4>{r.rows.length?r.rows.map(sourceRow):<p>生成时没有符合偏好的记录。</p>}</section>):<p>{periods.map(slot=>slots[slot]+' '+(board.preferences[slot].frequency==='off'?'已关闭':board.preferences[slot].time)).join(' · ')}</p>}</article>
    </>}
  </section>;
}
