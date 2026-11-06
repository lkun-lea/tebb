const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { act, create } = require('react-test-renderer');

function load(relative, mocks = {}) {
  const file = path.resolve(__dirname, '../src', relative);
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  const mod = new Module(file, module); mod.filename = file; mod.paths = Module._nodeModulePaths(path.dirname(file));
  const original = mod.require.bind(mod); mod.require = id => mocks[id] || original(id);
  mod._compile(code, file); return mod.exports;
}
const pets = load('builtin-pet.ts');
const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');

test('appearance saves only after a successful RPC and missing models remain disabled', async () => {
  const calls = []; let fail = false;
  const { PetSettings } = load('client/pet-settings.tsx', { '../builtin-pet': pets,
    '@tauri-apps/api/core': { isTauri: () => false }, './api': { rpc: async (_i, method, args) => {
      calls.push({ method, args });
      if (method === 'save_pet_preferences' && fail) throw Error('save failed');
      return { ok: true, skin: args?.skin || 'paper', live2d_available: false };
    } } });
  let view; await act(async () => { view = create(React.createElement(PetSettings, { info: { port: 1, token: 'test' } })); });
  const button = label => view.root.findAllByType('button').find(n => text(n).includes(label));
  assert.equal(button('凯尔希').props.disabled, true);
  await act(async () => button('鼠尾草').props.onClick());
  assert.equal(button('鼠尾草').props['aria-pressed'], true);
  assert.deepEqual(calls.at(-1), { method: 'save_pet_preferences', args: { skin: 'sage', size: 48 } });
  fail = true; await act(async () => button('墨黑').props.onClick());
  assert.equal(button('鼠尾草').props['aria-pressed'], true);
  assert(text(view.root.findByProps({ role: 'alert' })).includes('save failed'));
  await act(async () => view.unmount());
});

// Model only the DOM used by the renderer, including data-* reflection.
function petFixture(t) {
  const savedDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const savedSetTimeout = global.setTimeout, savedClearTimeout = global.clearTimeout;
  const pending = new Map(); let now = 0, next = 0, pet;
  global.setTimeout = (callback, delay) => { const id = ++next; pending.set(id, { callback, due: now + delay }); return id; };
  global.clearTimeout = id => pending.delete(id);
  const make = tag => {
    const attributes = new Map();
    const element = { tagName: tag, style: {}, children: [], innerHTML: '', removed: false,
      rect: { x: 20, y: 40, width: 48, height: 48 },
      appendChild(node) { this.children.push(node); node.parentElement = this; },
      remove() { this.removed = true; if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); },
      getBoundingClientRect() { return this.rect; },
      getAttribute(name) { return attributes.get(name) ?? null; },
      hasAttribute(name) { return attributes.has(name); },
      setAttribute(name, value) { attributes.set(name, String(value)); },
      removeAttribute(name) { attributes.delete(name); },
      toggleAttribute(name, enabled) { if (enabled) this.setAttribute(name, ''); else this.removeAttribute(name); },
      querySelector(selector) { assert.equal(selector, '.pet-eyes'); return this.innerHTML.includes('class="pet-eyes"') ? this.eyes : null; },
    };
    element.dataset = new Proxy({}, {
      get: (_, key) => attributes.get('data-' + key),
      set: (_, key, value) => { attributes.set('data-' + key, String(value)); return true; },
    });
    if (tag === 'div') element.eyes = make('g');
    return element;
  };
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { createElement: make } });
  t.after(() => {
    try { pet?.destroy(); } finally {
      global.setTimeout = savedSetTimeout; global.clearTimeout = savedClearTimeout;
      if (savedDocument) Object.defineProperty(globalThis, 'document', savedDocument); else delete globalThis.document;
    }
  });
  const parent = make('section'), canvas = { style: { visibility: '' }, parentElement: parent };
  pet = pets.mountBuiltinPet(canvas, 'sage');
  const host = parent.children.find(node => node.className === 'builtin-pet');
  function advance(ms) {
    const until = now + ms;
    for (;;) {
      const due = [...pending].filter(([, timer]) => timer.due <= until).sort((a,b) => a[1].due - b[1].due)[0];
      if (!due) break;
      now = due[1].due; pending.delete(due[0]); due[1].callback();
    }
    now = until;
  }
  return { pet, host, canvas, parent, pending, advance };
}

