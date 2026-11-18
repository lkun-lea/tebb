import {lazy,Suspense,useState} from 'react';
import type {BackendInfo} from './api';
const Trace=lazy(()=>import('./execution-trace').then(module=>({default:module.ExecutionTrace})));

export function executionRoot(ident:string,runs:{id:string;parent?:string}[]){
 const seen=new Set<string>();let current=ident;
 while(!seen.has(current)){seen.add(current);const parent=runs.find(r=>r.id===current)?.parent;if(!parent)return current;current=parent;}
 return ident;
}

export function ExecutionEntry({info,root,task}:{info:BackendInfo|null;root?:string;task?:string}){
 const [open,setOpen]=useState(false);
 return <section><button type="button" className="desk-btn" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>执行过程</button>{open&&<Suspense fallback={<p role="status">正在打开执行过程…</p>}><Trace info={info} root={root} task={task}/></Suspense>}</section>;
}
