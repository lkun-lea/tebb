import {useEffect,useRef,type CSSProperties} from 'react';
import {useAnimate,useReducedMotion} from 'framer-motion';
import {PROFILE_CHARACTERS,characterAsset,type ProfileCharacter} from './profile-appearance';
import {CHARACTER_LAYOUTS,characterMotionPlan,type MotionRequest,type BonePlan} from './profile-character-motion';
import './profile-avatar.css';

const box=(values:number[]):CSSProperties=>({left:values[0]+'%',top:values[1]+'%',width:values[2]+'%',height:values[3]+'%'});
type Playback={stop:()=>void;pause:()=>void;play:()=>void;then?:(callback:()=>void)=>unknown};
export function ProfileAvatar({character,request,paused=false,staticOnly=false}:{character:ProfileCharacter;request?:MotionRequest;paused?:boolean;staticOnly?:boolean}){
  const [scope,animate]=useAnimate<HTMLSpanElement>(),reduced=useReducedMotion();
  const controls=useRef<Playback[]>([]),generation=useRef(0);
  const stop=()=>{generation.current++;controls.current.forEach(c=>c.stop());controls.current=[];};
  useEffect(()=>{
    generation.current++;
    if(staticOnly||!scope.current)return;
    if(paused||reduced){controls.current.forEach(c=>c.pause());return;}
    stop();const serial=generation.current;
    function run(plans:BonePlan[]){
      return plans.map(({bone,duration,times,repeat,delay,...frames})=>{
        const playback=animate(`[data-bone="${bone}"]`,frames,{duration,times,repeat,delay,ease:'easeInOut'}) as Playback;
        if(typeof document!=='undefined'&&document.hidden)playback.pause();
        return playback;
      });
    }
    const kind=request?.kind||'idle';controls.current=run(characterMotionPlan(kind,character,request?.direction));
    if(kind!=='idle'){
      const longest=controls.current[0];
      longest?.then?.(()=>{if(serial===generation.current&&!paused){controls.current=run(characterMotionPlan('idle',character));}});
    }
    return()=>{generation.current++;controls.current.forEach(c=>c.stop());};
  },[character,request?.nonce,paused,reduced,staticOnly]);
  useEffect(()=>{
    const visibility=()=>{for(const c of controls.current)if(document.hidden||paused||reduced)c.pause();else c.play();};
    if(typeof document==='undefined')return;
    document.addEventListener('visibilitychange',visibility);return()=>document.removeEventListener('visibilitychange',visibility);
  },[paused,reduced]);
  useEffect(()=>()=>stop(),[]);
  const layout=CHARACTER_LAYOUTS[character],part=(name:string)=> <img src={characterAsset(character,name)} alt="" draggable={false}/>;
  return <span ref={scope} className="profile-avatar" role="img" aria-label={PROFILE_CHARACTERS.find(c=>c.id===character)!.label} data-character={character}>
    <span className="profile-avatar-root" data-bone="root">
      <span className="profile-avatar-body" style={box(layout.body)}>{part('body')}</span>
      {(['left','right'] as const).map((side,index)=><span key={side} className="profile-avatar-arm" data-bone={side} style={{...box([layout.shoulder[index]-layout.upper[0]/2,layout.shoulder[2],...layout.upper]),transform:`rotate(${character==='comic'?0:index===0?10:-10}deg)`}}>{part(index===0?'upperL':'upperR')}<span className="profile-avatar-lower" data-bone={side+'-lower'} style={{left:(100-layout.lower[0])/2+'%',top:layout.lower[2]+'%',width:layout.lower[0]+'%',height:layout.lower[1]+'%'}}>{part(index===0?'lowerL':'lowerR')}</span></span>)}
      <span className="profile-avatar-head" data-bone="head" style={box(layout.head)}>{part('head')}<span className="profile-avatar-eyes" data-bone="eyes" style={box(layout.eyes)}>{part('eyes')}</span></span>
    </span>
  </span>;
}
