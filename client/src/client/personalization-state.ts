export type ProfileRecord={id:string;version:number;cloud_version:number;kind:string;category:string;text:string;scope:string;scope_id:string;state:string;sync_state:string;pending_id:string|null;can_resolve:boolean;can_retry:boolean;error:string;updated:string;source_ref?:string|null;source_device_id?:string|null;remote:null|{text:string;state:string;version:number}};
export type ProfilePage={ok:boolean;mode:'local'|'account';auto_paused?:boolean;account:{key:string;mode:string;email:string};configured:boolean;cloud_url:string;revision:number;cursor?:number;head?:number;device_id:string;records:ProfileRecord[];counts:Record<string,number>;receipt:null|{id:string;record_id:string;version:number};job:null|{id:string;state:string;phase?:string;processed:number;error:string;cancel_requested?:boolean};scopes?:{scope:string;id:string;label:string}[];error?:string;notice?:string;accepted?:boolean;code?:string};
type Wire=(method:string,args:Record<string,unknown>)=>Promise<ProfilePage>;
type StorageLike=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
type Marker={id:string;type:string;job_id?:string};
export const PROFILE_MARKER='tebb.personalization.pending';
export class PersonalizationController{
  page:ProfilePage|null=null;busy=false;loading=false;error='';notice='';unknown:Marker|null=null;damaged=false;
  private serial=0;private binding='';private listeners=new Set<()=>void>();
  constructor(private wire:Wire,private storage:StorageLike,private id=()=>crypto.randomUUID()){
    try{const value=JSON.parse(storage.getItem(PROFILE_MARKER)||'null');if(value){if(typeof value.id!=='string'||typeof value.type!=='string')throw Error();this.unknown=value;}}
    catch{this.damaged=true;this.error='资料核对标记无法读取，请保留本机记录后核查。';}
  }
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  private emit(){this.listeners.forEach(fn=>fn());}
  private adopt(page:ProfilePage){
    if(!page.account||!Array.isArray(page.records)||!Number.isInteger(page.revision))throw Error('个人资料返回不完整。');
    if(this.binding&&this.binding!==page.account.key)throw Error('后台账号已变化，请完整重启客户端。');
    if(this.page&&this.page.revision>page.revision)return false;
    this.binding=page.account.key;
    this.page={...page,scopes:page.scopes||this.page?.scopes};return true;
  }
  private settle(page:ProfilePage){
    if(this.unknown&&(page.receipt?.id===this.unknown.id||this.unknown.type==='sync'&&page.job?.id===this.unknown.id||
      this.unknown.type==='cancel'&&page.job&&page.job.id===this.unknown.job_id&&
        (page.job.cancel_requested||!['running','queued'].includes(page.job.state))||page.accepted===false)){
      this.storage.removeItem(PROFILE_MARKER);this.unknown=null;
    }
  }
  async read(scopes=false){
    const serial=++this.serial;this.loading=true;this.emit();
    try{
      const marker=this.unknown;
      const page=await this.wire('personalization_status',{request_id:marker?.id||'',job_id:marker?.type==='sync'?marker.id:marker?.job_id||'',include_scopes:scopes});
      if(serial!==this.serial||!this.adopt(page))return false;
      this.settle(page);if(!this.damaged)this.error='';return true;
    }catch(error){if(serial===this.serial)this.error=String(error);return false;}
    finally{if(serial===this.serial)this.loading=false;this.emit();}
  }
  async act(type:string,args:Record<string,unknown>={}){
    if(!this.page||this.busy||this.unknown||this.damaged)return false;
    const marker={id:this.id(),type,...(type==='cancel'?{job_id:this.page.job?.id}:{})};this.busy=true;this.error='';this.notice='';++this.serial;
    try{this.storage.setItem(PROFILE_MARKER,JSON.stringify(marker));this.unknown=marker;}
    catch{this.busy=false;this.error='操作编号无法保存，尚未提交。';this.emit();return false;}
    this.emit();
    try{
      const page=await this.wire('personalization_action',{payload:{...args,type,request_id:marker.id,job_id:marker.job_id,confirmed:true}});
      this.adopt(page);this.settle(page);
      if(!page.ok){this.error=page.error||'资料操作未确认，请先核对原操作。';return false;}
      if(type==='cancel'){this.storage.removeItem(PROFILE_MARKER);this.unknown=null;}
      this.notice=page.notice||(type==='sync'?'同步任务已提交。':type==='cancel'?'已请求取消，正在等待本次请求收尾。':'资料已保存在当前账号；同步状态见卡片。');
      return true;
    }catch(error){this.error=String(error)+' 请核对原操作，不会自动重新提交。';return false;}
    finally{this.busy=false;this.emit();}
  }
}

export const PERSONALIZATION_FIXTURE:ProfilePage={ok:true,mode:'account',account:{key:'a'.repeat(64),mode:'account',email:'preview@tebb.invalid'},configured:true,cloud_url:'https://preview.supabase.invalid',revision:1,cursor:12,head:12,device_id:'00000000-0000-4000-8000-000000000001',receipt:null,job:{id:'preview-job',state:'needs_confirmation',processed:3,error:''},counts:{synced:2,conflict:1},scopes:[{scope:'user',id:'',label:'所有对话'},{scope:'project',id:'preview-project',label:'项目 · tebb'}],records:[
  {id:'00000000-0000-4000-8000-000000000002',version:3,cloud_version:2,kind:'preference',category:'communication',text:'先给结论，再解释依据；涉及代码时给出可验证的结果。',scope:'user',scope_id:'',state:'active',sync_state:'synced',pending_id:null,can_resolve:false,can_retry:false,error:'',remote:null,updated:'2026-11-03T08:00:00Z'},
  {id:'00000000-0000-4000-8000-000000000003',version:4,cloud_version:3,kind:'profile',category:'knowledge',text:'熟悉 Python，正在学习 Rust 的所有权。',scope:'user',scope_id:'',state:'active',sync_state:'conflict',pending_id:null,can_resolve:true,can_retry:false,error:'',remote:{text:'熟悉 Python 和 Rust，解释时可以使用进阶术语。',state:'active',version:3},updated:'2026-11-03T08:00:00Z'},
  {id:'00000000-0000-4000-8000-000000000004',version:2,cloud_version:1,kind:'memory',category:'project',text:'tebb 首先完成账号资料同步，再接入自动提炼。',scope:'project',scope_id:'preview-project',state:'active',sync_state:'synced',pending_id:null,can_resolve:false,can_retry:false,error:'',remote:null,updated:'2026-11-03T08:00:00Z'}]};
