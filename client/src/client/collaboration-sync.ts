import { useEffect } from 'react';
import { runActive, type DemoState } from './chat-prototype-state';
import { rpc, watchCollaboration, type BackendInfo } from './api';
export type CollaborationUpdate = {state?:DemoState;sync?:string;patch?:{base:string;values:Partial<DemoState>;collections:Record<string,{upsert:{id:string}[];order:string[]}>}};
const legacy = new Set<string>();
export async function loadCollaboration(info:BackendInfo,since:string) {
  const key=`${info.port}:${info.scope || ''}`;
  try{return await rpc<CollaborationUpdate>(info,'load_collaboration',legacy.has(key)?{}:{since},{timeoutMs:12000});}
  catch(error){
    // A source hot reload may precede a Python restart. Keep the old backend usable.
    if(!String(error).includes('unexpected keyword') || !String(error).includes('since'))throw error;
    legacy.add(key);return rpc<CollaborationUpdate>(info,'load_collaboration',{}, {timeoutMs:12000});
  }
}

// 把推送的累计正文写到对应任务、其根任务的链式回答和消息气泡上。
function applyText(state:DemoState,runId:string,text:string):DemoState {
  const runs=state.runs.map(run=>{
    if(run.id===runId){
      // 链式回答仍在展示本任务正文时才覆盖，避免抢掉交付阶段的最终正文。
      const chain=run.chain&&run.chain.answer===(run.answer||'')?{...run.chain,answer:text}:run.chain;
      return {...run,answer:text,chain};
    }
    // 根任务的链式回答等于子任务正文，同步覆盖，消息气泡才不会停在旧文本。
    if(run.chain?.children.includes(runId))return {...run,chain:{...run.chain,answer:text}};
    return run;
  });
  const messages=state.messages.map(message=>message.run===runId&&message.sender!=='user'?{...message,text}:message);
  return {...state,runs,messages};
}

export class CollaborationSync {
  state:DemoState | null = null;
  sync = '';
  private streams = new Map<string,string>();
  snapshot(state:DemoState, sync='') {
    if (this.state && (state.revision || 0) < (this.state.revision || 0)) return null;
    const merged=this.mergeStreams(state);
    this.state=merged;this.sync=sync;return merged;
  }
  update(reply:CollaborationUpdate) {
    if (reply.state) return this.snapshot(reply.state,reply.sync);
    if (!this.state || !reply.patch || reply.patch.base!==this.sync) return null;
    const next={...this.state,...reply.patch.values};
    for(const [key,collection] of Object.entries(reply.patch.collections)) {
      const rows=new Map(((this.state as unknown as Record<string,{id:string}[]>)[key] || []).map(row=>[row.id,row]));
      for(const row of collection.upsert)rows.set(row.id,row);
      const ordered=collection.order.map(id=>rows.get(id));
      if(ordered.some(row=>!row)){this.sync='';return null;}
      (next as unknown as Record<string,unknown>)[key]=ordered;
    }
    return this.snapshot(next,reply.sync);
  }
  /** 推送正文先落盘到本地状态；轮询快照随后到达时保留更长的正文。 */
  stream(runId:string,text:string) {
    this.streams.set(runId,text);
    if(!this.state)return null;
    this.state=applyText(this.state,runId,text);
    return this.state;
  }
  private mergeStreams(state:DemoState) {
    let next=state;
    for(const [runId,text] of [...this.streams]){
      const run=next.runs.find(row=>row.id===runId),answer=run?.answer||'';
      // 任务结束后以快照为准；快照已比推送更完整时也以快照为准。
      if(!run||!runActive(run)||answer.length>text.length){this.streams.delete(runId);continue;}
      if(answer===text){this.streams.delete(runId);continue;}
      next=applyText(next,runId,text);
    }
    return next;
  }
}

/** 订阅协作正文推送，与 400ms 快照轮询并行工作。 */
export function useCollaborationStream(info:BackendInfo|null,sync:CollaborationSync,onState:(state:DemoState)=>void) {
  const port=info?.port,token=info?.token;
  useEffect(()=>{
    if(port===undefined||token===undefined)return;
    return watchCollaboration({port,token},(run,text)=>{
      const next=sync.stream(run,text);
      if(next)onState(next);
    });
  },[port,token]);
}
