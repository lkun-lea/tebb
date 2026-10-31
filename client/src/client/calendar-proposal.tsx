import{useState}from'react';
import{rpc,type BackendInfo}from'./api';
import{calendarProposal,type CalendarProposal}from'./calendar-proposal-state';
import{openCalendarProposal,type ProposalResult}from'./calendar-proposal-navigation';
import{UiButton}from'./ui-controls';
import'./calendar-proposal.css';

export function CalendarProposalCards({proposals,info}:{proposals:readonly CalendarProposal[];info:BackendInfo|null|undefined}){
  return <>{proposals.map(value=>{try{const proposal=calendarProposal(value);return <ProposalCard key={proposal.id} proposal={proposal} info={info}/>;}catch{return <p role="alert" key={String(value?.id)}>提案格式未核实，未打开草稿。</p>;}})}</>;
}
function ProposalCard({proposal,info}:{proposal:CalendarProposal;info:BackendInfo|null|undefined}){
  const[busy,setBusy]=useState(false),[result,setResult]=useState<ProposalResult|null>(null),[error,setError]=useState('');
  async function open(){if(!info||busy)return;setBusy(true);setError('');try{
    const value=await rpc<ProposalResult>(info,'read_calendar_proposal',{task_id:proposal.source.task_id,proposal_id:proposal.id});setResult(value);
    if(!value.ok)throw Error(value.error||'原保存结果待核对。');
    if(['proposed','saved'].includes(value.state))await openCalendarProposal(proposal.source.task_id,proposal.id);
  }catch(error){setError(String(error));}finally{setBusy(false);}}
  return <section className="calendar-proposal-card" aria-label="日程提案"><strong>{proposal.summary}</strong>
    <p>{proposal.start.replace('T',' ')} → {proposal.end.replace('T',' ')} · 北京时间</p><p>{result?.state==='saved'?'此提案已保存，打开现有安排。':result?.notice||'提案尚未保存，打开后可调整。'}</p>
    <UiButton busy={busy} busyLabel="核对原提案…" disabled={!info||info.scope==='collaboration'||result?.state==='consumed'} onClick={()=>void open()}>{result?.state==='saved'?'查看已保存安排':result?.state==='consumed'?'此提案已使用':result?.state==='unconfirmed'?'核对原保存结果':'打开日程草稿'}</UiButton>
    {info?.scope==='collaboration'&&<p>请在桌面工作台打开此提案。</p>}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
