const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const {create, act} = require('react-test-renderer');
const load = require('./load-client.cjs');

test('cloud history is available on first render, scoped, deduplicated and safe across late receipts', async () => {
  const data = new Map();
  global.localStorage = {
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: key => data.delete(key)
  };
  const accounts = load('account-storage.ts');
  accounts.initializeAccountStorage('a'.repeat(64));
  const turn = {id:'run1', text:'缓存问题', answer:'缓存回答', state:'succeeded', error:''};
  accounts.accountStorage().setItem('tebb.cloud.history.A', JSON.stringify([turn]));
  const streams = [];
  let accept;
  const {useCloudChat} = load('cloud-chat.tsx', {
    './account-storage':accounts,
    './api':{
      readEvents: (_, path, receive, signal) => {
        streams.push({path, receive, signal});
        return new Promise(resolve => signal.addEventListener('abort', resolve));
      },
      cloudMessage: () => new Promise(resolve => {accept = resolve;})
    }
  });
  const info = {port:1234, token:'fixture'};
  let view, current;
  function Chat({id}) {current = useCloudChat(info,id,true);return null;}
  await act(async () => {view = create(React.createElement(Chat,{id:'A'}));});
  const initial = current.turns;
  assert.deepEqual(initial,[turn]);
  await act(async () => {
    streams[0].receive({type:'history',data:null});
    streams[0].receive({type:'turn',data:{...turn}});
  });
  assert.equal(current.turns,initial);
  let posted;
  await act(async () => {posted=current.send('新问题',undefined,()=>{});});
  await act(async () => {view.update(React.createElement(Chat,{id:'B'}));});
  assert.equal(streams[0].signal.aborted,true);
  await act(async () => {
    streams[0].receive({type:'turn',data:{...turn,id:'迟到'}});
    accept('run2');await posted;
  });
  assert.deepEqual(current.turns,[]);
  await act(async () => {view.update(React.createElement(Chat,{id:'A'}));});
  assert.deepEqual(current.turns.map(t=>t.id),['run1','run2']);
  assert.equal(current.pending,null);
  await act(async () => {streams.at(-1).receive({type:'turn',data:{...turn,id:'run2',answer:'更新'}});});
  assert.deepEqual(current.turns.map(t=>t.answer),['缓存回答','更新']);
  assert.equal(data.has('tebb.cloud.history.A'),false);
  await act(async () => {view.unmount();});
});
