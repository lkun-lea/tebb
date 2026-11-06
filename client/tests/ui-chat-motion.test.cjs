const {test,assert,React,create,act,loader,text,registerMarkdown}=require('./component-fixture.cjs');
test.before(registerMarkdown);
const motion={motion:{span:({children,...props})=>React.createElement('span',props,children)},useReducedMotion:()=>true};

test('stream arrivals preserve graphemes, finish on real events and bound a fast backlog',()=>{
 const {initialStream,advanceStream}=loader({})('stream-arrival');
 let state=initialStream('已有历史',true);
 assert.deepEqual(state.arrivals,[]);
 state=advanceStream(state,state.text+'👨‍👩‍👧‍👦e\u0301中',true,100);
 assert.deepEqual(state.arrivals.map(item=>item.value),['👨‍👩‍👧‍👦','e\u0301','中']);
 assert.deepEqual(state.arrivals.map(item=>item.at),[100,130,160]);
 for(let i=0;i<100;i++){
  state=advanceStream(state,state.text+'新字',true,101+i);
  assert(state.arrivals.length<=8);assert(state.arrivals.every(item=>item.at<=101+i+210));
 }
 const full=state.text;state=advanceStream(state,full,false,210);
 assert.deepEqual(state.arrivals,[]);assert.equal(state.text,full);
 assert.deepEqual(advanceStream(state,'重写后的正文',true,220).arrivals,[]);
 let joined=advanceStream(initialStream('',true),'e',true,100);
 joined=advanceStream(joined,'e\u0301👩',true,110);
 assert.deepEqual(joined.arrivals.map(item=>item.value),['👩']);
 joined=advanceStream(joined,'e\u0301👩‍💻',true,120);
 assert.deepEqual(joined.arrivals,[]);
});

test('Markdown leaves hydrated history alone and exposes only whole new glyphs across rerenders',async()=>{
 const {StreamText}=loader({'framer-motion':motion})('stream-text');let view;
 const render=(content,active=true)=>React.createElement(StreamText,{text:content,active});
 const glyphs=()=>view.root.findAllByType('span').filter(n=>n.props.className==='tebb-stream-new');
 await act(async()=>{view=create(render('历史 **重点**'));});assert.equal(glyphs().length,0);
 await act(async()=>view.update(render('历史 **重点**👩🏽‍💻你好')));
 assert.deepEqual(glyphs().map(text),['👩🏽‍💻','你','好']);
 const start=view.root.findByType('strong');
 await act(async()=>view.update(render('历史 **重点**👩🏽‍💻你好呀')));
 assert.equal(view.root.findByType('strong'),start);assert(!glyphs().some(n=>text(n).includes('历史')));
 await act(async()=>view.update(render('历史 **重点**👩🏽‍💻你好呀',false)));
 assert.equal(glyphs().length,0);assert.equal(text(view.root.findByType('strong')),'重点');await act(async()=>view.unmount());
});

test('disclosure keeps child state while closed, links controls and removes keyboard access',()=>{
 const {InspectorDisclosure}=loader({})('inspector-disclosure');let view,mounts=0;
 function Child(){const [value,setValue]=React.useState('保留');React.useEffect(()=>{mounts++;},[]);return React.createElement('input',{value,onChange:e=>setValue(e.target.value)});}
 act(()=>{view=create(React.createElement(InspectorDisclosure,{label:'执行过程'},React.createElement(Child)));});
 const trigger=view.root.findByType('button'),body=view.root.findByProps({className:'context-disclosure-grid'});
 assert.equal(trigger.props['aria-controls'],body.props.id);assert.equal(body.props.inert,'');assert.equal(body.props['aria-hidden'],true);
 assert.equal(view.root.findAllByType('input').length,0);
 act(()=>trigger.props.onClick());const input=view.root.findByType('input');act(()=>input.props.onChange({target:{value:'已编辑'}}));
 act(()=>trigger.props.onClick());assert.equal(body.props.inert,'');act(()=>trigger.props.onClick());
 assert.equal(body.props.inert,undefined);assert.equal(view.root.findByType('input'),input);assert.equal(input.props.value,'已编辑');assert.equal(mounts,1);act(()=>view.unmount());
});

test('copy waits for success, resets expiry, ignores late results and cleans up on unmount',async(t)=>{
 const originalNavigator=Object.getOwnPropertyDescriptor(globalThis,'navigator');
 const originalSet=global.setTimeout,originalClear=global.clearTimeout;const timers=new Map();let serial=0;const writes=[];
 Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:()=>new Promise((resolve,reject)=>writes.push({resolve,reject}))}}});
 global.setTimeout=(callback,ms)=>{const id=++serial;timers.set(id,{callback,ms});return id;};global.clearTimeout=id=>timers.delete(id);
 let view;
 t.after(()=>{if(view)act(()=>view.unmount());global.setTimeout=originalSet;global.clearTimeout=originalClear;if(originalNavigator)Object.defineProperty(globalThis,'navigator',originalNavigator);else delete globalThis.navigator;});
 const {CopyButton}=loader({'framer-motion':motion})('copy-button');
 act(()=>{view=create(React.createElement(CopyButton,{text:'原文',label:'复制回复'}));});const button=view.root.findByType('button');
 await act(async()=>button.props.onClick());assert.equal(button.props['data-copied'],undefined);assert.equal(button.props['aria-busy'],true);
 await act(async()=>button.props.onClick());await act(async()=>writes[0].resolve());assert.equal(button.props['data-copied'],undefined);
 await act(async()=>writes[1].resolve());assert.equal(button.props['data-copied'],true);assert.equal(timers.size,1);assert.equal([...timers.values()][0].ms,2500);
 const oldTimer=[...timers.keys()][0];await act(async()=>button.props.onClick());assert(!timers.has(oldTimer));await act(async()=>writes[2].resolve());
 const expiry=[...timers.values()][0];act(()=>expiry.callback());assert.equal(button.props['data-copied'],undefined);
 await act(async()=>button.props.onClick());await act(async()=>writes[3].reject(Error('权限被拒绝')));assert.match(text(view.root.findByProps({role:'alert'})),/权限被拒绝/);
 await act(async()=>button.props.onClick());await act(async()=>writes[4].resolve());assert.equal(view.root.findAllByProps({role:'alert'}).length,0);
 act(()=>view.unmount());view=null;assert.equal(timers.size,0);
});

test('copy never writes a deferred text read after its owner unmounts',async()=>{
 let read,writeCount=0;const previous=Object.getOwnPropertyDescriptor(globalThis,'navigator');
 Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async()=>{writeCount++;}}}});
 try{
  const {CopyButton}=loader({'framer-motion':motion})('copy-button');let view;
  act(()=>{view=create(React.createElement(CopyButton,{text:()=>new Promise(resolve=>{read=resolve;})}));});await act(async()=>view.root.findByType('button').props.onClick());act(()=>view.unmount());await act(async()=>read('迟到的原文'));assert.equal(writeCount,0);
 }finally{if(previous)Object.defineProperty(globalThis,'navigator',previous);else delete globalThis.navigator;}
});
