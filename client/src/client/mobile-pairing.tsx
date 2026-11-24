import {useEffect, useState} from 'react';
import {WorkspaceDialog} from './workspace-dialog';
import {rpc, type BackendInfo} from './api';

type Pairing = {state:string;account_ready?:boolean;legacy?:boolean; addresses:string[]; paired?:string; qr?:string; name?:string; code?:string; id?:string};

export function MobilePairingPane({info}:{info:BackendInfo|null}) {
  const [view,setView]=useState<Pairing|null>(null);
  const [address,setAddress]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    if(!info)return;
    let active=true;
    let timer:ReturnType<typeof setTimeout>;
    async function refresh(){
      try {
        const result=await rpc<Pairing>(info!, 'mobile_pairing', {});
        if(active)setView(result);
      } catch(e){if(active)setError(String(e));}
      if(active)timer=setTimeout(refresh,1500);
    }
    void refresh();
    return ()=>{active=false;clearTimeout(timer);};
  },[info]);
  async function change(action:string){
    if(!info||busy)return;
    setBusy(true);setError('');
    try {setView(await rpc<Pairing>(info,'mobile_pairing',{action,address,request_id:view?.id||''}));}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <section className="settings-card"><h3>Android 手机配对</h3>
    {view && !view.account_ready && <p>请先在「账号与空间」登录，与手机使用同一账号，并重启切换到该空间。</p>}
    {view?.paired ? <><p>{view.legacy?'旧版授权，请解除后重新配对':'已配对'} · {view.paired}</p><button className="desk-btn" disabled={busy} onClick={()=>void change('forget')}>解除配对</button></>
    : view?.state==='pending' ? <><p>{view.name} 正在申请配对。请核对手机上的校验码 <strong>{view.code}</strong>。</p>
      <button className="desk-btn" disabled={busy} onClick={()=>void change('approve')}>允许配对</button>
      <button className="desk-btn" disabled={busy} onClick={()=>void change('reject')}>拒绝</button></>
    : <>{view?.qr && <figure><img src={view.qr} width={260} alt="Android 局域网配对二维码"/><figcaption>手机登录同一账号后可点选此电脑或扫码，邀请三分钟有效。</figcaption></figure>}
      {view?.state==='expired' && <p>二维码已过期。</p>}
      {view?.state==='rejected' && <p>已拒绝此次申请。</p>}
      <label>局域网地址 <select value={address||view?.addresses[0]||''} onChange={e=>setAddress(e.target.value)}>
        {view?.addresses.map(ip=><option key={ip}>{ip}</option>)}</select></label>
      <button className="desk-btn" disabled={busy||!view?.account_ready||!view.addresses.length} onClick={()=>void change('start')}>{view?.qr?'重新生成':'配对 Android 手机'}</button></>}
    {error && <p role="alert">{error}</p>}</section>;
}

/** 申请到达时在工作区弹出确认框，关闭后仍可从账号设置继续处理。 */
export function MobilePairingNotice({info}:{info:BackendInfo|null}) {
  const [pending,setPending]=useState<Pairing|null>(null);
  const [dismissed,setDismissed]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    let timer:ReturnType<typeof setTimeout>;
    setPending(null);
    if(!info)return;
    async function poll(){
      try {
        const view=await rpc<Pairing>(info!,'mobile_pairing',{action:'pending'});
        if(active)setPending(view.state==='pending'?view:null);
      } catch {if(active)setPending(null);}
      if(active)timer=setTimeout(poll,3000);
    }
    void poll();
    return ()=>{active=false;clearTimeout(timer);};
  },[info]);
  if(!info||!pending?.id||pending.id===dismissed)return null;
  const requestId=pending.id;
  async function decide(action:'approve'|'reject'){
    setBusy(true);setError('');
    try {
      await rpc(info!,'mobile_pairing',{action,request_id:requestId});
      setDismissed(requestId);
    } catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <WorkspaceDialog title="手机申请连接" onClose={()=>setDismissed(requestId)} closeDisabled={busy}>
    <p>{pending.name} 请求连接这台电脑。请与手机核对校验码 <strong>{pending.code}</strong>。</p>
    <button className="desk-btn" disabled={busy} onClick={()=>void decide('approve')}>允许配对</button>
    <button className="desk-btn" disabled={busy} onClick={()=>void decide('reject')}>拒绝</button>
    {error&&<p role="alert">{error}</p>}
  </WorkspaceDialog>;
}
