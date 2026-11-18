import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { Agent as PiAgent } from "@earendil-works/pi-agent-core";
import { normalizeContext } from "@earendil-works/pi-ai";
import { stream, streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import { Agent as HttpAgent, EnvHttpProxyAgent, ProxyAgent, fetch } from "undici";

const expectedNode = "v24.22.3";
assert.equal(process.version, expectedNode, "Run with the pinned Node executable");
const mode = process.argv[2] || "offline";
const report = { node: process.version, pi: "1.5.2", mode, cases: [] };
let inputText = "";
if (mode === "live") for await (const piece of process.stdin) inputText += piece;
const input = mode === "live" ? JSON.parse(inputText) : {};
const secrets = (input.models || []).flatMap(model => [model.api_key, model.base_url]);
const sanitize = value => secrets.reduce((text, secret) => secret ? text.split(secret).join("[redacted]") : text, String(value))
  .replace(/https?:\/\/[^\s"'<>]+/g, "[endpoint]");

async function persist() {
  report.passed = report.cases.filter(row => row.status === "passed").length;
  report.failed = report.cases.filter(row => row.status === "failed").length;
  if (process.argv[3]) await writeFile(process.argv[3], JSON.stringify(report, null, 2) + "\n");
}

async function run(id, test) {
  if (input.caseFilter && id !== input.caseFilter) return;
  const started = performance.now();
  try {
    const observed = await test();
    report.cases.push({ id, status: "passed", milliseconds: Math.round(performance.now() - started), ...observed });
  } catch (error) {
    report.cases.push({ id, status: "failed", milliseconds: Math.round(performance.now() - started),
      error: sanitize(error.message).slice(0, 700) });
  }
  await persist();
}

function model(id, baseUrl, preserve = false) {
  return {
    id, name: id, api: "openai-completions", provider: "tebb-probe", baseUrl, reasoning: true, input: ["text"],
    // These are synthetic probe limits. Product capacity and prices remain unverified.
    contextWindow: 8192, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    thinkingLevelMap: { max: "max" },
    compat: {
      supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: true,
      supportsUsageInStreaming: true, maxTokensField: "max_tokens",
      ...(preserve ? { thinkingFormat: "zai", requiresReasoningContentOnAssistantMessages: true } : {}),
    },
  };
}

const textOf = message => message.content.filter(block => block.type === "text").map(block => block.text).join("");
const user = text => ({ role: "user", content: text, timestamp: Date.now() });
const toolSchema = { type: "object", properties: { a: { type: "integer" }, b: { type: "integer" } },
  required: ["a", "b"], additionalProperties: false };
const declaredTool = { name: "probe_add", description: "Add two integers using this isolated read-only calculator.", parameters: toolSchema };

function options(extra = {}) {
  return { apiKey: "synthetic", reasoningEffort: "low", temperature: 0.5, samplingParams: { top_p: 1 },
    maxTokens: 1024, maxRetries: 0, timeoutMs: 3000, ...extra };
}

async function collect(selected, context, config) {
  const events = [];
  let providerUsage = false;
  const response = stream(selected, normalizeContext(context), {
    ...config, onProviderStreamEvent: data => { if (data.usage) providerUsage = true; },
  });
  for await (const event of response) events.push(event.type);
  return { message: await response.result(), events, providerUsage };
}

async function agentRun(selected, apiKey, transport, prompt, { maxRequests = 3, extended = false } = {}) {
  const bodies = [], events = [], executed = [];
  let rawUsageFrames = 0;
  const agent = new PiAgent({
    initialState: { model: selected, thinkingLevel: "low",
      systemPrompt: "Use only the provided read-only calculator. Return the requested numerical result.",
      tools: [{ ...declaredTool, label: "Isolated calculator", replay: "safe",
        async execute(callId, args) {
          executed.push({ callId, args });
          return { content: [{ type: "text", text: String(args.a + args.b) }], details: { sum: args.a + args.b } };
        } }],
    },
    streamFn: (current, context, config) => streamSimple(current, context, {
      ...config, apiKey, fetch: transport, maxRetries: 0, timeoutMs: 45000, maxTokens: 1024,
      temperature: 0.5, samplingParams: { top_p: 1 },
      onProviderStreamEvent: data => { if (data.usage) rawUsageFrames++; },
      onPayload: body => {
        assert(bodies.length < maxRequests, "model request budget exceeded");
        if (extended && selected.id.toLowerCase().startsWith("glm-5")) body.tool_stream = true;
        bodies.push(structuredClone(body));
        return body;
      },
    }),
  });
  agent.subscribe(event => events.push(event.type));
  const deadline = setTimeout(() => agent.abort(), 90000);
  try {
    await agent.prompt(prompt);
    const last = agent.state.messages.filter(message => message.role === "assistant").at(-1);
    assert.equal(last.stopReason, "stop", sanitize(last.errorMessage || last.stopReason));
    return { last, bodies, executed, events, rawUsageFrames };
  } finally { clearTimeout(deadline); }
}

async function listen(server) {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  return server.address().port;
}

async function close(server) {
  server.closeAllConnections?.();
  await new Promise(resolve => server.close(resolve));
}

async function offline() {
  const requests = [];
  const sockets = new Set();
  const server = http.createServer(async (request, response) => {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    requests.push(body);
    const scenario = body.model;
    if (scenario === "timeout") return;
    if (scenario === "http-error") {
      response.writeHead(429, { "Content-Type": "application/json", "retry-after": "0" });
      response.end(JSON.stringify({ error: { message: "synthetic rate limit", type: "rate_limit" } }));
      return;
    }
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    const frame = (delta, finish = null) => response.write("data: " + JSON.stringify({
      id: "fixture", object: "chat.completion.chunk", created: 1, model: scenario,
      choices: [{ index: 0, delta, finish_reason: finish }],
    }) + "\n\n");
    if (scenario === "cancel") {
      frame({ content: "partial" });
      return; // AbortSignal closes this intentionally unfinished response.
    }
    const needsTool = scenario.includes("tool") && !body.messages.some(row => row.role === "tool");
    frame({ reasoning_content: "synthetic reasoning" });
    if (needsTool) {
      const args = scenario === "invalid-tool" ? '{"a":"wrong","b":23}' : '{"a":17,"b":23}';
      frame({ tool_calls: [{ index: 0, id: "calculator-1", type: "function",
        function: { name: "probe_add", arguments: args.slice(0, 8) } }] });
      frame({ tool_calls: [{ index: 0, function: { arguments: args.slice(8) } }] });
      frame({}, "tool_calls");
    } else {
      frame({ content: "4" });
      frame({ content: "0" });
      if (scenario !== "incomplete") frame({}, scenario === "length" ? "length" : "stop");
    }
    if (scenario !== "missing-usage") response.write("data: " + JSON.stringify({
      choices: [], usage: { prompt_tokens: 13, completion_tokens: 7, total_tokens: 20,
        prompt_tokens_details: { cached_tokens: 3 }, completion_tokens_details: { reasoning_tokens: 2 } },
    }) + "\n\n");
    response.end("data: [DONE]\n\n");
  });
  server.on("connection", socket => { sockets.add(socket); socket.on("close", () => sockets.delete(socket)); });
  const port = await listen(server);
  const base = `http://127.0.0.1:${port}/v1`;
  const direct = new HttpAgent();
  const transport = (url, config) => fetch(url, { ...config, dispatcher: direct });
  try {
    await run("stream-thinking-usage", async () => {
      const result = await collect(model("normal", base), { systemPrompt: "fixture", messages: [user("40")] }, options({ fetch: transport }));
      assert.equal(textOf(result.message), "40");
      assert(result.events.includes("text_delta") && result.events.includes("thinking_delta"));
      assert.equal(result.message.stopReason, "stop");
      assert(result.providerUsage);
      assert.equal(result.message.usage.totalTokens, 20);
      assert.equal(result.message.usage.input + result.message.usage.cacheRead, 13);
      assert.equal(result.message.usage.output, 7);
      assert.equal(result.message.usage.reasoning, 2);
      return { events: [...new Set(result.events)], usage: result.message.usage, cost_known: false };
    });
    for (const effort of ["low", "high", "max"]) await run(`sampling-${effort}`, async () => {
      await collect(model("sampling", base), { messages: [user("40")] }, options({ reasoningEffort: effort, fetch: transport }));
      const wire = requests.at(-1);
      assert.equal(wire.reasoning_effort, effort);
      assert.equal(wire.temperature, 0.5);
      assert.equal(wire.top_p, 1);
      assert.equal(wire.max_tokens, 1024);
      return { wire_fields: ["reasoning_effort", "temperature", "top_p", "max_tokens"] };
    });
    await run("tool-loop-and-reasoning-history", async () => {
      const result = await agentRun(model("glm-5-tool", base, true), "synthetic", transport, "Use probe_add to add 17 and 23.", { extended: true });
      assert.equal(result.executed.length, 1);
      assert.equal(result.bodies.length, 2);
      assert.equal(textOf(result.last), "40");
      const history = result.bodies[1].messages.find(row => row.role === "assistant" && row.tool_calls);
      assert.equal(history.reasoning_content, "synthetic reasoning");
      assert(result.bodies.every(body => body.thinking.clear_thinking === false && body.tool_stream === true));
      return { model_requests: result.bodies.length, actual_tool_executions: 1,
        reasoning_replayed: true, agent_events: [...new Set(result.events)] };
    });
    await run("invalid-tool-arguments", async () => {
      const result = await agentRun(model("invalid-tool", base), "synthetic", transport, "Use the calculator.");
      assert.equal(result.executed.length, 0);
      assert.equal(result.bodies.length, 2);
      const receipt = result.bodies[1].messages.find(row => row.role === "tool");
      assert(receipt && /invalid|validation|expected|argument/i.test(JSON.stringify(receipt.content)));
      return { actual_tool_executions: 0, model_received_error: true };
    });
    await run("length-is-not-complete", async () => {
      const result = await collect(model("length", base), { messages: [user("40")] }, options({ fetch: transport }));
      assert.equal(result.message.stopReason, "length");
      assert.equal(textOf(result.message), "40");
      return { stop_reason: result.message.stopReason, partial_preserved: true,
        migration_rule: "Product adapter must reject length before processing business output." };
    });
    await run("missing-finish-is-error", async () => {
      const result = await collect(model("incomplete", base), { messages: [user("40")] }, options({ fetch: transport }));
      assert.equal(result.message.stopReason, "error");
      return { stop_reason: result.message.stopReason, partial_preserved: textOf(result.message) === "40" };
    });
    await run("missing-usage-remains-unknown", async () => {
      const result = await collect(model("missing-usage", base), { messages: [user("40")] }, options({ fetch: transport }));
      assert.equal(result.providerUsage, false);
      return { provider_usage_reported: false, sdk_total_tokens: result.message.usage.totalTokens,
        migration_rule: "Track raw usage presence. SDK zero defaults cannot prove zero token use or cost." };
    });
    await run("http-error-no-retry", async () => {
      const before = requests.length;
      const result = await collect(model("http-error", base), { messages: [user("40")] }, options({ fetch: transport }));
      assert.equal(result.message.stopReason, "error");
      assert.equal(requests.length - before, 1);
      return { actual_requests: 1, stop_reason: result.message.stopReason };
    });
    await run("abort-partial-and-close", async () => {
      const cancel = new AbortController();
      const events = stream(model("cancel", base), normalizeContext({ messages: [user("40")] }),
        options({ signal: cancel.signal, fetch: transport }));
      for await (const event of events) if (event.type === "text_delta") cancel.abort();
      const result = await events.result();
      assert.equal(result.stopReason, "aborted");
      assert.equal(textOf(result), "partial");
      return { stop_reason: result.stopReason, partial_preserved: true };
    });
    await run("idle-network-timeout", async () => {
      const before = requests.length;
      const result = await collect(model("timeout", base), { messages: [user("40")] },
        options({ fetch: transport, timeoutMs: 150 }));
      assert.equal(result.message.stopReason, "error");
      assert.equal(requests.length - before, 1);
      return { actual_requests: 1, stop_reason: result.message.stopReason };
    });
    await proxyCases(base);
  } finally {
    for (const socket of sockets) socket.destroy();
    await close(server);
    await direct.close();
  }
}

async function proxyCases(base) {
  let connects = 0, credentials = false;
  const sockets = new Set();
  const proxy = http.createServer();
  proxy.on("connection", socket => { sockets.add(socket); socket.on("close", () => sockets.delete(socket)); });
  proxy.on("connect", (request, socket, head) => {
    connects++;
    credentials = request.headers["proxy-authorization"] === "Basic " + Buffer.from("fixture:password").toString("base64");
    const [host, port] = request.url.split(":");
    const upstream = net.connect(Number(port), host, () => {
      socket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
      if (head.length) upstream.write(head);
      socket.pipe(upstream).pipe(socket);
    });
    socket.on("error", () => upstream.destroy());
    upstream.on("error", () => socket.destroy());
    socket.on("close", () => upstream.destroy());
  });
  const port = await listen(proxy);
  const dispatchers = [];
  try {
    await run("custom-authenticated-http-proxy", async () => {
      const dispatcher = new ProxyAgent({ uri: `http://fixture:password@127.0.0.1:${port}`, proxyTunnel: true });
      dispatchers.push(dispatcher);
      const result = await collect(model("proxy", base), { messages: [user("40")] },
        options({ fetch: (url, config) => fetch(url, { ...config, dispatcher }) }));
      assert.equal(textOf(result.message), "40");
      assert(connects > 0 && credentials);
      return { proxy_used: true, proxy_credentials_received: true, fetch_injection: true };
    });
    await run("environment-http-proxy", async () => {
      const dispatcher = new EnvHttpProxyAgent({ httpProxy: `http://127.0.0.1:${port}`, noProxy: "", proxyTunnel: true });
      dispatchers.push(dispatcher);
      const before = connects;
      const result = await collect(model("system-proxy", base), { messages: [user("40")] },
        options({ fetch: (url, config) => fetch(url, { ...config, dispatcher }) }));
      assert.equal(textOf(result.message), "40");
      assert(connects > before);
      return { proxy_used: true, process_environment_unchanged: true };
    });
    await socksCase(base);
  } finally {
    for (const dispatcher of dispatchers) await dispatcher.destroy();
    for (const socket of sockets) socket.destroy();
    await close(proxy);
  }
}

async function socksCase(base) {
  let tunnels = 0;
  const sockets = new Set();
  const socks = net.createServer(socket => {
    sockets.add(socket);
    let buffer = Buffer.alloc(0), phase = "greeting";
    function receive(piece) {
      buffer = Buffer.concat([buffer, piece]);
      if (phase === "greeting") {
        if (buffer.length < 2 || buffer.length < 2 + buffer[1]) return;
        buffer = buffer.subarray(2 + buffer[1]);
        socket.write(Buffer.from([5, 0]));
        phase = "connect";
      }
      if (phase !== "connect" || buffer.length < 5) return;
      const end = buffer[3] === 1 ? 8 : buffer[3] === 3 ? 5 + buffer[4] : 20;
      if (buffer.length < end + 2) return;
      const hostname = buffer[3] === 1 ? [...buffer.subarray(4, 8)].join(".") : buffer.subarray(5, end).toString();
      const targetPort = buffer.readUInt16BE(end);
      const rest = buffer.subarray(end + 2);
      phase = "tunnel";
      const upstream = net.connect(targetPort, hostname, () => {
        tunnels++;
        socket.write(Buffer.from([5, 0, 0, 1, 127, 0, 0, 1, 0, 0]));
        socket.off("data", receive);
        if (rest.length) upstream.write(rest);
        socket.pipe(upstream).pipe(socket);
      });
      upstream.on("error", () => socket.destroy());
      socket.on("close", () => upstream.destroy());
    }
    socket.on("data", receive);
    socket.on("error", () => {});
    socket.on("close", () => sockets.delete(socket));
  });
  const port = await listen(socks);
  let dispatcher;
  try {
    await run("socks5-fetch-injection", async () => {
      dispatcher = new ProxyAgent(`socks5://127.0.0.1:${port}`);
      const result = await collect(model("socks", base), { messages: [user("40")] },
        options({ fetch: (url, config) => fetch(url, { ...config, dispatcher }) }));
      assert.equal(textOf(result.message), "40");
      assert(tunnels > 0);
      return { supported: true, experimental_transport: true, tunnels };
    });
  } finally {
    await dispatcher?.destroy();
    for (const socket of sockets) socket.destroy();
    await close(socks);
  }
}

async function live() {
  assert(input.models?.length > 0, "No configured models supplied");
  assert.equal(input.network.mode, "direct", "This live batch is limited to the configured direct route");
  const direct = new HttpAgent();
  const transport = (url, config) => fetch(url, { ...config, dispatcher: direct });
  try {
    for (const entry of input.models) {
      const selected = model(entry.model, entry.base_url, entry.model.toLowerCase().startsWith("glm-5"));
      const route = createHash("sha256").update(entry.base_url).digest("hex").slice(0, 16);
      const effort = input.effort || "low";
      const suffix = effort === "low" ? "" : `-${effort}`;
      await run(`live-text-${entry.model}${suffix}`, async () => {
        let actualRequests = 0, status;
        const result = await collect(selected, { systemPrompt: "Follow the fixed output instruction.",
          messages: [user("只输出 PI_COMPAT_OK，不调用工具。")] },
        options({ apiKey: entry.api_key, reasoningEffort: effort, fetch: transport, timeoutMs: 45000,
          signal: AbortSignal.timeout(60000),
          onPayload: body => { actualRequests++; assert(actualRequests <= 1); return body; },
          onResponse: response => { status = response.status; } }));
        assert.equal(result.message.stopReason, "stop", sanitize(result.message.errorMessage || result.message.stopReason));
        assert.equal(textOf(result.message).trim(), "PI_COMPAT_OK");
        assert(result.events.includes("text_delta"));
        return { route, model_requests: actualRequests, http_status: status, text_assertion: "PI_COMPAT_OK",
          thinking_effort: effort, thinking_events: result.events.filter(type => type === "thinking_delta").length,
          usage_reported: result.providerUsage, usage: result.providerUsage ? result.message.usage : null,
          stop_reason: result.message.stopReason, cost_known: false };
      });
      await run(`live-tool-${entry.model}`, async () => {
        const result = await agentRun(selected, entry.api_key, transport,
          "Call probe_add exactly once with a=17 and b=23. Then output only the number returned by the tool.",
          { extended: true });
        assert.equal(result.executed.length, 1);
        assert.deepEqual(result.executed[0].args, { a: 17, b: 23 });
        assert.equal(textOf(result.last).trim(), "40");
        const prior = result.bodies.at(-1).messages.find(row => row.role === "assistant" && row.tool_calls);
        return { route, model_requests: result.bodies.length, actual_tool_executions: result.executed.length,
          result_assertion: 40, reasoning_field_replayed: typeof prior?.reasoning_content === "string",
          nonempty_reasoning_replayed: Boolean(prior?.reasoning_content),
          usage_frames: result.rawUsageFrames, cost_known: false };
      });
    }
  } finally { await direct.close(); }
}

await persist();
if (mode === "offline") await offline();
else if (mode === "live") await live();
else throw new Error("Use offline or live");
report.source = fileURLToPath(import.meta.url);
assert(report.cases.length > 0, "No matching cases ran");
await persist();
process.stdout.write(JSON.stringify(report) + "\n");
process.exitCode = report.failed ? 1 : 0;
