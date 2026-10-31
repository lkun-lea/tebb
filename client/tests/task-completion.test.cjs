const{test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer'),load=require('./load-client.cjs');
const{TaskCompletionPanel}=load('task-completion.tsx',{'./api':{},'./reminders.css':{}});
const guid='b5e165af-3f0d-4708-89bc-c4fd3a69738d',task={guid,title:'可见待办',when:'今天',overdue:false};
const button=(view,text)=>view.root.findAllByType('button').find(node=>node.children.join('')===text);

test('the actual completion buttons require a verified preview and call complete without deleting or advancing local work',async()=>{
 let view,deleted=0,refreshed=0;const calls=[];let receipt;
 const transport=async(method,args)=>{calls.push([method,args]);if(method==='task_completion_status')return{ok:true,operations:receipt?[receipt]:[]};
  if(method==='task_completion_prepare')return receipt={ok:true,request_id:args.request_id,guid,summary:'服务端标题',identity:{user_name:'核实账号',open_id:'user-one'},state:'prepared'};
  assert.equal(method,'task_completion_confirm');assert.equal(args.request_id,receipt.request_id);return receipt={...receipt,state:'confirmed',remote_state:'confirmed',cache_state:'confirmed'};};
 await act(async()=>{view=create(React.createElement(TaskCompletionPanel,{info:null,debug:false,tasks:[task],transport,onRefresh:()=>refreshed++,onDeleteTask:()=>deleted++}));});
 try{await act(async()=>button(view,'完成待办').props.onClick());assert(button(view,'确认完成'));assert.equal(calls.filter(([m])=>m==='task_completion_confirm').length,0);
  await act(async()=>button(view,'确认完成').props.onClick());assert.equal(calls.filter(([m])=>m==='task_completion_confirm').length,1);assert.equal(deleted,0);assert.equal(refreshed,1);assert(calls.every(([m])=>!m.includes('delete')&&!m.includes('work_item')));
 }finally{act(()=>view.unmount());}
});

test('a lost completion response keeps its original request and offers only readonly inspection',async()=>{
 let view,receipt;const calls=[];const transport=async(method,args)=>{calls.push([method,args]);if(method==='task_completion_status')return{ok:true,operations:receipt?[receipt]:[]};
  if(method==='task_completion_prepare')return receipt={ok:true,request_id:args.request_id,guid,summary:'原待办',state:'prepared'};
  if(method==='task_completion_confirm'){receipt={...receipt,ok:false,state:'unconfirmed'};throw Error('lost acknowledgement');}
  assert.equal(method,'task_completion_inspect');assert.equal(args.request_id,receipt.request_id);return{...receipt,ok:true,state:'observed_done',execution_result:'unconfirmed'};};
 await act(async()=>{view=create(React.createElement(TaskCompletionPanel,{info:null,debug:false,tasks:[task],transport,onRefresh(){}}));});
 try{await act(async()=>button(view,'完成待办').props.onClick());await act(async()=>button(view,'确认完成').props.onClick());assert.equal(button(view,'确认完成'),undefined);
  await act(async()=>button(view,'核对原结果').props.onClick());assert.equal(calls.filter(([m])=>m==='task_completion_confirm').length,1);assert.equal(calls.filter(([m])=>m==='task_completion_inspect').length,1);
  assert(view.root.findAllByProps({role:'status'}).some(node=>node.children.join('').includes('原写入回执仍未知')));
 }finally{act(()=>view.unmount());}
});

test('cancelling the confirmation leaves the real task untouched',async()=>{
 let view;const calls=[];const transport=async(method,args)=>{calls.push(method);return method==='task_completion_status'?{ok:true,operations:[]}:{ok:true,guid,request_id:args.request_id,state:'prepared'};};
 await act(async()=>{view=create(React.createElement(TaskCompletionPanel,{info:null,debug:false,tasks:[task],transport,onRefresh(){}}));});
 try{await act(async()=>button(view,'完成待办').props.onClick());act(()=>button(view,'取消').props.onClick());assert.equal(button(view,'确认完成'),undefined);assert.deepEqual(calls,['task_completion_status','task_completion_prepare','task_completion_status']);}
 finally{act(()=>view.unmount());}
});
