import './workspace-dialog.css';
import { createContext, useContext, useEffect, useId, useLayoutEffect, useReducer, useRef, type ReactNode, type MutableRefObject } from 'react';
import { usePageActive } from './page-stack';

const DialogTarget = createContext<MutableRefObject<HTMLDialogElement | null> | null>(null);

/** Keep the closing dialog in the top layer until its exit finishes. */
export function DialogPresence({children}: {children: ReactNode}) {
  const node = useRef<HTMLDialogElement | null>(null);
  const previous = useRef<ReactNode>(null);
  const [, redraw] = useReducer(n => n + 1, 0);
  const visible = !!children;
  if (visible) previous.current = children;

  useLayoutEffect(() => {
    if (visible || !previous.current) return;
    const remove = () => { previous.current = null; redraw(); };
    const dialog = node.current;
    if (!dialog?.open || typeof dialog.animate !== 'function') { remove(); return; }
    const duration = parseFloat(getComputedStyle(dialog).getPropertyValue('--tebb-feedback'));
    if (!(duration > 0)) { remove(); return; }
    dialog.inert = true;
    const animation = dialog.animate([{opacity: 1, transform: 'none'}, {opacity: 0, transform: 'translateY(4px)'}],
      {duration, easing: 'ease-in', fill: 'forwards'});
    animation.onfinish = remove;
    return () => { animation.onfinish = null; animation.cancel(); dialog.inert = false; };
  }, [visible]);
  return <DialogTarget.Provider value={node}>{visible ? children : previous.current}</DialogTarget.Provider>;
}

// The native modal supplies background isolation, focus containment and Escape.
export function WorkspaceDialog({title,onClose,children,closeDisabled=false,className='',hideHeader=false,dismissOnBackdrop=false,role='dialog'}:{title:string;onClose:()=>void;children:ReactNode;closeDisabled?:boolean;className?:string;hideHeader?:boolean;dismissOnBackdrop?:boolean;role?:'dialog'|'alertdialog'}){
  const ref=useRef<HTMLDialogElement|null>(null),active=usePageActive(),id=useId();
  const target = useContext(DialogTarget);
  useLayoutEffect(() => {
    if (!target || !active) return;
    const dialog = ref.current;
    target.current = dialog;
    return () => { if (target.current === dialog) target.current = null; };
  }, [target, active]);
  useEffect(()=>{const dialog=ref.current;if(!dialog||!active)return;const previous=document.activeElement as HTMLElement|null;
    dialog.showModal();window.dispatchEvent(new CustomEvent('tebb-workspace-dialog',{detail:{id,open:true}}));
    return()=>{dialog.close();window.dispatchEvent(new CustomEvent('tebb-workspace-dialog',{detail:{id,open:false}}));if(previous?.isConnected)previous.focus();};
  },[active]);
  return active?<dialog role={role} onKeyDown={event=>{
    if(event.key==='Tab'||event.key==='Escape')event.stopPropagation();
  }} onClick={e=>{
    if(!dismissOnBackdrop || closeDisabled || e.target!==e.currentTarget)return;
    const box=e.currentTarget.getBoundingClientRect();
    if(e.clientX<box.left || e.clientX>box.right || e.clientY<box.top || e.clientY>box.bottom)onClose();
  }} ref={ref} className={`workspace-dialog ${className}`.trim()} aria-label={title} onCancel={event=>{event.preventDefault();event.stopPropagation();if(!closeDisabled)onClose();}}>
    <DialogTarget.Provider value={null}>
      {!hideHeader&&<header><h2>{title}</h2><button type="button" className="desk-menu-item" aria-label={`关闭${title}`} disabled={closeDisabled} onClick={onClose}>关闭</button></header>}{children}
    </DialogTarget.Provider>
  </dialog>:null;
}
