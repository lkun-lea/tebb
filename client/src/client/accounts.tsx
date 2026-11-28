import {WorkspaceDialog} from './workspace-dialog';
import {ReceiptNotice} from "./toast";
import {useEffect,useMemo,useRef,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {HardDrive,UserRound} from 'lucide-react';
import {rpc,type BackendInfo} from './api';
import {AccountController,ACCOUNT_FIXTURE} from './account-state';
import {accountStorage} from './account-storage';
import {UiButton,UiFeedback,UiField} from './ui-controls';
import './accounts.css';

const health:Record<string,string>={signed_in:'登录有效',expired:'需要刷新登录',reauth_required:'需要重新登录'};
export function AccountsPane({info,debug=false,developerMode=false}:{info:BackendInfo|null;debug?:boolean;developerMode?:boolean}){
  const controller=useMemo(()=>new AccountController((method,args)=>{
    if(debug)return Promise.resolve(ACCOUNT_FIXTURE);
    if(!info)return Promise.reject(Error('本地助手尚未连接。'));
    return rpc(info,method,args,{timeoutMs:30000});
  },accountStorage()),[info?.port,info?.token,debug]);
  const [,render]=useState(0),[email,setEmail]=useState(''),[code,setCode]=useState(''),[url,setUrl]=useState(''),[publicKey,setPublicKey]=useState(''),[loginOpen,setLoginOpen]=useState(false),[switching,setSwitching]=useState(false);
  const codeInput=useRef<HTMLInputElement>(null);
  useEffect(()=>controller.subscribe(()=>render(value=>value+1)),[controller]);
  useEffect(()=>{void controller.read();},[controller]);
  const page=controller.page,busy=controller.busy||switching,blocked=busy||!!controller.unknown||controller.damaged||debug;
  const codeError=controller.errorType==='verify_code'&&!controller.unknown&&page?.challenge?controller.error:'';
  useEffect(()=>{if(codeError){codeInput.current?.focus();codeInput.current?.parentElement?.scrollIntoView({block:'nearest'});}},[codeError]);
  useEffect(()=>{if(page)setUrl(page.url);},[page?.url]);
  useEffect(()=>{setCode('');},[page?.challenge?.id]);
  async function submit(type:string,args:Record<string,unknown>={}){
    const ok=await controller.act(type,args);
    if(type==='verify_code')setCode('');
    if(ok&&type==='configure')setPublicKey('');
    if(ok&&['verify_code','logout','activate'].includes(type)){
      if(controller.page?.restart_required)await switchWorkspace();
      else setLoginOpen(false);
    }
  }
  async function switchWorkspace(){
    setSwitching(true);
    try{await invoke('switch_account_workspace',{previousPort:info?.port});setLoginOpen(false);}
    catch(error){controller.error='切换空间失败：'+String(error);controller.errorType='';setLoginOpen(false);render(value=>value+1);}
    finally{setSwitching(false);}
  }
  if(!page){
    if(controller.error)return <><ReceiptNotice text={controller.error}/><UiButton onClick={()=>void controller.read()}>重新读取</UiButton></>;
    return <UiFeedback state="loading" title="正在读取账号状态…"/>;
  }
  return <section className="accounts-pane" aria-label="账号与本机空间">
    <header><h2>账号与本机空间</h2><UiButton disabled={busy} onClick={()=>void controller.read()}>刷新状态</UiButton></header>
    {debug&&<p>设计预览使用合成数据，不发送验证码或切换账号。</p>}
    <ReceiptNotice text={controller.error || controller.notice}/>
    {controller.unknown&&!controller.busy&&<UiFeedback state="unconfirmed" title="上次账号操作需要核对"><p>先读取原操作状态；结果不明时不会自动重新发送验证码或验证。</p><div className="accounts-actions"><UiButton disabled={busy} onClick={()=>void controller.read()}>核对原操作</UiButton><UiButton disabled={busy||debug} onClick={()=>void submit('acknowledge')}>结束核对并重新登录</UiButton></div></UiFeedback>}
    <article className="accounts-card accounts-current"><div className="accounts-avatar">{page.runtime.mode==='local'?<HardDrive size={22}/>:<UserRound size={22}/>}</div><div><h3>{page.runtime.mode==='local'?'本机空间':page.runtime.email}</h3><p>{page.runtime.mode==='local'?'现有资料保留在这台设备，不自动归属新账号。':'当前工作区按账号独立保存；确认资料在“个人资料”中管理与同步。'}</p></div><span className="accounts-badge">当前空间</span></article>
    {page.restart_required&&<UiButton disabled={busy||debug} onClick={()=>void switchWorkspace()}>{switching?'正在切换空间…':'进入已选空间'}</UiButton>}
    {developerMode&&<details className="accounts-card" open={!page.configured||!!page.config_error}><summary>账号服务连接</summary>
      <ReceiptNotice text={page.config_error}/>
      <p>{page.configured?'已配置：'+page.url:'账号服务尚未配置。需要部署方提供项目地址和公开客户端密钥。'}</p>
      {!page.config_managed&&<form className="accounts-connection-form" onSubmit={event=>{event.preventDefault();void submit('configure',{url,publishable_key:publicKey});}}>
        <UiField label="项目地址"><input value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://项目.supabase.co" disabled={blocked}/></UiField>
        <UiField label="公开客户端密钥" help="填写 publishable key；已保存时留空可保留。"><input type="password" autoComplete="off" value={publicKey} onChange={e=>setPublicKey(e.target.value)} disabled={blocked}/></UiField>
        <UiButton type="submit" disabled={blocked} busy={controller.activeType==='configure'} busyLabel="正在保存连接…">保存连接</UiButton>
      </form>}
    </details>}
    <article className="accounts-card"><h3>{page.runtime.mode==='local'?'访客模式':'账号登录'}</h3>
      <p>访客可以使用本机聊天和任务。云端聊天、个人资料云同步和同账号设备发现需要登录。</p>
      <UiButton variant="primary" disabled={busy} onClick={()=>setLoginOpen(true)}>{page.runtime.mode==='local'?'登录 tebb':'登录其他账号'}</UiButton>
    </article>
    {loginOpen&&<WorkspaceDialog title="邮箱登录" closeDisabled={busy} onClose={()=>setLoginOpen(false)} className="accounts-login">
      <div className="accounts-card"><p>暂不登录也可以使用本机聊天和任务。云端聊天、个人资料云同步和同账号设备发现需要登录。</p>
      <p>登录后进入独立账号空间。切换会结束当前空间运行中的本机任务，聊天记录保留在原空间。</p>
      {!page.configured&&<p role='status'>账号服务尚未配置，请联系部署方后再登录。</p>}
      <form onSubmit={event=>{event.preventDefault();void submit('send_code',{email});}}>
        <UiField label="邮箱"><input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} disabled={blocked}/></UiField>
        <UiButton type="submit" disabled={blocked||!page.configured||!email} busy={controller.activeType==='send_code'} busyLabel="正在申请验证码…">获取验证码</UiButton>
      </form>
      {page.challenge&&<form onSubmit={event=>{event.preventDefault();void submit('verify_code',{challenge_id:page.challenge!.id,code});}}>
        <UiField label="邮箱验证码" help={'已发送至 '+page.challenge.email}><input aria-invalid={!!codeError} ref={codeInput} type="password" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e=>setCode(e.target.value)} disabled={blocked}/></UiField>
        <UiButton type="submit" variant="primary" disabled={blocked||!/^\d{6}$/.test(code)} busy={controller.activeType==='verify_code'} busyLabel="正在核实登录…">验证并登录</UiButton>
      </form>}
      <UiButton disabled={busy} onClick={()=>setLoginOpen(false)}>暂不登录</UiButton></div>
    </WorkspaceDialog>}
    <article className="accounts-card"><h3>此设备上的账号</h3>
      {!page.accounts.length&&<p>尚未保存登录账号。</p>}
      {page.accounts.map(account=><div className="accounts-row" key={account.id}><UserRound size={18}/><div><strong>{account.email}</strong><p>{health[account.state]||account.state}{account.current?' · 当前空间':''}</p></div><div className="accounts-actions">{account.current?<><UiButton disabled={blocked||account.state==='reauth_required'} onClick={()=>void submit('check_session')}>核对登录</UiButton><UiButton disabled={blocked} onClick={()=>void submit('logout')}>退出账号</UiButton></>:<UiButton disabled={blocked||account.state==='reauth_required'} onClick={()=>void submit('activate',{account_id:account.id})}>切换到此账号</UiButton>}</div></div>)}
      {page.runtime.mode==='account'&&<UiButton disabled={blocked} onClick={()=>void submit('activate',{account_id:'local'})}>返回本机空间</UiButton>}
    </article>
  </section>;
}
