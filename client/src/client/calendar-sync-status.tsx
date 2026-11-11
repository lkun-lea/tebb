import { useEffect, useRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { UiButton } from './ui-controls';
import './calendar-sync-status.css';

export type SyncAction={label:string;run:()=>void;disabled?:boolean;primary?:boolean};
export type SyncItem={id:string;title:string;detail?:string;hint?:string;compact?:boolean;
  actions?:SyncAction[];input?:{label:string;value:string;onChange:(value:string)=>void;options?:{value:string;label:string}[]}};
export type SyncGroup={id:string;label:string;items:SyncItem[];empty?:string;collapsed?:boolean;action?:SyncAction};

// 标题右侧的同步状态胶囊与右侧浮层；只呈现状态，不触发自动重试或轮询。
export function CalendarSyncStatus({groups,open,onOpenChange,checking,lastChecked,onRefresh}:{
  groups:SyncGroup[];open:boolean;onOpenChange:(open:boolean)=>void;checking:boolean;lastChecked:string;onRefresh:()=>void}){
  const pill=useRef<HTMLButtonElement|null>(null),panel=useRef<HTMLElement|null>(null),close=useRef(onOpenChange);
  close.current=onOpenChange;
  const pending=groups.find(group=>group.id==='confirm')?.items.length||0;
  useEffect(()=>{
    if(!open)return;
    const previous=document.activeElement as HTMLElement|null;
    panel.current?.focus({preventScroll:true});
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close.current(false);}};
    const outside=(event:PointerEvent)=>{const target=event.target as Node;if(panel.current?.contains(target)||pill.current?.contains(target))return;close.current(false);};
    document.addEventListener('keydown',escape,true);document.addEventListener('pointerdown',outside,true);
    return()=>{document.removeEventListener('keydown',escape,true);document.removeEventListener('pointerdown',outside,true);
      // 打开确认框等后续弹窗时焦点已移出，此时不抢回焦点。
      if(panel.current?.contains(document.activeElement)){const target=previous?.isConnected?previous:pill.current;target?.focus({preventScroll:true});}
    };
  },[open]);
  return <div className="sw-sync">
    <button type="button" ref={pill} className={`sw-sync-pill${pending?' sw-sync-warn':''}`} aria-expanded={open} aria-haspopup="dialog"
      onClick={()=>close.current(!open)}>
      <span className="sw-sync-dot" aria-hidden="true"/>{pending?`同步 · ${pending} 项待核对`:'已同步'}
      <ChevronDown className="ui-inline-icon" size={12} aria-hidden="true"/>
    </button>
    {open&&<section className="sw-sync-panel" role="dialog" aria-modal="false" aria-label="同步与核对" ref={panel} tabIndex={-1}>
      <header><div><h2>同步与核对</h2><p>按编号去重 · 处理完成后自动归入已恢复</p></div>
        <button type="button" className="sw-sync-close" aria-label="关闭同步与核对" onClick={()=>close.current(false)}>×</button></header>
      <p className="sw-sync-policy">未确认前不会自动重发。</p>
      {groups.map(group=>{
        const body=<div className="sw-sync-items">
          {!group.items.length&&<p className="sw-sync-empty">{group.empty||'当前没有条目。'}</p>}
          {group.items.map(item=><article key={item.id} className={`sw-sync-item${item.compact?' sw-sync-item-row':''}`}>
            <div className="sw-sync-item-main"><strong>{item.title}</strong>{item.detail&&<p>{item.detail}</p>}{item.hint&&<p className="sw-sync-hint">{item.hint}</p>}</div>
            {item.input&&<label className="sw-sync-input">{item.input.label}
              <input value={item.input.value} onChange={event=>item.input!.onChange(event.target.value)}/>
              {!!item.input.options?.length&&<select aria-label="从本周日程选择" value="" onChange={event=>{if(event.target.value)item.input!.onChange(event.target.value);}}><option value="">从本周日程选择</option>{item.input.options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>}
            </label>}
            {!!item.actions?.length&&<div className="sw-sync-actions">{item.actions.map(action=><button key={action.label} type="button" className={action.primary?'wb-primary':''} disabled={action.disabled} onClick={action.run}>{action.label}</button>)}</div>}
          </article>)}
        </div>;
        return group.collapsed
          ? <details className="sw-sync-group sw-sync-collapsed" key={group.id}><summary>{group.label}<span>{group.items.length}</span></summary>{body}</details>
          : <section className="sw-sync-group" key={group.id} aria-label={group.label}>
              <div className="sw-sync-group-head"><h3>{group.label}<span>{group.items.length}</span></h3>
                {group.action&&<button type="button" disabled={group.action.disabled} onClick={group.action.run}>{group.action.label}</button>}</div>
              {body}
            </section>;
      })}
      <footer><span>上次核对 {lastChecked||'—'}</span><UiButton busy={checking} busyLabel="核对中…" onClick={onRefresh}>读取核对</UiButton></footer>
    </section>}
  </div>;
}
