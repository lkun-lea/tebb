import {WorkspaceDialog} from './workspace-dialog';
import {useEffect,useRef,useState} from 'react';
import {rpc,type BackendInfo} from './api';
import {UiButton,UiFeedback,UiField} from './ui-controls';

type Coverage={canonical_cases:number;splits:Record<string,number>;areas:{id:string;label:string;level:string;missing:string[];cases:{id:string;fixture:unknown;live:unknown}[]}[];suites:Record<string,string[]>;uncovered_entries:{entry:string;reason:string;drafts?:string[]}[];unmapped_cases?:string[]};
type Diagnosis={calls:number;timeout_calls:number;items:{id:string;case_id:string;timeout:boolean;label:string;error_kind:string;progress:Record<string,unknown>|null;limitation:string}[];tasks?:{task:string;case_id:string;state:string;timing:{stages:{label:string;duration_ms:number}[]}}[]};
type Gate={ready_for_review:boolean;checks:Record<string,boolean>;timeout_before:number;timeout_after:number;scope:string};

export function EvaluationCoverage({info,onSelect,onAdd,revision}:{revision?:number;onAdd?:(category:string)=>void;info:BackendInfo|null;onSelect:(versions:string[])=>void}){
 const [areaId,setAreaId]=useState("");
 const [value,setValue]=useState<Coverage|null>(null),[error,setError]=useState('');const epoch=useRef(0);
 async function refresh(){if(!info)return;const request=++epoch.current;try{const next=await rpc<Coverage>(info,'agent_evaluation',{operation:'coverage'});if(request===epoch.current){setValue(next);setError('');}}catch(e){if(request===epoch.current)setError(String(e));}}
 useEffect(()=>{setValue(null);setError('');void refresh();return()=>{epoch.current++;};},[info,revision]);
 return <section className="eval-coverage"><header className="calls-title"><h3>能力覆盖</h3><UiButton disabled={!info} onClick={()=>void refresh()}>刷新覆盖</UiButton></header><p className="ui-field-help">用例存在、模拟通过与真实模型通过分别记录；缺少端到端样本的入口保留为缺口。</p>
 {error&&<UiFeedback state="error" title="覆盖读取失败">{error}</UiFeedback>}
 {value&&<><p>已登记 {value.canonical_cases} 个用例 · {Object.entries(value.splits).map(([key,count])=>`${({regression:'回归集',holdout:'保留集',development:'开发集'} as Record<string,string>)[key]||key} ${count}`).join(' · ')}</p>
 <div className="evaluation-suites">{Object.entries(value.suites).map(([key,ids])=><UiButton key={key} onClick={()=>onSelect(ids)}>选择{({smoke:'冒烟集',timeout:'超时专项',judge:'审阅回归集',holdout:'独立保留集'} as Record<string,string>)[key]||key}（{ids.length}）</UiButton>)}</div>
 <div className="coverage-layout"><div className="coverage-scroll"><table className="coverage-table"><thead><tr><th>能力</th><th>用例</th><th>模拟记录</th><th>真实记录</th></tr></thead><tbody>
 {value.areas.map(area=><tr key={area.id} data-selected={area.id===areaId} onClick={()=>setAreaId(area.id)}><th scope="row"><button aria-pressed={area.id===areaId} onClick={()=>setAreaId(area.id)}>{area.label}</button></th><td><span className="coverage-case-count"><i aria-hidden="true" style={{width:40*area.cases.length/Math.max(1,...value.areas.map(item=>item.cases.length))}}/>{area.cases.length}</span></td><td>{area.cases.filter(c=>c.fixture).length}</td><td>{area.cases.filter(c=>c.live).length}</td></tr>)}</tbody></table></div>
 {value.areas.filter(area=>area.id===areaId).map(area=><WorkspaceDialog key={area.id} className="coverage-detail" title={area.label} onClose={()=>setAreaId("")}><p>{area.level==='end_to_end'?'端到端':'组件'} · {area.cases.length} 个用例</p><ul>{area.cases.map(c=><li key={c.id}><code>{c.id}</code><small>{c.fixture?'有模拟记录':'无模拟记录'} · {c.live?'有真实记录':'无真实记录'}</small></li>)}</ul>{area.missing.length>0&&<p>待补充 · {area.missing.join('、')}</p>}{onAdd&&<UiButton onClick={()=>{setAreaId("");onAdd(area.id)}}>补充用例</UiButton>}</WorkspaceDialog>)}
 {value.uncovered_entries.length>0&&<section className="coverage-missing"><h4>独立黄金样本缺口</h4><ul className="coverage-gaps">{value.uncovered_entries.map(g=><li key={g.entry}><span><strong>{g.entry}</strong><small>{g.reason}</small>{!!g.drafts?.length&&<small>已补充 · {g.drafts.join("、")}</small>}</span>{onAdd&&<UiButton onClick={()=>onAdd(g.entry)}>补充样本</UiButton>}</li>)}</ul></section>}</div></>}
 {value?.unmapped_cases&&value.unmapped_cases.length>0&&<UiFeedback state="unconfirmed" title="还有用例未归入覆盖矩阵">{value.unmapped_cases.join('、')}</UiFeedback>}
 </section>;
}

