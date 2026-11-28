import type {CalendarEvent} from './schedule-state';

type Period = {focus:string;time:string;keywords?:string};
export type PetBoard = {
  day:string;
  preferences:{project:string;morning:Period;evening:Period};
  projects:{id:string;name:string}[];
  questions:{run:string;prompt:string;title:string;time?:number}[];
  events:{time:number;title:string;source:string}[];
};
export type PetRow = {id:string;label:string;title:string;trace?:string;calendar?:{calendar_id:string;event_id:string;day:string}};

export function shortLine(text:string,limit:number){
  const line=(text||'').trim().replace(/\s+/g,' ');
  const chars=Array.from(line);
  return chars.length<=limit?line:chars.slice(0,limit-1).join('')+'…';
}

export function petRows(board:PetBoard,calendar:CalendarEvent[],now=new Date()):PetRow[]{
  const rows:PetRow[]=[];
  const clock=now.toTimeString().slice(0,5);
  const period=clock>=board.preferences.evening.time?board.preferences.evening:board.preferences.morning;
  const keywords=(period.keywords||'').split(/[\s、，,。；;]+/).filter(w=>w.length>1);
  const matches=(s:string)=>keywords.some(w=>s.includes(w))?1:0;
  const ordered=[...board.questions].sort((a,b)=>matches(b.prompt+b.title)-matches(a.prompt+a.title)||(b.time||0)-(a.time||0));
  const question=ordered[0];
  if(question)rows.push({id:question.run,label:'等你答复',title:shortLine(question.prompt||question.title,34)});
  const upcoming=calendar.filter(e=>e.status!=='cancelled'&&Date.parse(e.end)>+now&&Date.parse(e.start)<=+now+3*3600000).sort((a,b)=>Date.parse(a.start)-Date.parse(b.start));
  const event=upcoming[0];
  if(event){
    const start=new Date(event.start);
    rows.push({id:'calendar:'+event.calendar_id+':'+event.event_id,label:+start<=+now?'进行中的日程':start.toTimeString().slice(0,5)+' · 即将开始',title:shortLine(event.summary,32),calendar:{calendar_id:event.calendar_id,event_id:event.event_id,day:board.day}});
  }
  const project=board.projects.find(p=>p.id===board.preferences.project);
  if(project&&period.focus!=='questions'){
    const latest=board.events.filter(e=>new Date(e.time*1000).toDateString()===now.toDateString()&&!rows.some(r=>r.id===e.source)).sort((a,b)=>matches(b.title)-matches(a.title)||b.time-a.time)[0];
    if(latest)rows.push({id:latest.source,trace:latest.source,label:shortLine(project.name,15),title:shortLine(latest.title,32)});
  }
  return rows;
}
