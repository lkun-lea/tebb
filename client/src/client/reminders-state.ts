export type Reminder={id:string;summary:string;start:string;end:string;calendar_id:string;event_id:string;delivered_at?:string;acknowledged_at?:string};
export type ReminderResponse={ok:boolean;error?:string;enabled?:boolean;lead_minutes?:number;reminders?:Reminder[];candidates?:string[];scan?:{state:string;errors:string[];completed_at:string}};
export type ReminderTransport=(method:string,args:Record<string,unknown>)=>Promise<ReminderResponse>;

export class ReminderInbox{
  rows:Reminder[]=[];error='';busy=false;acking=false;private generation=0;
  constructor(readonly transport:ReminderTransport,readonly consumerId:string,readonly visible:()=>Promise<boolean>){}
  async poll(){
    if(this.busy||this.acking)return;this.busy=true;const generation=this.generation;
    try{
      if(!await this.visible())return;
      const result=await this.transport('calendar_reminder_claim',{consumer_id:this.consumerId,known_ids:this.rows.map(row=>row.id)});
      if(generation!==this.generation)return;
      if(!result.ok)throw Error(result.error||'提醒投递未确认，请核对提醒记录。');
      this.rows=result.enabled===false?[]:result.reminders||[];this.error='';
    }catch(error){if(generation===this.generation)this.error=String(error);}finally{this.busy=false;}
  }
  async acknowledge(ids:string[]){
    if(this.acking)return false;this.acking=true;this.generation++;
    try{
      const result=await this.transport('calendar_reminder_ack',{consumer_id:this.consumerId,ids});
      if(!result.ok)throw Error(result.error||'提醒确认未完成，请核对原记录。');
      this.rows=this.rows.filter(row=>!ids.includes(row.id));this.error='';return true;
    }catch(error){this.error=String(error);return false;}finally{this.acking=false;}
  }
}

export function reminderText(row:Reminder){
  const time=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(row.start));
  return `${time} · ${row.summary}`;
}