export function EvaluationDiagnosis({info,ident,baseline,holdouts}:{info:BackendInfo|null;ident:string;baseline:string;holdouts:{id:string;candidate:string}[]}){
 const [diagnosis,setDiagnosis]=useState<Diagnosis|null>(null),[gate,setGate]=useState<Gate|null>(null),[holdout,setHoldout]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const epoch=useRef(0);useEffect(()=>{epoch.current++;setDiagnosis(null);setGate(null);setError('');setBusy(false);},[info,ident,baseline,holdout]);
 async function inspect(operation:'diagnose'|'gate'){if(!info)return;const version=++epoch.current;setBusy(true);setError('');try{
  const next=await rpc<Diagnosis&Gate>(info,'agent_evaluation',{operation,payload:operation==='diagnose'?{ident}:{baseline,candidate:ident,holdout}});
  if(version===epoch.current){if(operation==='diagnose')setDiagnosis(next);else setGate(next);}
 }catch(e){if(version===epoch.current)setError(String(e));}finally{if(version===epoch.current)setBusy(false);}}
 return <section aria-label="超时分析与回归门槛"><h4>超时分析与回归门槛</h4>
 <UiButton busy={busy} disabled={!info} onClick={()=>void inspect('diagnose')}>分析本批超时</UiButton>
 {error&&<UiFeedback state="error" title="分析未完成">{error}</UiFeedback>}
 {diagnosis&&<><p>已关联 {diagnosis.calls} 次模型调用，其中 {diagnosis.timeout_calls} 次超时；调用超时与业务任务结果分别统计。</p><ul>{diagnosis.items.filter(r=>r.timeout).map(r=><li key={r.id}><strong>{r.case_id} · {r.label}</strong><code className="block">{r.id}</code><details><summary>观测依据与边界</summary><p>{r.limitation}</p><pre>{JSON.stringify(r.progress,null,2)}</pre></details></li>)}</ul></>}
 {diagnosis?.tasks?.length!==undefined&&diagnosis.tasks.length>0&&<details><summary>原任务阶段耗时</summary><p className="ui-field-help">排队、准备、模型、工具与收尾使用原任务事件；没有记录的阶段不补造。</p>{diagnosis.tasks.map(task=><div key={task.task}><strong>{task.case_id} · {task.state}</strong><ul>{task.timing.stages.map((stage,i)=><li key={i}>{stage.label}：{Math.round(stage.duration_ms)} ms</li>)}</ul></div>)}</details>}
 <div className="execution-toolbar"><UiField label="独立保留集批次"><select value={holdout} onChange={e=>setHoldout(e.target.value)}><option value="">选择独立保留集</option>{holdouts.filter(b=>b.id!==ident&&b.id!==baseline).map(b=><option key={b.id} value={b.id}>{b.candidate} · {b.id.slice(0,8)}</option>)}</select></UiField><UiButton busy={busy} disabled={!info||!baseline||!holdout} onClick={()=>void inspect('gate')}>核对闭环门槛</UiButton></div>
 <p className="ui-field-help">须同题同标准、候选全部通过、无退化、超时改善，并通过同配置的独立保留集。结果只适用于固定样本，不自动发布。</p>
 {gate&&<UiFeedback state={gate.ready_for_review?'success':'unconfirmed'} title={gate.ready_for_review?'固定样本闭环检查通过':'闭环检查尚未通过'}><p>基线超时 {gate.timeout_before} → 候选 {gate.timeout_after}</p><ul>{Object.entries(gate.checks).map(([key,passed])=><li key={key}>{({baseline_model_evidence_complete:'基线调用证据完整',candidate_model_evidence_complete:'候选调用证据完整',candidate_all_mandatory_checks:'候选全部必需条件',no_regressions:'无回归退化',timeout_baseline_observed:'基线有原始超时证据',no_candidate_timeouts:'候选无模型超时',independent_holdout:'保留集独立且配置一致',holdout_all_mandatory_checks:'保留集全部必需条件'} as Record<string,string>)[key]||key}：{passed?'通过':'未通过'}</li>)}</ul></UiFeedback>}
 </section>;
}
