import type {ProfileCharacter} from './profile-appearance';
export type CharacterMotion='idle'|'wave'|'nod'|'point';
export type MotionRequest={kind:CharacterMotion;direction?:'left'|'right';nonce:number};
export type Bone='root'|'head'|'left'|'left-lower'|'right'|'right-lower'|'eyes';
export type BonePlan={bone:Bone;rotate?:Array<number|null>;y?:Array<number|null>;scaleY?:Array<number|null>;x?:Array<number|null>;duration:number;times?:number[];repeat?:number;delay?:number};
export function characterMotionPlan(kind:CharacterMotion,character:ProfileCharacter,direction:'left'|'right'='right'):BonePlan[]{
  const arm=character==='comic'?0:10;
  if(kind==='idle')return [
    {bone:'root',y:[null,-.8,0],duration:4.8,repeat:Infinity},
    {bone:'head',rotate:[null,.6,-.6,0],y:[null,0,0,0],duration:5.6,repeat:Infinity},
    {bone:'left',rotate:[null,arm+1,arm],duration:4.8,repeat:Infinity},
    {bone:'right',rotate:[null,-arm-1,-arm],duration:4.8,repeat:Infinity},
    {bone:'left-lower',rotate:[null,0,0],duration:1},
    {bone:'right-lower',rotate:[null,0,0],duration:1},
    {bone:'eyes',scaleY:[null,1,1,.05,1,1],duration:4.9,times:[0,.08,.75,.78,.81,1],repeat:Infinity},
  ];
  const base:BonePlan[]=[{bone:'root',y:[null,1,-.5,0],duration:2.1},{bone:'head',rotate:[null,-2,1,0],y:[null,0,0,0],duration:2.1},
    {bone:'left',rotate:[null,arm,arm,arm],duration:2.1},{bone:'right',rotate:[null,-arm,-arm,-arm],duration:2.1},
    {bone:'left-lower',rotate:[null,0,0,0],duration:2.1},{bone:'right-lower',rotate:[null,0,0,0],duration:2.1},
    {bone:'eyes',scaleY:[null,1,1,1],duration:2.1}];
  if(kind==='wave'){
    base.find(p=>p.bone==='right')!.rotate=[null,-arm+7,-127,-127,-127,-127,-127,-arm];
    Object.assign(base.find(p=>p.bone==='right-lower')!,{rotate:[null,0,-14,19,-19,19,-8,0]});
    for(const plan of base)if(plan.rotate?.length===8)plan.times=[0,.09,.28,.4,.52,.64,.78,1];
  }else if(kind==='nod'){
    Object.assign(base.find(p=>p.bone==='head')!,{rotate:[null,9,-2,5,0],y:[null,2,0,1,0],duration:1.3});
    Object.assign(base.find(p=>p.bone==='eyes')!,{scaleY:[null,.25,1,.6,1],duration:1.3});
  }else{
    const left=direction==='left';
    Object.assign(base.find(p=>p.bone===(left?'left':'right'))!,{rotate:[null,left?88:-88,left?88:-88,left?arm:-arm],times:[0,.28,.72,1]});
    Object.assign(base.find(p=>p.bone==='head')!,{rotate:[null,left?-4:4,left?-4:4,0],times:[0,.28,.72,1]});
  }
  return base;
}
export const CHARACTER_LAYOUTS:Record<ProfileCharacter,{body:number[];head:number[];eyes:number[];shoulder:number[];upper:number[];lower:number[]}>={
  comic:{body:[36,36,28,61],head:[28,1,44,41],eyes:[20,53,60,18],shoulder:[42,58,41],upper:[9,20],lower:[120,108,70]},
  robot:{body:[31,42,38,55],head:[19,2,62,45],eyes:[31,27,38,23],shoulder:[36,64,51],upper:[10,18],lower:[118,108,70]},
  rabbit:{body:[27.5,43,45,54],head:[26,1,48,52],eyes:[21,65,58,17],shoulder:[39,61,53],upper:[10,18],lower:[125,100,65]},
};
