import type {ProfilePage,ProfileRecord} from './personalization-state';
export const profileKinds:Record<string,string>={profile:'画像',preference:'偏好',memory:'长期记忆'};
export const profileCategories:Record<string,string>={communication:'沟通方式',knowledge:'知识背景',goal:'长期目标',project:'项目背景',other:'其他'};
export const profileSyncNames:Record<string,string>={queued:'等待同步',syncing:'正在同步',synced:'已同步',local_disabled:'仅本机停用',unconfirmed:'回执待核对',conflict:'版本冲突',conflict_delete:'删除待确认'};
export function profileScopeLabel(page:ProfilePage,row:{scope:string;scope_id:string}){
  return page.scopes?.find(s=>s.scope===row.scope&&s.id===row.scope_id)?.label||(row.scope==='user'?'所有对话':({project:'项目',companion:'伙伴'}[row.scope]||'未知范围')+' · '+row.scope_id);
}
export function profileGroup(records:ProfileRecord[],category:string){return records.filter(row=>row.category===category&&row.state!=='deleted');}
export function profileUsable(row:ProfileRecord){return row.state==='active'&&!row.sync_state.startsWith('conflict');}
