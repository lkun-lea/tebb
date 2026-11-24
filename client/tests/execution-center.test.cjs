const {test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer'),load=require('./load-client.cjs');
const graph={ok:true,root:'task:root',nodes:[{id:'task:root',kind:'task',label:'root',state:'failed'},...Array.from({length:6},(_,i)=>({id:'node'+i,kind:'tool',label:'tool'+i,state:i?'returned':'unknown'}))],edges:Array.from({length:6},(_,i)=>({id:'edge'+i,source:'task:root',target:'node'+i,relation:'contains'})),timeline:['task:root',...Array.from({length:6},(_,i)=>'node'+i)],acceptance:{state:'unverified'},coverage:{}};
const buttons=view=>view.root.findAllByType('button');
const button=(view,text)=>buttons(view).find(n=>n.children.join('')===text);
const flow={ReactFlow:({children,nodes,edges})=>React.createElement('flow',{'data-nodes':nodes.length,'data-edges':edges.length},children),Controls:()=>null,Position:{Left:'left',Right:'right'},useReactFlow:()=>({fitView(){}}),useNodesInitialized:()=>true};
const info={port:1,token:'isolated'};

test('actual graph retains arbitrary branches and separates business acceptance',async()=>{
 const trace=load('execution-trace.tsx',{'./api':{rpc:async()=>graph},'@xyflow/react':flow});
 const layout=trace.graphLayout(graph);assert.equal(layout.edges.length,6);assert.equal(layout.nodes.length,7);assert(layout.edges.every(e=>!e.animated));
 let view;await act(async()=>view=create(React.createElement(trace.ExecutionTrace,{info,root:graph.root})));
 assert(JSON.stringify(view.toJSON()).includes('待核验'));
 await act(async()=>view.root.findByProps({'aria-label':'tool0 · 结果未知'}).props.onClick());
 assert(JSON.stringify(view.toJSON()).includes('"observed_state"')===false);assert(JSON.stringify(view.toJSON()).includes('node0'));
 act(()=>view.unmount());
});

test('trace ignores late root response and keeps original controls outside graph',async()=>{
 let resolve;const old=new Promise(r=>resolve=r);
 const {ExecutionTrace}=load('execution-trace.tsx',{'./api':{rpc:async(_,__,args)=>args.payload.root==='old'?old:{...graph,root:'new'}},'@xyflow/react':flow});
 let view;await act(async()=>view=create(React.createElement(ExecutionTrace,{info,root:'old'})));
 await act(async()=>view.update(React.createElement(ExecutionTrace,{info,root:'new'})));
 await act(async()=>{resolve({...graph,root:'old'});await old;});
 assert(JSON.stringify(view.toJSON()).includes('new'));assert(!JSON.stringify(view.toJSON()).includes('old'));
 assert.equal(button(view,'重跑节点'),undefined);act(()=>view.unmount());
});

test('switching runs preserves the list and restores the matching snapshot during refresh',async()=>{
 const waiting=[];
 const items=['A','B'].map(id=>({id,title:id,label:id,kind:'task',state:'returned'}));
 const rpc=async(_,__,args)=>args.operation==='list'?{items,next_offset:null,kinds:{task:2},task_states:{returned:2},acceptance:null}:new Promise(resolve=>waiting.push(resolve));
 const {ExecutionCenterPane}=load('execution-trace.tsx',{'./api':{rpc},'@xyflow/react':flow});
 let view;
 try {
  await act(async()=>{view=create(React.createElement(ExecutionCenterPane,{info,onInspectCalls(){}}));});
  const list=()=>view.root.findByProps({'aria-label':'最近运行'});
  const nav=list();
  const pick=i=>act(()=>list().findAllByType('button')[i].props.onClick());
  const heading=()=>view.root.findAllByProps({className:'run-heading'}).map(n=>n.findByType('h2').children.join(''));
  await act(async()=>waiting.shift()({...graph,root:'A'}));
  pick(1);
  assert.equal(list(),nav);
  assert.deepEqual(heading(),[]);
  const slowB=waiting.shift();
  pick(0);
  assert.equal(list(),nav);
  assert.deepEqual(heading(),['A']);
  await act(async()=>slowB({...graph,root:'B'}));
  assert.deepEqual(heading(),['A']);
 }finally{act(()=>view?.unmount());}
});

test('failure draft editor sends data-only version with source identity and rejects invalid JSON',async()=>{
 const calls=[];const {EvaluationCaseEditor}=load('evaluation-center.tsx',{'./api':{rpc:async(_,method,args)=>{calls.push({method,args});return {ok:true};}}});let view;
 await act(async()=>view=create(React.createElement(EvaluationCaseEditor,{info,sourceFailure:'failure-7'})));
 const input=view.root.findAllByType('input')[0],areas=view.root.findAllByType('textarea');
 act(()=>{input.props.onChange({target:{value:'case-7'}});areas[0].props.onChange({target:{value:'Return JSON total=7.'}});areas[1].props.onChange({target:{value:'invalid'}});});
 await act(async()=>button(view,'保存开发用例版本').props.onClick());assert.equal(calls.length,0);assert(view.root.findAllByProps({role:'alert'}).length);
 act(()=>areas[1].props.onChange({target:{value:'{"total":7}'}}));
 await act(async()=>button(view,'保存开发用例版本').props.onClick());
 assert.equal(calls[0].method,'agent_evaluation');assert.equal(calls[0].args.payload.value.source_failure,'failure-7');assert.deepEqual(calls[0].args.payload.value.expected,{total:7});
 assert(!('command'in calls[0].args.payload.value));act(()=>view.unmount());
});

test('waterfall groups successful calls and keeps the failed model visible with its receipt',async()=>{
 const calls=[0,1,2].map(i=>({id:'m'+i,kind:'model',label:'model',purpose:'task',task:'coder',started:i+1,ended:i+2,state:i===2?'failed':'returned'}));
 const sample={...graph,nodes:[graph.nodes[0],...calls],edges:[],timeline:[graph.root,...calls.map(c=>c.id)]};
 const {ExecutionTrace}=load('execution-trace.tsx',{'./api':{rpc:async()=>sample},'@xyflow/react':flow});
 let view;
 await act(async()=>view=create(React.createElement(ExecutionTrace,{info,root:sample.root})));
 try {
   const group=view.root.findByProps({'aria-label':'模型调用 × 2'});
   assert.equal(group.props['aria-expanded'],false);
   assert.equal(view.root.findByProps({'aria-label':'model · 失败'}).props['aria-pressed'],true);
   act(()=>group.props.onClick());
   assert.equal(view.root.findAllByProps({'aria-label':'model · 已返回'}).length,2);
 } finally {act(()=>view.unmount());}
});

test('an unlinked task shows an empty state without an error toast',async()=>{
 const notices=[];
 const {ExecutionTrace}=load('execution-trace.tsx',{'./api':{rpc:async()=>({ok:true,state:'unlinked'})},'./toast':{notifyReceipt:text=>notices.push(text)},'@xyflow/react':flow});
 let view;await act(async()=>{view=create(React.createElement(ExecutionTrace,{info,task:'historical'}));});
 assert.match(JSON.stringify(view.toJSON()),/这项任务暂无执行记录/);
 assert.deepEqual(notices,[]);
 act(()=>view.unmount());
});
