import {useEffect,useState,type ReactNode} from 'react';
import {backendInfo,rpc} from './api';
import {initializeAccountStorage} from './account-storage';
import {debugPane} from './debug';
import {startupStatus,startupFailed} from './startup';

export function AccountBootstrap({children}:{children:ReactNode}){
  const [state,setState]=useState({ready:false,error:''});
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    let active=true;
    void (async()=>{
      try{
        startupStatus('正在核对本机账号空间…');
        const snapshot=debugPane()?{runtime:{key:'local'}}:await rpc<{runtime:{key:string}}>(await backendInfo(),'account_session');
        if(!active)return;
        initializeAccountStorage(snapshot.runtime.key);
        if(active)setState({ready:true,error:''});
      }catch(error){
        if(active){setState({ready:false,error:String(error)});startupFailed(error);}
      }
    })();
    return()=>{active=false;};
  },[attempt]);
  if(state.error)return <section role="alert" className="p-6"><p>账号空间初始化失败：{state.error}</p><button onClick={()=>{setState({ready:false,error:''});setAttempt(value=>value+1);}}>重试</button></section>;
  return state.ready?<>{children}</>:<p className="p-6">正在核对本机账号空间…</p>;
}
