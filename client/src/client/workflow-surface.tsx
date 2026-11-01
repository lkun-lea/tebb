import {useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {WorkspaceDialog} from './workspace-dialog';

// Keep the portal target stable: moving it preserves the canvas and input state.
export function WorkflowSurface({focused,onClose,children}:{focused:boolean;onClose:()=>void;children:ReactNode}){
  const home=useRef<HTMLDivElement|null>(null),modal=useRef<HTMLDivElement|null>(null);
  const [target]=useState(()=>typeof document==='undefined'?null:document.createElement('div'));
  useLayoutEffect(()=>{
    if(!target)return;
    target.className='workflow-surface-content';
    (focused?modal.current:home.current)?.appendChild(target);
  },[target,focused]);
  if(!target)return <>{children}</>;
  return <><div ref={home} className="workflow-surface" hidden={focused}/>
    {focused&&<WorkspaceDialog title="工作流专注画布" onClose={onClose} hideHeader className="workflow-focus-dialog"><div ref={modal} className="workflow-focus-host"/></WorkspaceDialog>}
    {createPortal(children,target)}
  </>;
}
