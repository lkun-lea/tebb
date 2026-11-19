import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {createWriteStream} from 'node:fs';
import {access, mkdir, mkdtemp, rename, rm} from 'node:fs/promises';
import path from 'node:path';
import {Readable, Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';

export const NODE_VERSION = '24.22.3';
const ARCHIVE = `node-v${NODE_VERSION}-win-x64`;
const SHA256 = 'e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f';

export function inspectNode(command) {
  try {
    return JSON.parse(execFileSync(command, ['-p', 'JSON.stringify({version:process.version,execPath:process.execPath})'], {
      encoding: 'utf8', timeout: 5000, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'],
    }));
  } catch {
    return null;
  }
}

// Verify before extraction; a partial download is never published as a runtime.
export async function downloadArchive(url, destination, checksum) {
  const response = await fetch(url, {signal: AbortSignal.timeout(120_000)});
  if (!response.ok || !response.body) throw new Error(`Node 下载失败（HTTP ${response.status}）。`);
  const hash = createHash('sha256');
  let size = 0;
  const verify = new Transform({transform(chunk, encoding, callback) {
    size += chunk.length;
    if (size > 100 * 1024 * 1024) return callback(new Error('Node 下载超过大小限制。'));
    hash.update(chunk);
    callback(null, chunk);
  }});
  await pipeline(Readable.fromWeb(response.body), verify, createWriteStream(destination, {flags: 'wx'}));
  if (hash.digest('hex') !== checksum) throw new Error('Node 下载 SHA-256 不匹配，未解压或使用该文件。');
}

async function installNode(cacheRoot, inspect) {
  await mkdir(cacheRoot, {recursive: true});
  const temporary = await mkdtemp(path.join(cacheRoot, 'node-download-'));
  try {
    const archive = path.join(temporary, 'node.zip');
    console.log(`[tebb] 正在准备 Node ${NODE_VERSION}（官方下载，SHA-256 校验）…`);
    await downloadArchive(`https://nodejs.org/dist/v${NODE_VERSION}/${ARCHIVE}.zip`, archive, SHA256);
    execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      'Expand-Archive -LiteralPath $env:TEBB_NODE_ARCHIVE -DestinationPath $env:TEBB_NODE_EXTRACT'], {
      windowsHide: true, timeout: 120_000, stdio: ['ignore', 'pipe', 'pipe'],
      env: {...process.env, TEBB_NODE_ARCHIVE: archive, TEBB_NODE_EXTRACT: temporary},
    });
    const extracted = path.join(temporary, ARCHIVE);
    if (inspect(path.join(extracted, 'node.exe'))?.version !== `v${NODE_VERSION}`) {
      throw new Error('下载的 Node 无法运行或版本不匹配。');
    }
    const destination = path.join(cacheRoot, ARCHIVE);
    try {
      await rename(extracted, destination);
    } catch (error) {
      // Another dev launch may have finished installing this same pinned runtime.
      if (inspect(path.join(destination, 'node.exe'))?.version !== `v${NODE_VERSION}`) throw error;
    }
    return path.join(destination, 'node.exe');
  } finally {
    // Only remove this invocation's staging directory, never an existing runtime.
    if (path.dirname(path.resolve(temporary)) !== path.resolve(cacheRoot)
        || !path.basename(temporary).startsWith('node-download-')) {
      throw new Error('Node 临时目录不在项目运行时缓存内，拒绝清理。');
    }
    await rm(temporary, {recursive: true, force: true});
  }
}

export async function resolveNode({root, env = process.env, platform = process.platform,
  arch = process.arch, currentNode = process.execPath, inspect = inspectNode, install = installNode}) {
  function required(command, source) {
    const runtime = inspect(command);
    if (runtime?.version !== `v${NODE_VERSION}`) {
      throw new Error(`${source} 必须为 Node ${NODE_VERSION}，当前为 ${runtime?.version ?? '无法运行'}。`);
    }
    return runtime.execPath;
  }
  if (env.TEBB_PI_NODE) return required(env.TEBB_PI_NODE, 'TEBB_PI_NODE');
  const cacheRoot = path.join(root, '.runtime');
  const cached = path.join(cacheRoot, ARCHIVE, 'node.exe');
  try {
    await access(cached);
    return required(cached, '项目缓存');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  for (const command of new Set([currentNode, 'node'])) {
    const runtime = inspect(command);
    if (runtime?.version === `v${NODE_VERSION}`) return runtime.execPath;
  }
  if (platform !== 'win32' || arch !== 'x64') {
    throw new Error(`自动下载仅支持 Windows x64；请安装 Node ${NODE_VERSION} 或设置 TEBB_PI_NODE。`);
  }
  return required(await install(cacheRoot, inspect), '项目运行时');
}

export function runtimeEnvironment(node, env = process.env) {
  // Windows environment keys are case-insensitive; don't leave both PATH and Path.
  const inherited = Object.fromEntries(Object.entries(env).filter(([key]) => key.toUpperCase() !== 'PATH'));
  const searchPath = Object.entries(env).find(([key]) => key.toUpperCase() === 'PATH')?.[1] ?? '';
  return {...inherited, TEBB_PI_NODE: node, PATH: `${path.dirname(node)}${path.delimiter}${searchPath}`};
}
