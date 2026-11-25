import type { DemoState } from './chat-prototype-state';

/** Only project evidence already present in the visible workspace snapshot. */
export function conversationTimeline(state: DemoState, conversation: string) {
  const entries: {source: string; text: string; time?: number}[] = [];
  if (!state.conversations.some(chat => chat.id === conversation)) return entries;
  for (const message of state.messages) {
    if (message.conversation === conversation) entries.push({source: message.id, text: message.text, time: message.created});
  }
  for (const run of state.runs) {
    if (run.conversation !== conversation) continue;
    for (const event of run.flow_events || []) {
      if (event.kind !== 'file_change' || !event.data.path) continue;
      entries.push({source: run.id + ' · ' + event.seq, time: event.ts,
        text: event.data.path + ' · ' + (event.data.revision || '未记录版本')});
    }
    for (const receipt of run.project_receipts || []) {
      entries.push({source: run.id + ' · ' + receipt.call_id,
        text: receipt.tool + ' · ' + (receipt.ok ? '已确认' : receipt.error || '未完成')});
    }
    if (run.artifact) entries.push({source: run.id, time: run.finished, text: run.artifact});
  }
  return entries.sort((a, b) => (a.time ?? Infinity) - (b.time ?? Infinity));
}

export function ConversationTimeline({state, conversation}: {state: DemoState; conversation: string}) {
  const entries = conversationTimeline(state, conversation);
  return <section aria-label="留存的原文与回执">
    <p>按留存时间排列。未记录时间的材料列在末尾。</p>
    {entries.length ? <ol>{entries.map((entry, index) => <li key={index}>
      <small>{entry.time ? new Date(entry.time * 1000).toLocaleString() : '时间未知'} · {entry.source}</small>
      <p>{entry.text}</p></li>)}</ol> : <p>当前快照没有留存材料</p>}
  </section>;
}
