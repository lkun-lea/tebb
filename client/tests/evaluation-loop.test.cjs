const {test}=require('node:test'),assert=require('node:assert/strict');
const React=require('react'),{act,create}=require('react-test-renderer'),load=require('./load-client.cjs');
const info={port:1,token:'fixture'};
const button=(view,text)=>view.root.findAllByType('button').find(n=>n.children.join('')===text);

test('coverage exposes missing entry evidence and selects immutable suite versions',async()=>{
 let selected;const {EvaluationCoverage}=load('evaluation-evidence.tsx',{'./api':{rpc:async()=>({canonical_cases:64,splits:{regression:60,holdout:4},areas:[{id:'read',label:'读取',level:'component',cases:[],missing:[]}],suites:{timeout:['frozen-1','frozen-2']},uncovered_entries:[{entry:'知识库',reason:'缺少端到端样本'}]})}});
 let view;await act(async()=>view=create(React.createElement(EvaluationCoverage,{info,onSelect:v=>selected=v})));
 assert(JSON.stringify(view.toJSON()).includes('缺少端到端样本'));
 act(()=>button(view,'读取').props.onClick());
 const detail=view.root.findByType('dialog');
 assert.equal(detail.props['aria-label'],'读取');
 act(()=>detail.findByType('button').props.onClick());
 assert.equal(view.root.findAllByType('dialog').length,0);
 act(()=>button(view,'选择超时专项（2）').props.onClick());assert.deepEqual(selected,['frozen-1','frozen-2']);
 act(()=>view.unmount());
});

test('real model evaluation requires explicit cost authorization and clears it when plan changes',async()=>{
 const sent=[];const rpc=async(_,method,args)=>{
  if(method==='load_models')return {ok:true,active:'model-1',items:[{id:'model-1',model:'configured',has_key:true}]};
  if(args.operation==='cases')return {items:[{id:'judge',version:'frozen',split:'regression',spec:{prompt:'fixed',category:'judge',expected:{status:'pass'}}}]};
  if(args.operation==='list')return {items:[],next_offset:null};
  if(args.operation==='runtime')return {source_harness:true,node:true,promptfoo_installed:true};
  if(args.operation==='start')sent.push(args.payload);
  return {ok:true};
 };
 const {EvaluationPane}=load('evaluation-center.tsx',{'./api':{rpc},'./evaluation-evidence':{EvaluationCoverage:()=>null,EvaluationDiagnosis:()=>null},'./execution-trace':{ExecutionTrace:()=>null}});
 let view;await act(async()=>view=create(React.createElement(EvaluationPane,{info})));
 const selects=()=>view.root.findAllByType('select');
 await act(async()=>selects().find(n=>n.props.value==='fixture').props.onChange({target:{value:'live'}}));
 const checks=()=>view.root.findAllByType('input').filter(n=>n.props.type==='checkbox');
 act(()=>view.root.findAllByType('button').find(n=>n.children.join('').includes('选择固定用例')).props.onClick());
 act(()=>checks()[0].props.onChange({target:{checked:true}}));
 act(()=>view.root.findAllByType('button').find(n=>n.children.join('').includes('完成选择')).props.onClick());
 assert(button(view,'启动真实模型评测').props.disabled);
 act(()=>checks().at(-1).props.onChange({target:{checked:true}}));
 assert(!button(view,'启动真实模型评测').props.disabled);
 act(()=>view.root.findAllByType('input').find(n=>n.props.value===120).props.onChange({target:{value:'90'}}));
 assert(button(view,'启动真实模型评测').props.disabled);
 act(()=>checks().at(-1).props.onChange({target:{checked:true}}));
 await act(async()=>button(view,'启动真实模型评测').props.onClick());
 assert.equal(sent.length,1);assert.equal(sent[0].live_authorized,true);assert.equal(sent[0].model_id,'model-1');assert.equal(sent[0].timeout,90);assert.equal(sent[0].review_effort,'provider_default');
 act(()=>view.unmount());
});
