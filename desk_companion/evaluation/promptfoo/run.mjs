// Fixed local adapter. No remote providers, generated assertions or cloud sharing.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';
// The framework scores local product reports through child-process stdio. It
// needs no network. Product model workers retain their normal network policy.
let outboundAttempts=0;
net.Socket.prototype.connect=function(){outboundAttempts++;throw new Error('EvaluationFrameworkNetworkDisabled');};
process.env.PROMPTFOO_DISABLE_TELEMETRY='1';
process.env.PROMPTFOO_DISABLE_UPDATE='1';
process.env.PROMPTFOO_DISABLE_SHARING='1';
process.env.PROMPTFOO_CACHE_ENABLED='false';
const here=path.dirname(fileURLToPath(import.meta.url));
const installed=JSON.parse(fs.readFileSync(path.join(here,'node_modules/promptfoo/package.json'),'utf8'));
if(process.version!=='v24.22.3'||installed.version!=='0.125.1')throw new Error('EvaluationRuntimeVersionMismatch');
const batch=path.resolve(process.argv[2]);
const manifest=JSON.parse(fs.readFileSync(path.join(batch,'manifest.json'),'utf8'));
// Relative file URI avoids the framework's assertion function parser treating
// a Windows drive colon as a function separator.
const provider=path.relative(process.cwd(),path.join(here,'provider.py')).replaceAll('\\','/');
const { evaluate }=await import('promptfoo');
const result=await evaluate({description:'tebb frozen product acceptance',prompts:['{{attempt}}'],
 providers:[{id:'file://'+provider,config:{batch_dir:batch,pythonExecutable:process.env.PROMPTFOO_PYTHON}}],
 tests:manifest.planned.map((row,index)=>({description:row.case_id+' sample '+row.sample,vars:{attempt:index},
  assert:[{type:'python',value:'file://'+provider}]})),
 evaluateOptions:{maxConcurrency:1,cache:false,repeat:1},sharing:false,
},{writeResults:false,cache:false,maxConcurrency:1});
const summary=await result.toEvaluateSummary();
fs.writeFileSync(path.join(batch,'framework.json'),JSON.stringify({...summary,tebb:{frameworkNetwork:{policy:'deny_all_tcp',blocked_attempts:outboundAttempts,connected:0},productUsage:'result-*.json model_observations; framework tokenUsage is not product usage'}},null,2));
if (summary.stats?.errors) process.exitCode=2;
