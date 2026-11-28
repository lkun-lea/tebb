import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import '../journal/buttons.js';
import '../journal/journal.js';
import '../journal/journal.css';
import '../journal/buttons.css';
import {rpc, type BackendInfo} from './api';
import {BriefPreferences,type Preferences} from './brief-preferences';
import {UiFeedback} from './ui-controls';
import {usePageActive} from './page-stack';
import './today-pane.css';

import type { ChoiceAnswer } from './clarification-state';
type JournalAction = {type:string; answers?:Record<string,ChoiceAnswer>; run?:string; version?:string; conversation?:string; text?:string};
type JournalView = {update:(data:unknown)=>void};
declare global { interface Window { TodayJournal:new(root:HTMLElement,action:(a:JournalAction)=>void)=>JournalView } }

type Source = {title:string; conversation:string; source:string; time?:number};
type Board = {
  preferences:Preferences; projects:{id:string; name:string}[];
  day:string; receipt:unknown; questions:{version:string; run:string; title:string; prompt:string; conversation:string}[];
  events:Source[]; reports:{slot:string; date:string; generated:number; rows:Source[]}[];
};
const slots = {morning:'早报', evening:'晚报'} as const;



type TodayProps = {info:BackendInfo|null; onOpen:(id:string,run?:string)=>Promise<void>; onProfiles?:()=>void; onChat?:()=>void};
export function TodayPane(props:TodayProps) {
  return <AccountJournal key={props.info?.token} {...props}/>;
}
function AccountJournal({info,onOpen,onProfiles,onChat}:TodayProps) {
  const [board,setBoard]=useState<Board|null>(null);
  const [draft,setDraft]=useState<Preferences|null>(null);
  const [busy,setBusy]=useState(false);
  const [actionError,setActionError]=useState('');
  const [error,setError]=useState('');
  const visible=usePageActive();
  useEffect(()=>{
    if (!visible || !info || busy) return;
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
  },[info,busy,visible]);
  async function save(){
    if(!info || !draft) return;
    setBusy(true);setActionError('');
    try {
      setBoard(await rpc<Board>(info,'today_board',{preferences:draft}));
      setDraft(null); setError('');
    } catch(e){setActionError(String(e));}
    finally{setBusy(false);}
  }
  const [solo,setSolo]=useState(false);
  const [selected,setSelected]=useState('');
  const container=useRef<HTMLDivElement>(null);
  const viewer=useRef<JournalView>();
  const handle=useRef<(a:JournalAction)=>void>(()=>{});
  handle.current=async a=>{
    if(a.type==='layout')return setSolo(value=>!value);
    if(a.type==='profiles')return onProfiles?.();
    if(a.type==='settings' && board){
      setActionError(''); setDraft(board.preferences); return;
    }
    if(a.type==='select')return setSelected(a.run || '');
    if(a.type==='chat' && onChat)return onChat();
    try {
      if((a.type==='answer'||a.type==='form-answer') && info){
        setBusy(true);
        const result=await rpc<{ok:boolean;error?:string}>(info,'collaboration_action',{action:a.type==='form-answer' ? {type:'clarification_answer',id:a.run,conversation:a.conversation,version:a.version,answers:a.answers,request_id:crypto.randomUUID()} : {
          type:'send',run:a.run,conversation:a.conversation,question_version:a.version,text:a.text,request_id:crypto.randomUUID()
        }});
        if(result.ok===false)throw Error(result.error || '原任务未接收');
        setBoard(await rpc<Board>(info,'today_board',{}));
      } else if(a.type==='source'||a.type==='chat')await onOpen(a.conversation || 'dm-tebb',a.run);
      setActionError('');
    }catch(e){setActionError(String(e));}finally{setBusy(false);}
  };
  useLayoutEffect(()=>{
    if(container.current)viewer.current=new window.TodayJournal(container.current,a=>handle.current(a));
    return ()=>{viewer.current=undefined};
  },[info]);
  useLayoutEffect(()=>{
    if(!board)return;
    const questions=[...board.questions].sort((a,b)=>Number(b.run===selected)-Number(a.run===selected));
    const sections=[...(board.events.length?[{title:'项目时间线',rows:board.events}]:[]),
      ...board.reports.map(report=>({title:slots[report.slot as keyof typeof slots],rows:report.rows}))];
    viewer.current?.update({...board,questions,sections,solo,busy,online:Boolean(info)&&!error,
      notice:actionError||error,settings:true,profiles:Boolean(onProfiles)});
  },[board,solo,busy,selected,info,actionError,error]);
  return <section className="journal-host">
    {!board&&<UiFeedback state={info?'loading':'unconfirmed'} title={error || (info?'正在读取今日手记…':'等待本地助手连接')}/>}
    <div ref={container} hidden={!board}/>
    {draft&&<BriefPreferences draft={draft} projects={board?.projects||[]} busy={busy} error={actionError}
      change={setDraft} cancel={()=>setDraft(null)} save={()=>void save()}/>}
  </section>;
}
