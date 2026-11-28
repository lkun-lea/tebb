import {useEffect,useState} from 'react';
import {invoke,isTauri} from '@tauri-apps/api/core';
import {emitTo,listen} from '@tauri-apps/api/event';
import {backendInfo,rpc,type BackendInfo} from './api';
import {petRows,type PetBoard,type PetRow} from './pet-board';
import type {SchedulePage} from './schedule-state';
import './pet-board.css';

export function PetChat({backend}:{backend?:BackendInfo}){
  const [visible,setVisible]=useState(true),[pinned,setPinned]=useState(false);
  const [rows,setRows]=useState<PetRow[]>([]),[day,setDay]=useState(''),[warning,setWarning]=useState('');
  const [actionError,setActionError]=useState(''),[retry,setRetry]=useState(0);
  useEffect(()=>{
    if(!isTauri())return;
    let live=true;
    const listener=listen<boolean>('pet-chat-visible',e=>{if(live)setVisible(e.payload)});
    void invoke<{visible:boolean;pinned:boolean}>('get_pet_chat_state').then(s=>{if(live){setVisible(s.visible);setPinned(s.pinned)}}).catch(()=>{});
    return ()=>{live=false;void listener.then(f=>f())};
  },[]);
  useEffect(()=>{
    if(!visible)return;
    let live=true,timer:number;
    async function load(){
      try{
        const info=backend||await backendInfo();
        const board=await rpc<PetBoard>(info,'today_board');
        const schedule=await rpc<SchedulePage>(info,'load_schedule',{day:board.day,refresh:false}).catch(()=>null);
        if(live){
          setRows(petRows(board,schedule?.events||[]));setDay(board.day);
          setWarning(schedule?.events_valid?'':'日程未能完整读取');
        }
      }catch{if(live){setWarning('今日看板读取失败');setDay('');setRows([])}}
      if(live)timer=window.setTimeout(load,15000);
    }
    void load();
    return ()=>{live=false;window.clearTimeout(timer)};
  },[backend,visible,retry]);
  async function act(fn:()=>Promise<unknown>){try{setActionError('');await fn()}catch{setActionError('窗口操作失败，请重试')}}
  async function today(){await invoke('show_main');await emitTo('main','pet-open-journal',{})}
  return <main className="pet-today"><header><div><time>{day||'今日'}</time><h1>今日看板</h1></div><div>
    <button aria-pressed={pinned} onClick={()=>void act(async()=>setPinned(await invoke<boolean>('set_pet_chat_pinned',{pinned:!pinned})))}>{pinned?'取消置顶':'置顶'}</button>
    <button aria-label="关闭今日看板" onClick={()=>void act(()=>invoke('set_pet_chat_visible',{visible:false}))}>×</button></div></header>
    <section aria-label="今日要事">{rows.map(row=><button key={row.id} className="pet-today-row" onClick={()=>void act(row.trace?()=>invoke('open_settings_window',{section:'monitor',trace:'collab:'+row.trace}):row.calendar?async()=>{await invoke('show_main');await emitTo('main','pet-open-journal',row.calendar)}:today)}><small>{row.label}</small><strong>{row.title}</strong></button>)}
    {!rows.length&&<p>{day?'此刻没有待处理的要事。':warning?'': '正在读取今日安排…'}</p>}</section>
    <footer>{(warning||actionError)&&<small role="status">{actionError||warning} <button onClick={()=>{setActionError('');setRetry(n=>n+1)}}>重试</button></small>}
    <div><button onClick={()=>void act(async()=>{await invoke('show_main');await emitTo('main','open-collaboration',{})})}>主聊天</button><button onClick={()=>void act(today)}>完整今日 ›</button></div></footer>
  </main>;
}
