const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function startup() {
  const listeners = new Map();
  const timers = new Map();
  let nextTimer = 0;
  let reloads = 0;
  const panel = {
    dataset: { state: "loading" },
    classes: new Set(),
    classList: { add(name) { panel.classes.add(name); } },
    setAttribute() {},
    removed: false,
    remove() { this.removed = true; },
  };
  const status = { textContent: "正在载入界面…" };
  const retry = { hidden: true, addEventListener(_, fn) { this.click = fn; } };
  const window = {
    addEventListener(type, fn) { listeners.set(type, fn); },
    removeEventListener(type) { listeners.delete(type); },
  };
  vm.runInNewContext(readFileSync(path.join(__dirname, "../public/startup.js"), "utf8"), {
    window,
    document: { getElementById: (id) => ({ startup: panel, "startup-status": status, "startup-retry": retry })[id] },
    location: { reload() { reloads += 1; } },
    setTimeout(fn, delay) { timers.set(++nextTimer, { fn, delay }); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
  });
  return {
    panel, status, retry, timers, listeners,
    event(detail) { listeners.get("desk-startup")({ detail }); },
    reloads: () => reloads,
  };
}

test("静态启动页先于 React 资源存在，主窗有暗色底色", () => {
  const html = readFileSync(path.join(__dirname, "../client.html"), "utf8");
  assert.ok(html.indexOf('id="startup"') < html.indexOf('src="/src/client/main.tsx"'));
  assert.ok(html.includes("prefers-reduced-motion"));
  const config = JSON.parse(readFileSync(path.join(__dirname, "../src-tauri/tauri.conf.json"), "utf8"));
  assert.equal(config.app.windows.find((win) => win.label === "main").backgroundColor, "#101216");
});

test("阶段提示跟随真实启动状态，等待较久时保留当前阶段", () => {
  const ui = startup();
  ui.event({ state: "loading", message: "正在连接本地助手…" });
  assert.equal(ui.status.textContent, "正在连接本地助手…");
  const slow = [...ui.timers.values()].find((timer) => timer.delay === 12000);
  slow.fn();
  ui.event({ state: "loading", message: "正在读取会话…" });
  assert.match(ui.status.textContent, /正在读取会话/);
  assert.match(ui.status.textContent, /首次启动/);
});

test("就绪立即开始淡出，清理计时器和全局错误监听", () => {
  const ui = startup();
  ui.event({ state: "ready" });
  assert.equal(ui.panel.dataset.state, "ready");
  assert.ok(ui.panel.classes.has("startup-exit"));
  assert.equal(ui.listeners.has("error"), false);
  assert.equal(ui.listeners.has("unhandledrejection"), false);
  assert.equal([...ui.timers.values()].some((timer) => timer.delay === 12000), false);
  [...ui.timers.values()].find((timer) => timer.delay === 240).fn();
  assert.equal(ui.panel.removed, true);
});

test("启动失败停在错误页，重试重新加载且错误正文按文本显示", () => {
  const ui = startup();
  ui.event({ state: "error", message: "<script>失败原因</script>" });
  assert.equal(ui.panel.dataset.state, "error");
  assert.equal(ui.retry.hidden, false);
  assert.match(ui.status.textContent, /<script>失败原因<\/script>/);
  assert.equal(ui.panel.classes.has("startup-exit"), false);
  assert.equal(ui.timers.size, 0);
  ui.retry.click();
  assert.equal(ui.reloads(), 1);
});

test("主资源加载失败和初始化异常都能显示恢复入口", () => {
  for (const [type, event] of [
    ["error", { target: { tagName: "SCRIPT" } }],
    ["error", { message: "初始化错误" }],
    ["unhandledrejection", { reason: new Error("连接失败") }],
  ]) {
    const ui = startup();
    ui.listeners.get(type)(event);
    assert.equal(ui.panel.dataset.state, "error");
    assert.equal(ui.retry.hidden, false);
  }
});

test("启动失败后迟到的阶段、就绪和慢启动回调不能覆盖恢复页", () => {
  const ui = startup();
  const queuedSlow = [...ui.timers.values()].find(timer => timer.delay === 12000).fn;
  ui.event({ state: "error", message: "首次资源加载失败" });
  const failure = ui.status.textContent;
  ui.event({ state: "loading", message: "迟到的会话响应" });
  ui.event({ state: "ready" });
  queuedSlow();
  ui.event({ state: "error", message: "后续异常" });
  assert.equal(ui.status.textContent, failure);
  assert.equal(ui.panel.dataset.state, "error");
  assert.equal(ui.retry.hidden, false);
  assert.equal(ui.panel.classes.has("startup-exit"), false);
  assert.equal(ui.panel.removed, false);
  assert.equal(ui.timers.size, 0);
  ui.retry.click();
  assert.equal(ui.reloads(), 1);
});
