import assert from 'node:assert/strict';
import { createInterface } from 'node:readline';
import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { Agent } from '@earendil-works/pi-agent-core';
import { normalizeContext } from '@earendil-works/pi-ai';
import { stream, streamSimple } from '@earendil-works/pi-ai/api/openai-completions';
import { Agent as HttpAgent, EnvHttpProxyAgent, ProxyAgent, fetch } from 'undici';
import { runProductAgent } from './chat_agent.mjs';

assert.equal(process.version, 'v24.22.3');
const packageFile = name => new URL(`node_modules/@earendil-works/${name}/package.json`, import.meta.url);
for (const name of ['pi-agent-core', 'pi-ai', 'pi-schema']) {
  assert.equal(JSON.parse(await readFile(packageFile(name), 'utf8')).version, '1.5.2');
}
const emit = (id, type, data) => process.stdout.write(JSON.stringify({ v: 1, id, type, data }) + '\n');
let active;
const pending = new Map();
let serial = 0;
function ask(id, type, data) {
  const ticket = String(++serial);
  return new Promise((resolve, reject) => {
    pending.set(ticket, { resolve, reject });
    emit(id, type, { ...data, ticket });
  });
}
function cancel() {
  active?.abort.abort();
  active?.agent?.abort();
  for (const request of pending.values()) request.reject(new Error('cancelled'));
  pending.clear();
}
function proxyUrl(value) {
  // Undici's SOCKS5 implementation sends hostnames to the proxy (remote DNS).
  return value?.replace(/^socks5h:/i, 'socks5:');
}
async function transport(policy, baseUrl) {
  const ca = [];
  if (policy?.ca_file) ca.push(await readFile(policy.ca_file, 'utf8'));
  if (policy?.ca_dir) {
    for (const entry of await readdir(policy.ca_dir, { withFileTypes: true })) {
      if (entry.isFile() || entry.isSymbolicLink()) {
        const text = await readFile(join(policy.ca_dir, entry.name), 'utf8');
        if (text.includes('-----BEGIN CERTIFICATE-----')) ca.push(text);
      }
    }
  }
  const tls = ca.length ? { ca } : {};
  const options = { connect: tls, requestTls: tls, connectTimeout: 5000 };
  if (policy?.mode === 'direct') return new HttpAgent(options);
  if (!policy || policy.mode === 'system') {
    const proxies = policy?.system_proxies;
    const httpProxy = proxyUrl(proxies ? proxies.http ?? proxies.all : process.env.http_proxy ?? process.env.HTTP_PROXY ?? process.env.all_proxy ?? process.env.ALL_PROXY);
    const httpsProxy = proxyUrl(proxies ? proxies.https ?? proxies.all : process.env.https_proxy ?? process.env.HTTPS_PROXY ?? process.env.all_proxy ?? process.env.ALL_PROXY);
    const selected = new URL(baseUrl).protocol === 'https:' ? httpsProxy : httpProxy;
    // SOCKS is plain TCP; passing even an empty proxyTls object enables TLS to it.
    // Match HTTPX's scheme-specific selection; its HTTP proxy does not cover HTTPS.
    return new EnvHttpProxyAgent({ ...options, httpProxy: selected || '', httpsProxy: selected || '', noProxy: proxies?.no,
      ...(selected?.startsWith('https:') ? { proxyTls: tls } : {}),
    });
  }
  if (policy.mode === 'custom') {
    const target = new URL(proxyUrl(policy.proxy_url));
    if (policy.username || policy.password) { target.username = policy.username || ''; target.password = policy.password || ''; }
    return new ProxyAgent({ ...options, uri: target.toString(),
      ...(target.protocol === 'https:' ? { proxyTls: tls } : {}),
    });
  }
  throw new Error('Unsupported network policy');
}

