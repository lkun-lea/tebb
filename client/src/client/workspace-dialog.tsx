import './workspace-dialog.css';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { usePageActive } from './page-stack';

// The native modal supplies background isolation, focus containment and Escape.
export function WorkspaceDialog({title,onClose,children,closeDisabled=false,className='',hideHeader=false,dismissOnBackdrop=false}:{title:string;onClose:()=>void;children:ReactNode;closeDisabled?:boolean;className?:string;hideHeader?:boolean;dismissOnBackdrop?:boolean}){
  const ref=useRef<HTMLDialogElement|null>(null),active=usePageActive(),id=useId();
  useEffect(()=>{const dialog=ref.current;if(!dialog||!active)return;const previous=document.activeElement as HTMLElement|null;
    dialog.showModal();window.dispatchEvent(new CustomEvent('tebb-workspace-dialog',{detail:{id,open:true}}));
    return()=>{dialog.close();window.dispatchEvent(new CustomEvent('tebb-workspace-dialog',{detail:{id,open:false}}));if(previous?.isConnected)previous.focus();};
  },[active]);
  return active?<dialog role="dialog" onClick={e=>{
    if(!dismissOnBackdrop || closeDisabled || e.target!==e.currentTarget)return;
    const box=e.currentTarget.getBoundingClientRect();
    if(e.clientX<box.left || e.clientX>box.right || e.clientY<box.top || e.clientY>box.bottom)onClose();
  }} ref={ref} className={`workspace-dialog ${className}`.trim()} aria-label={title} onCancel={event=>{event.preventDefault();if(!closeDisabled)onClose();}}>
    {!hideHeader&&<header><h2>{title}</h2><button type="button" className="desk-menu-item" aria-label={`关闭${title}`} disabled={closeDisabled} onClick={onClose}>关闭</button></header>}{children}
  </dialog>:null;
}
