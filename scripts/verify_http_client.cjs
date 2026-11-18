// Execute the actual client transport against the isolated headless product service.
const fs = require('node:fs');
const load = require('../client/tests/load-client.cjs');
const api = load('api.ts', { '@tauri-apps/api/core': {} });
const info = JSON.parse(fs.readFileSync(0, 'utf8'));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const pages = [], errors = [];
  const refresh = () => {
    api.rpc(info, 'load_work_board').then(page => pages.push(page)).catch(error => errors.push(error.message));
  };
  let stop = api.watchWorkBoard(info, refresh);
  try {
    for (let i = 0; i < 100 && !pages.length; i++) await delay(50);
    if (!pages.length) throw Error('No initial HTTP/SSE board snapshot');
    const page = await api.rpc(info, 'change_work_item', { action: {
      type: 'create', request_id: crypto.randomUUID(), fields: { title: 'isolated-http-client' },
    } });
    if (!page.ok) throw Error('Board mutation failed');
    const id = page.items.find(item => item.title === 'isolated-http-client')?.id;
    // Ordinary UI writes return their own snapshot; partner writes broadcast.
    // Reconnect must independently recover the committed ordinary UI change.
    stop(); stop = api.watchWorkBoard(info, refresh);
    for (let i = 0; i < 100 && !pages.some(page => page.items.some(item => item.id === id)); i++) await delay(50);
    if (!pages.some(page => page.items.some(item => item.id === id))) throw Error('Board change not recovered after SSE reconnect');
    const tokens = [];
    const answer = await new Promise((resolve, reject) => api.streamChat(info, 'offline question',
      { reasoning_effort: 'low', temperature: .5, top_p: 1 }, { skills: [], cli: [], github: '' }, '', {
        onToken: piece => tokens.push(piece), onSnapshot: text => { tokens.length = 0; tokens.push(text); },
        onThink() {}, onStatus() {}, onDone: resolve, onError: message => reject(Error(message)),
      }));
    if (answer !== '本地流式回归正常。') throw Error('Unexpected final answer');
    const history = await api.rpc(info, 'load_chat_log');
    if (history.items.length !== 2 || history.items[1].text !== answer) throw Error('History mismatch');
    const tasks = await api.rpc(info, 'list_agent_tasks');
    const task = tasks.items.find(value => value.source?.transport === 'http');
    if (!task || task.state !== 'succeeded' || !task.source.request_id) throw Error('Task identity or final state mismatch');
    const record = await fetch(`http://127.0.0.1:${info.port}/v1/runs/${task.id}`, { headers: { Authorization: `Bearer ${info.token}` } });
    if (!record.ok) throw Error('Task snapshot unavailable');
    const snapshot = await record.json();
    const tools = snapshot.events.filter(event => event.kind === 'tool_end');
    if (snapshot.task.answer !== answer || tools.length !== 1 || tools[0].data.tool !== 'channel_lookup') throw Error('Task snapshot or actual tool receipt mismatch');
    if (errors.length) throw Error('Notification read failure');
    process.stdout.write(JSON.stringify({ status: 'passed', node: process.version, checks: {
      authenticated_http_rpc: true, board_sse_reconnect_snapshot: true, task_chat_sse: true, final_answer: true, persisted_history: true,
    }, request_id: task.source.request_id, run_id: task.id, board_snapshots: pages.length, stream_tokens: tokens.length,
      persisted: { state: snapshot.task.state, answer: snapshot.task.answer, cursor: snapshot.cursor,
        events: snapshot.events.map(event => ({ seq: event.seq, kind: event.kind })),
        tool_receipts: tools.map(event => event.data) } }));
  } finally { stop(); }
})().catch(error => { process.stderr.write(error.message); process.exitCode = 1; });
