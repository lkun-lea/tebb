type AccountStorage=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
let profile='local';
let initialized=false;

export function initializeAccountStorage(key:string){
  if(key!=='local'&&!/^[a-f0-9]{64}$/.test(key))throw Error('后台账号空间标识无效，未读取界面缓存。');
  if(initialized&&key!==profile)throw Error('账号空间已固定，请完整重启客户端后切换。');
  profile=key;initialized=true;
}
export function accountStorageKey(key:string){return profile==='local'?key:`tebb.account.${profile}.${key}`;}
export function accountStorage(storage:AccountStorage=globalThis.localStorage):AccountStorage{
  const prefix=profile==='local'?'':`tebb.account.${profile}.`;
  return {getItem:key=>storage.getItem(prefix+key),setItem:(key,value)=>storage.setItem(prefix+key,value),removeItem:key=>storage.removeItem(prefix+key)};
}
