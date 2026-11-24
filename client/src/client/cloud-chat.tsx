import { useEffect, useMemo, useRef, useSyncExternalStore, type ReactNode } from 'react';
import { cloudMessage, readEvents, type BackendInfo } from './api';
import { accountStorage, accountStorageKey } from './account-storage';

type Turn = {created?: number; id: string; text: string; answer: string; state: string; error: string};
type Pending = {request_id: string; text: string};

function stored(key: string) {
  try { return JSON.parse(accountStorage().getItem(key) || 'null'); }
  catch { return null; }
}

function isTurn(row: unknown): row is Turn {
  return !!row && typeof row === 'object' && ['id','text','answer','state','error'].every(
    key => typeof (row as Record<string,unknown>)[key] === 'string');
}

// A pending POST may finish after navigation. Keep its receipt with its original conversation.
function openSession(conversation: string, available: boolean) {
  const historyKey = 'tebb.cloud.history.' + conversation;
  const pendingKey = 'tebb.cloud.pending.' + conversation;
  const history = available ? stored(historyKey) : null;
  const pending = available ? stored(pendingKey) : null;
  let snapshot = {
    turns: (Array.isArray(history) ? history.filter(isTurn) : []) as Turn[],
    pending: (typeof pending?.request_id === 'string' && typeof pending.text === 'string' ? pending : null) as Pending | null,
    sending: false, sendError: '', connectionError: '', cacheError: ''
  };
  type Snapshot = typeof snapshot;
  const listeners = new Set<() => void>();
  function update(change: Partial<Snapshot>) {
    snapshot = {...snapshot, ...change};
    listeners.forEach(listener => listener());
  }
  function merge(row: Turn) {
    const old = snapshot.turns.find(turn => turn.id === row.id);
    if (old?.created && !row.created) row = {...row, created: old.created};
    if (old && old.created === row.created && old.text === row.text && old.answer === row.answer && old.state === row.state && old.error === row.error) return;
    const turns = old ? snapshot.turns.map(turn => turn.id === row.id ? row : turn) : [...snapshot.turns, row];
    let cacheError = '';
    try { accountStorage().setItem(historyKey, JSON.stringify(turns)); }
    catch { cacheError = '本机空间不足或不可写，本次记录仅在当前窗口保留。'; }
    update({turns, cacheError});
  }
  return {
    read: () => snapshot,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    update, merge, pendingKey
  };
}

export function useCloudChat(info: BackendInfo | undefined | null, conversation: string, listen: boolean) {
  const sessions = useRef(new Map<string, ReturnType<typeof openSession>>());
  const available = !!info && !info.scope;
  const key = available ? accountStorageKey(conversation) : '';
  const session = useMemo(() => {
    let entry = sessions.current.get(key);
    if (!entry) { entry = openSession(conversation, available); sessions.current.set(key, entry); }
    return entry;
  }, [key, conversation, available]);
  const snapshot = useSyncExternalStore(session.subscribe, session.read, session.read);
  const port = info?.port, token = info?.token;
  useEffect(() => {
    if (!available || !listen || !port || !token) return;
    const transport = {port, token};
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function sync() {
      try {
        await readEvents(transport, '/desktop/cloud/events?conversation='+encodeURIComponent(conversation), event => {
          if (controller.signal.aborted) return;
          if (session.read().connectionError) session.update({connectionError: ''});
          if (event.type === 'turn' && isTurn(event.data)) session.merge(event.data);
        }, controller.signal);
      } catch (e) {
        if (!controller.signal.aborted) session.update({connectionError: e instanceof Error ? e.message : '云端连接中断'});
      }
      if (!controller.signal.aborted) timer = setTimeout(sync, 3000);
    }
    void sync();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [session, available, listen, conversation, port, token]);

  async function send(draft: string, projectId: string | undefined, accepted: (text:string) => void) {
    const current = session.read();
    if (!info || current.sending) return;
    const message = current.pending || {request_id: crypto.randomUUID(), text: draft.trim()};
    if (!message.text) return;
    session.update({sending: true, sendError: ''});
    try {
      accountStorage().setItem(session.pendingKey, JSON.stringify(message));
      session.update({pending: message});
      const id = await cloudMessage(info, {...message, conversation, project_id: projectId});
      if (!session.read().turns.some(row => row.id === id))
        session.merge({id, created: Date.now()/1000, text: message.text, answer: '', state: 'queued', error: ''});
      accountStorage().removeItem(session.pendingKey);
      session.update({pending: null});
      accepted(message.text);
    } catch (e) {
      session.update({sendError: (e instanceof Error ? e.message : '发送结果未知') + ' 请求编号 ' + message.request_id});
    } finally { session.update({sending: false}); }
  }
  return {...snapshot, send};
}

export function CloudTurn({turn}: {turn: Turn}) {
  return <article className="cp-message">
    <div className="cp-message-content">
      <div className="cp-message-author"><strong>你 · 云端</strong></div>
      <p className="whitespace-pre-wrap">{turn.text}</p>
      <div className="cp-message-author"><strong>tebb · 云端</strong></div>
      <p className="whitespace-pre-wrap">{turn.answer || turn.error || ({queued:'等待执行',running:'正在回答'}[turn.state] || turn.state)}</p>
      {turn.error && turn.answer && <p role="alert">{turn.error}</p>}
      <small>任务 {turn.id}</small>
    </div>
  </article>;
}

export function CloudComposer({chat, executionPicker, draft, setDraft, submit}: {
  chat: ReturnType<typeof useCloudChat>; executionPicker: ReactNode; draft: string; setDraft:(text:string)=>void; submit:()=>void
}) {
  const text = chat.pending?.text ?? draft;
  return <div className="cp-compose-area">
    {chat.sendError && <p role="alert">{chat.sendError}</p>}
    <form className="cp-composer" onSubmit={event => { event.preventDefault(); submit(); }}>
      <textarea aria-label="云端消息" rows={2} maxLength={4000} readOnly={!!chat.pending || chat.sending} value={text}
        onChange={event => setDraft(event.target.value)} placeholder="给云端 tebb 发消息" onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
            event.preventDefault(); submit();
          }
        }}/>
      <div className="cp-composer-bottom">
        <div className="cp-composer-controls"><span>Qwen · 免费</span>{executionPicker}</div>
        <button className="cp-send" type="submit" disabled={chat.sending || !text.trim()}>{chat.pending && !chat.sending ? '重试原消息' : '发送'}<span>↑</span></button>
      </div>
    </form>
  </div>;
}
