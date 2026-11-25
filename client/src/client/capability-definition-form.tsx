import {useRef,useState} from 'react';
import {rpc,type BackendInfo} from './api';
import {UiButton,UiField} from './ui-controls';

export type Capability = {id:string; name:string; kind:string; revision:number; version:string; parameters:Record<string,string>; template:Record<string,unknown>};
export type Adapter = {kind:string;label:string;defaults:Record<string,unknown>};

export function CapabilityDefinitionForm({info,existing,adapters,onSaved}:{info:BackendInfo;existing?:Capability;adapters:Adapter[];onSaved:()=>Promise<void>}) {
  const available=adapters.filter(item=>item.kind!=='trigger');
  const initial=available.find(item=>item.kind===(existing?.kind||'ai'))||available[0];
  const [kind,setKind]=useState(initial?.kind||''),[name,setName]=useState(existing?.name||'');
  const [parameters,setParameters]=useState(JSON.stringify(existing?.parameters||{},null,2));
  const [template,setTemplate]=useState(JSON.stringify(existing?.template||initial?.defaults||{},null,2));
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const attempt=useRef<{key:string;operation:string}>();
  async function save() {
    if(busy)return;
    setBusy(true);setError('');
    try {
      const payload={name:name.trim(),kind,parameters:JSON.parse(parameters),template:JSON.parse(template),id:existing?.id,revision:existing?.revision};
      const key=JSON.stringify(payload);
      if(attempt.current?.key!==key)attempt.current={key,operation:crypto.randomUUID().replaceAll('-','')};
      const value=await rpc<{ok:boolean;error?:string}>(info,'automation_workflow',{operation:'capability_save',payload:{...payload,operation:attempt.current.operation}});
      if(!value.ok)throw Error(value.error||'保存失败');
      await onSaved();
    } catch(e) {setError(e instanceof SyntaxError?'参数或模板的 JSON 格式有误。':String(e));} finally {setBusy(false);}
  }
  return <details><summary>手动编辑执行定义</summary><form className="library-form" onSubmit={e=>{e.preventDefault();void save();}}>
    <UiField label="能力名称"><input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></UiField>
    <UiField label="执行动作"><select value={kind} onChange={e=>{setKind(e.target.value);setTemplate(JSON.stringify(available.find(item=>item.kind===e.target.value)?.defaults||{},null,2));}}>{available.map(a=><option key={a.kind} value={a.kind}>{a.label}</option>)}</select></UiField>
    <UiField label="参数默认值（JSON）"><textarea value={parameters} onChange={e=>setParameters(e.target.value)}/></UiField>
    <UiField label="执行模板（JSON）" help="例如，先声明 text 参数，再用 {{input.text}} 引用它。"><textarea value={template} onChange={e=>setTemplate(e.target.value)}/></UiField>
    <UiButton type="submit" disabled={!name.trim()||!kind} busy={busy}>保存执行定义</UiButton>{error&&<p role="alert">{error}</p>}
  </form></details>;
}
