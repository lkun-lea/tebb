import { useDraggable } from '@dnd-kit/core';
import { useState } from 'react';
import type { CalendarItem, CalendarDragSource } from './calendar-drag';
import { UiStableText } from './ui-controls';
import './calendar-item-source.css';
const itemHelp='拖动整行放入时间轴，或点行尾 ＋；保存前都是草稿。';

function ItemCard({item,disabled,onArrange}:{item:CalendarItem;disabled:boolean;onArrange:(item:CalendarItem)=>void}){
  const drag=useDraggable({id:'work-item/'+item.id,data:{source:{kind:'item',item} satisfies CalendarDragSource},disabled});
  return <li ref={drag.setNodeRef} data-calendar-item={item.id} className={drag.isDragging?'sw-item-card sw-source-lifted':'sw-item-card'}>
    <button type="button" ref={drag.setActivatorNodeRef} {...drag.attributes} {...drag.listeners} tabIndex={-1} disabled={disabled}
      className="sw-item-drag" aria-label={`拖动事项：${item.title}`} title="拖动整行放入日/周时间轴">
      <span className="sw-item-grip" aria-hidden="true">⠿</span><strong>{item.title}</strong>
    </button>
    <button type="button" className="sw-item-add" disabled={disabled} aria-label={`安排时间：${item.title}`} title="安排时间" onClick={()=>onArrange(item)}>＋</button>
  </li>;
}

export function CalendarItemSource({items,disabled,loading,onArrange}:{items:CalendarItem[];disabled:boolean;loading:boolean;onArrange:(item:CalendarItem)=>void}){
  const [query,setQuery]=useState('');
  const available=items.filter(item=>!item.archived),visible=available.filter(item=>item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <aside className="sw-item-source" aria-label="待安排事项">
    <header><h2>待安排</h2><span>{available.length}</span></header>
    <p><UiStableText reserve={itemHelp}>{disabled?'请先结束当前编辑或核对原操作。':itemHelp}</UiStableText></p>
    <label>搜索事项<input type="search" value={query} onChange={event=>setQuery(event.target.value)} aria-label="搜索可安排事项" placeholder="按事项标题搜索"/></label>
    {!available.length?<p role="status">{loading?'正在读取事项…':'暂无未归档事项。'}</p>:!visible.length?<p role="status">没有匹配的事项。</p>:<ul>{visible.map(item=><ItemCard key={item.id} item={item} disabled={disabled} onArrange={onArrange}/>)}</ul>}
  </aside>;
}
