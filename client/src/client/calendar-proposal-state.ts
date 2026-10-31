export type CalendarProposal={kind:'calendar_proposal';version:1;id:string;save_request_id:string;source:{task_id:string;run_id:string};summary:string;start:string;end:string;item_id:string;timezone:'Asia/Shanghai'};
export function calendarProposal(value:unknown):CalendarProposal{
  const p=value as CalendarProposal;const ident=(value:unknown)=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,200}$/.test(value);
  if(!p||p.kind!=='calendar_proposal'||p.version!==1||!/^[a-f0-9]{32}$/.test(p.id)||!/^[a-f0-9]{32}$/.test(p.save_request_id)||!p.source||!ident(p.source.task_id)||typeof p.source.run_id!=='string'||p.source.run_id!==''&&!ident(p.source.run_id)||p.timezone!=='Asia/Shanghai'||typeof p.summary!=='string'||!p.summary.trim()||typeof p.item_id!=='string'||p.item_id!==''&&!ident(p.item_id))throw Error('结构化日程提案未核实。');
  if([p.start,p.end].some(value=>typeof value!=='string'||!/(?:Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))||Date.parse(p.end)<=Date.parse(p.start))throw Error('日程提案时间无效。');
  return p;
}
export function proposalsFromEvents(events:readonly{kind:string;data:unknown}[]){
  const result:CalendarProposal[]=[];
  for(const event of events){if(event.kind!=='calendar_proposal')continue;try{const proposal=calendarProposal((event.data as{proposal?:unknown})?.proposal);if(!result.some(row=>row.id===proposal.id))result.push(proposal);}catch{/* Invalid task events never become UI actions. */}}
  return result;
}
export function proposalTree(run:{id:string}|undefined,runs:readonly{id:string;parent?:string;calendar_proposals?:CalendarProposal[]}[]){
  if(!run)return[];const ids=new Set([run.id]);let size=0;
  while(size!==ids.size){size=ids.size;for(const row of runs)if(row.parent&&ids.has(row.parent))ids.add(row.id);}
  const result:CalendarProposal[]=[];for(const row of runs)if(ids.has(row.id))for(const value of row.calendar_proposals||[])try{const proposal=calendarProposal(value);if(!result.some(p=>p.id===proposal.id))result.push(proposal);}catch{}
  return result;
}
