import {useEffect,useRef,useState}from'react';
import {getCurrentWindow}from'@tauri-apps/api/window';
import {rpc,type BackendInfo}from'./api';
import {ReminderInbox,reminderText,type ReminderResponse,type ReminderTransport}from'./reminders-state';
import './reminders.css';

type Props={info:BackendInfo|null;debug?:boolean;transport?:ReminderTransport};
export function ReminderNotice({info,debug=false,transport,visible}:Props&{visible?:()=>Promise<boolean>}){
  const consumer=useRef('main_'+crypto.randomUUID());const inbox=useRef<ReminderInbox|null>(null);
  const [,render]=useState(0);
  useEffect(()=>{
    if(!transport&&(!info||debug)){inbox.current=null;return;}
    const call=transport||((method,args)=>rpc<ReminderResponse>(info!,method,args));
    const current=new ReminderInbox(call,consumer.current,visible||(()=>getCurrentWindow().isVisible()));inbox.current=current;
    let active=true;const poll=async()=>{await current.poll();if(active)render(value=>value+1);};
    void poll();const timer=setInterval(()=>void poll(),2000);
    return()=>{active=false;clearInterval(timer);};
  },[info?.port,info?.token,debug,transport,visible]);
  const current=inbox.current;if(!current?.rows.length)return null;
  return <aside className="reminder-notice" aria-label="会前提醒" role="status" aria-live="polite">
    <strong>即将开始 · 10 分钟内</strong>{current.rows.map(row=><section key={row.id}><p>{reminderText(row)}</p>
      <button type="button" disabled={current.acking} onClick={()=>void current.acknowledge([row.id]).then(()=>render(value=>value+1))}>知道了</button></section>)}
    {current.error&&<p role="alert">{current.error}</p>}
  </aside>;
}

export function ReminderSettings({info,debug=false,transport,visible=true}:Props&{visible?:boolean}){
  const [status,setStatus]=useState<ReminderResponse|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function call(method:string,args:Record<string,unknown>={}){
    if(busy||(!transport&&(!info||debug)))return;setBusy(true);setError('');
    try{const result=await(transport?transport(method,args):rpc<ReminderResponse>(info!,method,args));if(!result.ok)throw Error(result.error||'提醒状态未确认。');setStatus(result);}
    catch(error){setError(String(error));}finally{setBusy(false);}
  }
  useEffect(()=>{if(visible)void call('calendar_reminder_status');},[info?.port,info?.token,visible,transport]);
  return <section className="reminder-settings"><h2>会前提醒</h2>
    <label><input type="checkbox" checked={status?.enabled===true} disabled={busy||!status||(!transport&&debug)} onChange={event=>void call('calendar_reminder_settings',{enabled:event.target.checked})}/>应用运行时，提前 10 分钟提醒</label>
    <p>覆盖本地与已连接的飞书主日历，通过桌宠或主窗口提示。确认后不再重复。</p>
    <button type="button" disabled={busy||(!transport&&(!info||debug))} onClick={()=>void call('calendar_reminder_status')}>核对提醒记录</button>
    {status?.scan&&<p role="status">扫描：{({never:'尚未扫描',pending:'等待扫描',disabled:'已关闭',scanning:'读取中',completed:'已核对',partial:'部分来源未核实',failed:'未完成'}as Record<string,string>)[status.scan.state]||status.scan.state} · 当前候选 {status.candidates?.length||0} 条</p>}
    {status?.scan?.errors?.length?<p role="alert">部分日程来源未核实，请检查飞书连接；未核实的远端日程不会投递。</p>:null}
    <details><summary>最近提醒记录</summary>{status?.reminders?.length?status.reminders.map(row=><p key={row.id}>{reminderText(row)} · {row.acknowledged_at?'已确认':row.delivered_at?'已投递':'未投递'} · <code>{row.id}</code></p>):<p>暂无提醒记录。</p>}</details>
    {error&&<p role="alert">{error}</p>}{debug&&!transport&&<p>隔离演示不投递真实提醒。</p>}
  </section>;
}
