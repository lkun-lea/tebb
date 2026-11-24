import { invoke } from "@tauri-apps/api/core";
import type { Sampling } from "./sampling";

export type BackendInfo = { port: number; token: string; scope?: "collaboration" };

export type ChatItem = {
  role: string;
  text: string;
  ts?: string;
  notes?: string[];
  knowledge?: {
    subagent: string;
    question: string;
    candidates: { doc: string; title: string; score: number; text: string }[];
    kept: { doc: string; title: string; score: number; text: string }[];
    answer?: string;
  };
  thinking?: string;
  elapsed_s?: number;
  react_loops?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  model?: string;
  reasoning_effort?: string;
  temperature?: number;
  top_p?: number;
};

export type SessionItem = {
  id: string;
  title: string;
  updated: string;
  count: number;
};

type RpcEnvelope<T> = { ok: boolean; result?: T; error?: string };
export type CollaborationTextVersion = [attempt: number, event: number];

export async function backendInfo(): Promise<BackendInfo> {
  return invoke<BackendInfo>("backend_info");
}

export type StreamHandlers = {
  onToken: (piece: string) => void;
  onSnapshot?: (text: string) => void;
  onThink: (piece: string) => void;
  onStatus: (text: string) => void;
  onDone: (answer: string) => void;
  onError: (message: string) => void;
  onKnowledge?: (trace: ChatItem["knowledge"]) => void;
  onCalendarProposal?:(event:unknown)=>void;
};

export type ChatChips = { skills: string[]; cli: string[]; github: string; attachments?: string[] };

export type NotebookDone = {
  answer: string;
  cites: {
    n: number;
    doc: string;
    title: string;
    text: string;
    doc_id: string;
    context?: string;
  }[];
};

export type NotebookFailure = Partial<NotebookDone> & { answer_complete?: boolean };

