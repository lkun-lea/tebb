import {useState, useEffect} from 'react';
import {usePageActive} from './page-stack';
import {WorkspaceDialog} from './workspace-dialog';
import {UiButton} from './ui-controls';

type Pending = {scope:string; title:string; detail:string; action:{label:string; danger?:boolean}; apply:()=>void};

/** 绑定到打开时的账号与操作对象；切换页面、取消或 Escape 都只收起确认框。 */
export function useActionConfirmation(scope:string, disabled=false) {
  const visible = usePageActive();
  const [pending,setPending] = useState<Pending|null>(null);
  useEffect(()=>{setPending(null);},[scope,visible]);
  const ask = (title:string, detail:string, action:Pending["action"], apply:()=>void) => setPending({scope,title,detail,action,apply});
  const close = () => setPending(null);
  const dialog = visible && pending?.scope === scope && <WorkspaceDialog role="alertdialog" title={pending.title} onClose={close} className="workspace-confirmation">
    <p>{pending.detail}</p>
    <footer><UiButton autoFocus onClick={close}>取消</UiButton>
      <UiButton disabled={disabled} variant={pending.action.danger ? "danger" : "primary"} className={pending.action.danger ? "desk-btn-danger-solid" : ""} onClick={()=>{close();pending.apply();}}>{pending.action.label}</UiButton></footer>
  </WorkspaceDialog>;
  return {ask,dialog};
}

export function DraftLeaveDialog({title,detail,saveLabel,discardLabel,saveDisabled,discardDisabled,onKeep,onDiscard,onSave}:{
  title:string;detail:string;saveLabel:string;discardLabel:string;saveDisabled:boolean;discardDisabled:boolean;
  onKeep:()=>void;onDiscard:()=>void;onSave:()=>void;
}) {
  return <WorkspaceDialog role="alertdialog" title={title} onClose={onKeep} className="workspace-confirmation">
    <p>{detail}</p>
    <footer>
      <UiButton onClick={onDiscard} disabled={discardDisabled}>{discardLabel}</UiButton>
      <UiButton autoFocus onClick={onKeep}>继续编辑</UiButton>
      <UiButton variant="primary" onClick={onSave} disabled={saveDisabled}>{saveLabel}</UiButton>
    </footer>
  </WorkspaceDialog>;
}
