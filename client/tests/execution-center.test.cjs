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
 await act(async()=>button(view,'tool0 · 结果未知').props.onClick());
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
