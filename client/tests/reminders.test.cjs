const{test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer'),load=require('./load-client.cjs');
const state=load('reminders-state.ts'),{ReminderInbox}=state;
const row={id:'meeting-one',summary:'隔离会议',start:'2040-01-02T10:00:00+08:00',end:'2040-01-02T11:00:00+08:00',calendar_id:'tebb-local',event_id:'one'};
const button=(view,text)=>view.root.findAllByType('button').find(node=>node.children.join('')===text);

test('hidden windows never claim, an uncertain response reconciles the same consumer, and acknowledgement is durable',async()=>{
 let visible=false,attempt=0,acked=false;const calls=[];
 const inbox=new ReminderInbox(async(method,args)=>{calls.push([method,args]);if(method==='calendar_reminder_ack'){acked=true;return{ok:true};}if(++attempt===1)throw Error('lost response');return{ok:true,enabled:true,reminders:acked?[]:[row]};},'fixed-window',async()=>visible);
 await inbox.poll();assert.equal(calls.length,0);visible=true;await inbox.poll();assert(inbox.error);await inbox.poll();assert.equal(inbox.rows[0].id,row.id);
 assert(calls.every(([,args])=>args.consumer_id==='fixed-window'));await inbox.acknowledge([row.id]);await inbox.poll();assert.equal(inbox.rows.length,0);
 assert(calls.every(([method])=>['calendar_reminder_claim','calendar_reminder_ack'].includes(method)));
});

test('a late poll cannot redisplay an acknowledged reminder',async()=>{
 let resolve,delay=false;const inbox=new ReminderInbox(async method=>method==='calendar_reminder_ack'?{ok:true}:delay?await new Promise(done=>resolve=done):{ok:true,reminders:[row]},'fixed-window',async()=>true);
 await inbox.poll();delay=true;const pending=inbox.poll();await Promise.resolve();await inbox.acknowledge([row.id]);resolve({ok:true,reminders:[row]});await pending;assert.deepEqual(inbox.rows,[]);
});

test('the actual main-window notice is nonmodal, never focuses a window, and acknowledges only its reminder',async()=>{
 const methods=[];let acknowledged=false,view;const transport=async(method,args)=>{methods.push([method,args]);if(method==='calendar_reminder_ack'){acknowledged=true;return{ok:true};}return{ok:true,enabled:true,reminders:acknowledged?[]:[row]};};
 const{ReminderNotice}=load('reminders.tsx',{'./api':{},'./reminders-state':state,'./reminders.css':{},'@tauri-apps/api/window':{getCurrentWindow:()=>{throw Error('unexpected native access');}}});
 await act(async()=>{view=create(React.createElement(ReminderNotice,{info:null,transport,visible:async()=>true}));});
 try{assert.equal(view.root.findByProps({'aria-label':'会前提醒'}).props.role,'status');assert.equal(view.root.findAllByProps({'aria-modal':'true'}).length,0);await act(async()=>button(view,'知道了').props.onClick());assert.equal(view.toJSON(),null);assert.deepEqual(methods.map(([method])=>method),['calendar_reminder_claim','calendar_reminder_ack']);assert.deepEqual(methods[1][1].ids,[row.id]);}
 finally{act(()=>view.unmount());}
});

test('the independent settings checkbox changes only reminder preferences',async()=>{
 let enabled=false,view;const calls=[];const transport=async(method,args)=>{calls.push([method,args]);if(method==='calendar_reminder_settings')enabled=args.enabled;return{ok:true,enabled,reminders:[],candidates:[],scan:{state:'completed',errors:[],completed_at:''}};};
 const{ReminderSettings}=load('reminders.tsx',{'./api':{},'./reminders-state':state,'./reminders.css':{},'@tauri-apps/api/window':{}});
 await act(async()=>{view=create(React.createElement(ReminderSettings,{info:null,transport}));});
 try{await act(async()=>view.root.findByType('input').props.onChange({target:{checked:true}}));assert.equal(enabled,true);assert.deepEqual(calls[1],['calendar_reminder_settings',{enabled:true}]);assert.equal(view.root.findByType('input').props.checked,true);}
 finally{act(()=>view.unmount());}
});
