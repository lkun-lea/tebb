const {test,assert,React,create,act,loader,text,button}=require('./component-fixture.cjs');
const base=()=>{
 const item={id:'memory-one',text:'项目使用 Node 20 和 pnpm',version:1,scope:'project',owner:'project-one',state:'active',selected:true,reason:'归属一致',source:{kind:'manual'}};
 const selection={selected:[item],excluded:[],scope:{project:'project-one',partner:'tebb',conversation:'one'},revision:'v1'};
 const request={model:'fixture',messages:[{role:'system',content:item.text},{role:'user',content:'真实输入末尾'}],tools:[{type:'function',function:{name:'calendar_change'}}]};
 return {item,selection,request,inspection:{ok:true,items:[{id:'call-one',created:1,agent:'tebb',phase:'route',model:'fixture'}],selected:'call-one',recording:true,budget:{input_tokens:123,input_source:'provider',window:null},detail:{request,request_raw:JSON.stringify(request),call:{state:'succeeded'},meta:{sources:{status:'captured',selection,messages:[{index:0,status:'matched',sources:[{category:'memory_project',start:0,end:item.text.length,source:item}]},{index:1,status:'matched',sources:[{category:'current_input',start:0,end:6}]}]}}}},catalog:{selection,scope:selection.scope,agents:[{id:'tebb',name:'tebb'}]}};
};
async function mount(fixture=base(),handler,props={}){
 global.window={setInterval:()=>1,clearInterval(){}};global.crypto=require('node:crypto').webcrypto;
 const calls=[];const load=loader({'./api':{rpc:async(_i,method,args)=>{calls.push({method,args});if(handler){const result=await handler(method,args);if(result!==undefined)return result;}return method==='load_context_debug'?fixture.inspection:fixture.catalog;}}});
 const {MemoryInspector}=load('memory-inspector');let view;await act(async()=>{view=create(React.createElement(MemoryInspector,{info:{port:1,token:'fixture'},conversation:'one',draft:'下一轮目标',onClose(){},...props}));});
 return {view,calls};
}
test('memory desk displays immutable sent provenance and full request, not current partner preferences',async()=>{
 const {view,calls}=await mount();const all=text(view.toJSON());
 assert(all.includes('调用检查台'));assert(all.includes('Node 20'));assert(all.includes('v1'));assert(all.includes('已冻结'));assert(!all.includes('这位伙伴记住的偏好'));
 await act(async()=>button(view,'完整有序消息、工具定义与请求 JSON').props.onClick());
 await act(async()=>button(view,'完整请求 JSON').props.onClick());assert(text(view.toJSON()).includes('真实输入末尾'));assert(text(view.toJSON()).includes('calendar_change'));
 assert.deepEqual(new Set(calls.map(c=>c.method)),new Set(['load_context_debug','memory_debug']));assert(!calls.some(c=>c.args.action?.type==='trial_run'));
 await act(async()=>view.unmount());
});
test('old calls with unknown provenance never show current preferences as historically sent',async()=>{
 const fixture=base();fixture.inspection.detail.meta={};const {view}=await mount(fixture);
 assert(text(view.toJSON()).includes('不能代替历史记忆'));assert(!text(view.toJSON()).includes('Node 20'));
 await act(async()=>button(view,'管理当前来源').props.onClick());assert(text(view.toJSON()).includes('当前来源库（非已发送）'));assert(text(view.toJSON()).includes('Node 20'));
 await act(async()=>view.unmount());
});
test('next preview uses separate RPC assembly without appending to old JSON or invoking model',async()=>{
 const fixture=base();const {view,calls}=await mount(fixture,async(method,args)=>{
  if(args.action?.type==='preview')return {request:{messages:[{role:'user',content:'新组装输入'}]},sources:{selection:fixture.selection},revision:'next',action:args.action.send,kind:'route',note:'共享组装器'};
 });
 await act(async()=>button(view,'下次发送预览').props.onClick());await act(async()=>button(view,'组装下一次请求').props.onClick());
 assert.equal(calls.at(-1).args.action.type,'preview');assert.equal(calls.at(-1).args.action.send.text,'下一轮目标');assert(text(view.toJSON()).includes('共享组装器'));assert(!calls.some(c=>c.args.action?.type==='trial_run'));
 await act(async()=>view.unmount());
});
test('source edit compares the current version and uncertain save cannot be automatically repeated',async()=>{
 let edits=0;const {view,calls}=await mount(base(),async(method,args)=>{if(args.action?.type==='edit'){edits++;throw Error('断连');}});
 await act(async()=>button(view,'编辑当前来源').props.onClick());
 await act(async()=>view.root.findByProps({'aria-label':'记忆来源正文'}).props.onChange({target:{value:'Node 22'}}));
 await act(async()=>button(view,'保存来源修改').props.onClick());
 const action=calls.find(c=>c.args.action?.type==='edit').args.action.change;assert.equal(action.version,1);assert.equal(action.text,'Node 22');assert.equal(action.scope,'project');assert.equal(action.owner,'project-one');assert.match(action.operation,/^[a-f0-9]{32}$/);
 assert.equal(edits,1);assert(button(view,'保存来源修改').props.disabled);assert(text(view.toJSON()).includes('不自动重发'));await act(async()=>view.unmount());
});
test('trial is local until explicit run and never calls external action APIs',async()=>{
 const fixture=base();const {view,calls}=await mount(fixture,async(method,args)=>{
  if(args.action?.type==='trial_prepare')return {request:{messages:fixture.request.messages},diffs:[],revision:'trial-v1',target:{model:'fixture',base_url:'https://model.invalid'},note:'local'};
  if(args.action?.type==='trial_run')return {task_id:'trial-one'};
  if(args.action?.type==='trial_status')return {task:{id:'trial-one',state:'succeeded',answer:'真实试验回执'}};
 });
 await act(async()=>button(view,'独立试验').props.onClick());await act(async()=>button(view,'试验中停用此条').props.onClick());
 await act(async()=>button(view,'组装独立试验').props.onClick());assert(!calls.some(c=>c.args.action?.type==='trial_run'));
 const prepare=calls.find(c=>c.args.action?.type==='trial_prepare');assert.equal(prepare.args.action.overrides['memory-one'],null);
 await act(async()=>button(view,'明确试跑一次').props.onClick());assert.equal(calls.filter(c=>c.args.action?.type==='trial_run').length,1);assert(text(view.toJSON()).includes('真实试验回执'));assert(text(view.toJSON()).includes('结果未写回'));assert(!calls.some(c=>['collaboration_action','terminal_start','tebb_operation'].includes(c.method)));
 await act(async()=>view.unmount());
});
test('missing request is explicit and a new source defaults to the current conversation',async()=>{
 const fixture=base();fixture.inspection.detail={request:null,request_raw:'',missing:true,call:{state:'missing'}};const {view,calls}=await mount(fixture);
 assert(text(view.toJSON()).includes('此调用文件缺失'));
 await act(async()=>view.root.findByProps({'aria-label':'新增记忆来源'}).props.onClick());assert.equal(view.root.findByProps({'aria-label':'记忆来源作用域'}).props.value,'conversation');
 assert(!calls.some(c=>c.args.action?.type==='edit'));await act(async()=>view.unmount());
});
test('source navigation expands the requested full message instead of linking to collapsed content',async()=>{
 const {view}=await mount();
 const source=view.root.findByProps({className:'memory-source-count'}).findAllByType('button').find(n=>text(n).includes('本轮输入'));
 await act(async()=>source.props.onClick());
 assert(text(view.toJSON()).includes('真实输入末尾'));
 await act(async()=>view.unmount());
});
test('preview carries composer choices and notifies the composer only after confirmed send',async()=>{
 const fixture=base();let sent='';const options={target:'tebb',model_id:'selected-model',skills:['selected-skill'],attachments:['selected-file'],sampling:{reasoning_effort:'high',temperature:.8,top_p:.9}};
 const {view,calls}=await mount(fixture,async(_method,args)=>{if(args.action?.type==='preview')return {request:fixture.request,sources:{selection:fixture.selection},revision:'version',action:args.action.send,model:{model:'selected-model'},note:'预览'};if(args.action?.type==='send_preview')return {ok:true};},{sendOptions:options,onSent:text=>sent=text});
 await act(async()=>button(view,'下次发送预览').props.onClick());await act(async()=>button(view,'组装下一次请求').props.onClick());
 const action=calls.find(c=>c.args.action?.type==='preview').args.action.send;
 assert.equal(action.model_id,'selected-model');assert.deepEqual(action.skills,options.skills);assert.deepEqual(action.attachments,options.attachments);assert.deepEqual(action.sampling,options.sampling);assert.equal(sent,'');
 await act(async()=>button(view,'按此版本发送').props.onClick());assert.equal(sent,'下一轮目标');assert.equal(calls.filter(c=>c.args.action?.type==='send_preview').length,1);
 await act(async()=>view.unmount());
});
test('an older selected call remains selectable and supplies its own partner after pagination',async()=>{
 const fixture=base();fixture.inspection.has_more=true;const older={id:'old-call',created:0,agent:'writer',phase:'task',model:'fixture',run_title:'旧任务'};
 const {view,calls}=await mount(fixture,async(method,args)=>{
  if(method==='load_context_debug'&&args.before!==undefined)return {...fixture.inspection,items:[older],has_more:false};
  if(method==='load_context_debug'&&args.call_id==='old-call')return {...fixture.inspection,selected:'old-call',detail:{...fixture.inspection.detail,request_raw:'旧调用的完整原始输入'}};
 });
 await act(async()=>button(view,'更早调用').props.onClick());
 await act(async()=>view.root.findByProps({'aria-label':'记忆检查调用'}).props.onChange({target:{value:'old-call'}}));
 assert(view.root.findAllByType('option').some(n=>n.props.value==='old-call'));
 assert.equal(calls.filter(c=>c.args.action?.type==='catalog').at(-1).args.action.agent_id,'writer');
 await act(async()=>button(view,'完整有序消息、工具定义与请求 JSON').props.onClick());await act(async()=>button(view,'完整请求 JSON').props.onClick());assert(text(view.toJSON()).includes('旧调用的完整原始输入'));
 await act(async()=>view.unmount());
});
