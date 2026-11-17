import { useEffect } from 'react';
import { runActive, type DemoState } from './chat-prototype-state';
import { rpc, watchCollaboration, type BackendInfo, type CollaborationTextVersion } from './api';
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
    const chain = run.chain?.answer_run === runId ? {...run.chain, answer:text} : run.chain;
    if (run.id === runId) return {...run, answer:text, chain};
    if (chain !== run.chain) return {...run, chain};
    return run;
  });
  const messages=state.messages.map(message=>message.run===runId&&message.sender!=='user'?{...message,text}:message);
  return {...state,runs,messages};
}

function newer(version: CollaborationTextVersion, previous: CollaborationTextVersion) {
  return version[0] > previous[0] || version[0] === previous[0] && version[1] > previous[1];
}

export class CollaborationSync {
  // 只用服务端快照作为后续补丁的基线。
  state:DemoState | null = null;
  sync = '';
  private streams = new Map<string,{text:string;version:CollaborationTextVersion}>();
  snapshot(state:DemoState, sync='') {
    if (this.state && (state.revision || 0) < (this.state.revision || 0)) return null;
    for (const runId of this.streams.keys()) {
      if (this.state?.runs.some(run=>run.id===runId) && !state.runs.some(run=>run.id===runId)) this.streams.delete(runId);
    }
    this.state=state;this.sync=sync;return this.mergeStreams(state);
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
  stream(runId:string,text:string,version:CollaborationTextVersion) {
    const previous = this.streams.get(runId);
    if (previous && !newer(version,previous.version)) return null;
    this.streams.set(runId,{text,version});
    if (this.streams.size > 100) {
      const oldest = this.streams.keys().next();
      if (!oldest.done) this.streams.delete(oldest.value);
    }
    return this.state && this.mergeStreams(this.state);
  }
  private mergeStreams(state:DemoState) {
    let next=state;
    for(const [runId,{text,version}] of this.streams){
      const run=state.runs.find(row=>row.id===runId);
      if (!run) continue;
      const snapshotVersion=run.text_version ?? [0,0];
      // 新阶段开始前先显示快照，待对应的任务出现在快照中再应用推送。
      if (version[0] > snapshotVersion[0]) continue;
      if (!runActive(run) || !newer(version,snapshotVersion)) { this.streams.delete(runId);continue; }
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
    return watchCollaboration({port,token},(run,text,version)=>{
      const next=sync.stream(run,text,version);
      if(next)onState(next);
    });
  },[port,token,sync,onState]);
}
