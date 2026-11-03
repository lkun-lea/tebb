type Receipt={id:string;type:string;state:'pending'|'complete'|'failed'|'unconfirmed';notice?:string;error?:string;code?:string;remote_status?:string};
export type AccountPage={ok:boolean;version:number;runtime:{key:string;mode:'local'|'account';email:string};configured:boolean;config_managed:boolean;url:string;config_error:string;accounts:{id:string;email:string;state:string;current:boolean}[];selected:string;restart_required:boolean;challenge:{id:string;email:string;expires_at:number}|null;operation:Receipt|null;error?:string;code?:string;accepted?:boolean};
type Marker={id:string;type:string;original_id?:string};
type StorageLike=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
type Wire=(method:string,args?:Record<string,unknown>)=>Promise<AccountPage>;
export const ACCOUNT_MARKER_KEY='tebb.account.pending-operation';
export const ACCOUNT_FIXTURE:AccountPage={ok:true,version:0,runtime:{key:'local',mode:'local',email:''},configured:false,config_managed:false,url:'',config_error:'',accounts:[],selected:'local',restart_required:false,challenge:null,operation:null};

export class AccountController{
  page:AccountPage|null=null;busy=false;loading=false;activeType='';error='';errorType='';notice='';unknown:Marker|null=null;
  private serial=0;private binding='';private storageError=false;private listeners=new Set<()=>void>();
  constructor(private wire:Wire,private storage:StorageLike,private id=()=>crypto.randomUUID()){
    try{const value=JSON.parse(storage.getItem(ACCOUNT_MARKER_KEY)||'null');if(value){if(typeof value.id!=='string'||typeof value.type!=='string')throw Error();this.unknown=value;}}
    catch{this.storageError=true;this.error='账号核对标记无法读取，请保留本机记录后核查。';}
  }
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  get damaged(){return this.storageError;}
  private emit(){this.listeners.forEach(fn=>fn());}
  private adopt(page:AccountPage){
    if(!page.runtime||!Array.isArray(page.accounts)||!Number.isInteger(page.version))throw Error(page.error||'账号状态返回不完整。');
    if(this.binding&&this.binding!==page.runtime.key)throw Error('后台账号绑定发生变化，请完整重启客户端。');
    if(this.page&&page.version<this.page.version)return false;
    this.binding=page.runtime.key;this.page=page;
    return true;
  }
  private clearUnknown(){
    this.storage.removeItem(ACCOUNT_MARKER_KEY);this.unknown=null;
  }
  async read(){
    const serial=++this.serial;this.loading=true;if(!this.storageError){this.error='';this.errorType='';}this.emit();
    try{
      const page=await this.wire('account_session',{operation_id:this.unknown?.id||''});
      if(serial!==this.serial)return false;
      if(!this.adopt(page))return false;
      if(this.unknown&&page.operation&&page.operation.id===this.unknown.id&&page.operation.state!=='pending'){
        this.clearUnknown();
        if(page.operation.state==='complete')this.notice=page.operation.notice||'已读取原操作结果。';
        else{this.notice='';this.error=page.operation.error||'原账号操作未完成。';this.errorType=page.operation.type;}
      }
      return true;
    }catch(error){if(serial===this.serial){this.error=String(error);this.errorType='';}return false;}
    finally{if(serial===this.serial)this.loading=false;this.emit();}
  }
  async act(type:string,args:Record<string,unknown>={}){
    if(!this.page||this.busy||this.storageError||(this.unknown&&type!=='acknowledge'))return false;
    const previous=this.unknown,marker:Marker={id:this.id(),type,...(type==='acknowledge'&&this.unknown?{original_id:this.unknown.original_id||this.unknown.id}:{})};
    this.busy=true;this.activeType=type;this.error='';this.errorType=type;this.notice='';++this.serial;
    try{this.storage.setItem(ACCOUNT_MARKER_KEY,JSON.stringify(marker));this.unknown=marker;}
    catch{this.busy=false;this.error='账号操作编号无法保存，尚未提交。';this.emit();return false;}
    this.emit();
    try{
      const page=await this.wire('account_action',{payload:{...args,type,request_id:marker.id,version:this.page.version,
                                               ...(type==='acknowledge'?{operation_id:marker.original_id}:{})}});
      this.adopt(page);
      if(page.operation?.id===marker.id&&page.operation.state!=='pending')this.clearUnknown();
      else if(page.code==='version_conflict'||page.code==='busy'||page.accepted===false){
        if(type==='acknowledge'&&previous){this.storage.setItem(ACCOUNT_MARKER_KEY,JSON.stringify(previous));this.unknown=previous;}
        else this.clearUnknown();
      }
      if(!page.ok){this.error=page.error||'账号操作未确认，请先核对。';return false;}
      this.notice=page.operation?.notice||'账号状态已保存。';return true;
    }catch(error){this.error=String(error)+' 请先核对原操作，不会自动重发。';return false;}
    finally{this.busy=false;this.activeType='';this.emit();}
  }
}