async function execute(command) {
  const { id, data, type } = command;
  const abort = new AbortController();
  active = { id, abort };
  let dispatcher;
  const deadline = setTimeout(cancel, data.timeout_ms);
  try {
    dispatcher = await transport(data.network, data.model.baseUrl);
    const model = data.model;
    const usage = { reported: false };
    let modelCalls = 0;
    const common = {
      ...data.options, apiKey: data.api_key, maxRetries: 0,
      timeoutMs: data.call_timeout_ms || data.timeout_ms, signal: abort.signal,
      fetch: async (url, init) => {
        const response = await fetch(url, { ...init, dispatcher });
        emit(id, 'http_status', { call_id: modelCalls, status: response.status });
        if (!response.ok && data.observe_provider) {
          emit(id, 'provider_error', { body: await response.clone().text() });
        }
        return response;
      },
      onPayload: async body => {
        usage.reported = false;
        delete usage.raw;
        // The product owns verified generation bindings; Pi defaults cannot invent one.
        if (data.wire_options || data.product_gate) {
          delete body.max_tokens; delete body.max_completion_tokens;
          Object.assign(body, data.wire_options);
        }
        // Apply verified transport bindings before admission/observation.
        if (data.tool_stream) body.tool_stream = true;
        const allowed = await ask(id, 'before_model', { model: model.id, payload: body, call_id: ++modelCalls });
        if (!allowed.ok || abort.signal.aborted) throw new Error('Model admission denied');
        return allowed.payload || body;
      },
      onProviderStreamEvent: event => {
        if (data.observe_provider) emit(id, 'provider_frame', event);
        if (event.usage) { usage.reported = true; usage.raw = event.usage; emit(id, 'provider_usage', { call_id: modelCalls, usage: event.usage }); }
      },
    };
    let message;
    if (type === 'complete') {
      const output = stream(model, normalizeContext(data.context), common);
      for await (const event of output) {
        if (event.type === 'text_delta' || event.type === 'thinking_delta') emit(id, event.type, event.delta);
      }
      message = await output.result();
    } else if (data.product_gate) {
      message=await runProductAgent({ id,data,model,common,ask,emit,active,usage });
    } else {
      const tools = (data.tools || []).map(tool => ({ ...tool, label: tool.name,
        execute: async (callId, args) => {
          if (abort.signal.aborted) throw new Error('cancelled');
          const receipt = await ask(id, 'tool_call', { name: tool.name, call_id: callId, arguments: args });
          if (!receipt.ok) throw new Error('Tool denied or failed');
          return { content: [{ type: 'text', text: JSON.stringify(receipt.result) }], details: receipt.result };
        },
      }));
      const agent = new Agent({ initialState: { model, tools, systemPrompt: data.context.systemPrompt || '',
        messages: data.context.messages || [], thinkingLevel: data.thinking_level || 'low' },
        streamFn: (current, context, config) => streamSimple(current, context, { ...config, ...common }),
      });
      active.agent = agent;
      agent.subscribe(event => {
        if (event.type === 'message_update') {
          const change = event.assistantMessageEvent;
          if (change.type === 'text_delta' || change.type === 'thinking_delta') emit(id, change.type, change.delta);
        }
        if (event.type === 'tool_execution_start' || event.type === 'tool_execution_end') {
          emit(id, event.type, { call_id: event.toolCallId, name: event.toolName, is_error: event.isError });
        }
      });
      await agent.prompt(data.prompt);
      message = agent.state.messages.filter(row => row.role === 'assistant').at(-1);
    }
    // Error text and provider payloads never cross the public error boundary.
    const clean = structuredClone(message);
    delete clean.errorMessage;
    emit(id, 'result', { message: clean, usage_reported: usage.reported,
      provider_usage: usage.raw,
      cost_known: data.cost_known === true && usage.reported,
      model_calls: modelCalls, cancelled: abort.signal.aborted });
  } catch {
    emit(id, 'error', { cancelled: abort.signal.aborted, message: 'Pi process call did not complete.' });
  } finally {
    clearTimeout(deadline);
    cancel();
    await dispatcher?.destroy();
    active = undefined;
  }
}

emit('', 'ready', { node: process.version, pi: '1.5.2', protocol: 1 });
const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on('line', line => {
  try {
    const command = JSON.parse(line);
    if (command.v !== 1) throw new Error('Invalid protocol');
    if (command.type === 'cancel' && command.id === active?.id) { cancel(); return; }
    if (command.type === 'reply' && command.id === active?.id) {
      const request = pending.get(command.ticket);
      if (request) { pending.delete(command.ticket); request.resolve(command.data); }
      return;
    }
    if (active || !['complete', 'agent'].includes(command.type)) throw new Error('Invalid call');
    void execute(command);
  } catch { emit('', 'protocol_error', { message: 'Invalid private process message.' }); }
});
lines.on('close', () => { cancel(); process.exitCode = 0; });
