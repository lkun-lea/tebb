import {notifyReceipt} from './toast';
import {lazy,Suspense,useState} from 'react';
import {invoke,isTauri} from '@tauri-apps/api/core';
import type {BackendInfo} from './api';
const Trace=lazy(()=>import('./execution-trace').then(module=>({default:module.ExecutionTrace})));

export function executionRoot(ident:string,runs:{id:string;parent?:string}[]){
 const seen=new Set<string>();let current=ident;
 while(!seen.has(current)){seen.add(current);const parent=runs.find(r=>r.id===current)?.parent;if(!parent)return current;current=parent;}
 return ident;
}

export function ConnectionEntry({service}:{service:string}){
 const [error,setError]=useState('');
 async function open(){
  try{
   if(isTauri())await invoke('open_settings_window',{section:'connections',service});
   else window.dispatchEvent(new CustomEvent('tebb-open-settings',{detail:{section:'connections',service}}));
  }catch(e){setError(String(e));}
 }
 return <><button type="button" className="desk-btn" onClick={()=>void open()}>管理{service==='feishu'?'飞书':service}连接</button>{error&&<span role="alert">{error}</span>}</>;
}

export function ExecutionEntry({info,root,task}:{info:BackendInfo|null;root?:string;task?:string}){
 const [open,setOpen]=useState(false);
 async function inspect(){
  if(!isTauri()){setOpen(v=>!v);return;}
  try{await invoke('open_settings_window',{section:'monitor',trace:root||'@'+task});}
  catch(e){notifyReceipt(String(e));}
 }
 return <section><button type="button" className="desk-btn" aria-expanded={open} onClick={()=>void inspect()}>查看运行详情</button>{open&&<Suspense fallback={<p role="status">正在打开执行过程…</p>}><Trace info={info} root={root} task={task}/></Suspense>}</section>;
}
