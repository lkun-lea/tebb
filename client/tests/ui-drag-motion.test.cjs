const {test,assert,React,create,act,loader}=require('./component-fixture.cjs');
const load=require('./load-client.cjs');
const spring=load('drag-motion.ts');
function environment(){global.window=new EventTarget();global.document={documentElement:{dataset:{}}};global.ResizeObserver=class{constructor(fn){global.resizePreview=fn;}observe(){}disconnect(){}};}
function pointer(target,type,x,id=1){const e=new Event(type);Object.assign(e,{clientX:x,pointerId:id});target.dispatchEvent(e);}
async function harness(reduced=true){
 environment();const animations=[];let reducedState=reduced;
 const mock={...require('./motion-fixture.cjs'),useReducedMotion:()=>reducedState,animate:(from,to,options)=>{const record={from,to,options,stopped:false,stop(){this.stopped=true;}};animations.push(record);return record;}};
 const {useWorkspaceResize}=loader({'framer-motion':mock})('use-workspace-resize');
 const node={getBoundingClientRect:()=>({width:1000,right:1000})},box={current:node};let result;
 function Component(){result=useWorkspaceResize(box,true);return React.createElement('button',result.handleProps);}
 const handle=new EventTarget();let captured=false;Object.assign(handle,{focus(){},setPointerCapture(){captured=true;},hasPointerCapture:()=>captured,releasePointerCapture(){captured=false;}});
 let view;await act(async()=>{view=create(React.createElement(Component));});
 const down=(x=560)=>act(()=>result.handleProps.onPointerDown({button:0,pointerId:1,clientX:x,currentTarget:handle,preventDefault(){}}));
 return {view,handle,animations,node,down,setReduced(next){act(()=>{reducedState=next;view.update(React.createElement(Component));});},get result(){return result;},async close(){await act(async()=>view.unmount());}};
}
test('1200/80 curve has monotone progress, zero overshoot and matches CSS samples',()=>{
 assert.deepEqual(spring.DRAG_SPRING,{type:'spring',stiffness:1200,damping:80,mass:1});
 let previous=0;for(let i=0;i<=500;i++){const p=spring.dragProgress(i/1000);assert(p>=previous&&p<=1);previous=p;}
 assert(1-previous<0.0001);const values=spring.DRAG_EASING.slice(7,-1).split(',').map(Number);
 assert.equal(values.length,51);assert.equal(values[0],0);assert.equal(values.at(-1),1);
 assert(Math.abs(values[20]-spring.dragProgress(.2))<.000001);
});
test('splitter follows pointer delta without spring; Escape restores width and retains focus owner',async()=>{
 const h=await harness();h.down(558);act(()=>pointer(h.handle,'pointermove',459));assert.equal(h.result.width,539);assert.equal(h.animations.length,0);
 act(()=>{const e=new Event('keydown',{cancelable:true});e.key='Escape';window.dispatchEvent(e);assert(e.defaultPrevented);});
 assert.equal(h.result.width,440);act(()=>pointer(h.handle,'pointermove',300));assert.equal(h.result.width,440);await h.close();
});
test('splitter snaps near bounds, clamps keyboard and respects available conversation width',async()=>{
 const h=await harness();h.down();act(()=>pointer(h.handle,'pointerup',710));assert.equal(h.result.width,280);
 const key=key=>act(()=>h.result.handleProps.onKeyDown({key,preventDefault(){}}));key('End');assert.equal(h.result.width,614);
 key('ArrowLeft');assert.equal(h.result.width,614);key('Home');key('ArrowRight');assert.equal(h.result.width,280);
 assert.equal(h.result.handleProps.role,'separator');assert.equal(h.result.handleProps['aria-valuenow'],280);await h.close();
});
test('pointercancel, lost capture and window blur each restore the pre-drag width',async()=>{
 for(const type of ['pointercancel','lostpointercapture','blur']){
  const h=await harness();h.down();act(()=>pointer(h.handle,'pointermove',500));assert.equal(h.result.width,500);
  act(()=>type==='blur'?window.dispatchEvent(new Event('blur')):pointer(h.handle,type,500));assert.equal(h.result.width,440);
  act(()=>pointer(h.handle,'pointerup',300));assert.equal(h.result.width,440);await h.close();
 }
});
test('regrab stops settling spring and unmount disposes captured pointer listeners',async()=>{
 const h=await harness(false);h.down();act(()=>pointer(h.handle,'pointerup',710));assert.equal(h.animations.length,1);
 assert.equal(h.animations[0].to,280);act(()=>h.animations[0].options.onUpdate(310));h.down(690);assert(h.animations[0].stopped);
 act(()=>pointer(h.handle,'pointermove',680));assert.equal(h.result.width,320);
 await h.close();assert.equal(h.handle.hasPointerCapture(),false);pointer(h.handle,'pointermove',500);pointer(h.handle,'pointerup',500);
 assert.equal(h.animations.length,1);
});
test('manual reduced motion changes live without remounting',async()=>{
 environment();let callback;global.MutationObserver=class{constructor(fn){callback=fn;}observe(){}disconnect(){}};
 const {useUiReducedMotion}=loader({'framer-motion':{useReducedMotion:()=>false}})('use-ui-reduced-motion');let reduce;
 function Component(){reduce=useUiReducedMotion();return null;}let view;act(()=>{view=create(React.createElement(Component));});assert.equal(reduce,false);
 act(()=>{document.documentElement.dataset.reduceMotion='true';callback();});assert.equal(reduce,true);
 act(()=>{document.documentElement.dataset.reduceMotion='false';callback();});assert.equal(reduce,false);
 act(()=>view.unmount());delete global.MutationObserver;
});
test('viewport narrowing stops a spring before its old destination can exceed the new limit',async()=>{
 const h=await harness(false);act(()=>h.result.setWidth(680));act(()=>h.animations[0].options.onUpdate(500));
 h.node.getBoundingClientRect=()=>({width:686,right:686});act(()=>global.resizePreview());
 assert(h.animations[0].stopped);assert.equal(h.result.width,300);assert.equal(h.result.handleProps['aria-valuemax'],300);await h.close();
});
test('enabling reduced motion during a held pointer also affects its existing release callback',async()=>{
 const h=await harness(false);h.down();act(()=>pointer(h.handle,'pointermove',710));h.setReduced(true);act(()=>pointer(h.handle,'pointerup',710));
 assert.equal(h.result.width,280);assert.equal(h.animations.length,0);await h.close();
});
test('calendar cancel never commits; valid landing uses preview and invalid landing returns to origin',async()=>{
 environment();document.body={};let context,overlay,commits=[],finished=[];let projected={time:{start:'2026-11-06T01:00:00Z',end:'2026-11-06T02:00:00Z'},style:{left:100,top:200}};
 const Wrapper=props=>{context=props;return React.createElement('div',{},props.children);};
 const dnd={DndContext:Wrapper,DragOverlay:props=>{overlay=props;return null;},PointerSensor:{},useSensor(){},useSensors(){},defaultDropAnimation:{keyframes:()=>[{transform:'origin'},{transform:'return'}]}};
 const {CalendarDragSurface}=loader({'@dnd-kit/core':dnd,'react-dom':{createPortal:node=>node}})('calendar-drag');
 let view;act(()=>{view=create(React.createElement(CalendarDragSurface,{reduce:false,project:()=>projected,onStart(){},onCommit:(...args)=>commits.push(args),onFinish:value=>finished.push(value)},'calendar'));});
 const event={active:{data:{current:{source:{kind:'item',item:{title:'Synthetic'}}}}},delta:{x:0,y:0}};
 act(()=>context.onDragStart(event));act(()=>context.onDragCancel());assert.equal(commits.length,0);assert.deepEqual(finished,[true]);
 const args={transform:{initial:{x:30,y:50}},dragOverlay:{rect:{left:40,top:70}}};assert.equal(overlay.dropAnimation.keyframes(args)[1].transform,'return');
 act(()=>context.onDragStart(event));act(()=>context.onDragEnd(event));assert.equal(commits.length,1);assert.equal(overlay.dropAnimation.easing,spring.DRAG_EASING);
 assert.equal(overlay.dropAnimation.keyframes(args)[1].transform,'translate3d(90px, 180px, 0) scaleX(1) scaleY(1)');
 projected=null;act(()=>context.onDragStart(event));act(()=>context.onDragEnd(event));assert.equal(commits[1][1],null);assert.equal(overlay.dropAnimation.keyframes(args)[1].transform,'return');
 act(()=>view.update(React.createElement(CalendarDragSurface,{reduce:true,project:()=>null,onStart(){},onCommit(){},onFinish(){}},'calendar')));assert.equal(overlay.dropAnimation,null);act(()=>view.unmount());
});
