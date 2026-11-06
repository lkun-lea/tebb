import { useId, useRef, useState, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import './inspector-disclosure.css';
export function InspectorDisclosure({label,icon,meta,children,defaultOpen=false,className=''}:{label:ReactNode;icon?:ReactNode;meta?:string;children:ReactNode;defaultOpen?:boolean;className?:string}){
 const [open,setOpen]=useState(defaultOpen),[seen,setSeen]=useState(defaultOpen),id=useId(),button=useRef<HTMLButtonElement>(null),body=useRef<HTMLDivElement>(null);
 function toggle(){
  if(open && body.current?.contains(document.activeElement))button.current?.focus();
  if(!open)setSeen(true);
  setOpen(value=>!value);
 }
 return <section className={`context-disclosure ${className}`}><button ref={button} type="button" aria-controls={id} aria-expanded={open} onClick={toggle}>{icon}<span>{label}</span>{meta&&<small>{meta}</small>}<ChevronRight size={15} className={open?'is-open':''}/></button><div ref={body} id={id} className="context-disclosure-grid" data-open={open} aria-hidden={!open} {...(!open?{inert:''}:{})}><div className="context-disclosure-clip"><div className="context-disclosure-content">{seen?children:null}</div></div></div></section>;
}
