import {after, before, beforeEach, test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {mkdtemp,rm,rmdir} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {PGlite} from '@electric-sql/pglite';
import {vector} from '@electric-sql/pglite-pgvector';

// GoTrue is NOT simulated as authenticated production HTTP. The SQL fixture only
// supplies the roles/auth.uid() Supabase provides, so the real migration can run.
const A='a0000000-0000-4000-8000-000000000001', B='b0000000-0000-4000-8000-000000000002';
let db;
const body=(text='请先给结论，再补依据')=>({kind:'preference',category:'communication',text});
async function scalar(sql,args=[]){return (await db.query(sql,args)).rows[0].value;}
async function actor(id=A,role='authenticated'){
  await db.exec('reset role');
  await db.query("select set_config('request.jwt.claims',$1,false)",[JSON.stringify(id?{sub:id}:{})]);
  assert.ok(['authenticated','anon'].includes(role));
  await db.exec(`set role ${role}`);
}
const apply=(id,version=0,action='put',payload=body(),op=randomUUID())=>scalar(
  'select public.tebb_personalization_apply($1::uuid,$2::uuid,$3::bigint,$4::text,$5::jsonb) as value',
  [op,id,version,action,payload===null?null:JSON.stringify(payload)]);
const pull=(after=0,limit=100)=>scalar('select public.tebb_personalization_pull($1::bigint,$2::integer) as value',[after,limit]);
const status=()=>scalar('select public.tebb_personalization_status() as value');
const operation=id=>scalar('select public.tebb_personalization_operation($1::uuid) as value',[id]);

before(async()=>{
  db=await PGlite.create({extensions:{vector}});
  console.log('Database fixture:',(await db.query('select version()')).rows[0].version);
  await db.exec(`
    create role anon noinherit;
    create role authenticated noinherit;
    create schema auth;
    create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $auth$
      select (nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub')::uuid;
    $auth$;
    grant usage on schema auth to anon,authenticated;
    grant execute on function auth.uid() to anon,authenticated;
    insert into auth.users values ('${A}'),('${B}');
  `);
  await db.exec(await readFile(new URL('../../migrations/20261103000000_personalization.sql',import.meta.url),'utf8'));
});
beforeEach(()=>actor());
after(async()=>{await db?.close();});

test('migration enables pgvector and enforces RLS on all private tables',async()=>{
  const state=await status();assert.equal(state.contract,'tebb.personalization.v1');assert.equal(state.pgvector,true);
  assert.equal(await scalar("select extensions.l2_distance('[1,2,3]'::extensions.vector,'[1,2,4]'::extensions.vector) as value"),1);
  const {rows}=await db.query("select relrowsecurity,relforcerowsecurity from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='tebb_private' and c.relkind='r'");
  assert.equal(rows.length,3);assert.ok(rows.every(r=>r.relrowsecurity&&r.relforcerowsecurity));
});

test('anonymous roles cannot invoke any entry point even with a forged sub',async()=>{
  await actor(A,'anon');
  for(const fn of [status,()=>pull(),()=>operation(randomUUID()),()=>apply(randomUUID())])
    await assert.rejects(fn,{code:'42501'});
});

test('authenticated role without a user identity is rejected',async()=>{
  await actor(null);
  for(const fn of [status,()=>pull(),()=>operation(randomUUID()),()=>apply(randomUUID())])
    await assert.rejects(fn,{code:'42501'});
});

test('records, direct table reads and operation lookup are isolated between users',async()=>{
  const id=randomUUID(),op=randomUUID();const receipt=await apply(id,0,'put',body('A的偏好'),op);
  assert.equal(receipt.user_id,A);assert.equal(receipt.status,'applied');assert.equal(receipt.version,1);
  await actor(B);assert.equal((await pull()).records.length,0);assert.equal((await status()).revision,0);
  assert.deepEqual(await operation(op),{user_id:B,found:false,receipt:null});
  assert.equal(await scalar('select count(*)::integer as value from tebb_private.personalization_records where user_id=$1',[A]),0);
  await apply(id,0,'put',body('B的偏好'),op);
  assert.deepEqual((await pull()).records.map(r=>r.text),['B的偏好']);
  await actor(A);assert.equal((await pull()).records.find(r=>r.id===id).text,'A的偏好');
});

test('authenticated clients cannot write tables directly',async()=>{
  await assert.rejects(db.query('update tebb_private.personalization_records set text=$1',['绕过版本']),{code:'42501'});
  await assert.rejects(db.exec('delete from tebb_private.personalization_operations'),{code:'42501'});
  await assert.rejects(db.exec('update tebb_private.personalization_heads set revision=0'),{code:'42501'});
});

test('only confirmed practical record fields are accepted; invalid requests make no changes',async()=>{
  const head=(await status()).revision;
  const invalid=[{...body(),user_id:B},{...body(),state:'candidate'},{...body(),category:'emotion'},
    {...body(),kind:'personality'},{...body(),text:null},{...body(),text:''},{...body(),text:'x'.repeat(4001)},
    {...body(),scope:'user',scope_id:'project-a'},{...body(),scope:'project',scope_id:''},
    {...body(),source_ref:null},{...body(),scope:null},[],null];
  for(const payload of invalid)await assert.rejects(apply(randomUUID(),0,'put',payload),{code:'22023'});
  assert.equal((await status()).revision,head);
});

test('per-project and companion scope stays explicit and never grants resource access',async()=>{
  const id=randomUUID();await apply(id,0,'put',{...body(),scope:'project',scope_id:'opaque-project-id'});
  const record=(await pull()).records.find(r=>r.id===id);assert.equal(record.scope,'project');assert.equal(record.scope_id,'opaque-project-id');
  assert.ok(!('user_id' in record));
});

test('idempotent retry returns the original receipt without incrementing a version',async()=>{
  const id=randomUUID(),op=randomUUID(),payload=body();const first=await apply(id,0,'put',payload,op);
  await apply(id,1,'put',body('更正后'));
  assert.deepEqual(await apply(id,0,'put',payload,op),first);
  assert.equal((await pull()).records.find(r=>r.id===id).version,2);
  assert.deepEqual((await operation(op)).receipt,first);
  assert.ok(!JSON.stringify(first).includes(payload.text));
});

test('reusing an operation ID for another payload or record is rejected',async()=>{
  const id=randomUUID(),op=randomUUID();await apply(id,0,'put',body(),op);
  await assert.rejects(apply(id,0,'put',body('另一次请求'),op),{code:'22023'});
  await assert.rejects(apply(randomUUID(),0,'put',body(),op),{code:'22023'});
});

test('stale device updates return a durable conflict instead of replacing a newer value',async()=>{
  const id=randomUUID(),op=randomUUID();await apply(id);await apply(id,1,'put',body('设备一更新'));
  const conflict=await apply(id,1,'put',body('离线设备旧更新'),op);
  assert.equal(conflict.status,'conflict');assert.equal(conflict.version,2);
  await apply(id,2,'put',body('已明确处理冲突'));
  assert.deepEqual(await apply(id,1,'put',body('离线设备旧更新'),op),conflict);
  assert.equal((await pull()).records.find(r=>r.id===id).text,'已明确处理冲突');
});

test('disable is synchronized, and explicit reconfirmation can enable it again',async()=>{
  const id=randomUUID();await apply(id);await apply(id,1,'disable',null);
  assert.equal((await pull()).records.find(r=>r.id===id).state,'disabled');
  await apply(id,2,'put',body('再次确认'));assert.equal((await pull()).records.find(r=>r.id===id).state,'active');
});

test('delete clears content/source and retains a tombstone that old or fresh puts cannot resurrect',async()=>{
  const id=randomUUID(),device=randomUUID(),op=randomUUID(),payload={...body('随后删除'),source_device_id:device,source_ref:'turn-opaque-id'};
  const first=await apply(id,0,'put',payload,op);const head=(await status()).revision;
  const deleted=await apply(id,1,'delete',null);assert.equal(deleted.status,'applied');
  const row=(await pull(head)).records.find(r=>r.id===id);
  assert.equal(row.state,'deleted');assert.equal(row.text,null);assert.equal(row.source_ref,null);assert.equal(row.source_device_id,null);
  assert.equal((await apply(id,1,'put',payload)).status,'gone');assert.equal((await apply(id,2,'put',payload)).status,'gone');
  assert.deepEqual(await apply(id,0,'put',payload,op),first);
  assert.equal((await pull()).records.find(r=>r.id===id).text,null);
  assert.equal(await scalar("select count(*)::integer as value from tebb_private.personalization_operations where receipt::text like '%随后删除%'"),0);
});

test('unknown records have explicit receipts and never advance the change cursor',async()=>{
  const head=(await status()).revision,id=randomUUID();
  for(const action of ['disable','delete'])assert.equal((await apply(id,0,action,null)).status,'not_found');
  assert.equal((await status()).revision,head);
});

test('change pagination uses server revisions, includes tombstones, and returns an empty catch-up page',async()=>{
  const start=(await status()).revision,ids=[];
  for(let i=0;i<5;i++){const id=randomUUID();ids.push(id);await apply(id,0,'put',body('分页'+i));}
  await apply(ids[0],1,'delete',null);
  let cursor=start,rows=[],more=true;
  while(more){const page=await pull(cursor,2);assert.ok(page.cursor>cursor);rows.push(...page.records);cursor=page.cursor;more=page.has_more;}
  assert.equal(rows.length,5);assert.deepEqual(new Set(rows.map(r=>r.id)),new Set(ids));
  assert.equal(rows.find(r=>r.id===ids[0]).state,'deleted');assert.equal(cursor,(await status()).revision);
  assert.deepEqual(await pull(cursor),{user_id:A,records:[],cursor,head:cursor,has_more:false});
});

test('invalid or foreign/future cursors fail explicitly instead of silently clearing data',async()=>{
  for(const [cursor,limit] of [[-1,100],[(await status()).revision+1,100],[0,0],[0,101]])
    await assert.rejects(pull(cursor,limit),{code:'22023'});
});

test('invalid source UUID and payload-bearing deletes leave the original value intact',async()=>{
  const id=randomUUID();await apply(id);
  await assert.rejects(apply(id,1,'put',{...body(),source_device_id:'bad-id'}),{code:'22P02'});
  await assert.rejects(apply(id,1,'delete',body()),{code:'22023'});
  assert.equal((await pull()).records.find(r=>r.id===id).version,1);
});

test('Python two-account/device acceptance runs against the migration through a synthetic HTTP auth fixture',async()=>{
  const tokens={'synthetic-A':A,'synthetic-A2':A,'synthetic-B':B};
  const server=createServer(async(req,res)=>{
    try{
      const owner=tokens[(req.headers.authorization||'').replace('Bearer ','')];
      if(!owner){res.writeHead(401);res.end('{}');return;}
      let value;
      if(req.url==='/auth/v1/user')value={id:owner};
      else{
        const chunks=[];for await(const chunk of req)chunks.push(chunk);
        const args=JSON.parse(Buffer.concat(chunks).toString()||'{}');
        await actor(owner);
        if(req.url==='/rest/v1/rpc/tebb_personalization_status')value=await status();
        else if(req.url==='/rest/v1/rpc/tebb_personalization_pull')value=await pull(args.p_after,args.p_limit);
        else if(req.url==='/rest/v1/rpc/tebb_personalization_operation')value=await operation(args.p_operation_id);
        else if(req.url==='/rest/v1/rpc/tebb_personalization_apply')value=await apply(args.p_record_id,args.p_expected_version,args.p_action,args.p_payload,args.p_operation_id);
        else{res.writeHead(404);res.end('{}');return;}
      }
      res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(value));
    }catch(error){res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({code:error.code}));}
  });
  const folder=await mkdtemp(join(tmpdir(),'tebb-cloud-contract-'));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    const report=join(folder,'report.json');
    const child=spawn(process.env.TEBB_CLOUD_TEST_PYTHON||'python',['scripts/eval_personalization_cloud.py','--live','--report',report],{
      cwd:fileURLToPath(new URL('../../../',import.meta.url)),
      env:{...process.env,PYTHONUTF8:'1',NO_PROXY:'127.0.0.1,localhost',
        TEBB_CLOUD_URL:`http://127.0.0.1:${server.address().port}`,TEBB_CLOUD_PUBLISHABLE_KEY:'sb_publishable_'+'a'.repeat(24),
        TEBB_CLOUD_TEST_PROJECT:'1',TEBB_CLOUD_TEST_TOKEN_A:'synthetic-A',TEBB_CLOUD_TEST_TOKEN_A2:'synthetic-A2',TEBB_CLOUD_TEST_TOKEN_B:'synthetic-B'},
      timeout:60000
    });
    let stdout='',stderr='';child.stdout.on('data',data=>stdout+=data);child.stderr.on('data',data=>stderr+=data);
    const code=await new Promise((resolve,reject)=>{child.on('error',reject);child.on('close',resolve);});
    const result=JSON.parse(await readFile(report,'utf8'));
    assert.equal(code,0,stdout+stderr+JSON.stringify(result));assert.equal(result.status,'passed');
    assert.equal(result.cleanup,'tombstone_confirmed');assert.equal(result.steps.length,4);
    assert.ok(!JSON.stringify(result).includes('synthetic-A'));
  }finally{
    await new Promise(resolve=>server.close(resolve));
    await rm(join(folder,'report.json'),{force:true});
    await rm(join(folder,'report.json.tmp'),{force:true});
    await rmdir(folder);
  }
});
