const{test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer'),load=require('./load-client.cjs');
const protocol=load('calendar-proposal-state.ts'),shared=load('schedule-state.ts'),week=load('schedule-week-state.ts',{'./schedule-state':shared});
const{LocalCalendarController}=load('local-calendar-state.ts'),{CalendarEventEditor}=load('calendar-event-editor.tsx');
const proposal={kind:'calendar_proposal',version:1,id:'a'.repeat(32),save_request_id:'b'.repeat(32),source:{task_id:'actual-task',run_id:'actual-run'},summary:'模型安排提案',start:'2040-01-02T09:00:00+08:00',end:'2040-01-02T10:00:00+08:00',item_id:'item-one',timezone:'Asia/Shanghai'};
const memory=()=>{const values=new Map();return{getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
const button=(view,label)=>view.root.findAllByType('button').find(node=>node.children.join('')===label);

test('only typed task events supply actions and child-run proposals reach the root message',()=>{
 assert.throws(()=>protocol.calendarProposal('模型说已创建草稿'));assert.throws(()=>protocol.calendarProposal({...proposal,version:true}));
 assert.deepEqual(protocol.proposalsFromEvents([{kind:'token',data:{proposal}},{kind:'calendar_proposal',data:{proposal:{...proposal,timezone:'UTC'}}}]),[]);
 const events=[{kind:'calendar_proposal',data:{proposal}},{kind:'calendar_proposal',data:{proposal}}];assert.deepEqual(protocol.proposalsFromEvents(events),[proposal]);
 assert.deepEqual(protocol.proposalTree({id:'root'},[{id:'root'},{id:'child',parent:'root',calendar_proposals:[proposal]},{id:'grand',parent:'child',calendar_proposals:[proposal]}]),[proposal]);
});

test('the shared factory preserves proposal identity, exact fields and a local-only default',()=>{
 const draft=week.createCalendarDraft(proposal.start,proposal.end,{id:proposal.id,summary:proposal.summary,item_id:proposal.item_id,proposal});
 assert.equal(draft.id,proposal.id);assert.equal(draft.start,'2040-01-02T09:00');assert.equal(draft.end,'2040-01-02T10:00');assert.equal(draft.item_id,'item-one');assert.equal(draft.sync,false);
 const item=week.createCalendarDraft(proposal.start,undefined,{id:'item-draft',summary:'事项',item_id:'item-one'});assert.equal(item.end,draft.end);
});

test('the actual editor creates nothing before explicit submit and uses the proposal save request',async()=>{
 let writes=0,action,view;const draft=week.createCalendarDraft(proposal.start,proposal.end,{...proposal,proposal});
 const controller=new LocalCalendarController(async(method,args)=>{if(method==='change_local_calendar'){writes++;action=args.action;return{ok:true,event:{local_id:action.local_id}};}return{ok:true,events:[],operations:[],batches:[]};},memory());
 await act(async()=>{view=create(React.createElement(CalendarEventEditor,{value:draft,items:[{id:'item-one',title:'来源事项',version:1,archived:false}],busy:false,blocked:false,error:'',onChange(){},onClose(){},onSave:()=>controller.change({type:'create',local_id:draft.id,summary:draft.summary,start:proposal.start,end:proposal.end,item_id:draft.item_id},proposal.save_request_id)}));});
 try{assert.equal(writes,0);assert.equal(view.root.findByProps({'aria-label':'日程标题'}).props.value,proposal.summary);assert.equal(view.root.findByProps({'aria-label':'关联事项'}).props.value,'item-one');
  await act(async()=>view.root.findByType('form').props.onSubmit({preventDefault(){}}));assert.equal(writes,1);assert.equal(action.local_id,proposal.id);assert.equal(action.request_id,proposal.save_request_id);assert.equal(action.item_id,'item-one');
 }finally{act(()=>view.unmount());}
});

test('lost save acknowledgement retains the original proposal request and only reconciles after restart',async()=>{
 const store=memory();let writes=0,saved;
 const transport=async(method,args)=>{if(method==='change_local_calendar'){writes++;saved=args.action;throw Error('lost response');}return{ok:true,events:[],operations:[],batches:[]};};
 let controller=new LocalCalendarController(transport,store);await controller.change({type:'create',local_id:proposal.id,summary:proposal.summary},proposal.save_request_id);assert.equal(writes,1);assert.equal(controller.unknown.request_id,proposal.save_request_id);
 controller=new LocalCalendarController(async(method,args)=>{assert.equal(method,'load_local_calendar');assert.equal(args.request_id,proposal.save_request_id);return{ok:true,events:[{local_id:proposal.id}],operations:[],batches:[],operation:{id:saved.request_id,state:'saved'}};},store);await controller.read();assert.equal(controller.unknown,null);assert.equal(writes,1);
});

test('the actual proposal card verifies the original task before opening and never saves',async()=>{
 const calls=[],opens=[];const{CalendarProposalCards}=load('calendar-proposal.tsx',{'./api':{rpc:async(_info,method,args)=>{calls.push([method,args]);return{ok:true,state:'proposed',proposal};}},'./calendar-proposal-state':protocol,'./calendar-proposal-navigation':{openCalendarProposal:async(...args)=>opens.push(args)},'./calendar-proposal.css':{}});let view;
 await act(async()=>{view=create(React.createElement(CalendarProposalCards,{info:{port:1,token:'test'},proposals:[proposal]}));});
 try{await act(async()=>button(view,'打开日程草稿').props.onClick());assert.deepEqual(calls,[['read_calendar_proposal',{task_id:proposal.source.task_id,proposal_id:proposal.id}]]);assert.deepEqual(opens,[[proposal.source.task_id,proposal.id]]);}
 finally{act(()=>view.unmount());}
});

test('consumed or unknown proposals do not reopen a new draft or submit a write',async()=>{
 for(const state of['consumed','unconfirmed']){
  let opened=0,calls=0;const{CalendarProposalCards}=load('calendar-proposal.tsx',{'./api':{rpc:async()=>{calls++;return{ok:state==='consumed',state,notice:'已使用',error:'原结果待核对'};}},'./calendar-proposal-state':protocol,'./calendar-proposal-navigation':{openCalendarProposal:async()=>opened++},'./calendar-proposal.css':{}});let view;
  await act(async()=>{view=create(React.createElement(CalendarProposalCards,{info:{port:1,token:'test'},proposals:[proposal]}));});
  try{await act(async()=>button(view,'打开日程草稿').props.onClick());assert.equal(calls,1);assert.equal(opened,0);assert.equal(button(view,state==='consumed'?'此提案已使用':'核对原保存结果').props.disabled,state==='consumed');}finally{act(()=>view.unmount());}
 }
});
