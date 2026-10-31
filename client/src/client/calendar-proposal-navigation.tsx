import{useEffect,useRef,useState}from'react';
import{invoke,isTauri}from'@tauri-apps/api/core';
import{emit,listen}from'@tauri-apps/api/event';
import{rpc,type BackendInfo}from'./api';
import{calendarProposal,type CalendarProposal}from'./calendar-proposal-state';
import{beijingDay,type CalendarEvent}from'./schedule-state';
import type{ScheduleTarget}from'./schedule';

const EVENT='tebb-open-calendar-proposal';
export type ProposalResult={ok:boolean;state:string;proposal?:CalendarProposal;event?:CalendarEvent;error?:string;notice?:string};
export async function openCalendarProposal(task_id:string,proposal_id:string){
  const detail={task_id,proposal_id};const event=new CustomEvent(EVENT,{detail,cancelable:true});window.dispatchEvent(event);
  if(event.defaultPrevented)return;
  if(!isTauri())throw Error('请在主工作台打开原任务中的日程提案。');
  await invoke('show_main');await emit(EVENT,detail);
}
export function CalendarProposalNavigation({info,onTarget}:{info:BackendInfo|null;onTarget:(target:ScheduleTarget)=>void}){
  const target=useRef(onTarget);target.current=onTarget;const[error,setError]=useState('');
  useEffect(()=>{
    if(!info)return;let active=true,off:(()=>void)|undefined;
    async function open(detail:{task_id?:unknown;proposal_id?:unknown}){
      try{
        if(typeof detail?.task_id!=='string'||typeof detail.proposal_id!=='string')throw Error('提案来源编号无效。');
        const result=await rpc<ProposalResult>(info!,'read_calendar_proposal',detail);
        if(!active)return;if(!result.ok)throw Error(result.error||'原保存结果待核对，请先读取原编号。');
        if(result.state==='proposed'&&result.proposal){const proposal=calendarProposal(result.proposal);target.current({day:beijingDay(proposal.start),proposal});}
        else if(result.state==='saved'&&result.event)target.current({day:beijingDay(result.event.start),calendar_id:result.event.calendar_id,event_id:result.event.event_id});
        else throw Error(result.notice||'此提案已使用，不会再次创建。');setError('');
      }catch(error){if(active)setError(String(error));}
    }
    const local=(event:Event)=>{event.preventDefault();void open((event as CustomEvent).detail);};window.addEventListener(EVENT,local);
    if(isTauri())void listen<{task_id:string;proposal_id:string}>(EVENT,event=>void open(event.payload)).then(stop=>{if(active)off=stop;else stop();});
    return()=>{active=false;window.removeEventListener(EVENT,local);off?.();};
  },[info?.port,info?.token]);
  return error?<aside role="alert" className="calendar-proposal-notice">{error}<button type="button" onClick={()=>setError('')}>关闭</button></aside>:null;
}
