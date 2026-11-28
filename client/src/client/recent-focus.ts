import type {DemoState} from './chat-prototype-state';
import type {NoteSession} from './note';
import type {WorkItem} from './work-board-state';

type Signal={title:string;project:string;stamp:number;weight:number;kind:'会话'|'事项'|'笔记'};
const DAY=86400000;
const ignore=new Set('今天 最近 正在 本周 明天 昨天 需要 可以 请问 帮我 我们 这个 继续 整理 准备 确认 处理 一下 一份 请把 请帮 工作 项目 笔记 安排 任务 资料 关于 更新 进行 完成 计划 当前 怎么 是否 一个 事情 记得 开始 相关 记录'.split(' '));

export function recentFocus(sessions:NoteSession[],chat:Pick<DemoState,'messages'|'conversations'|'projects'>|null,items:WorkItem[],now=Date.now()){
  const signals:Signal[]=[];
  const add=(s:Signal)=>{if(s.title.trim() && s.stamp>=now-14*DAY && s.stamp<=now)signals.push(s);};
  const projects=new Map(chat?.projects?.map(p=>[p.id,p.name]));
  const conversations=new Map(chat?.conversations.map(c=>[c.id,c]));
  for(const m of chat?.messages||[])if(m.sender==='user' && m.created){
    const title=m.text.split('\n')[0].trim();
    add({title,project:projects.get(conversations.get(m.conversation)?.project_id||'')||'',stamp:m.created*1000,weight:1,kind:'会话'});
  }
  for(const item of items)if(!item.archived && item.state!=='done')add({title:item.title,project:item.project_name,stamp:item.updated*1000,weight:item.state==='doing'?3:2,kind:'事项'});
  for(const session of sessions)for(const n of session.notes)add({title:n.question,project:'',stamp:Date.parse(n.saved),weight:1,kind:'笔记'});
  const ordered=signals.sort((a,b)=>b.stamp-a.stamp).slice(0,120);
  const Segmenter=(Intl as unknown as {Segmenter:new(locale:string,options:{granularity:string})=>{segment:(s:string)=>Iterable<{segment:string;isWordLike:boolean}>}}).Segmenter;
  const tokenizer=Segmenter?new Segmenter('zh',{granularity:'word'}):null;
  const groups=new Map<string,Set<Signal>>();
  for(const s of ordered){
    const title=s.title.slice(0,140);
    const words=tokenizer?Array.from(tokenizer.segment(title)).filter(x=>x.isWordLike).map(x=>x.segment):title.split(/\s+/);
    const labels=new Set([s.project,...words,...words.slice(1).flatMap((word,i)=>ignore.has(word)||ignore.has(words[i])?[]:[words[i]+word])]);
    for(const label of labels){if(!label||label.length<2||ignore.has(label)||/^\d+$/.test(label))continue;
      const seen=groups.get(label)||new Set<Signal>();seen.add(s);groups.set(label,seen);}
  }
  const score=(rows:Set<Signal>)=>Array.from(rows).reduce((n,s)=>n+s.weight*(1-(now-s.stamp)/(20*DAY)),0);
  const topics:string[]=[],used=new Set<Signal>();
  for(const [label,rows] of [...groups].sort((a,b)=>score(b[1])-score(a[1])||b[0].length-a[0].length)){
    if(rows.size<2||[...rows].some(s=>used.has(s)))continue;
    topics.push(label);rows.forEach(s=>used.add(s));if(topics.length===2)break;
  }
  for(const s of ordered){if(topics.length===2)break;if(used.has(s))continue;
    if(s.kind==='笔记'&&s.title.length>=4&&!ignore.has(s.title)||s.kind==='事项'&&s.weight===3||s.project||(s.kind==='会话'&&/最近关注|在研究|正在准备|这周重点/.test(s.title))){
      const label=(s.project||s.title).slice(0,42);if(!topics.includes(label))topics.push(label);
    }
  }
  return topics;
}
