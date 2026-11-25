import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
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
      const status = (e as {status?:number})?.status;
      if (status === 413 || status === 422) {
        accountStorage().removeItem(session.pendingKey);
        session.update({pending:null, sendError:e instanceof Error ? e.message : '消息未提交'});
      } else {
        session.update({sendError: (e instanceof Error ? e.message : '发送结果未知') + ' 请求编号 ' + message.request_id});
      }
    } finally { session.update({sending: false}); }
  }
  return {...snapshot, send};
}
