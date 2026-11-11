import {accountStorage} from './account-storage';
import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import FullCalendar from '@fullcalendar/react';
import timeGridPlugin from '@fullcalendar/timegrid';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin, { type EventResizeDoneArg } from '@fullcalendar/interaction';
import luxonPlugin from '@fullcalendar/luxon3';
import zhLocale from '@fullcalendar/core/locales/zh-cn';
import type { EventDropArg, EventInput } from '@fullcalendar/core';
import { useUiReducedMotion } from './use-ui-reduced-motion';
import { DRAG_EASING, DRAG_SETTLE_MS } from './drag-motion';
import { rpc, type BackendInfo } from './api';
import { UiFeedback, UiStableText } from './ui-controls';
import { DateTimeField } from './datetime-field';
import { usePageActive } from './page-stack';
import { absoluteTime, addCalendarDays, beijingDay, beijingStamp, calendarKey, calendarWeekStart, eventHealth, eventTime,
  type CalendarEvent } from './schedule-state';
import { ScheduleWeekController, createCalendarDraft, dragTimeDraft, pointerTimeDraft, minutesInDay, overlappingEvents, timeEditable, validTimeDraft,
  type TimeDraft, type WeekTransport } from './schedule-week-state';
import type { ScheduleTarget } from './schedule';
import { LocalCalendarController, type SyncBatch } from './local-calendar-state';
import { CalendarEventEditor, type CalendarDraft } from './calendar-event-editor';
import { CalendarDragSurface, CalendarDragContent, type CalendarDragSource, type CalendarItem } from './calendar-drag';
import { CalendarItemSource } from './calendar-item-source';
import { CalendarSyncStatus, type SyncAction, type SyncGroup, type SyncItem } from './calendar-sync-status';
import { WorkspaceDialog } from './workspace-dialog';
import{calendarProposal}from'./calendar-proposal-state';
import type { DragStartEvent } from '@dnd-kit/core';
import './schedule-week.css';
import './calendar-interaction.css';

type Props={info:BackendInfo|null;debug?:boolean;transport?:WeekTransport;target:ScheduleTarget;revision?:number;
  onClose:()=>void;onReturn:(id:string)=>void;onDay:(target:ScheduleTarget)=>void;onChange:()=>void;view?:'month'|'week'|'day';onViewDay?:(day:string)=>void;closeLabel?:string;onNavigationGuard?:(guard:((next:()=>void)=>void)|null)=>void;extraActions?:ReactNode;viewTabs?:ReactNode};
type Form={key:string;start:string;end:string;summary:string};
type KeyboardDraft={event:CalendarEvent;draft:TimeDraft};
const calendarHelp='双击空白新建日程，单击日程查看详情；普通个人日程可长按拖动改期。';
const keyboardHelp='聚焦时间块后：空格抓取，方向键移动；Shift + 上下调整结束，Alt + 上下调整开始；Enter 保存，Escape 取消。';
const sameDraft=(event:CalendarEvent,draft:TimeDraft)=>Date.parse(event.start)===Date.parse(draft.start)&&Date.parse(event.end)===Date.parse(draft.end)&&(draft.summary===undefined||draft.summary===event.summary);
// ISO 周序号用于周期标题，不依赖服务端返回值。
function isoWeek(day:string){
  const date=new Date(day+'T00:00:00Z');
  const target=new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth(),date.getUTCDate()));
  const weekday=(target.getUTCDay()+6)%7;
  target.setUTCDate(target.getUTCDate()-weekday+3);
  const first=new Date(Date.UTC(target.getUTCFullYear(),0,4));
  first.setUTCDate(first.getUTCDate()-((first.getUTCDay()+6)%7)+3);
  return 1+Math.round((target.getTime()-first.getTime())/604800000);
}
const safeDay=(event:CalendarEvent,fallback:string)=>{try{return event.start.includes('T')?beijingDay(event.start):event.start||fallback;}catch{return fallback;}};
function scrollHost(node:HTMLElement):HTMLElement{
  for(let parent:HTMLElement|null=node;parent;parent=parent.parentElement){
    if(/auto|scroll/.test(getComputedStyle(parent).overflowY)&&parent.scrollHeight>parent.clientHeight+1)return parent;
  }
  return (document.scrollingElement||document.documentElement) as HTMLElement;
}
function annotateEvent(element:HTMLElement,source:CalendarEvent,phase=''){
  const reason=phase||(timeEditable(source)?'长按拖动；空格开始键盘调整，方向键移动，Enter保存，Escape取消。':source.edit_reason||'正在核对编辑资格');
  element.setAttribute('aria-label',`${source.summary}，${eventTime(source)}。${reason}`);
  element.title=source.summary+'\n'+eventTime(source)+'\n'+reason;
}