test('built-in rendering initializes Idle, tracks live hit bounds and removes its DOM without Core or WebGL', t => {
  const { pet, host, canvas, parent, pending } = petFixture(t);
  assert(host.innerHTML.includes('鼠尾草'));
  assert.equal(canvas.style.visibility, 'hidden');
  assert.equal(host.dataset.mood, 'Idle'); assert.equal(host.getAttribute('data-mood'), 'Idle');
  assert(host.eyes.innerHTML.includes('<rect')); assert.equal(host.eyes.getAttribute('fill'), '#303f39');
  assert.deepEqual(pet.bounds(), { x: 20, y: 40, w: 48, h: 48 });
  host.rect = { x: 30, y: 50, width: 64, height: 64 };
  assert.deepEqual(pet.bounds(), { x: 30, y: 50, w: 64, h: 64 });
  pet.destroy(); assert.equal(host.removed, true); assert.equal(canvas.style.visibility, '');
  assert(!parent.children.includes(host)); assert.equal(pending.size, 0);
  assert.equal(pets.isBuiltinSkin('__proto__'), false); assert.equal(pets.isPetMood('__proto__'), false);
});

test('working state selects Busy without overwriting an explicit ongoing expression', t => {
  const { pet, host, pending, advance } = petFixture(t);
  const idleEyes = host.eyes.innerHTML;
  pet.active(true); assert(host.hasAttribute('data-active')); assert.equal(host.dataset.mood, 'Busy');
  assert.notEqual(host.eyes.innerHTML, idleEyes); assert.equal(pending.size, 0);
  pet.active(true); assert.equal(host.dataset.mood, 'Busy');
  pet.active(false); assert(!host.hasAttribute('data-active')); assert.equal(host.dataset.mood, 'Idle');
  pet.play('Talk'); const talkEyes = host.eyes.innerHTML;
  pet.active(true); pet.active(false); advance(10000);
  assert.equal(host.dataset.mood, 'Talk'); assert.equal(host.eyes.innerHTML, talkEyes); assert.equal(pending.size, 0);
  pet.play('Idle'); assert.equal(host.eyes.innerHTML, idleEyes);
});

test('Done, Tap and Fail expire at their deadlines, while replay and replacement invalidate the old timer', t => {
  const { pet, host, pending, advance } = petFixture(t);
  const idleEyes = host.eyes.innerHTML;
  for (const [mood, duration] of [['Done', 900], ['Tap', 700], ['Fail', 2600]]) {
    pet.play(mood); assert.equal(host.getAttribute('data-mood'), mood); assert.notEqual(host.eyes.innerHTML, idleEyes);
    assert.equal(pending.size, 1); advance(duration - 1); assert.equal(host.dataset.mood, mood);
    advance(1); assert.equal(host.dataset.mood, 'Idle'); assert.equal(host.eyes.innerHTML, idleEyes); assert.equal(pending.size, 0);
  }
  pet.play('Tap'); advance(600); pet.play('Tap'); advance(100);
  assert.equal(host.dataset.mood, 'Tap'); assert.equal(pending.size, 1);
  advance(600); assert.equal(host.dataset.mood, 'Idle');
  pet.play('Fail'); advance(100); pet.play('Busy'); advance(2600);
  assert.equal(host.dataset.mood, 'Busy'); assert.equal(pending.size, 0);
  pet.play('Wish'); advance(10000); assert.equal(host.dataset.mood, 'Wish'); assert.equal(pending.size, 0);
  pet.play('unknown-motion'); assert.equal(host.dataset.mood, 'Tap');
});

test('destroy cancels expression recovery and never mutates the removed pet later', t => {
  const { pet, host, canvas, pending, advance } = petFixture(t);
  pet.play('Done'); assert.equal(pending.size, 1);
  const eyes = host.eyes.innerHTML;
  pet.destroy(); assert.equal(pending.size, 0); assert.equal(canvas.style.visibility, '');
  advance(10000); assert.equal(host.dataset.mood, 'Done'); assert.equal(host.eyes.innerHTML, eyes); assert(host.removed);
});
