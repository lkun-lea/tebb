import {createPortal} from "react-dom";
import {useEffect,useState} from "react";

type Receipt = {id:number;text:string};
const pending:Receipt[]=[];
let sequence=0;
const listeners=new Set<()=>void>();
function update(){listeners.forEach(listener=>listener());}

export function notifyReceipt(text:string){
  if(!text.trim())return;
  const same=pending.findIndex(item=>item.text===text);
  const next={id:++sequence,text};
  if(same<0)pending.push(next);
  else pending[same]=next;
  update();
}

export function ToastHost(){
  const [current,setCurrent]=useState<Receipt|undefined>(pending[0]);
  useEffect(()=>{
    const sync=()=>setCurrent(pending[0]);
    listeners.add(sync);sync();return ()=>{listeners.delete(sync);};
  },[]);
  useEffect(()=>{
    if(!current)return;
    const timer=setTimeout(()=>{if(pending[0]?.id===current.id){pending.shift();update();}},2600);
    return ()=>clearTimeout(timer);
  },[current]);
  const [dialog,setDialog]=useState<HTMLDialogElement|null>(null);
  useEffect(()=>{
    if(typeof document==='undefined'||typeof window.addEventListener!=='function')return;
    const sync=()=>setDialog(Array.from(document.querySelectorAll<HTMLDialogElement>('dialog[open]')).pop()||null);
    window.addEventListener('tebb-workspace-dialog',sync);sync();
    return ()=>window.removeEventListener('tebb-workspace-dialog',sync);
  },[]);
  const region=<div className="ui-toast-region" role="status" aria-live="polite" aria-atomic="true">{current&&<span key={current.id}>{current.text}</span>}</div>;
  return dialog?createPortal(region,dialog):region;
}

export function ReceiptNotice({text}:{text:string}){
  useEffect(()=>{if(text)notifyReceipt(text);},[text]);
  return null;
}