const url = (info: BackendInfo, path: string) => `http://127.0.0.1:${info.port}${path}`;
const headers = (info: BackendInfo) => ({ Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' });

async function response(info: BackendInfo, path: string, init: RequestInit = {}): Promise<Response> {
  const result = await fetch(url(info, path), { ...init, headers: { ...headers(info), ...init.headers }, cache: 'no-store' });
  if (!result.ok) {
    let message = `后台请求失败（${result.status}），请核对原操作结果。`;
    try { message = (await result.json()).detail || message; } catch { /* Keep the status on a non-JSON failure. */ }
    throw new Error(String(message));
  }
  return result;
}

export async function fetchCloudTools(info: BackendInfo): Promise<{available:number;loaded:number}> {
  return (await response(info, '/desktop/cloud/tools',{method:'POST'})).json();
}

export async function cloudMessage(info: BackendInfo, message: {request_id: string; text: string; conversation?:string; project_id?:string}) {
  const reply = await response(info, '/desktop/cloud/messages', {method: 'POST', body: JSON.stringify(message)});
  const receipt = await reply.json();
  if (receipt.request_id !== message.request_id || !/^[a-f0-9]{32}$/.test(receipt.run_id))
    throw new Error('云端回执无效，请重试原消息。');
  return receipt.run_id as string;
}

export async function rpc<T>(info: BackendInfo, method: string, args: Record<string, unknown> = {},
  options: { timeoutMs?: number } = {}): Promise<T> {
  const controller = new AbortController();
  const timer = options.timeoutMs ? setTimeout(() => controller.abort(), options.timeoutMs) : undefined;
  try {
    const reply = await response(info, '/rpc', { method: 'POST', body: JSON.stringify({ method, args }), signal: controller.signal });
    let envelope: RpcEnvelope<T>;
    try { envelope = await reply.json(); } catch { throw new Error('本地后端返回了无法解析的结果，请查看日志。'); }
    if (envelope?.ok !== true) throw new Error(envelope?.error || 'RPC 失败，请核对原操作结果。');
    return envelope.result as T;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('调用超时，已停止等待；操作可能仍在执行，请先核查结果。');
    if (error instanceof TypeError) throw new Error('连接已断开，尚未收到操作结果；请先核查是否已执行。');
    throw error;
  } finally { clearTimeout(timer); }
}

type EventFrame = { type: string; data: any };

/** Fetch supports Authorization headers; SSE IDs are acknowledged only after delivery. */
export async function readEvents(info: BackendInfo, path: string, receive: (event: EventFrame, id?: number) => void,
  signal: AbortSignal): Promise<void> {
  const reply = await response(info, path, { signal, headers: { Accept: 'text/event-stream' } });
  if (!reply.headers.get('Content-Type')?.startsWith('text/event-stream') || !reply.body) throw new Error('无法解析后端事件流。');
  const reader = reply.body.getReader(), decoder = new TextDecoder();
  let buffer = '';
  try {
    while (!signal.aborted) {
      const part = await reader.read();
      if (part.done) break;
      buffer += decoder.decode(part.value, { stream: true });
      if (buffer.length > 2_000_000) throw new Error('无法解析过大的后端事件。');
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, match.index); buffer = buffer.slice(match.index + match[0].length);
        const lines = block.split(/\r?\n/);
        const payload = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (!payload || signal.aborted) continue;
        const rawId = lines.find(line => line.startsWith('id:'))?.slice(3).trim();
        const id = rawId === undefined ? undefined : Number(rawId);
        if (id !== undefined && (!Number.isSafeInteger(id) || id < 0)) throw new Error('无法解析事件游标。');
        let event: EventFrame;
        try { event = JSON.parse(payload); } catch { throw new Error('无法解析后端事件。'); }
        if (typeof event?.type !== 'string') throw new Error('无法解析后端事件。');
        receive(event, id);
      }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

function subscribe(info: BackendInfo, receive: (event: EventFrame) => void, topic: 'board' | 'collaboration', onDisconnect = () => {}): () => void {
  const controller = new AbortController();
  let retry: ReturnType<typeof setTimeout> | undefined;
  async function connect() {
    try { await readEvents(info, `/v1/notifications?topic=${topic}`, event => { if (!controller.signal.aborted) receive(event); }, controller.signal); }
    catch { /* Existing page polling still reads authoritative snapshots. */ }
    if (!controller.signal.aborted) { onDisconnect(); retry = setTimeout(connect, 1000); }
  }
  void connect();
  return () => { controller.abort(); clearTimeout(retry); };
}

export function watchWorkBoard(info: BackendInfo, refresh: () => void): () => void {
  let checked = false;
  return subscribe(info, event => { if (event.type === 'work_board_changed') { checked = true; refresh(); } }, 'board', () => {
    if (!checked) { checked = true; refresh(); }
  });
}

export function watchCollaboration(info: BackendInfo, onText: (run: string, text: string, version: CollaborationTextVersion) => void): () => void {
  return subscribe(info, event => {
    const value = event.data, version = value?.version;
    if (event.type === 'run_text' && typeof value?.run === 'string' && typeof value?.text === 'string'
      && Array.isArray(version) && version.length === 2 && version.every(Number.isSafeInteger)) onText(value.run, value.text, [version[0], version[1]]);
  }, 'collaboration');
}

type RunHandlers = {
  onToken: (piece: string) => void;
  onSnapshot?: (text: string) => void;
  onStatus: (text: string) => void;
  onThink?: (text: string) => void;
  onKnowledge?: (value: any) => void;
  onCalendarProposal?: (value: any) => void;
  onDone: (answer: string) => void;
  onError: (message: string, result?: NotebookFailure) => void;
};

function streamRun(info: BackendInfo, input: Record<string, unknown>, handlers: RunHandlers): () => void {
  const controller = new AbortController();
  const command = { ...input, request_id: crypto.randomUUID() };
  let cursor = 0, notebookResult: NotebookFailure | undefined, settled = false, replacePending = false;
  async function run() {
    try {
      // A lost submit response can be reconciled with this same ID, never a new question.
      let reply: Response;
      try { reply = await response(info, '/v1/runs', { method: 'POST', body: JSON.stringify(command), signal: controller.signal }); }
      catch (error) {
        if (!(error instanceof TypeError) || controller.signal.aborted) throw error;
        reply = await response(info, '/v1/runs', { method: 'POST', body: JSON.stringify(command), signal: controller.signal });
      }
      let run_id: string;
      try { ({ run_id } = await reply.json()); }
      catch { throw new Error('无法解析任务提交回执，后台可能已接收；请查询原任务，不要重复提交。'); }
      if (!/^[a-f0-9]{32}$/.test(run_id)) throw new Error('无法解析任务提交结果。');
      for (let attempt = 0; !settled && attempt < 3; attempt++) {
        try {
          await readEvents(info, `/v1/runs/${run_id}/events?after=${cursor}`, (event, id) => {
            if (settled || controller.signal.aborted || (id !== undefined && id <= cursor && event.type !== 'snapshot')) return;
            const data = event.data;
            if (event.type === 'snapshot') {
              notebookResult = data.events.find((row: any) => row.kind === 'notebook_result')?.data;
              handlers.onSnapshot?.(notebookResult?.answer || data.task.answer || '');
              replacePending = Boolean(data.replace_pending);
            } else if (event.type === 'token') {
              if (replacePending) { handlers.onSnapshot?.(String(data)); replacePending = false; }
              else handlers.onToken(String(data));
            }
            else if (event.type === 'answer_reset') replacePending = true;
            else if (event.type === 'think') handlers.onThink?.(String(data));
            else if (event.type === 'status') handlers.onStatus(String(data));
            else if (event.type === 'knowledge') handlers.onKnowledge?.(data);
            else if (event.type === 'calendar_proposal') handlers.onCalendarProposal?.(data);
            else if (event.type === 'notebook_result') notebookResult = data;
            else if (event.type === 'settled') {
              settled = true;
              if (data.task.state === 'succeeded') handlers.onDone(data.task.answer);
              else handlers.onError(data.task.error || '任务未完成，请核对原任务。', notebookResult);
              controller.abort();
            }
            if (id !== undefined) cursor = id;
          }, controller.signal);
        } catch (error) {
          if (settled || controller.signal.aborted) return;
          if (!(error instanceof TypeError)) throw error;
        }
      }
      if (!settled && !controller.signal.aborted) throw new Error('后台可能继续执行，请读取原任务与笔记核对；不要重复提交。');
    } catch (error) {
      if (!controller.signal.aborted && !settled) {
        settled = true;
        handlers.onError(error instanceof Error ? error.message : '后台可能继续执行，请核对原任务。', notebookResult);
      }
    }
  }
  void run();
  // Unsubscribe only. Cancellation remains an explicit product command.
  return () => controller.abort();
}

export function streamChat(info: BackendInfo, text: string, sampling: Sampling, chips: ChatChips, modelId: string,
  handlers: StreamHandlers, knowledge = false): () => void {
  return streamRun(info, { kind: 'chat', text, sampling, chips, model_id: modelId, knowledge }, handlers);
}

export function streamNotebook(info: BackendInfo, sessionId: string, text: string, docIds: string[], sampling: Sampling,
  handlers: { onToken: (piece: string) => void; onSnapshot?: (text: string) => void; onStatus: (text: string) => void;
    onDone: (result: NotebookDone) => void; onError: (message: string, result?: NotebookFailure) => void }): () => void {
  return streamRun(info, { kind: 'notebook', session_id: sessionId, text, doc_ids: docIds, sampling }, {
    ...handlers,
    onDone: answer => {
      let payload: NotebookDone;
      try {
        payload = JSON.parse(answer);
        if (typeof payload?.answer !== 'string' || !payload.answer.trim() || !Array.isArray(payload.cites)) throw Error();
      } catch { handlers.onError('无法解析笔记完成结果，请重新读取原笔记核对。'); return; }
      handlers.onDone(payload);
    },
  });
}
