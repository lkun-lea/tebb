import {useState, useEffect} from 'react';
import {usePageActive} from './page-stack';
import {WorkspaceDialog} from './workspace-dialog';
import {UiButton} from './ui-controls';

type Pending = {scope:string; title:string; detail:string; apply:()=>void};

/** 绑定到打开时的账号与操作对象；切换页面、取消或 Escape 都只收起确认框。 */
export function useActionConfirmation(scope:string) {
  const visible = usePageActive();
  const [pending,setPending] = useState<Pending|null>(null);
  useEffect(()=>{setPending(null);},[scope,visible]);
  const ask = (title:string, detail:string, apply:()=>void) => setPending({scope,title,detail,apply});
  const close = () => setPending(null);
  const dialog = visible && pending?.scope === scope && <WorkspaceDialog title={pending.title} onClose={close} className="workspace-confirmation">
    <p>{pending.detail}</p>
    <footer><UiButton autoFocus onClick={close}>取消</UiButton>
      <UiButton onClick={()=>{close();pending.apply();}}>确认</UiButton></footer>
  </WorkspaceDialog>;
  return {ask,dialog};
}
