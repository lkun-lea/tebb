import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {resolveNode, runtimeEnvironment} from './node-runtime.mjs';

const args = process.argv.slice(2);
try {
  if (args[0] === 'dev') {
    const root = fileURLToPath(new URL('../../', import.meta.url));
    const node = await resolveNode({root});
    const env = runtimeEnvironment(node);
    for (const key of Object.keys(process.env)) {
      if (key.toUpperCase() === 'PATH') delete process.env[key];
    }
    Object.assign(process.env, env);
    console.log(`[tebb] Pi Node ${node}`);
  }
  // Use the official CLI in this process so its native cancellation/exit handling stays intact.
  const {run} = createRequire(import.meta.url)('@tauri-apps/cli');
  await run(args, 'pnpm tauri');
} catch (error) {
  console.error(`[tebb] ${error.message}`);
  process.exitCode = 1;
}
