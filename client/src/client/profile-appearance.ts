export const PROFILE_CHARACTERS=[{id:'comic',label:'漫画分身'},{id:'robot',label:'几何小机器人'},{id:'rabbit',label:'原创小兔'}] as const;
export type ProfileCharacter=typeof PROFILE_CHARACTERS[number]['id'];
export type Appearance={version:1;character:ProfileCharacter;motion:boolean};
export type AppearanceStorage=Pick<Storage,'getItem'|'setItem'>;
export const APPEARANCE_KEY='tebb.profile.appearance';
export const DEFAULT_APPEARANCE:Appearance={version:1,character:'comic',motion:true};
export function isProfileCharacter(value:unknown):value is ProfileCharacter{return PROFILE_CHARACTERS.some(item=>item.id===value);}
export function loadAppearance(storage:AppearanceStorage):{value:Appearance;error:string}{
  try{
    const raw=storage.getItem(APPEARANCE_KEY);if(!raw)return {value:{...DEFAULT_APPEARANCE},error:''};
    const value=JSON.parse(raw);
    if(value?.version!==1||!isProfileCharacter(value.character)||typeof value.motion!=='boolean')throw Error();
    return {value:{version:1,character:value.character,motion:value.motion},error:''};
  }catch{return {value:{...DEFAULT_APPEARANCE},error:'形象设置无法读取，暂用漫画分身；原设置未覆盖。'};}
}
export function saveAppearance(storage:AppearanceStorage,value:Appearance):string{
  if(!isProfileCharacter(value.character)||typeof value.motion!=='boolean')return '形象设置无效，尚未保存。';
  try{storage.setItem(APPEARANCE_KEY,JSON.stringify({version:1,character:value.character,motion:value.motion}));return '';}
  catch{return '形象设置未能保存，请检查本机存储后重试。';}
}
export function characterAsset(character:ProfileCharacter,part:string){return `/profile-avatars/${character}/${part}.png`;}
