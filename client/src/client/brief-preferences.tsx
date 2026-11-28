import {useEffect, useRef, useState} from 'react';
import {WorkspaceDialog} from './workspace-dialog';

type Period = {time:string; focus:string; keywords?:string; frequency?:string; enabled?:boolean};
type Slot = 'morning'|'evening';
export type Preferences = {version:number; project:string; morning:Period; evening:Period};
const frequencies = {daily:'每天',weekdays:'工作日',weekends:'周末'} as const;
const focusOptions = {questions:'待答任务',project:'项目进展',both:'任务与项目'};
const suggestions = ['每日科技资讯','关注行业动态','每天学英语','每天长点知识'];
const hours = Array.from({length:24},(_,index)=>index);
const minutes = Array.from({length:12},(_,index)=>index*5);
const pad = (value:number)=>String(value).padStart(2,'0');

function TimeWheel({label,values,value,onChange}:{label:string;values:number[];value:number;onChange:(v:number)=>void}){
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const el=ref.current;
    const frame=requestAnimationFrame(()=>{if(el)el.scrollTop=values.indexOf(value)*36;});
    return ()=>cancelAnimationFrame(frame);
  },[]); // Align the existing time when the picker opens.
  function move(i:number){
    const index=Math.max(0,Math.min(values.length-1,i));
    if(ref.current) ref.current.scrollTop=index*36;
    onChange(values[index]);
  }
  return <div ref={ref} className="brief-wheel" role="spinbutton" tabIndex={0} aria-label={label}
    aria-valuemin={values[0]} aria-valuemax={values[values.length-1]} aria-valuenow={value}
    onScroll={e=>onChange(values[Math.min(values.length-1,Math.max(0,Math.round(e.currentTarget.scrollTop/36)))])}
    onKeyDown={e=>{
      const index=values.indexOf(value);
      const target=({ArrowUp:index-1,ArrowDown:index+1,Home:0,End:values.length-1} as Record<string,number>)[e.key];
      if(target!==undefined){e.preventDefault();move(target);}
    }}>
    {values.map((v,i)=><div key={v} aria-hidden="true" data-current={v===value} onClick={()=>move(i)}>{pad(v)}</div>)}
  </div>;
}

function TimeChooser({value,onClose,onApply}:{value:string;onClose:()=>void;onApply:(time:string)=>void}){
  const [initialHour,initialMinute]=value.split(':').map(Number);
  const [hour,setHour]=useState(initialHour),[minute,setMinute]=useState(initialMinute);
  const choices=minutes.includes(initialMinute)?minutes:[...minutes,initialMinute].sort((a,b)=>a-b);
  return <WorkspaceDialog title="选择时间" hideHeader className="brief-time-dialog glass-card" onClose={onClose} dismissOnBackdrop>
    <header><button type="button" aria-label="取消选择时间" onClick={onClose}>×</button><h3>选择时间</h3><button type="button" aria-label="确认时间" onClick={()=>onApply(pad(hour)+':'+pad(minute))}>✓</button></header>
    <div className="brief-wheels"><TimeWheel label="小时" values={hours} value={hour} onChange={setHour}/><span>:</span><TimeWheel label="分钟" values={choices} value={minute} onChange={setMinute}/></div>
  </WorkspaceDialog>;
}

export function BriefPreferences({draft,projects,busy,error,change,cancel,save}:{
  draft:Preferences;projects:{id:string;name:string}[];busy:boolean;error:string;change:(p:Preferences)=>void;cancel:()=>void;save:()=>void
}){
  const [slot,setSlot]=useState<Slot>('morning'),[picking,setPicking]=useState(false);
  const period=draft[slot],words=period.keywords||'';
  const frequency=period.frequency==='off'?'daily':period.frequency||'daily';
  const enabled=period.enabled??period.frequency!=='off';
  const update=(patch:Partial<Period>)=>change({...draft,[slot]:{...period,...patch}});
  function toggleSuggestion(word:string){
    const tokens=words.split(/(\s+)/);
    const next=tokens.includes(word)
      ? tokens.filter(token=>token!==word).join('').trim()
      : [words.trimEnd(),word].filter(Boolean).join(' ');
    if(next.length<=2000)update({keywords:next});
  }
  return <WorkspaceDialog title="编辑早晚报" hideHeader closeDisabled={busy} onClose={cancel} className="brief-preferences glass-card">
    <form onSubmit={e=>{e.preventDefault();save();}}>
      <header><h2>编辑早晚报</h2><button type="button" disabled={busy} aria-label="关闭编辑早晚报" onClick={cancel}>×</button></header>
      <fieldset disabled={busy}>
        <div className="brief-switch" role="group" aria-label="简报时段">{(['morning','evening'] as const).map(id=><button key={id} type="button" aria-pressed={slot===id} onClick={()=>setSlot(id)}>{id==='morning'?'早间简报':'晚间简报'}</button>)}</div>
        <section className="brief-content"><h3><label htmlFor="brief-words">内容偏好</label></h3>
          <p>从待答任务和项目进展中筛选你关心的内容。多个关注词用空格分开。</p>
          <div className="brief-keywords"><textarea id="brief-words" maxLength={2000} value={words} placeholder="添加你关注的内容" onChange={e=>update({keywords:e.target.value})}/><small>{words.length} / 2000</small></div>
          <div className="brief-chips" aria-label="推荐关注词">{suggestions.map(word=><button key={word} type="button" aria-pressed={words.split(/\s+/).includes(word)} onClick={()=>toggleSuggestion(word)}>{words.split(/\s+/).includes(word)?'✓':'＋'} {word}</button>)}</div>
        </section>
        <section><h3>推送设置</h3><div className="brief-schedule">
          <div><span>开启推送</span><button type="button" role="switch" aria-checked={enabled} aria-label="开启推送" title="定时将简报送到今日页" onClick={()=>update({enabled:!enabled,frequency})}><i/></button></div>
          <button type="button" className="brief-time-row" disabled={!enabled} onClick={()=>setPicking(true)}><span>推送时间</span><span>{frequencies[frequency as keyof typeof frequencies]} {period.time}　›</span></button>
        </div></section>
        <details className="brief-options"><summary>项目、内容来源与周期</summary>
          <label>关注项目<select value={draft.project} onChange={e=>change({...draft,project:e.target.value})}><option value="">选择项目</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <div role="group" aria-label="关注内容">{Object.entries(focusOptions).map(([id,name])=><button key={id} type="button" aria-pressed={period.focus===id} onClick={()=>update({focus:id})}>{name}</button>)}</div>
          <div role="group" aria-label="周期">{Object.entries(frequencies).map(([id,name])=><button key={id} type="button" aria-pressed={frequency===id} onClick={()=>update({frequency:id,enabled})}>{name}</button>)}</div>
        </details>
      </fieldset>
      {error&&<p role="alert">{error}</p>}
      <footer><button type="button" disabled={busy} onClick={cancel}>取消</button><button type="submit" disabled={busy}>{busy?'保存中…':'保存更改'}</button></footer>
    </form>
    {picking&&<TimeChooser value={period.time} onClose={()=>setPicking(false)} onApply={time=>{update({time});setPicking(false);}}/>}
  </WorkspaceDialog>;
}
