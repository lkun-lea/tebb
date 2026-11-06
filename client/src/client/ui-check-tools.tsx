import { useEffect, useState } from 'react';
import { previewQuote } from './side-workspace';
import { UiButton } from './ui-controls';

// Mounted only by the DEV entry with ui-check=1. Uses the real preview event, no backend.
export function UiCheckTools() {
  const [ready,setReady]=useState(false);
  useEffect(()=>{
    const check=()=>{if(!document.querySelector('[data-side-workspace]'))return false;setReady(true);return true;};
    if(check())return;
    const observer=new MutationObserver(()=>{if(check())observer.disconnect();});
    observer.observe(document.body,{childList:true,subtree:true});
    return()=>observer.disconnect();
  },[]);
  return <aside aria-label="UI 验收工具" style={{position:'fixed',left:12,bottom:12,zIndex:100,width:140,padding:8,borderRadius:10,background:'hsl(var(--card))',color:'hsl(var(--foreground))',fontSize:12}}>
    <span>UI 验收 · 合成数据</span>
    <UiButton disabled={!ready} style={{width:'100%',marginTop:8}} onClick={()=>previewQuote({n:1,doc:'隔离验收',doc_id:'ui-check-synthetic',title:'合成资料',text:'仅用于原生侧栏验收。\n\n[Example 网页](https://example.org)'})}>{ready?'打开合成资料':'等待工作台…'}</UiButton>
  </aside>;
}
