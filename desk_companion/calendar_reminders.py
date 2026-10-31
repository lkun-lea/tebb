"""Calendar reminders own delivery facts, independently of Agent execution."""
import copy
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import re
import threading

from .calendar_time import TZ
from .feishu_access import connected
from .paths import data_root
from .resource_lock import ResourceLock
from .video import atomic_write

LEAD=timedelta(minutes=10)
FRESH=timedelta(minutes=5)


def stamp(value):return value.astimezone(TZ).isoformat(timespec='seconds')


def absolute(value):
    parsed=datetime.fromisoformat(value)
    if parsed.utcoffset()is None:raise ValueError('时间必须包含时区。')
    return parsed.astimezone(TZ)


class CalendarReminderService:
    def __init__(self,scheduling,*,path=None,clock=None,remote_connected=None,stop_event=None):
        self.scheduling=scheduling;self.path=Path(path or data_root()/'memory/calendar-reminders.json')
        self.clock=clock or(lambda:datetime.now(TZ));self.connected=remote_connected or connected
        self.stopped=stop_event or threading.Event()
        self.store=ResourceLock('calendar-reminders-store',directory=self.path.parent/'locks')
        self.scan=ResourceLock('calendar-reminders-scan',directory=self.path.parent/'locks')

    @classmethod
    def for_work_board(cls,board):
        from .calendar_adapter import CalendarAdapter
        from .scheduling import SchedulingService
        stopped=threading.Event()
        source=SchedulingService(board,calendar=CalendarAdapter(timeout_cap=5,cancelled=stopped.is_set))
        return cls(source,stop_event=stopped)

    def stop(self):self.stopped.set()

    def _read(self):
        if not self.path.exists():
            return dict(version=1,enabled=True,records={},aliases={},candidates=[],
                scan=dict(state='never',attempted_at='',completed_at='',remote_attempted_at='',errors=[],skipped={}))
        value=json.loads(self.path.read_text('utf-8'))
        if(not isinstance(value,dict)or value.get('version')!=1 or type(value.get('enabled'))is not bool
            or not isinstance(value.get('records'),dict)or not isinstance(value.get('aliases'),dict)
            or not isinstance(value.get('candidates'),list)or not isinstance(value.get('scan'),dict)):
            raise ValueError('提醒记录格式异常，请保留原文件并核对。')
        for key,row in value['records'].items():
            fields=('id','summary','start','end','calendar_id','event_id','created_at','delivered_at','consumer_id','acknowledged_at','merged_into')
            if not isinstance(row,dict)or any(not isinstance(row.get(field),str)for field in fields)or row['id']!=key or type(row.get('active'))is not bool:
                raise ValueError('提醒条目格式异常，请保留原文件并核对。')
            for field in('start','end','created_at','delivered_at','acknowledged_at'):
                if row[field]or field in('start','end','created_at'):absolute(row[field])
            if row['merged_into']and row['merged_into']not in value['records']:raise ValueError('提醒合并记录缺失。')
        if any(not isinstance(alias,str)or target not in value['records']for alias,target in value['aliases'].items()):raise ValueError('提醒别名记录异常。')
        if not isinstance(value['scan'].get('state'),str)or not isinstance(value['scan'].get('errors'),list):raise ValueError('提醒扫描记录异常。')
        return value

    def _change(self,action):
        with self.store.hold():
            state=self._read();before=copy.deepcopy(state);result=action(state)
            if state!=before:atomic_write(self.path,state)
            return result

    @staticmethod
    def _public(row):
        return {k:copy.deepcopy(row.get(k))for k in('id','summary','start','end','calendar_id','event_id',
            'active','created_at','delivered_at','consumer_id','acknowledged_at','merged_into')}

    def snapshot(self):
        try:
            with self.store.hold():state=self._read()
            rows=sorted(state['records'].values(),key=lambda row:row['created_at'],reverse=True)
            return dict(ok=True,enabled=state['enabled'],lead_minutes=10,scan=state['scan'],
                candidates=state['candidates'],reminders=[self._public(row)for row in rows[:100]],truncated=len(rows)>100)
        except Exception as exc:
            return dict(ok=False,error='提醒状态读取失败，请保留原记录并核对。',error_kind=type(exc).__name__)

    def save_settings(self,enabled):
        if type(enabled)is not bool:return dict(ok=False,error='提醒开关必须为布尔值。')
        def save(state):
            if state['enabled']==enabled:return
            state['enabled']=enabled;state['candidates']=[];state['scan']['state']='pending'if enabled else'disabled'
            for row in state['records'].values():row['active']=False
        try:self._change(save);return self.snapshot()
        except Exception as exc:return dict(ok=False,error='提醒设置未保存。',error_kind=type(exc).__name__)

    def _collect(self,now,refresh,remote_enabled):
        dates=[now.date()];last=(now+LEAD).date()
        if last-timedelta(days=last.weekday())!=dates[0]-timedelta(days=dates[0].weekday()):dates.append(last)
        candidates=[];errors=[];skipped={}
        def skip(reason):skipped[reason]=skipped.get(reason,0)+1
        for day in dates:
            if self.stopped.is_set():break
            page=self.scheduling.load_week(day.isoformat(),refresh=refresh)
            if not isinstance(page,dict)or not page.get('ok'):
                errors.append('calendar_read_failed');continue
            if remote_enabled and(not page.get('events_valid')or page.get('events_error')):errors.append('remote_unverified')
            for event in page.get('events',[]):
                try:
                    if not isinstance(event,dict):raise ValueError()
                    source=event['calendar_id']+'/'+event['event_id']
                    if not event['calendar_id']or not event['event_id']:raise ValueError()
                    if 'T'not in event.get('start',''):skip('all_day');continue
                    start,end=absolute(event['start']),absolute(event['end'])
                    if end<=start:skip('invalid_time');continue
                    if event.get('status')in{'cancelled','deleted'}:skip('cancelled');continue
                    if start<now or end<=now:skip('past');continue
                    if start>now+LEAD:skip('outside_window');continue
                    local=event['calendar_id']=='tebb-local'and not event.get('remote')
                    if not local:
                        if not remote_enabled or not page.get('events_valid')or page.get('events_error'):
                            skip('remote_unverified');continue
                        target=event.get('remote')or event
                        if target.get('calendar_id')!=(page.get('calendar')or{}).get('id'):
                            skip('other_calendar');continue
                        if event.get('verification')!='confirmed'or event.get('error'):
                            skip('remote_unverified');continue
                        times=[absolute(event.get('checked_at','')),absolute(page.get('checked_at',''))]
                        if any(now-time>FRESH or time>now+timedelta(seconds=60)for time in times):
                            skip('stale_remote');continue
                    identities=[source]
                    if event.get('remote'):
                        identities.append(event['remote']['calendar_id']+'/'+event['remote']['event_id'])
                    identities=sorted(set(identity+'|'+stamp(start)for identity in identities))
                    candidates.append(dict(identities=identities,summary=str(event.get('summary')or'未命名日程')[:500],
                        start=stamp(start),end=stamp(end),calendar_id=event['calendar_id'],event_id=event['event_id']))
                except (ValueError,TypeError,KeyError):skip('invalid_event')
        return candidates,sorted(set(errors)),skipped

    def tick(self):
        if self.stopped.is_set():return dict(ok=True,state='stopped')
        if not self.scan.acquire(blocking=False):return dict(ok=True,state='scanning')
        try:
            now=self.clock().astimezone(TZ)
            with self.store.hold():previous=self._read()
            if not previous['enabled']:return dict(ok=True,state='disabled')
            remote_enabled=self.connected();last=previous['scan'].get('remote_attempted_at','')
            interval=timedelta(seconds=30)if previous['scan'].get('errors')else FRESH
            refresh=remote_enabled and(not last or now<absolute(last)or now-absolute(last)>=interval)
            def begin(state):
                state['scan'].update(state='scanning',attempted_at=stamp(now),errors=[])
                if refresh:state['scan']['remote_attempted_at']=stamp(now)
            self._change(begin)
            candidates,errors,skipped=self._collect(now,refresh,remote_enabled)
            def finish(state):
                for row in state['records'].values():row['active']=False
                active=[]
                if state['enabled']and not self.stopped.is_set():
                    for candidate in candidates:
                        ids={state['aliases'][key]for key in candidate['identities']if key in state['aliases']}
                        rows=[state['records'][key]for key in ids]
                        rows.sort(key=lambda row:(not bool(row.get('delivered_at')),row['created_at'],row['id']))
                        key=rows[0]['id']if rows else'meeting_'+hashlib.sha256(candidate['identities'][0].encode()).hexdigest()[:24]
                        row=state['records'].setdefault(key,dict(id=key,created_at=stamp(now),delivered_at='',consumer_id='',acknowledged_at='',merged_into=''))
                        row.update({k:v for k,v in candidate.items()if k!='identities'});row['active']=True
                        acknowledged=sorted(other['acknowledged_at']for other in rows if other.get('acknowledged_at'))
                        if acknowledged and not row['acknowledged_at']:row['acknowledged_at']=acknowledged[0]
                        for other in rows[1:]:other.update(active=False,merged_into=key)
                        for identity,target in list(state['aliases'].items()):
                            if target in ids:state['aliases'][identity]=key
                        for identity in candidate['identities']:state['aliases'][identity]=key
                        if key not in active:active.append(key)
                state['candidates']=[key for key in active if state['records'][key]['active']]
                state['scan'].update(state='partial'if errors else'completed',completed_at=stamp(now),errors=errors,skipped=skipped)
            self._change(finish);return self.snapshot()
        except Exception as exc:
            def failed(state):
                state['scan'].update(state='failed',errors=[type(exc).__name__])
                for row in state['records'].values():row['active']=False
                state['candidates']=[]
            try:self._change(failed)
            except Exception:pass
            return dict(ok=False,state='failed',error='提醒扫描未完成，请核对状态。',error_kind=type(exc).__name__)
        finally:self.scan.__exit__()

    def claim(self,consumer_id,known_ids=None):
        if not isinstance(consumer_id,str)or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',consumer_id):
            return dict(ok=False,error='提醒窗口编号无效。')
        if not isinstance(known_ids,list)or len(known_ids)>100 or any(not isinstance(key,str)for key in known_ids):
            return dict(ok=False,error='提醒核对编号无效。')
        try:
            now=self.clock().astimezone(TZ)
            def claim(state):
                if self.stopped.is_set():return dict(ok=True,enabled=False,state='stopped',reminders=[])
                if not state['enabled']:return dict(ok=True,enabled=False,reminders=[])
                scanning=state['scan']['state']=='scanning'
                completed=state['scan'].get('completed_at','')
                fresh=bool(completed)and timedelta(0)<=now-absolute(completed)<=timedelta(seconds=30)
                rows=[];recovered=[]
                for row in sorted(state['records'].values(),key=lambda row:(row['start'],row['id'])):
                    if not row['active']or row.get('merged_into')or row['acknowledged_at']or not now<=absolute(row['start'])<=now+LEAD:continue
                    if row['delivered_at']:
                        if row['consumer_id']==consumer_id and(fresh or scanning and row['id']in known_ids):
                            rows.append(row)
                            if row['id']not in known_ids:recovered.append(row['id'])
                    elif not scanning and fresh and len(rows)<20:
                        row.update(delivered_at=stamp(now),consumer_id=consumer_id);rows.append(row)
                return dict(ok=True,enabled=True,scanning=scanning,reminders=[self._public(row)for row in rows[:20]],
                    recovered_ids=recovered)
            return self._change(claim)
        except Exception as exc:return dict(ok=False,error='提醒投递未确认，请读取状态。',error_kind=type(exc).__name__)

    def acknowledge(self,consumer_id,ids):
        if not isinstance(ids,list)or not ids or len(ids)>20 or any(not isinstance(key,str)for key in ids):
            return dict(ok=False,error='缺少有效提醒编号。')
        try:
            now=self.clock().astimezone(TZ)
            def acknowledge(state):
                rows=[state['records'].get(key)for key in ids]
                if any(not row or not row['delivered_at']or row['consumer_id']!=consumer_id for row in rows):
                    return dict(ok=False,error='提醒不属于当前投递，请读取核对。')
                for row in rows:
                    if not row['acknowledged_at']:row['acknowledged_at']=stamp(now)
                return dict(ok=True,acknowledged=ids)
            return self._change(acknowledge)
        except Exception as exc:return dict(ok=False,error='提醒确认未完成，请读取状态。',error_kind=type(exc).__name__)
