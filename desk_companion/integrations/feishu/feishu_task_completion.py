"""Explicit task completion with account facts and durable, non-replayed receipts."""
import copy
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import re
import uuid

from desk_companion.planning import board_data
from desk_companion.planning.calendar_time import TZ
from desk_companion.integrations.feishu.feishu_auth import same_user_identity, verified_user_identity
from desk_companion.integrations.feishu.feishu_tools import _run_lark
from desk_companion.infrastructure.paths import data_root
from desk_companion.infrastructure.resource_lock import ResourceLock
from desk_companion.infrastructure import storage


def _guid(value):
    if not isinstance(value,str):raise ValueError('缺少真实待办 GUID。')
    try:uuid.UUID(value)
    except ValueError:raise ValueError('需要真实待办 GUID，不能使用显示编号。')from None
    return value.strip()


def _completed(value):
    return type(value)in(int,str)and str(value).isdigit()and int(value)>0


class FeishuTaskCompletionService:
    def __init__(self,*,path=None,clock=None,identity=None,cli=None,board=None):
        self.path=Path(path or data_root()/'memory/feishu-task-completions.json')
        self.clock=clock or(lambda:datetime.now(TZ));self.identity=identity or verified_user_identity
        self.cli=cli or _run_lark;self.board=board or board_data
        self.store=ResourceLock('feishu-task-completions-store',directory=self.path.parent/'locks')

    def _now(self):return self.clock().astimezone(TZ).isoformat(timespec='seconds')

    def _read(self):
        if not self.path.exists():return dict(version=1,operations={})
        state=json.loads(self.path.read_text('utf-8'))
        if not isinstance(state,dict)or state.get('version')!=1 or not isinstance(state.get('operations'),dict):
            raise ValueError('完成待办回执格式异常，请保留原文件并核对。')
        for key,row in state['operations'].items():
            fields=('request_id','guid','summary','state','stage','created_at','updated_at','execution_result','observed_state','remote_state','cache_state','error')
            if(not isinstance(row,dict)or any(not isinstance(row.get(field),str)for field in fields)
                or row['request_id']!=key or not isinstance(row.get('identity'),dict)
                or row['state']not in{'preparing','prepared','calling','unconfirmed','confirmed','observed_done','not_started'}):
                raise ValueError('完成待办条目格式异常，请保留原文件并核对。')
            _guid(row['guid'])
        return state

    def _change(self,action):
        with self.store.hold():
            state=self._read();before=copy.deepcopy(state);result=action(state)
            if state!=before:storage.atomic_write(self.path,state)
            return copy.deepcopy(result)

    def _record(self,key):
        with self.store.hold():return copy.deepcopy(self._read()['operations'].get(key))

    def _save(self,key,**fields):
        def save(state):
            row=state['operations'][key];row.update(fields,updated_at=self._now());return row
        return self._change(save)

    def _guard(self,guid):
        return ResourceLock('feishu-task-'+hashlib.sha256(guid.lower().encode()).hexdigest()[:24],directory=self.path.parent/'locks')

    @staticmethod
    def _view(row):
        keys=('request_id','guid','summary','identity','state','stage','created_at','updated_at','expires_at',
            'execution_result','observed_state','observed_at','receipt','remote_state','cache_state','completed_at','already_completed','error')
        return dict(ok=row['state']in{'prepared','confirmed','observed_done'},
            **{key:copy.deepcopy(row.get(key))for key in keys})

    @staticmethod
    def _error(stage,error,**details):return dict(ok=False,state='not_started',stage=stage,error=error,**details)

    def _task(self,guid):
        raw=self._run(['task','tasks','get','--params',json.dumps(dict(task_guid=guid)), '--as','user'],timeout=20)
        env=json.loads(raw)
        if not isinstance(env,dict)or env.get('ok')is not True:raise RuntimeError('待办只读核对未成功。')
        task=(env.get('data')or{}).get('task')
        if(not isinstance(task,dict)or str(uuid.UUID(_guid(task.get('guid'))))!=str(uuid.UUID(guid))
            or not isinstance(task.get('summary'),str)or not task['summary'].strip()
            or 'completed_at'not in task or(type(task['completed_at'])not in(int,str))):
            raise RuntimeError('待办详情缺少可核实的 GUID、标题或完成时间。')
        if not str(task['completed_at']).isdigit():raise RuntimeError('待办完成时间格式未确认。')
        return dict(summary=task['summary'][:1000],completed_at=task['completed_at'],done=_completed(task['completed_at']))

    def _run(self,args,timeout):
        try:return self.cli(args,timeout=timeout)
        except Exception as exc:raise RuntimeError('飞书调用未完成（'+type(exc).__name__+'），请核对原操作。')from None

    def _recover(self,row):
        if row and row['state']in{'calling','preparing'}:
            guard=self._guard(row['guid'])
            if guard.acquire(blocking=False):
                try:
                    latest=self._record(row['request_id'])
                    if latest['state']in{'calling','preparing'}:
                        row=self._save(row['request_id'],state='unconfirmed'if latest['state']=='calling'else'not_started',
                            stage='interrupted',error='原操作已中断；写入结果未知时仅可只读核对。')
                    else:row=latest
                finally:guard.__exit__()
        return row

    def status(self,request_id=''):
        try:
            if request_id:
                row=self._recover(self._record(request_id))
                return self._view(row)if row else self._error('lookup','没有此完成待办回执。')
            with self.store.hold():rows=copy.deepcopy(list(self._read()['operations'].values()))
            rows.sort(key=lambda row:row['created_at'],reverse=True)
            return dict(ok=True,operations=[self._view(self._recover(row))for row in rows[:100]],truncated=len(rows)>100)
        except Exception as exc:return self._error('receipt_read','完成待办回执未能读取，请保留原文件。',error_kind=type(exc).__name__)

    def prepare(self,guid,request_id):
        try:
            guid=_guid(guid)
            if not isinstance(request_id,str)or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id):raise ValueError('完成操作编号无效。')
            existing=self._recover(self._record(request_id))
            if existing:
                if existing['guid']!=guid:raise ValueError('操作编号已用于其他待办。')
                return self._view(existing)
            guard=self._guard(guid)
            if not guard.acquire(blocking=False):return self._error('admission','此待办正在核对或完成。')
            try:
                context=self.board.visible_task_context(guid)
                registered={'new':False}
                def register(state):
                    existing=state['operations'].get(request_id)
                    if existing:
                        if existing['guid']!=guid:raise ValueError('操作编号已用于其他待办。')
                        return existing
                    prior=next((row for row in state['operations'].values()if row['guid'].lower()==guid.lower()
                        and(row['state']in{'calling','unconfirmed'}or row['state']in{'confirmed','observed_done'}and row.get('context')==context)),None)
                    if prior:return prior
                    now=self._now();row=dict(request_id=request_id,guid=guid,summary='',identity={},state='preparing',stage='prepare',
                        created_at=now,updated_at=now,execution_result='not_started',observed_state='unknown',remote_state='not_started',
                        cache_state='not_started',completed_at='',already_completed=None,error='')
                    state['operations'][request_id]=row;registered['new']=True;return row
                row=self._change(register)
                if not registered['new']:return self._view(row)
                try:
                    actor=self.identity();task=self._task(guid)
                    if not same_user_identity(actor,self.identity()):raise RuntimeError('核对期间飞书账号已变化，请重新刷新。')
                    row=self._save(request_id,state='prepared',stage='confirmation',identity=actor,context=context,summary=task['summary'],
                        observed_state='done'if task['done']else'open',observed_at=self._now(),completed_at=task['completed_at'],
                        expires_at=(self.clock()+timedelta(minutes=2)).isoformat(timespec='seconds'))
                except Exception as exc:row=self._save(request_id,state='not_started',stage='prepare_read',error=str(exc))
                return self._view(row)
            finally:guard.__exit__()
        except (ValueError,RuntimeError)as exc:return self._error('validation',str(exc))
        except Exception as exc:return self._error('receipt_save','核对回执未保存，未开始完成待办。',error_kind=type(exc).__name__)

    def _cache(self,row):
        try:
            self.board.cache_completed_task(row['context'])
            return self._save(row['request_id'],cache_state='confirmed')
        except Exception:
            return self._save(row['request_id'],cache_state='unconfirmed',error='飞书完成状态已核实，本地缓存未更新；请刷新，勿重复完成。')

    def complete(self,request_id):
        row=None;remote='not_started'
        try:
            row=self._record(request_id)
            if not row:return self._error('lookup','没有已核对的完成操作。')
            guard=self._guard(row['guid'])
            if not guard.acquire(blocking=False):return self._view(row)
            try:
                row=self._record(request_id)
                if row['state']!='prepared':return self._view(self._recover(row))
                with self.store.hold():
                    prior=next((other for other in self._read()['operations'].values()if other['request_id']!=request_id
                        and other['guid'].lower()==row['guid'].lower()and(other['state']in{'calling','unconfirmed'}
                            or other['state']in{'confirmed','observed_done'}and other.get('context')==row.get('context'))),None)
                if prior:return self._view(prior)
                with self.board.calendar_operation():
                    if self.clock()>=datetime.fromisoformat(row['expires_at']):
                        return self._view(self._save(request_id,state='not_started',stage='expired',error='核对已过期，请重新核对并确认。'))
                    try:actor=self.identity()
                    except Exception:return self._view(self._save(request_id,state='not_started',stage='identity_unverified',error='当前飞书身份未能核实，未开始完成待办。'))
                    if not same_user_identity(row['identity'],actor):
                        return self._view(self._save(request_id,state='not_started',stage='identity_changed',error='飞书账号已变化，未完成原待办。'))
                    if self.board.visible_task_context(row['guid'])!=row['context']:
                        return self._view(self._save(request_id,state='not_started',stage='cache_changed',error='可见列表已变化，请刷新核对。'))
                    row=self._save(request_id,state='calling',stage='remote',execution_result='unconfirmed',remote_state='unconfirmed',observed_state='unknown',observed_at='',completed_at='')
                    remote='unconfirmed'
                    try:
                        raw=self._run(['task','+complete','--task-id',row['guid'],'--as','user'],timeout=30)
                        env=json.loads(raw);data=env.get('data')if isinstance(env,dict)and env.get('ok')is True else None
                        receipt=dict(shortcut_ok=isinstance(env,dict)and env.get('ok')is True)
                        if isinstance(data,dict):
                            receipt.update(status=data.get('status','')[:100]if isinstance(data.get('status'),str)else'',
                                completed_at=data.get('completed_at')if type(data.get('completed_at'))in(int,str)and len(str(data['completed_at']))<=64 else'',
                                already_completed=data.get('already_completed')if type(data.get('already_completed'))is bool else None)
                        self._save(request_id,receipt=receipt)
                        confirmed=(isinstance(data,dict)and data.get('status')=='done'and _completed(data.get('completed_at'))
                            and type(data.get('already_completed'))is bool)
                        if not confirmed:raise RuntimeError('完成回执缺少 done、完成时间或 already_completed。')
                        if not same_user_identity(row['identity'],self.identity()):raise RuntimeError('调用期间飞书账号已变化，原身份的写入结果未确认。')
                    except Exception as exc:
                        return self._view(self._save(request_id,state='unconfirmed',stage='remote',error=str(exc)))
                    remote='confirmed'
                    row=self._save(request_id,state='confirmed',stage='completed',execution_result='confirmed',remote_state='confirmed',
                        observed_state='done',observed_at=self._now(),completed_at=data['completed_at'],already_completed=data['already_completed'],error='')
                    return self._view(self._cache(row))
            finally:guard.__exit__()
        except board_data.BoardChangeError as exc:return self._error('admission',str(exc),request_id=request_id)
        except Exception as exc:return dict(ok=False,request_id=request_id,
            state='confirmed'if remote=='confirmed'else'unconfirmed'if remote=='unconfirmed'or row and row.get('state')=='calling'else'not_started',
            execution_result='confirmed'if remote=='confirmed'else'unconfirmed'if remote=='unconfirmed'else'not_started',
            remote_state=remote,receipt_state='unconfirmed',cache_state='unconfirmed'if remote=='confirmed'else'not_started',
            stage='receipt_or_preflight',error='操作未完整完成，请读取原回执核对，勿直接重复提交。',error_kind=type(exc).__name__)

    def inspect(self,request_id):
        row=None
        try:
            row=self._recover(self._record(request_id))
            if not row:return self._error('lookup','没有此完成操作。')
            if row['state']!='unconfirmed':return self._view(row)
            guard=self._guard(row['guid'])
            if not guard.acquire(blocking=False):return self._view(row)
            try:
                with self.board.calendar_operation():
                    if not same_user_identity(row['identity'],self.identity()):
                        return self._view(self._save(request_id,stage='identity_changed',error='当前账号与原操作不同，已停止核对；请恢复原账号。'))
                    task=self._task(row['guid'])
                    if not same_user_identity(row['identity'],self.identity()):
                        return self._view(self._save(request_id,stage='identity_changed',error='核对期间账号已变化，结果未归属原操作。'))
                    row=self._save(request_id,state='observed_done'if task['done']else'unconfirmed',stage='inspected',
                        observed_state='done'if task['done']else'open',observed_at=self._now(),remote_state='observed_done'if task['done']else'unconfirmed',
                        completed_at=task['completed_at'],error='原写入回执仍未知；只读查询到已完成。'if task['done']else'当前仍未完成；原写入回执未知，不自动再次提交。')
                    return self._view(self._cache(row)if task['done']else row)
            finally:guard.__exit__()
        except Exception as exc:
            if row:
                try:return dict(self._view(self._save(request_id,stage='inspection_failed',error='只读核对未完成，保留原写入回执。')),ok=False)
                except Exception:return dict(self._view(row),ok=False,receipt_state='unconfirmed',error='核对回执未保存，保留已取得的远端事实；请读取原编号核对。')
            return self._error('inspection','只读核对未完成，保留原回执。',request_id=request_id,error_kind=type(exc).__name__)
