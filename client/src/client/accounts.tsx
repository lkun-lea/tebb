import {useEffect,useMemo,useRef,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {HardDrive,UserRound} from 'lucide-react';
import {rpc,type BackendInfo} from './api';
import {AccountController,ACCOUNT_FIXTURE} from './account-state';
import {accountStorage} from './account-storage';
import {UiButton,UiFeedback,UiField} from './ui-controls';
import './accounts.css';

const health:Record<string,string>={signed_in:'登录有效',expired:'需要刷新登录',reauth_required:'需要重新登录'};
export function AccountsPane({info,debug=false}:{info:BackendInfo|null;debug?:boolean}){
  const controller=useMemo(()=>new AccountController((method,args)=>{
    if(debug)return Promise.resolve(ACCOUNT_FIXTURE);
    if(!info)return Promise.reject(Error('本地助手尚未连接。'));
    return rpc(info,method,args,{timeoutMs:30000});
  },accountStorage()),[info?.port,info?.token,debug]);
  const [,render]=useState(0),[email,setEmail]=useState(''),[code,setCode]=useState(''),[url,setUrl]=useState(''),[publicKey,setPublicKey]=useState(''),[restarting,setRestarting]=useState(false);
  const codeInput=useRef<HTMLInputElement>(null);
  useEffect(()=>controller.subscribe(()=>render(value=>value+1)),[controller]);
  useEffect(()=>{void controller.read();},[controller]);
  const page=controller.page,busy=controller.busy||restarting,blocked=busy||!!controller.unknown||controller.damaged||debug;
  const codeError=controller.errorType==='verify_code'&&!controller.unknown&&page?.challenge?controller.error:'';
  useEffect(()=>{if(codeError){codeInput.current?.focus();codeInput.current?.parentElement?.scrollIntoView({block:'nearest'});}},[codeError]);
  useEffect(()=>{if(page)setUrl(page.url);},[page?.url]);
  useEffect(()=>{setCode('');},[page?.challenge?.id]);
  async function submit(type:string,args:Record<string,unknown>={}){
    const ok=await controller.act(type,args);
    if(type==='verify_code')setCode('');
    if(ok&&type==='configure')setPublicKey('');
  }
  async function restart(){
    setRestarting(true);
    try{await invoke('restart_for_account');}
    catch(error){controller.error=String(error);controller.errorType='';setRestarting(false);render(value=>value+1);}
  }
  if(!page)return <UiFeedback state={controller.error?'error':'loading'} title={controller.error||'正在读取账号状态…'}>{controller.error&&<UiButton onClick={()=>void controller.read()}>重新读取</UiButton>}</UiFeedback>;
  return <section className="accounts-pane" aria-label="账号与本机空间">
    <header><h2>账号与本机空间</h2><UiButton disabled={busy} onClick={()=>void controller.read()}>刷新状态</UiButton></header>
    {debug&&<p>设计预览使用合成数据，不发送验证码或切换账号。</p>}
    {controller.error&&!codeError&&<UiFeedback state="error" title={controller.error}/>}
    {controller.notice&&<UiFeedback state="success" title={controller.notice}/>}
    {controller.unknown&&<UiFeedback state="unconfirmed" title="上次账号操作需要核对"><p>先读取原操作状态；结果不明时不会自动重新发送验证码或验证。</p><div className="accounts-actions"><UiButton disabled={busy} onClick={()=>void controller.read()}>核对原操作</UiButton><UiButton disabled={busy||debug} onClick={()=>void submit('acknowledge')}>结束核对并重新登录</UiButton></div></UiFeedback>}
    <article className="accounts-card accounts-current"><div className="accounts-avatar">{page.runtime.mode==='local'?<HardDrive size={22}/>:<UserRound size={22}/>}</div><div><h3>{page.runtime.mode==='local'?'本机空间':page.runtime.email}</h3><p>{page.runtime.mode==='local'?'现有资料保留在这台设备，不自动归属新账号。':'当前工作区按账号独立保存；本阶段尚未启用跨设备同步。'}</p></div><span className="accounts-badge">当前空间</span></article>
    {page.restart_required&&<UiFeedback state="unconfirmed" title="待重启切换空间"><p>目标：{page.selected==='local'?'本机空间':page.accounts.find(a=>a.id===page.selected)?.email||'已验证账号'}。重启会结束当前本机任务并收尾；未确认的外部回执保留在原空间。</p><div className="accounts-actions"><UiButton variant="primary" busy={restarting} busyLabel="正在收尾并重启…" disabled={busy||debug} onClick={()=>void restart()}>重启并切换</UiButton><UiButton disabled={blocked} onClick={()=>void submit('cancel_switch')}>保留当前空间</UiButton></div></UiFeedback>}
    <details className="accounts-card" open={!page.configured||!!page.config_error}><summary>账号服务连接</summary>
      {page.config_error&&<p role="alert">{page.config_error}</p>}
      <p>{page.configured?'已配置：'+page.url:'账号服务尚未配置。需要部署方提供项目地址和公开客户端密钥。'}</p>
      {!page.config_managed&&<form onSubmit={event=>{event.preventDefault();void submit('configure',{url,publishable_key:publicKey});}}>
        <UiField label="项目地址"><input value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://项目.supabase.co" disabled={blocked}/></UiField>
        <UiField label="公开客户端密钥" help="填写 publishable key；已保存时留空可保留。"><input type="password" autoComplete="off" value={publicKey} onChange={e=>setPublicKey(e.target.value)} disabled={blocked}/></UiField>
        <UiButton type="submit" disabled={blocked} busy={controller.activeType==='configure'} busyLabel="正在保存连接…">保存连接</UiButton>
      </form>}
    </details>
    <article className="accounts-card"><h3>邮箱登录</h3><p>新账号使用独立的空白空间，不自动复制本机聊天、模型密钥或飞书配置。</p>
      <form onSubmit={event=>{event.preventDefault();void submit('send_code',{email});}}>
        <UiField label="邮箱"><input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} disabled={blocked}/></UiField>
        <UiButton type="submit" disabled={blocked||!page.configured||!email} busy={controller.activeType==='send_code'} busyLabel="正在申请验证码…">获取验证码</UiButton>
      </form>
      {page.challenge&&<form onSubmit={event=>{event.preventDefault();void submit('verify_code',{challenge_id:page.challenge!.id,code});}}>
        <UiField label="邮箱验证码" help={'已发送至 '+page.challenge.email} error={codeError?<span role="alert">{codeError}</span>:undefined}><input ref={codeInput} type="password" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e=>setCode(e.target.value)} disabled={blocked}/></UiField>
        <UiButton type="submit" variant="primary" disabled={blocked||!/^\d{6}$/.test(code)} busy={controller.activeType==='verify_code'} busyLabel="正在核实登录…">验证并登录</UiButton>
      </form>}
    </article>
    <article className="accounts-card"><h3>此设备上的账号</h3>
      {!page.accounts.length&&<p>尚未保存登录账号。</p>}
      {page.accounts.map(account=><div className="accounts-row" key={account.id}><UserRound size={18}/><div><strong>{account.email}</strong><p>{health[account.state]||account.state}{account.current?' · 当前空间':''}</p></div><div className="accounts-actions">{account.current?<><UiButton disabled={blocked||account.state==='reauth_required'} onClick={()=>void submit('check_session')}>核对登录</UiButton><UiButton disabled={blocked} onClick={()=>void submit('logout')}>退出账号</UiButton></>:<UiButton disabled={blocked||account.state==='reauth_required'} onClick={()=>void submit('activate',{account_id:account.id})}>切换到此账号</UiButton>}</div></div>)}
      {page.runtime.mode==='account'&&<UiButton disabled={blocked} onClick={()=>void submit('activate',{account_id:'local'})}>返回本机空间</UiButton>}
    </article>
  </section>;
}
