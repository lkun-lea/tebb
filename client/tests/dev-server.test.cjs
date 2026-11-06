const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');

test('standard Vite config serves, invalidates changed frontend modules and excludes native outputs',async()=>{
  const {createServer}=await import('vite');
  const root=path.resolve(__dirname,'..'),probe=await fs.mkdtemp(path.join(root,'src/dev-watch-'));
  const cache=await fs.mkdtemp(path.join(os.tmpdir(),'tebb-vite-test-')),file=path.join(probe,'sample.ts');
  let server;
  try {
    await fs.writeFile(file,'export const label = "before";');
    server=await createServer({root,configFile:path.join(root,'vite.config.ts'),cacheDir:cache,
      server:{host:'127.0.0.1',port:0,strictPort:true},optimizeDeps:{noDiscovery:true,include:[]},logLevel:'error'});
    await server.listen();const address=server.httpServer.address(),base=`http://127.0.0.1:${address.port}`;
    const get=async url=>{const r=await fetch(base+url,{signal:AbortSignal.timeout(15000)});assert.equal(r.status,200);return r.text();};
    assert.match(await get('/client.html'),/root/);
    const url='/'+path.relative(root,file).replaceAll('\\','/');assert.match(await get(url),/before/);
    const changed=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{server.watcher.off('change',listener);reject(Error('frontend change not observed'));},15000);
      const listener=name=>{if(path.resolve(name)!==file)return;clearTimeout(timer);server.watcher.off('change',listener);resolve();};
      server.watcher.on('change',listener);
    });
    await fs.writeFile(file,'export const label = "after";');await changed;
    assert.match(await get(url),/after/);
    assert(!Object.keys(server.watcher.getWatched()).some(name=>name.replaceAll('\\','/').startsWith(root.replaceAll('\\','/')+'/src-tauri')));
  } finally {
    await server?.close();
    assert(probe.startsWith(path.join(root,'src/dev-watch-')));await fs.rm(probe,{recursive:true,force:true});
    assert(cache.startsWith(path.join(os.tmpdir(),'tebb-vite-test-')));await fs.rm(cache,{recursive:true,force:true});
  }
});