export function ScheduleWeekPane({info,debug=false,transport,target,revision,onClose,onReturn,onDay,onChange,view='week',closeLabel='返回工作看板',onViewDay,onNavigationGuard,extraActions,viewTabs}:Props){
  const active=usePageActive(),reduce=useUiReducedMotion();
  const lastBlankClick=useRef<{start:string;at:number}|null>(null),blankDoubleTimer=useRef<number|undefined>();
  const root=useRef<HTMLElement|null>(null),calendar=useRef<FullCalendar|null>(null),details=useRef<HTMLElement|null>(null);
  const draftRoot=useRef<HTMLDivElement|null>(null);
  const [day,setDay]=useState(target.day||beijingDay()),[paneWidth,setPaneWidth]=useState(Number.POSITIVE_INFINITY);
  const narrow=paneWidth<680;
  const [selected,setSelected]=useState(target.event_id&&target.calendar_id?calendarKey(target as {calendar_id:string;event_id:string}):'');
  const [form,setForm]=useState<Form|null>(null),[picker,setPicker]=useState<'start'|'end'|null>(null),[formError,setFormError]=useState('');
  const [leave,setLeave]=useState<null|(()=>void)>(null),[keyboard,setKeyboard]=useState<KeyboardDraft|null>(null),[announcement,setAnnouncement]=useState('');
  // 快捷键说明在「更多」菜单内就地展开/收起，复用现有菜单，不另开弹出层
  const [keyboardHelpOpen,setKeyboardHelpOpen]=useState(false);
  const [pointerCancelled,setPointerCancelled]=useState(false),[locateCount,setLocateCount]=useState(0);
  const [detailsOpen,setDetailsOpen]=useState(!!target.event_id),[draft,setDraft]=useState<CalendarDraft|null>(null),[draftError,setDraftError]=useState('');
  const [bulk,setBulk]=useState(false),[batchChoice,setBatchChoice]=useState<SyncBatch|null>(null),[resolveId,setResolveId]=useState('');
  const [bulkPreview,setBulkPreview]=useState<CalendarEvent[]>([]);
  const [syncHint,setSyncHint]=useState('');
  const [syncOpen,setSyncOpen]=useState(false),[periodOpen,setPeriodOpen]=useState(false);
  const moreMenu=useRef<HTMLDetailsElement|null>(null);
  const [popover,setPopover]=useState<{left:number;top:number;maxHeight?:number}>({left:12,top:150});
  const dragElement=useRef<HTMLElement|null>(null);
  const dragPointer=useRef<{x:number;y:number}|null>(null),grabOffset=useRef(0);
  const draggedRange=useRef<TimeDraft|null>(null);
  const cancelPointer=useRef(false),pointerActive=useRef(false),keyboardRef=useRef(keyboard);keyboardRef.current=keyboard;
  const pointerGeneration=useRef(0);
  const locateInitial=useRef(!!target.event_id),changes=useRef(onChange);changes.current=onChange;
  const [version,redraw]=useReducer(value=>value+1,0);
  const wire=useMemo(()=>transport||((method:string,args:Record<string,unknown>)=>{
    if(!info)throw Error('后端尚未连接。');return rpc(info,method,args,{timeoutMs:120000});
  }),[transport,info?.port,info?.token]);
  const controller=useMemo(()=>new ScheduleWeekController(wire,target.day||beijingDay(),typeof window!=='undefined'?accountStorage(window.localStorage):undefined),[wire]);
  const local=useMemo(()=>new LocalCalendarController(wire,typeof window!=='undefined'?accountStorage(window.localStorage):undefined),[wire]);
  const monday=calendarWeekStart(day);
  const viewStart=view==='week'?monday:view==='month'?day.slice(0,7)+'-01':day;
  useEffect(()=>{lastBlankClick.current=null;return()=>{if(blankDoubleTimer.current!==undefined)window.clearTimeout(blankDoubleTimer.current);};},[view,day]);
  const event=controller.event(selected),owner=controller.page.links.find(link=>calendarKey(link.event)===selected);
  const item=controller.page.items.find(i=>i.id===owner?.item_id);
  const busy=controller.pending.has(selected),blocked=controller.blocked(selected),checking=controller.checking.has(selected);
  const initialForm=event&&event.start.includes('T')&&Number.isFinite(Date.parse(event.start))&&Number.isFinite(Date.parse(event.end))?{key:selected,start:beijingStamp(event.start),end:beijingStamp(event.end),summary:event.summary}:null;
  const dirty=!!draft?.existing&&(!!draft.summary.trim()||!!draft.item_id||draft.sync)||!!form&&!!initialForm&&(form.start!==initialForm.start||form.end!==initialForm.end||form.key!==initialForm.key||form.summary!==initialForm.summary);
  const itemDraftBlocked=!!draft||!!form||!!keyboard||local.busy||!!local.unknown||controller.pending.size>0||controller.unknown.size>0;
  useEffect(()=>{onNavigationGuard?.(guard);return()=>onNavigationGuard?.(null);},[onNavigationGuard,dirty,form,selected,draft,local.busy,local.unknown]);
  useEffect(()=>{if(!active)return;const before=(event:Event)=>{if(dirty||local.unknown&&draft){event.preventDefault();guard((event as CustomEvent<{navigate:()=>void}>).detail.navigate);}};window.addEventListener?.('tebb-before-navigate',before);return()=>window.removeEventListener?.('tebb-before-navigate',before);},[active,dirty,form,selected,draft,local.unknown,local.busy]);
  useEffect(()=>controller.subscribe(redraw),[controller]);
  useEffect(()=>local.subscribe(redraw),[local]);
  // 点击菜单外部时收起「更多」；菜单内按钮由点击代理统一关闭。
  useEffect(()=>{const close=(event:PointerEvent)=>{if(moreMenu.current?.open&&!moreMenu.current.contains(event.target as Node)){moreMenu.current.open=false;setKeyboardHelpOpen(false);}};document.addEventListener('pointerdown',close,true);return()=>document.removeEventListener('pointerdown',close,true);},[]);
  useEffect(()=>{if(!active)return;void(async()=>{if(await local.read()){const hint=local.syncNotice();if(hint)setSyncHint(hint);}})();},[active,local,revision]);
  useEffect(()=>{if(target.create)beginDraft((target.day||beijingDay())+'T09:00:00+08:00');},[target.create,target.item_id,target.day]);
  useEffect(()=>{if(!target.proposal)return;try{
    const proposal=calendarProposal(target.proposal);if(draft?.proposal?.id===proposal.id)return;
    guard(()=>{setDetailsOpen(false);setForm(null);setDraftError('');setDay(beijingDay(proposal.start));setDraft(createCalendarDraft(proposal.start,proposal.end,{id:proposal.id,summary:proposal.summary,item_id:proposal.item_id,proposal}));});
  }catch(error){setDraftError(String(error));}},[target]);
  useEffect(()=>{if(!active)return;controller.setPeriod(view==='month'?'month':'week');void controller.read(day);},[active,controller,monday,view,day.slice(0,7)]);
  useEffect(()=>{if(active&&revision!==undefined)void controller.read(day);},[active,controller,revision]);
  useEffect(()=>{if(!root.current||typeof ResizeObserver==='undefined')return;const observer=new ResizeObserver(entries=>setPaneWidth(entries[0].contentRect.width));observer.observe(root.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{calendar.current?.getApi().changeView(view==='month'?'dayGridMonth':view==='day'?'timeGridDay':'timeGridWeek',viewStart);},[viewStart,view]);
  useEffect(()=>{root.current?.querySelectorAll<HTMLElement>('[data-week-event]').forEach(element=>{
    const key=element.dataset.weekEvent||'',source=controller.event(key),pending=controller.pending.get(key);
    if(source)annotateEvent(element,pending?.start&&pending.end?{...source,start:pending.start,end:pending.end}:source,
      pending?'时间保存中，完成后可继续拖动。':controller.blocked(key)?'结果待核对，请先读取原回执。':'');
    element.setAttribute('aria-busy',String(!!pending));
  });},[controller,version,day,narrow]);
  useEffect(()=>{if(!active)return;calendar.current?.getApi().updateSize();},[active,narrow]);
  useEffect(()=>{if(!selected&&target.event_id&&controller.page.events.length){const first=controller.page.events.find(e=>e.event_id===target.event_id);if(first)setSelected(calendarKey(first));}},[selected,controller.page.events,target.event_id]);
  useEffect(()=>{
    if(!active||!selected)return;
    const source=controller.event(selected)||((target.calendar_id&&target.event_id)?{calendar_id:target.calendar_id,event_id:target.event_id}:null);
    if(!source)return;let live=true;
    void controller.inspect(source).then(()=>{const current=controller.event(selected);if(live&&current&&locateInitial.current){locateInitial.current=false;setDay(safeDay(current,day));setLocateCount(n=>n+1);}});
    return()=>{live=false;};
  },[active,controller,selected]);
  // One explicit locate request gets one scroll. Saving a drag must not replay an old request.
  useEffect(()=>{if(!locateCount)return;const id=window.requestAnimationFrame?.(()=>{const element=[...(root.current?.querySelectorAll<HTMLElement>('[data-week-event]')||[])].find(node=>node.dataset.weekEvent===selected);element?.scrollIntoView?.({block:'nearest',behavior:reduce?'instant':'smooth'});element?.focus({preventScroll:true});});return()=>{if(id!==undefined)window.cancelAnimationFrame?.(id);};},[locateCount]);
  useEffect(()=>{if(!draft)return;const previous=document.activeElement as HTMLElement|null;
    // Desktop editors are already placed inside the viewport by positionPopover.
    if(narrow)draftRoot.current?.scrollIntoView?.({block:'nearest',behavior:reduce?'instant':'smooth'});
    draftRoot.current?.querySelector<HTMLElement>('input')?.focus({preventScroll:true});
    return()=>{if(previous?.isConnected)previous.focus({preventScroll:true});};},[!!draft,narrow,reduce]);
  useEffect(()=>{if(!leave)return;const previous=document.activeElement as HTMLElement|null;root.current?.querySelector<HTMLElement>('[role=alertdialog] button')?.focus();return()=>{if(previous?.isConnected)previous.focus();};},[!!leave]);
  useEffect(()=>{
    if(!active)return;
    // FullCalendar's pointer capture can leave focus outside the calendar root.
    const cancel=(e:globalThis.KeyboardEvent)=>{if(e.key==='Escape'&&pointerActive.current){
      cancelPointer.current=true;setPointerCancelled(true);setAnnouncement('已取消拖动，未发送修改。');e.preventDefault();
    }};
    const interrupted=()=>{if(pointerActive.current){cancelPointer.current=true;setPointerCancelled(true);setAnnouncement('拖动已中断，未发送修改。');}};
    document.addEventListener?.('keydown',cancel,true);document.addEventListener?.('pointercancel',interrupted,true);window.addEventListener?.('blur',interrupted);
    return()=>{document.removeEventListener?.('keydown',cancel,true);document.removeEventListener?.('pointercancel',interrupted,true);window.removeEventListener?.('blur',interrupted);};
  },[active]);
  useEffect(()=>{if(!active)return;const move=(e:PointerEvent)=>{if(pointerActive.current)dragPointer.current={x:e.clientX,y:e.clientY};};document.addEventListener?.('pointermove',move,true);return()=>document.removeEventListener?.('pointermove',move,true);},[active]);
  function guard(next:()=>void){if(local.busy)return;if(local.unknown&&draft){setDraftError('保存结果尚未确认，请先读取原编号核对，不能当作未保存草稿丢弃。');return;}if(dirty)setLeave(()=>next);else {lastBlankClick.current=null;if(keyboardRef.current)controller.endInteraction();setForm(null);setPicker(null);setKeyboard(null);setDraft(null);next();}}
  function choose(key:string){if(key!==selected)guard(()=>{setSelected(key);setFormError('');});}
  function focusDetails(){details.current?.scrollIntoView?.({block:'nearest',behavior:reduce?'instant':'smooth'});details.current?.querySelector<HTMLElement>('button,input')?.focus();}
  function locate(source:CalendarEvent){guard(()=>{setSelected(calendarKey(source));setDay(safeDay(source,day));setLocateCount(n=>n+1);});}
  // 从同步浮层跳转时同时展开详情，保持与原「定位日程」一致的落点。
  function openEvent(source:CalendarEvent){setSyncOpen(false);guard(()=>{setSelected(calendarKey(source));setDetailsOpen(true);setDay(safeDay(source,day));setLocateCount(n=>n+1);});}
  function openBulk(){setSyncOpen(false);guard(()=>{setSyncHint('');void local.read().then(ok=>{if(ok){local.batch=null;setBatchChoice(null);setBulkPreview(local.page.events.filter(event=>event.sync_state==='local'));setBulk(true);}});});}
  async function apply(source:CalendarEvent,draft:TimeDraft){
    const invalid=validTimeDraft(source,draft);if(invalid){setAnnouncement(invalid+' 未保存。');return false;}
    if(sameDraft(source,draft)){setAnnouncement('时间未变化，未发送修改。');return true;}
    const overlaps=overlappingEvents(controller.page.events,source,draft);
    setAnnouncement((overlaps.length?`与已读的 ${overlaps.length} 场日程重叠；`:'')+'正在保存时间。');
    const ok=await controller.retime(source,draft);if(ok)changes.current();
    if(ok){setForm(null);setPicker(null);setDay(beijingDay(draft.start));setAnnouncement(overlaps.length?`已保存；与已读的 ${overlaps.length} 场日程重叠，未阻止安排。`:'时间已保存。');}
    else setAnnouncement('本轮未完整确认，请按页面实际阶段读取核对。');
    return ok;
  }
  function changed(arg:EventDropArg|EventResizeDoneArg){
    if(cancelPointer.current){arg.revert();return;}
    const source=arg.oldEvent.extendedProps.source as CalendarEvent;
    if(!arg.event.start||!arg.event.end||arg.event.allDay){arg.revert();return;}
    const draft=pointerTimeDraft(source,{start:arg.event.start.toISOString(),end:arg.event.end.toISOString()});
    if(validTimeDraft(source,draft)){arg.revert();setAnnouncement('此位置不符合时间规则，未保存。');return;}
    if(source.calendar_id==='tebb-draft'){setDraft(previous=>previous?{...previous,start:beijingStamp(draft.start),end:beijingStamp(draft.end)}:previous);pulse();return;}
    void apply(source,draft);
  }
  function startPointer(){pointerGeneration.current++;controller.beginInteraction();cancelPointer.current=false;pointerActive.current=true;setPointerCancelled(false);setKeyboard(null);}
  function stopPointer(){const generation=pointerGeneration.current;controller.endInteraction();draggedRange.current=null;window.setTimeout(()=>{if(generation!==pointerGeneration.current)return;pointerActive.current=false;cancelPointer.current=false;setPointerCancelled(false);},0);}
  function keyboardMove(e:KeyboardEvent<HTMLElement>){
    if(e.key==='Escape'){
      if(pointerActive.current){cancelPointer.current=true;setPointerCancelled(true);setAnnouncement('已取消拖动，未发送修改。');e.preventDefault();
        // Custom dnd-kit gestures must receive Escape at their document listener.
        if(!draggedRange.current)e.stopPropagation();return;}
      if(keyboardRef.current){controller.endInteraction();setKeyboard(null);setAnnouncement('已取消键盘调整，未发送修改。');e.preventDefault();e.stopPropagation();return;}
      if(picker){setPicker(null);e.stopPropagation();return;}
      if(draft||detailsOpen){guard(()=>{setDraft(null);setDetailsOpen(false);});e.preventDefault();e.stopPropagation();return;}
    }
    const node=(e.target as HTMLElement).closest<HTMLElement>('[data-week-event]');
    if(!node)return;const source=controller.event(node.dataset.weekEvent||'');if(!source)return;
    if(e.key===' '||e.key==='Enter'){
      if(view==='month'){e.preventDefault();clickEvent(calendarKey(source));return;}
      e.preventDefault();e.stopPropagation();
      const draft=keyboardRef.current;
      if(draft){controller.endInteraction();setKeyboard(null);void apply(draft.event,draft.draft);}
      else if(timeEditable(source)&&!controller.blocked(calendarKey(source))&&!controller.checking.has(calendarKey(source))&&!dirty){controller.beginInteraction();setSelected(calendarKey(source));setKeyboard({event:source,draft:{start:source.start,end:source.end}});setAnnouncement('已抓取。方向键移动，Shift或Alt加上下键调整边缘，Enter保存，Escape取消。');}
      else {choose(calendarKey(source));void controller.inspect(source);focusDetails();}
      return;
    }
    const current=keyboardRef.current;
    if(current&&['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)){
      e.preventDefault();e.stopPropagation();
      const mode=e.altKey?'start':e.shiftKey?'end':'move';
      const draft=dragTimeDraft({...current.event,...current.draft},mode,e.key==='ArrowUp'?-15:e.key==='ArrowDown'?15:0,e.key==='ArrowLeft'?-1:e.key==='ArrowRight'?1:0);
      if(beijingDay(draft.start)<monday||beijingDay(draft.start)>=addCalendarDays(monday,7)){setAnnouncement('跨周调整请使用日期表单。');return;}
      setKeyboard({...current,draft});setDay(beijingDay(draft.start));setAnnouncement(validTimeDraft(current.event,draft)||`预览 ${beijingStamp(draft.start)} → ${beijingStamp(draft.end)}`);
    }
  }
  const visible=useMemo(()=>controller.page.events.map(row=>controller.event(calendarKey(row))||row),[controller,version]);
  const unknownDate=visible.filter(row=>!row.start||!Number.isFinite(Date.parse(row.start)));
  const baseEvents=useMemo<EventInput[]>(()=>visible.filter(row=>!unknownDate.includes(row)).map(source=>{
    const key=calendarKey(source),pending=controller.unknown.get(key),preview=keyboard?.event&&calendarKey(keyboard.event)===key?keyboard.draft:null;
    const timed=source.start.includes('T');
    const shown=preview||(pending?.start&&pending.end?{start:pending.start,end:pending.end}:source);
    const editable=view!=='month'&&timeEditable(source)&&!controller.blocked(key)&&!controller.checking.has(key)&&!dirty&&!keyboard;
    return {id:key,title:source.summary,start:shown.start,end:timed?shown.end:(source.end>source.start?source.end:undefined),allDay:!timed,
      editable,startEditable:false,durationEditable:editable,
      classNames:[key===selected?'sw-selected':'',timeEditable(source)?'':'sw-readonly',controller.pending.has(key)?'sw-pending':'',pending&&!controller.pending.has(key)?'sw-unknown':'',preview?'sw-preview':''],
      extendedProps:{source,linked:controller.page.links.some(l=>calendarKey(l.event)===key),pending:controller.pending.has(key),unknown:!!pending&&!controller.pending.has(key)}};
  }),[visible,selected,keyboard,dirty,controller,version,view]);
  async function saveForm(){if(!form||!event||form.key!==selected)return false;try{setFormError('');
    return await apply(event,{start:form.start===beijingStamp(event.start)?event.start:absoluteTime(form.start),end:form.end===beijingStamp(event.end)?event.end:absoluteTime(form.end),summary:form.summary});
  }catch(error){setFormError(String(error));return false;}}
  function field(which:'start'|'end'|'summary',value:string){if(initialForm)setForm({...initialForm,...form,[which]:value});}
  const draftEvent=useMemo<CalendarEvent|null>(()=>{try{return draft&&{
    calendar_id:'tebb-draft',event_id:draft.id,summary:draft.summary||'新日程',start:absoluteTime(draft.start),end:absoluteTime(draft.end),
    status:'confirmed',eligible:true,reason:'',verification:'confirmed',error:'',checked_at:new Date().toISOString(),editable:true,
    sync_state:'local' as const,edit_checked_at:new Date().toISOString()};}catch{return null;}},[draft]);
  function pulse(){if(reduce)return;window.requestAnimationFrame?.(()=>{root.current?.querySelector<HTMLElement>('.sw-draft')?.animate?.([{transform:'translateY(0)'},{transform:'translateY(-4px)'},{transform:'translateY(0)'}],{duration:260,easing:'ease-out'});});}
  function beginDraft(start:string,end?:string,source?:CalendarItem){guard(()=>{setDetailsOpen(false);setForm(null);setDraftError('');
    setDraft(createCalendarDraft(start,end,{summary:source?.title||'',item_id:source?source.id:target.item_id||''}));pulse();});}
  function arrangeItem(source:CalendarItem){
    if(itemDraftBlocked||source.archived)return;
    beginDraft(day+'T09:00:00+08:00',undefined,source);
    setAnnouncement(`已为“${source.title}”打开草稿，保存后才会创建日程。`);
  }
  function doubleBlank(event:MouseEvent<HTMLElement>){
    const node=event.target as HTMLElement,at=event.timeStamp;
    if(event.button!==0||!node.closest('.sw-calendar')||node.closest('.fc-event, .fc-col-header-cell, .fc-daygrid-day-number')||!node.closest('.fc-timegrid-slot-lane, .fc-timegrid-col, .fc-daygrid-day'))return;
    event.preventDefault();
    if(blankDoubleTimer.current!==undefined)window.clearTimeout(blankDoubleTimer.current);
    // FullCalendar defers dateClick after mouseup; let its hit calculation settle first.
    blankDoubleTimer.current=window.setTimeout(()=>{
      blankDoubleTimer.current=undefined;const hit=lastBlankClick.current;
      if(!hit||at-hit.at<0||at-hit.at>1000||pointerActive.current||keyboardRef.current)return;
      lastBlankClick.current=null;
      if(draft&&!draft.existing)setDraftFields({...draft,start:beijingStamp(hit.start),end:beijingStamp(new Date(Date.parse(hit.start)+Date.parse(absoluteTime(draft.end))-Date.parse(absoluteTime(draft.start))).toISOString())});
      else beginDraft(hit.start);
    },0);
  }
  function setDraftFields(next:CalendarDraft){setDraft(next);setDraftError('');if(next.start!==draft?.start||next.end!==draft?.end)pulse();}
  async function saveDraft(){if(!draft||local.busy)return false;setDraftError('');
    try{if(!draft.summary.trim())throw Error('请填写日程标题。');const start=absoluteTime(draft.start),end=absoluteTime(draft.end);
      const existing=draft.existing;let current=existing;
      if(existing?.remote&&(Date.parse(start)!==Date.parse(existing.start)||Date.parse(end)!==Date.parse(existing.end)||draft.summary!==existing.summary)){
        if(!await apply(existing,{start,end,summary:draft.summary}))return false;await local.read();current=local.page.events.find(e=>e.local_id===existing.local_id)||existing;
      }
      const result=await local.change({type:current?'update':'create',local_id:current?.local_id||draft.id,version:current?.local_version,
        summary:draft.summary,start:current?.remote?current.start:start,end:current?.remote?current.end:end,item_id:draft.item_id},!current?draft.proposal?.save_request_id:undefined);
      if(!result.ok||!result.event){setDraftError(result.error||'本地保存未完整确认，请先读取核对。');return false;}
      current=result.event;setDraft(previous=>previous?{...previous,existing:current}:previous);
      if(draft.sync&&current.sync_state!=='synced'){
        const synced=await local.change({type:'sync',local_id:current.local_id,version:current.local_version});
        if(!synced.ok){setDraftError('本地日程已保存；'+(synced.error||'飞书同步结果待核对。'));changes.current();await controller.read(day);return false;}
      }
      setDraft(null);setDraftError('');setDay(beijingDay(start));changes.current();await controller.read(beijingDay(start));
      setAnnouncement(draft.sync?'日程已保存，飞书同步已确认。':'日程已保存到本地，飞书未改动。');return true;
    }catch(error){setDraftError(String(error));return false;}
  }
  useEffect(()=>{if(draft&&!draft.existing&&!local.busy){const saved=local.page.events.find(e=>e.local_id===draft.id);if(saved)setDraft(previous=>previous?{...previous,existing:saved}:previous);}},[local.page,draft?.id,local.busy]);
  function editLocal(source:CalendarEvent){guard(()=>{setDetailsOpen(false);setForm(null);setDraftError('');setDraft({id:source.local_id!,existing:source,
    summary:source.summary,start:beijingStamp(source.start),end:beijingStamp(source.end),item_id:owner?.item_id||'',sync:source.sync_state==='synced'});});}
  function clickEvent(key:string){if(key==='tebb-draft/'+draft?.id){guard(()=>setDraft(null));return;}
    guard(()=>{setSelected(key);setDetailsOpen(previous=>key===selected?!previous:true);setFormError('');});}
  function positionPopover(){if(!root.current||narrow||!detailsOpen&&!draft)return;const key=draft?draft.existing?calendarKey(draft.existing):'tebb-draft/'+draft.id:selected;
    const node=[...root.current.querySelectorAll<HTMLElement>('[data-week-event]')].find(el=>el.dataset.weekEvent===key);
    const calendarNode=root.current.querySelector<HTMLElement>('.sw-calendar'),panel=root.current.querySelector<HTMLElement>('.sw-event-editor,.sw-details');if(!calendarNode||!panel)return;
    const base=root.current.getBoundingClientRect(),rect=(node||calendarNode).getBoundingClientRect(),width=Math.min(330,base.width-24);
    const viewport=scrollHost(calendarNode).getBoundingClientRect();
    const visibleTop=Math.max(base.top,viewport.top,0)+12,visibleBottom=Math.min(base.bottom,viewport.bottom,window.innerHeight)-12;
    const maxHeight=Math.max(120,visibleBottom-visibleTop),height=Math.min(panel.offsetHeight,maxHeight);
    const left=rect.right-base.left+12+width<=base.width?rect.right-base.left+12:rect.left-base.left-width-12;
    const next={left:Math.max(12,Math.min(base.width-width-12,left)),top:Math.max(visibleTop-base.top,Math.min(rect.top-base.top,visibleBottom-base.top-height)),maxHeight};
    setPopover(old=>old.left===next.left&&old.top===next.top&&old.maxHeight===next.maxHeight?old:next);
  }
  useLayoutEffect(()=>positionPopover(),[selected,detailsOpen,draft,version,narrow]);
  useEffect(()=>{const node=root.current;if(!node)return;node.addEventListener('scroll',positionPopover,true);window.addEventListener?.('resize',positionPopover);return()=>{node.removeEventListener('scroll',positionPopover,true);window.removeEventListener?.('resize',positionPopover);};},[selected,detailsOpen,draft,narrow]);
  function projectedDrag(source:Pick<CalendarEvent,'start'|'end'>,delta:{x:number;y:number}):TimeDraft|null{
    const rows=[...(root.current?.querySelectorAll<HTMLElement>('.fc-timegrid-slots .fc-timegrid-slot-lane[data-time]')||[])];
    const hour=rows.length>1?(rows[1].getBoundingClientRect().top-rows[0].getBoundingClientRect().top)*2:50;
    const sourceRect=dragElement.current?.getBoundingClientRect();const x=dragPointer.current?.x??((sourceRect?.left||0)+(sourceRect?.width||0)/2+delta.x);
    const calendarBounds=root.current?.querySelector<HTMLElement>('.sw-calendar')?.getBoundingClientRect();
    if(calendarBounds&&(x<Math.max(0,calendarBounds.left)||x>=Math.min(window.innerWidth,calendarBounds.right)))return null;
    const col=[...(root.current?.querySelectorAll<HTMLElement>('.fc-timegrid-col[data-date]')||[])].find(el=>{const rect=el.getBoundingClientRect();return x>=rect.left&&x<rect.right;});
    const viewport=root.current?scrollHost(root.current).getBoundingClientRect():null;
    if(!col)return null;const bounds=col.getBoundingClientRect();
    if(dragPointer.current&&viewport&&(dragPointer.current.y<Math.max(0,viewport.top,bounds.top)
      ||dragPointer.current.y>Math.min(window.innerHeight,viewport.bottom,bounds.bottom)))return null;
    const destination=col?.dataset.date||beijingDay(source.start),offset=Math.round((Date.parse(destination+'T00:00Z')-Date.parse(beijingDay(source.start)+'T00:00Z'))/86400000);
    if(col&&dragPointer.current){const minute=Math.round(((dragPointer.current.y-grabOffset.current-col.getBoundingClientRect().top)/(hour||50)*60+0)/15)*15;
      const start=Date.parse(destination+'T00:00:00+08:00')+minute*60000;return {start:new Date(start).toISOString(),end:new Date(start+Date.parse(source.end)-Date.parse(source.start)).toISOString()};}
    return dragTimeDraft(source,'move',Math.round(delta.y/(hour||50)*60/15)*15,offset);
  }
  function dragStart(source:CalendarDragSource,event:DragStartEvent){
    startPointer();
    const rows=root.current?.querySelectorAll<HTMLElement>(source.kind==='event'?'[data-week-event]':'[data-calendar-item]')||[];
    dragElement.current=[...rows].find(el=>source.kind==='event'?el.dataset.weekEvent===calendarKey(source.event):el.dataset.calendarItem===source.item.id)||null;
    const start=day+'T09:00:00+08:00';draggedRange.current=source.kind==='event'?source.event:{start,end:new Date(Date.parse(start)+3600000).toISOString()};
    const origin=event.activatorEvent as PointerEvent;dragPointer.current=Number.isFinite(origin.clientX)?{x:origin.clientX,y:origin.clientY}:null;
    grabOffset.current=source.kind==='event'&&dragPointer.current&&dragElement.current?dragPointer.current.y-dragElement.current.getBoundingClientRect().top:0;
    setAnnouncement(source.kind==='item'?'已拿起事项，放入时间轴后确认；保存前不会创建。':'已拿起日程，松手放下；Escape取消。');}
  function dragProjection(source:CalendarDragSource,delta:{x:number;y:number}){
    const range=source.kind==='event'?source.event:draggedRange.current;if(!range)return null;
    const time=projectedDrag(range,delta);if(!time||validTimeDraft(range,time))return null;
    const col=root.current?.querySelector<HTMLElement>(`.fc-timegrid-col[data-date="${beijingDay(time.start)}"]`),slot=root.current?.querySelector<HTMLElement>('.fc-timegrid-slot-lane[data-time]');
    if(!col||!slot)return null;const rect=col.getBoundingClientRect(),half=slot.getBoundingClientRect().height;
    return {time,style:{position:'fixed' as const,left:rect.left+3,top:rect.top+(minutesInDay(time.start)-0)/30*half,width:rect.width-7,height:(Date.parse(time.end)-Date.parse(time.start))/1800000*half}};
  }
  function dragCommit(source:CalendarDragSource,next:TimeDraft|null){if(cancelPointer.current)return;
    if(!next){setAnnouncement(source.kind==='item'?'请选择当日可容纳一小时的时间轴位置，未创建草稿。':'无效落点，已取消拖动。');return;}
    if(source.kind==='item'){
      const current=controller.page.items.find(item=>item.id===source.item.id&&!item.archived);
      if(!draggedRange.current||validTimeDraft(draggedRange.current,next)){setAnnouncement('此位置不符合当日时间规则，未创建草稿。');return;}
      if(view==='month'||itemDraftBlocked||!current){setAnnouncement('事项或编辑状态已变化，未创建草稿。');return;}
      beginDraft(next.start,next.end,current);setAnnouncement(`已为“${current.title}”打开草稿，保存后才会创建日程。`);return;
    }
    const event=source.event;
    if(event.calendar_id==='tebb-draft'){if(validTimeDraft(event,next)){setAnnouncement('此位置不符合时间规则，草稿未移动。');return;}setDraft(previous=>previous?{...previous,start:beijingStamp(next.start),end:beijingStamp(next.end)}:previous);pulse();return;}
    void apply(event,next);}
  async function resolveSync(operationId:string,localId:string,resolution:'link'|'absent'){
    if(resolution==='absent'&&!window.confirm('已核对原飞书身份，并确认没有创建出有效日程？不会自动重发。'))return;
    await local.change({type:'resolve_sync',local_id:localId,operation_id:operationId,resolution,confirmed:resolution==='absent',event_id:resolveId});
    changes.current();await controller.read(day,true);
  }
  const events=useMemo<EventInput[]>(()=>draftEvent&&!draft?.existing?[...baseEvents,{id:calendarKey(draftEvent),title:draftEvent.summary,start:draftEvent.start,end:draftEvent.end,
    editable:true,startEditable:false,durationEditable:true,classNames:['sw-draft'],extendedProps:{source:draftEvent}}]:baseEvents,[baseEvents,draftEvent,draft?.existing]);
  const calendarView=useMemo(()=><FullCalendar ref={calendar} plugins={[timeGridPlugin,dayGridPlugin,interactionPlugin,luxonPlugin]} locale={zhLocale} timeZone="Asia/Shanghai"
      firstDay={1} initialView={view==='month'?'dayGridMonth':view==='day'?'timeGridDay':'timeGridWeek'} initialDate={day} headerToolbar={false} height="auto" stickyHeaderDates={false} allDaySlot allDayText="全天"
      slotMinTime="00:00:00" slotMaxTime="24:00:00" slotDuration="00:30:00" snapDuration="00:15:00"
      slotLabelInterval="01:00:00" slotLabelFormat={{hour:'2-digit',minute:'2-digit',hour12:false}} eventTimeFormat={{hour:'2-digit',minute:'2-digit',hour12:false}}
      fixedWeekCount={false} dayMaxEvents={3} moreLinkClick="popover" navLinks={view==='month'} navLinkDayClick={date=>guard(()=>onViewDay?.(beijingDay(date.toISOString())))}
      dayHeaderFormat={view==='month'?{weekday:'long'}:{weekday:'short',month:'numeric',day:'numeric'}} events={events} editable={view!=='month'} eventResizableFromStart eventOverlap slotEventOverlap={false}
      eventDragMinDistance={6} dragRevertDuration={reduce?0:DRAG_SETTLE_MS} dragScroll={!reduce} nowIndicator eventMinHeight={18} eventShortHeight={44} eventLongPressDelay={250}
      eventAllow={(drop,dragged)=>{const source=dragged?.extendedProps?.source as CalendarEvent|undefined;return view!=='month'&&!!source&&!cancelPointer.current&&!drop.allDay&&(source.calendar_id==='tebb-draft'||timeEditable(source))&&!controller.blocked(calendarKey(source))&&(!dirty||source.calendar_id==='tebb-draft')
        &&!validTimeDraft(source,pointerTimeDraft(source,{start:drop.start.toISOString(),end:drop.end.toISOString()}));}}
      eventDragStart={startPointer} eventResizeStart={startPointer} eventDragStop={stopPointer} eventResizeStop={stopPointer} eventDrop={changed} eventResize={changed}
      eventClick={arg=>{lastBlankClick.current=null;arg.jsEvent.preventDefault();clickEvent(arg.event.id);}} dateClick={arg=>{
        if(arg.allDay&&view!=='month'){lastBlankClick.current=null;return;}
        lastBlankClick.current={start:arg.allDay?arg.dateStr+'T09:00:00+08:00':arg.date.toISOString(),at:arg.jsEvent.timeStamp};}}
      eventDidMount={arg=>{arg.el.dataset.weekEvent=arg.event.id;arg.el.setAttribute('role','button');arg.el.setAttribute('tabindex','0');const source=arg.event.extendedProps.source as CalendarEvent;
        // FullCalendar clones the source for its revert mirror. Keep its top/left ownership.
        arg.el.style.setProperty('transition-timing-function',DRAG_EASING,'important');
        annotateEvent(arg.el,source);}}
      eventContent={arg=>{const preview=arg.isMirror&&arg.event.start&&arg.event.end?pointerTimeDraft(arg.event.extendedProps.source as CalendarEvent,{start:arg.event.start.toISOString(),end:arg.event.end.toISOString()}):null;
        const source=arg.event.extendedProps.source as CalendarEvent;if(!source)return null;
        const content=<div className="sw-event-content"><b>{arg.event.extendedProps.pending?'保存中 · ':arg.event.extendedProps.unknown?'未核对 · ':arg.event.extendedProps.linked?'↗ ':''}{arg.event.title}</b><span className="sw-event-time">{preview?`${beijingStamp(preview.start).slice(11)} – ${beijingStamp(preview.end).slice(11)}`:view==='month'&&source.start.includes('T')?`${beijingStamp(source.start).slice(11)} – ${beijingStamp(source.end).slice(11)}`:arg.timeText}</span></div>;
        return arg.isMirror||view==='month'?content:<CalendarDragContent event={source} enabled={(source.calendar_id==='tebb-draft'||timeEditable(source))&&!controller.blocked(calendarKey(source))&&!controller.checking.has(calendarKey(source))&&(!dirty||source.calendar_id==='tebb-draft')}>{content}</CalendarDragContent>;}}/>,[events,day,view,dirty,keyboard,pointerCancelled,controller,reduce,onViewDay]);
  const periodText=view==='month'?`${day.slice(0,4)} 年 ${Number(day.slice(5,7))} 月`
    :view==='day'?`${day.slice(0,4)} 年 ${Number(day.slice(5,7))} 月 ${Number(day.slice(8,10))} 日`
    :`${monday.slice(0,4)} 年 ${Number(monday.slice(5,7))} 月 ${Number(monday.slice(8,10))} 日 — ${Number(addCalendarDays(monday,6).slice(8,10))} 日`;
  // 同步与核对条目按操作编号聚合，同一编号只渲染一次。
  const localPending=local.page.events.filter(row=>row.sync_state==='local');
  const remoteCount=visible.filter(row=>row.sync_state!=='local').length;
  const localWeekCount=visible.filter(row=>row.sync_state==='local').length;
  const checkedAt=controller.page.checked_at&&Number.isFinite(Date.parse(controller.page.checked_at))?beijingStamp(controller.page.checked_at).slice(11,16):'';
  // 底部状态条固定文案；实时播报仍通过 aria-live 覆盖这一段。
  const statusSummary=controller.page.events_valid
    ?`已读取本周日程 · 飞书 ${remoteCount} 条 / 本地 ${localWeekCount} 条${checkedAt?` · 上次核对 ${checkedAt}`:''}`
    :'上次读取的日程尚未核对';
  const confirmItems:SyncItem[]=[];
  if(controller.error)confirmItems.push({id:'error:schedule',title:'日程读取未完成',detail:controller.error,hint:'保留上次已读内容；不会用旧数据判断没有安排。',
    actions:[{label:'重新读取',primary:true,run:()=>void controller.read(day,true)}]});
  if(!draft&&!bulk&&local.error)confirmItems.push({id:'error:local',title:'本地日程结果未确认',detail:local.error,
    actions:[{label:'读取核对',primary:true,run:()=>void local.read()}]});
  if(target.event_id&&controller.page.events_valid&&!controller.loading&&!controller.page.events.some(row=>row.event_id===target.event_id))
    confirmItems.push({id:'target-missing',title:'当前区间未找到目标日程',detail:'请核对日期、访问权限或远端是否已删除；不会用另一场日程替代。'});
  if(!controller.page.events_valid)confirmItems.push({id:'remote-unverified',title:controller.remoteAttempt?'本周远端核对未完成':'上次读取的日程尚未核对',
    detail:controller.page.events_error||'尚未完成本周远端核对。',hint:visible.length?'下方保留上次信息，不能据此判断没有安排。':undefined,
    actions:[{label:'读取核对',primary:true,run:()=>void controller.read(day,true)}]});
  for(const row of unknownDate)confirmItems.push({id:'date:'+calendarKey(row),title:row.summary+' · 时间未核实',
    detail:'读取到的开始时间无法解析，暂不放入时间轴。',actions:[{label:'查看日程',run:()=>openEvent(row)}]});
  for(const [key,record] of controller.unknown){
    if(controller.pending.has(key))continue;
    confirmItems.push({id:'retime:'+record.request_id,title:controller.event(key)?.summary||record.event_id,
      detail:`原时间 ${record.original_start} → ${record.original_end}${record.start?`；拟调整 ${record.start} → ${record.end}`:''}`,
      hint:controller.missing.has(key)?'尚未查到原回执，不能据此认为没有执行。请先读取当前日程，再明确结束等待。':undefined,
      actions:[{label:'读取此日程及原回执',run:()=>{setSelected(key);void controller.inspect(record);void controller.read(day);}},
        {label:'结束本轮等待',disabled:!['confirmed','missing','deleted'].includes(controller.event(key)?.verification||'')||controller.checking.has(key),
          run:()=>void controller.reconcile(key).then(()=>{changes.current();void controller.inspect(record);})}]});
  }
  if(local.unknown){
    const marker=local.unknown,syncMarker=marker.type==='sync'&&!local.page.operations.some(operation=>operation.id===marker.request_id);
    const actions:SyncAction[]=[{label:'读取原编号',run:()=>void local.read()}];
    if(['create','update'].includes(marker.type))actions.push({label:'核对本地记录并结束等待',disabled:local.busy,
      run:()=>{if(window.confirm('已核对当前本地日程，登记当前状态并结束原请求等待？'))void local.change({type:'resolve_save',local_id:marker.local_id!,operation_id:marker.request_id,confirmed:true});}});
    if(syncMarker&&marker.local_id)actions.push(
      {label:'核对并关联已创建日程',disabled:!resolveId||local.busy,run:()=>void resolveSync(marker.request_id,marker.local_id!,'link')},
      {label:'确认未创建并封存原编号',disabled:local.busy,run:()=>void resolveSync(marker.request_id,marker.local_id!,'absent')});
    confirmItems.push({id:'save:'+marker.request_id,title:'本地日程保存结果未确认',
      detail:`原请求编号 ${marker.request_id}。请读取核对，不要重新创建。`,
      input:syncMarker?{label:'已创建的飞书事件 ID',value:resolveId,onChange:setResolveId}:undefined,actions});
  }
  for(const operation of local.page.operations.filter(row=>row.type==='delete'))confirmItems.push({id:'delete:'+operation.id,
    title:'删除结果待核对',detail:`编号 ${operation.id} · 阶段 ${operation.stage}`,actions:[
      {label:'核对删除结果',disabled:local.busy,run:()=>void local.change({type:'resolve_delete',operation_id:operation.id}).then(()=>{changes.current();void controller.read(day,true);})},
      {label:'保留当前记录并结束等待',disabled:local.busy,run:()=>{if(window.confirm('读取当前记录；若仍存在，明确保留它并结束原等待？不会重发删除。'))void local.change({type:'resolve_delete',operation_id:operation.id,resolution:'present',confirmed:true}).then(()=>{changes.current();void controller.read(day,true);});}}]});
  for(const operation of local.page.operations.filter(row=>row.type==='sync'))confirmItems.push({id:'sync:'+operation.id,
    title:'飞书同步结果待核对',detail:`编号 ${operation.id} · 阶段 ${operation.stage}${operation.error?' · '+operation.error:''}`,
    input:{label:'已创建的飞书事件 ID',value:resolveId,onChange:setResolveId,
      options:controller.page.events.filter(row=>row.calendar_id!=='tebb-local'&&row.eligible).map(row=>({value:row.event_id,label:`${row.summary} · ${eventTime(row)}`}))},
    actions:[{label:'核对并关联已创建日程',disabled:local.busy||!resolveId,run:()=>void resolveSync(operation.id,operation.local_id,'link')},
      {label:'确认没有创建，结束等待',disabled:local.busy,run:()=>void resolveSync(operation.id,operation.local_id,'absent')}]});
  const localItems:SyncItem[]=localPending.map(row=>({id:'local:'+calendarKey(row),title:row.summary,detail:eventTime(row),compact:true,
    actions:[{label:'查看',run:()=>openEvent(row)}]}));
  const recoveredItems:SyncItem[]=local.page.batches.flatMap(batch=>batch.entries.filter(entry=>entry.state==='synced').map(entry=>({
    id:batch.id+'/'+entry.local_id,title:local.page.events.find(row=>row.local_id===entry.local_id)?.summary||entry.local_id,
    detail:`清单 ${batch.id} · ${batch.created_at&&Number.isFinite(Date.parse(batch.created_at))?beijingStamp(batch.created_at).slice(5,16).replace('T',' '):''}`,compact:true})));
  // 面板只读控制器已有状态，不新增轮询或自动重试。
  const syncGroups:SyncGroup[]=[
    {id:'confirm',label:'需要确认',items:confirmItems,empty:'当前没有待确认的同步结果。'},
    {id:'local',label:'本地未同步',items:localItems,empty:'没有待同步的本地日程。',
      action:localItems.length?{label:`同步全部 ${localItems.length} 条`,run:openBulk}:undefined},
    {id:'recovered',label:'最近已恢复',items:recoveredItems,empty:'处理完成的条目会归入这里。',collapsed:true}];
  return <section className={`schedule-week${pointerCancelled?' sw-cancelled':''}${narrow?' sw-compact':''}`} ref={root} aria-label="周日程安排" onKeyDownCapture={keyboardMove} onDoubleClickCapture={doubleBlank} data-week-view data-week-version={version}>
    <header className="sw-heading"><div className="sw-heading-main"><span className="wb-eyebrow">工作区 / 日程</span>
      <div className="sw-title-row"><h1>日程</h1><CalendarSyncStatus groups={syncGroups} open={syncOpen} onOpenChange={setSyncOpen}
        checking={controller.loading||local.loading} lastChecked={checkedAt} onRefresh={()=>{void controller.read(day,true);void local.read();}}/></div>
      <p>本地与飞书主日历 · 北京时间 UTC+8{debug?' · 演示数据':''}</p></div>
      <div className="sw-primary-actions">
        <details className="sw-more" ref={moreMenu} onClick={event=>{const target=event.target as HTMLElement;if(!target.closest('button')||target.closest('[data-menu-keep-open]'))return;setKeyboardHelpOpen(false);if(moreMenu.current)moreMenu.current.open=false;}}>
          <summary>更多</summary>
          <div className="sw-more-menu">
            <button type="button" onClick={openBulk}>整体同步到飞书</button>
            <button type="button" disabled={controller.loading} onClick={()=>{void controller.read(day,true);void local.read();}}>读取核对</button>
            <button type="button" onClick={()=>guard(()=>onDay({day,item_id:item?.id||target.item_id,...(event?{calendar_id:event.calendar_id,event_id:event.event_id}:{})}))}>关联事项</button>
            <button type="button" data-menu-keep-open aria-expanded={keyboardHelpOpen} onClick={()=>setKeyboardHelpOpen(open=>!open)}>快捷键说明</button>
            {keyboardHelpOpen&&<p className="sw-more-help">{keyboardHelp}</p>}
            {extraActions}{closeLabel&&<button type="button" onClick={()=>guard(onClose)}>{closeLabel}</button>}
          </div>
        </details>
        <button type="button" className="wb-primary" onClick={()=>beginDraft(day+'T09:00:00+08:00')}>＋ 新建日程</button>
      </div></header>
    <div className="sw-datenav"><div className="sw-datenav-controls">
      <button type="button" className="sw-step" aria-label={view==='month'?'上一月':view==='day'?'上一天':'上一周'} onClick={()=>guard(()=>setDay(view==='month'?new Date(Date.UTC(Number(day.slice(0,4)),Number(day.slice(5,7))-2,1)).toISOString().slice(0,10):addCalendarDays(day,view==='day'?-1:-7)))}>‹</button>
      <button type="button" onClick={()=>guard(()=>setDay(beijingDay()))}>今天</button>
      <button type="button" className="sw-step" aria-label={view==='month'?'下一月':view==='day'?'下一天':'下一周'} onClick={()=>guard(()=>setDay(view==='month'?new Date(Date.UTC(Number(day.slice(0,4)),Number(day.slice(5,7)),1)).toISOString().slice(0,10):addCalendarDays(day,view==='day'?1:7)))}>›</button>
      <div className="sw-period">
        <button type="button" className="sw-period-title" aria-expanded={periodOpen} onClick={()=>setPeriodOpen(open=>!open)}>{periodText}
          {view==='week'&&<span className="sw-week-no">第 {isoWeek(day)} 周</span>}</button>
        {periodOpen&&<div className="sw-period-pop" onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();setPeriodOpen(false);}}}>
          <label>定位日期<input type="date" aria-label="周日程定位日期" value={day} autoFocus onChange={event=>{if(event.target.value){setPeriodOpen(false);guard(()=>setDay(event.target.value));}}}/></label>
        </div>}
      </div>
    </div>{viewTabs}</div>
    {!controller.loading&&!local.loading&&!local.busy&&!local.unknown&&!controller.error&&!local.error&&controller.page.events_valid&&!visible.length&&<UiFeedback state="empty" title="当前区间没有已读日程">可切换日期，或新建日程草稿。</UiFeedback>}
    <CalendarDragSurface reduce={!!reduce} onPending={pending=>pending?controller.beginInteraction():controller.endInteraction()} onStart={dragStart} project={dragProjection} onCommit={dragCommit} onFinish={cancelled=>{stopPointer();if(cancelled)setAnnouncement('已取消拖动。');}}>
    <div className={`sw-calendar-layout${view!=='month'?' sw-with-items':''}`}>
      {view!=='month'&&<CalendarItemSource items={controller.page.items} disabled={itemDraftBlocked} loading={controller.loading} onArrange={arrangeItem}/>}
      <div className={`sw-calendar sw-${view}`} role="region" aria-label="日程时间轴" tabIndex={0}>{calendarView}</div>
    </div></CalendarDragSurface>
    <footer className="sw-statusbar">
      <div className="sw-live" role="status" aria-live="polite" title={announcement||controller.notice||syncHint||calendarHelp}><span className={`sw-status-dot${confirmItems.length?' sw-warn':''}`} aria-hidden="true"/><UiStableText reserve={statusSummary}>{announcement||controller.notice||syncHint||statusSummary}</UiStableText></div>
      <button type="button" className="sw-status-help" title={keyboardHelp} onClick={()=>setAnnouncement(keyboardHelp)}>双击空白处新建 · 拖动改期 · 快捷键说明</button>
    </footer>
    {detailsOpen&&event&&<section className="sw-details" ref={details} role="dialog" aria-modal="false" style={narrow?undefined:popover} aria-label="日程时间详情"><button type="button" className="sw-popover-close" aria-label="关闭日程详情" onClick={()=>guard(()=>setDetailsOpen(false))}>×</button>
      <div className="sw-detail-heading"><h2>{event?.summary||'选择一场日程'}</h2>{event&&<button type="button" onClick={()=>locate(event)}>定位日程</button>}{item&&<button type="button" onClick={()=>guard(()=>onReturn(item.id))}>↗ {item.title}{item.archived?' · 已归档':''}</button>}</div>
      {event&&<><p className="sc-caption">{eventTime(event)} · {eventHealth(event)}{checking?' · 编辑资格核对中':!timeEditable(event)?' · '+(event.edit_reason||'请重新核对编辑资格'):''}</p>
        <div className="sc-actions">
          <button type="button" className="wb-primary" disabled={!timeEditable(event)||blocked||checking} onClick={()=>{if(view==='month'){guard(()=>onViewDay?.(beijingDay(event.start)));return;}controller.endInteraction();setKeyboard(null);setForm(initialForm);setFormError('');setPicker(null);focusDetails();}}>修改时间</button>
          {event.local_id&&<button type="button" disabled={blocked||local.busy} onClick={()=>editLocal(event)}>编辑日程</button>}
          <details className="sw-detail-more"><summary>更多</summary><div className="sw-detail-menu">
            <button type="button" disabled={checking} onClick={()=>void controller.inspect(event)}>核对编辑资格</button>
            <button type="button" onClick={()=>guard(()=>onDay({day:safeDay(event,day),calendar_id:event.calendar_id,event_id:event.event_id,item_id:item?.id||target.item_id}))}>关联事项</button>
            <button type="button" disabled={!timeEditable(event)||Date.parse(event.end)<=Date.now()||blocked||local.busy} onClick={()=>{if(window.confirm('删除这场日程？已同步日程会同时删除飞书记录，事项和AI历史保留。'))void local.change({type:'delete',calendar_id:event.calendar_id,event_id:event.event_id,version:event.local_version,original_start:event.start,original_end:event.end}).then(result=>{if(result.ok)setDetailsOpen(false);changes.current();void controller.read(day,true);});}}>删除日程</button>
          </div></details>
        </div>
      </>}
      {form&&event&&form.key===selected&&<form className="sw-time-form" onSubmit={e=>{e.preventDefault();void saveForm();}}>
        <label>标题<input aria-label="编辑日程标题" maxLength={120} required value={form.summary} disabled={blocked} onChange={e=>field('summary',e.target.value)}/></label><div className="sw-fields"><span>开始</span><DateTimeField portalRoot={root.current} marker="start" placeholder="开始时间" value={form.start} disabled={blocked} open={picker==='start'} onOpen={()=>setPicker('start')} onClose={()=>setPicker(null)} onChange={value=>field('start',value)}/>
          <span>结束</span><DateTimeField portalRoot={root.current} marker="end" placeholder="结束时间" value={form.end} disabled={blocked} open={picker==='end'} onOpen={()=>setPicker('end')} onClose={()=>setPicker(null)} onChange={value=>field('end',value)}/></div>
        {formError&&<p className="sc-error" role="alert">{formError}</p>}
        <div className="sc-actions"><button type="submit" className="wb-primary" disabled={!dirty||blocked}>保存时间</button><button type="button" disabled={busy} onClick={()=>{setForm(null);setPicker(null);setFormError('');}}>放弃表单</button></div>
      </form>}
    </section>}
    {draft&&<div className="sw-editor-anchor" ref={draftRoot} style={narrow?undefined:popover}><CalendarEventEditor value={draft} items={controller.page.items} busy={local.busy} blocked={!!local.unknown} error={draftError||local.error}
      onChange={setDraftFields} onSave={()=>void saveDraft()} onClose={()=>guard(()=>setDraft(null))}/></div>}
    {bulk&&<WorkspaceDialog title="整体同步到飞书" closeDisabled={local.busy} onClose={()=>{if(!local.busy)setBulk(false);}}><p>全部未同步本地日程 · {bulkPreview.length} 条 · 目标为当前飞书主日历</p>
      {bulkPreview.map(e=><div className="sw-sync-row" key={e.local_id}><strong>{e.summary}</strong><span>{eventTime(e)}</span></div>)}
      <p className="sc-caption">未保存草稿不在清单中；已同步日程跳过。每条分别保存结果，部分失败不回滚成功项。</p>
      <button type="button" className="wb-primary" disabled={local.busy||!!local.unknown||!bulkPreview.length||!!local.batch} onClick={()=>void local.runBatch(bulkPreview).then(()=>{changes.current();void controller.read(day);})}>{local.busy?'正在逐条同步…':local.batch?'本轮清单已提交':`确认同步 ${bulkPreview.length} 条`}</button>
      {local.error&&<p role="alert" className="sc-error">{local.error}</p>}
      {(local.batch||batchChoice)&&<section aria-label="本轮同步结果"><h3>清单 {(local.batch||batchChoice)!.id}</h3>{(local.batch||batchChoice)!.entries.map(entry=><p key={entry.local_id}>{local.page.events.find(e=>e.local_id===entry.local_id)?.summary||entry.local_id} · {({queued:'尚未执行',synced:'已同步',failed:'未同步',unconfirmed:'待核对'})[entry.state]} {entry.error}</p>)}</section>}
      {local.page.batches.filter(b=>b.entries.some(e=>e.state==='queued')).map(batch=><div key={batch.id}><span>未完成清单 {batch.id}</span><button type="button" disabled={local.busy||!!local.unknown} onClick={()=>{setBatchChoice(batch);void local.continueBatch(batch).then(()=>{changes.current();void controller.read(day);});}}>明确继续尚未执行的条目</button></div>)}
    </WorkspaceDialog>}
    {leave&&<div className="sc-leave" role="alertdialog" aria-label="未保存的日程时间"><h3>日程时间尚未保存</h3><button type="button" disabled={blocked} onClick={()=>void (draft?saveDraft():saveForm()).then(ok=>{if(ok){const next=leave;setLeave(null);next();}})}>保存并继续</button><button type="button" disabled={busy} onClick={()=>{const next=leave;setDraft(null);setForm(null);setPicker(null);setLeave(null);next();}}>放弃并继续</button><button type="button" onClick={()=>setLeave(null)}>继续编辑</button></div>}
  </section>;
}
