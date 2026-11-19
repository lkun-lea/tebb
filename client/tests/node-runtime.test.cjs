const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const {createHash} = require('node:crypto');
const {createServer} = require('node:http');
const {spawnSync} = require('node:child_process');
const runtime = import('../scripts/node-runtime.mjs');
const client = path.resolve(__dirname, '..');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'tebb-node-test-'));
  t.after(async () => {
    assert.equal(path.dirname(root), os.tmpdir());
    assert(path.basename(root).startsWith('tebb-node-test-'));
    await fs.rm(root, {recursive: true, force: true});
  });
  const cached = path.join(root, '.runtime/node-v24.22.3-win-x64/node.exe');
  return {root, cached};
}
const pinned = execPath => ({version: 'v24.22.3', execPath});

test('explicit override wins over cache, system and download', async t => {
  const {resolveNode} = await runtime, {root} = await fixture(t);
  assert.equal(await resolveNode({root, env: {TEBB_PI_NODE: 'custom'}, inspect: command => {
    assert.equal(command, 'custom'); return pinned('/custom/node');
  }}), '/custom/node');
});

test('invalid explicit override fails instead of silently using another Node', async t => {
  const {resolveNode} = await runtime, {root} = await fixture(t);
  for (const info of [null, {version: 'v20.17.0'}]) {
    await assert.rejects(resolveNode({root, env: {TEBB_PI_NODE: 'custom'}, inspect: () => info}), /TEBB_PI_NODE.*24\.22\.3/);
  }
});

test('project cache works offline even when system Node is too old', async t => {
  const {resolveNode} = await runtime, {root, cached} = await fixture(t);
  await fs.mkdir(path.dirname(cached), {recursive: true}); await fs.writeFile(cached, 'fixture');
  assert.equal(await resolveNode({root, env: {}, inspect: command => {
    assert.equal(command, cached); return pinned(cached);
  }}), cached);
});

test('wrong cached version is reported without overwriting it', async t => {
  const {resolveNode} = await runtime, {root, cached} = await fixture(t);
  await fs.mkdir(path.dirname(cached), {recursive: true}); await fs.writeFile(cached, 'keep');
  await assert.rejects(resolveNode({root, env: {}, inspect: () => ({version: 'v24.0.0'})}), /项目缓存/);
  assert.equal(await fs.readFile(cached, 'utf8'), 'keep');
});

test('matching current Node is reused without downloading', async t => {
  const {resolveNode} = await runtime, {root} = await fixture(t);
  assert.equal(await resolveNode({root, env: {}, currentNode: '/current/node', inspect: pinned}), '/current/node');
});

test('matching PATH Node supplies its actual executable path', async t => {
  const {resolveNode} = await runtime, {root} = await fixture(t);
  assert.equal(await resolveNode({root, env: {}, currentNode: 'old', inspect: command =>
    command === 'node' ? pinned('/path/node') : {version: 'v20.17.0'}}), '/path/node');
});

test('missing Node provisions into this project and validates installed version', async t => {
  const {resolveNode} = await runtime, {root, cached} = await fixture(t);
  let installed = false;
  assert.equal(await resolveNode({root, env: {}, platform: 'win32', arch: 'x64',
    inspect: command => installed && command === cached ? pinned(cached) : null,
    install: async cache => {assert.equal(cache, path.join(root, '.runtime')); installed = true; return cached;},
  }), cached);
  await assert.rejects(resolveNode({root, env: {}, platform: 'win32', arch: 'x64', inspect: () => null,
    install: async () => cached}), /项目运行时/);
});

test('unsupported download target provides a manual setup error', async t => {
  const {resolveNode} = await runtime, {root} = await fixture(t);
  await assert.rejects(resolveNode({root, env: {}, platform: 'linux', inspect: () => null}), /仅支持 Windows x64/);
});

test('child environment selects Node and preserves other settings without mutating parent', async () => {
  const {runtimeEnvironment} = await runtime;
  const env = {Path: 'system-path', SOME_SETTING: 'preserved'};
  const actual = runtimeEnvironment(path.resolve('/runtime/node'), env);
  assert.equal(actual.TEBB_PI_NODE, path.resolve('/runtime/node'));
  assert.equal(actual.PATH, `${path.resolve('/runtime')}${path.delimiter}system-path`);
  assert.equal(actual.SOME_SETTING, 'preserved');
  assert(!('Path' in actual)); assert.deepEqual(env, {Path: 'system-path', SOME_SETTING: 'preserved'});
});

test('download enforces HTTP status and SHA-256 before extraction', async t => {
  const {downloadArchive} = await runtime, {root} = await fixture(t);
  const content = Buffer.from('isolated archive fixture');
  const server = createServer((request, response) => {
    response.writeHead(request.url === '/missing' ? 404 : 200); response.end(content);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => {server.closeAllConnections(); server.close();});
  const base = `http://127.0.0.1:${server.address().port}`;
  const checksum = createHash('sha256').update(content).digest('hex');
  await downloadArchive(base, path.join(root, 'verified.zip'), checksum);
  assert.deepEqual(await fs.readFile(path.join(root, 'verified.zip')), content);
  await assert.rejects(downloadArchive(base, path.join(root, 'bad.zip'), '0'.repeat(64)), /SHA-256/);
  await assert.rejects(downloadArchive(`${base}/missing`, path.join(root, 'missing.zip'), checksum), /HTTP 404/);
  await assert.rejects(fs.access(path.join(root, 'missing.zip')), /ENOENT/);
});

test('non-dev CLI commands forward arguments and exit status without runtime preparation', () => {
  const options = {cwd: client, env: {...process.env, TEBB_PI_NODE: 'does-not-exist'}, encoding: 'utf8', timeout: 15000, windowsHide: true};
  const version = spawnSync(process.execPath, ['scripts/tauri.mjs', '--version'], options);
  assert.equal(version.status, 0, version.stderr); assert.match(version.stdout, /tauri-cli/);
  const invalid = spawnSync(process.execPath, ['scripts/tauri.mjs', 'invalid-command'], options);
  assert.notEqual(invalid.status, 0); assert.match(invalid.stderr, /invalid-command/);
});

test('dev refuses invalid explicit runtime before starting Vite or Cargo', () => {
  const result = spawnSync(process.execPath, ['scripts/tauri.mjs', 'dev'], {cwd: client,
    env: {...process.env, TEBB_PI_NODE: 'does-not-exist'}, encoding: 'utf8', timeout: 15000, windowsHide: true});
  assert.equal(result.status, 1); assert.match(result.stderr, /TEBB_PI_NODE.*24\.22\.3/);
  assert.doesNotMatch(result.stdout, /VITE|Compiling/);
});
