import { useEffect, useRef, useState } from 'react';
import { ChatPrototype } from './chat-prototype';
import { initialDemo, type DemoState } from './chat-prototype-state';
import { startupReady } from './startup';

const history = '# 聊天交互验收\n\n已有历史 **重点**，不应因新增文字重播。👩🏽‍💻\n\n```ts\nconsole.log("保留代码结构");\n```\n\n| 项目 | 结果 |\n| --- | --- |\n| Markdown | 保留 |\n\n新增内容：';
function fixture(): DemoState {
  const state = initialDemo();
  state.selected = 'dm-tebb';
  state.messages = [{ id:'ui-user', conversation:state.selected, sender:'user', text:'请检查聊天的流式、折叠与复制交互。' },
    { id:'ui-answer', conversation:state.selected, sender:'tebb', text:history, run:'ui-run' }];
  state.runs = [{ ...state.runs[0], id:'ui-run', conversation:state.selected, agent:'tebb', kind:'chat', title:'合成回复', state:'running', events:['tool_start: web_search 示例资料','tool_end: web_search succeeded'], updates:[], applied:0, calls:1 }];
  return state;
}
// Development-only harness: real chat components, synthetic state, no backend requests.
export function ChatMotionDebug() {
  const [state,setState]=useState(fixture),[dark,setDark]=useState(true),timer=useRef<ReturnType<typeof setInterval>>();
  useEffect(()=>startupReady(),[]);
  useEffect(()=>{document.documentElement.classList.toggle('dark',dark);document.documentElement.classList.toggle('light',!dark);},[dark]);
  useEffect(()=>()=>clearInterval(timer.current),[]);
  function append(text:string){setState(previous=>({...previous,revision:(previous.revision||0)+1,messages:previous.messages.map(item=>item.id==='ui-answer'?{...item,text:item.text+text}:item)}));}
  function burst(){clearInterval(timer.current);let count=0;timer.current=setInterval(()=>{append('连续新增👩🏽‍💻');if(++count===30)clearInterval(timer.current);},20);}
  return <div className="tebb-workspace" style={{height:'100%',display:'flex',flexDirection:'column'}}>
    <header style={{display:'flex',gap:12,flexWrap:'wrap',padding:12,background:'hsl(var(--card))'}}>
      <span>开发验收：合成资料，不连接后端</span>
      <button type="button" onClick={()=>setDark(value=>!value)}>切换深浅主题</button>
      <button type="button" onClick={()=>append('你好👩🏽‍💻e\u0301')}>追加字素</button>
      <button type="button" onClick={burst}>高速追加</button>
      <button type="button" onClick={()=>append('\n\n'+('长回复保留正文、换行与阅读位置。\n\n').repeat(600)+'末尾新增内容')}>追加长回复</button>
      <button type="button" onClick={()=>{clearInterval(timer.current);setState(previous=>({...previous,runs:previous.runs.map(run=>({...run,state:'succeeded'}))}));}}>完成回复</button>
      <button type="button" onClick={()=>{clearInterval(timer.current);setState(fixture());}}>重置样例</button>
    </header>
    <ChatPrototype live={{state,act:async()=>false,busy:false,error:''}}/>
  </div>;
}
