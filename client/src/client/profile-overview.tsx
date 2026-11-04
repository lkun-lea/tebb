import {useMemo,useState} from 'react';
import {BookOpen,Flag,FolderOpen,MessagesSquare,Plus,ShieldCheck} from 'lucide-react';
import {accountStorage} from './account-storage';
import {UiButton,UiFeedback} from './ui-controls';
import {loadAppearance,saveAppearance,PROFILE_CHARACTERS,characterAsset,type Appearance} from './profile-appearance';
import {ProfileAvatar} from './profile-avatar';
import type {MotionRequest,CharacterMotion} from './profile-character-motion';
import type {ProfilePage} from './personalization-state';
import {profileCategories,profileGroup,profileUsable} from './profile-records';
import {ProfileRecordCard,type ProfileRecordActions} from './profile-record-card';
import './profile-overview.css';

const domains=[['communication',MessagesSquare],['knowledge',BookOpen],['goal',Flag],['project',FolderOpen]] as const;
function previewStorage(){const data=new Map<string,string>();return {getItem:(key:string)=>data.get(key)||null,setItem:(key:string,value:string)=>{data.set(key,value);}};}
export function ProfileOverview({page,debug=false,onAdd,onInspect,...actions}:ProfileRecordActions&{page:ProfilePage;debug?:boolean;onAdd:(category:string)=>void;onInspect?:()=>void}){
  const storage=useMemo(()=>debug?previewStorage():accountStorage(),[debug]);
  const initial=useMemo(()=>loadAppearance(storage),[storage]);
  const [appearance,setAppearance]=useState(initial.value),[error,setError]=useState(initial.error);
  const [category,setCategory]=useState('communication'),[selectedId,setSelectedId]=useState('');
  const [request,setRequest]=useState<MotionRequest>({kind:'idle',nonce:0});
  const records=profileGroup(page.records,category),selected=records.find(r=>r.id===selectedId)||records[0];
  const live=page.records.filter(profileUsable),local=page.mode==='local';
  function motion(kind:CharacterMotion,direction?:'left'|'right'){setRequest(value=>({kind,direction,nonce:value.nonce+1}));}
  function appearanceChange(next:Appearance){const failure=saveAppearance(storage,next);setError(failure);if(!failure){setAppearance(next);if(next.motion)motion('wave');}}
  function choose(next:string){setCategory(next);setSelectedId('');motion('point',['communication','goal','other'].includes(next)?'left':'right');}
  return <section className="profile-model" aria-label="用户画像总览" data-profile-character={appearance.character} data-profile-category={category} data-profile-paused={!appearance.motion}>
    <div className="profile-model-toolbar"><div><h3>我的用户模型</h3><p>{local?'本机空间 · 尚无同步画像':`${live.length} 条已启用资料 · 按各自范围选择`}</p></div><div className="profile-model-tools"><details className="profile-character-picker"><summary>更换形象 · {PROFILE_CHARACTERS.find(c=>c.id===appearance.character)!.label}</summary><div className="profile-character-options" role="group" aria-label="选择画像形象">{PROFILE_CHARACTERS.map(character=><button type="button" key={character.id} aria-pressed={appearance.character===character.id} onClick={()=>appearanceChange({...appearance,character:character.id})}><img src={characterAsset(character.id,'reference')} alt=""/><span>{character.label}</span></button>)}</div><small>保存在当前账号的本机界面设置中</small></details>{onInspect&&<UiButton onClick={onInspect}>查看模型调用</UiButton>}</div></div>
    {error&&<UiFeedback state="error" title={error}/>}
    <div className="profile-model-layout"><div className="profile-map-column"><div className="profile-map" aria-label="画像地图">
      <svg className="profile-map-connections" viewBox="0 0 600 420" preserveAspectRatio="none" aria-hidden="true"><path d="M300 210 C300 90 190 85 100 85 M300 210 C300 90 410 85 500 85 M300 210 C300 330 190 335 100 335 M300 210 C300 330 410 335 500 335"/></svg>
      <div className="profile-map-person"><button type="button" className="profile-character-trigger" aria-label="让画像角色挥手" onClick={()=>motion('wave')}><ProfileAvatar key={appearance.character} character={appearance.character} request={request} paused={!appearance.motion}/></button><strong>我的画像</strong><small>{page.records.filter(r=>r.state!=='deleted').length} 条已保存资料</small></div>
      {domains.map(([id,Icon])=>{const rows=profileGroup(page.records,id),usable=rows.filter(profileUsable),conflict=rows.some(r=>r.sync_state.startsWith('conflict'));return <button type="button" className="profile-domain" key={id} data-domain={id} aria-pressed={category===id} onClick={()=>choose(id)}><span><Icon size={17}/>{profileCategories[id]}</span><strong>{rows[0]?.text||'尚未补充'}</strong><footer><span>{conflict?'有待处理冲突':`${usable.length} 条已启用`}</span><small>{rows.length} 条资料</small></footer></button>;})}
    </div><div className="profile-map-under"><button type="button" aria-pressed={category==='other'} onClick={()=>choose('other')}>其他资料 · {profileGroup(page.records,'other').length} 条</button><span><ShieldCheck size={13}/>已保存资料与某次实际采用分别查看</span></div>
      <details className="profile-motion-tools"><summary>角色动作</summary><div className="profile-actions">{([['idle','待机'],['wave','挥手'],['nod','点头'],['point','指向']] as const).map(([kind,label])=><UiButton key={kind} disabled={!appearance.motion} onClick={()=>motion(kind,['communication','goal','other'].includes(category)?'left':'right')}>{label}</UiButton>)}<UiButton aria-pressed={!appearance.motion} onClick={()=>appearanceChange({...appearance,motion:!appearance.motion})}>{appearance.motion?'暂停动作':'恢复动作'}</UiButton></div></details>
    </div><aside className="profile-model-detail" aria-label="所选画像详情"><header><h3>{profileCategories[category]}</h3><span>{records.length} 条资料</span></header>{records.length>1&&<nav className="profile-record-picker" aria-label="选择画像条目">{records.map((row,index)=><button type="button" key={row.id} aria-pressed={selected?.id===row.id} onClick={()=>setSelectedId(row.id)}>{index+1} · {row.text.slice(0,16)}</button>)}</nav>}{selected?<ProfileRecordCard key={selected.id} row={selected} {...actions}/>:<UiFeedback state="empty" title="这里尚未补充"><p>{local?'登录账号并切换空间后可管理同步画像。':'补充你希望用于后续对话的背景或偏好。'}</p><UiButton disabled={actions.blocked||local} onClick={()=>onAdd(category)}><Plus size={14}/>补充资料</UiButton></UiFeedback>}</aside></div>
  </section>;
}
