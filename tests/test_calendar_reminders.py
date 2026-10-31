import copy
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
import asyncio
import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock,patch

from desk_companion.calendar_time import TZ
from desk_companion.calendar_reminders import CalendarReminderService,stamp


class CalendarRemindersTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'reminders.json'
        self.now=datetime(2040,1,2,9,50,tzinfo=TZ);self.events=[];self.calls=[];self.remote=False;self.valid=True
        self.service=self.make_service()

    def make_service(self):
        return CalendarReminderService(self,path=self.path,clock=lambda:self.now,remote_connected=lambda:self.remote)

    def load_week(self,day,refresh=False):
        self.calls.append((day,refresh))
        return dict(ok=True,events=copy.deepcopy(self.events),events_valid=self.valid,events_error=''if self.valid else'isolated read failure',
            calendar=dict(id='primary'),checked_at=stamp(self.now))

    def event(self,key='first',**fields):
        return dict(calendar_id='tebb-local',event_id=key,summary='隔离安排',start=stamp(self.now+timedelta(minutes=10)),
            end=stamp(self.now+timedelta(hours=1)),status='confirmed',verification='confirmed',checked_at=stamp(self.now),**fields)

    def test_startup_window_restart_and_multiple_windows_deliver_once(self):
        self.events=[self.event()];self.assertTrue(self.service.tick()['ok'])
        first=self.service.claim('main-window-0001',[])['reminders'];self.assertEqual(len(first),1)
        key=first[0]['id'];self.assertEqual(self.service.claim('pet-window-0002',[])['reminders'],[])
        self.assertEqual(self.make_service().claim('main-restarted-0003',[])['reminders'],[])
        self.assertEqual(self.service.claim('main-window-0001',[key])['reminders'][0]['id'],key)
        self.assertTrue(self.service.acknowledge('main-window-0001',[key])['ok'])
        self.assertEqual(self.make_service().claim('main-window-0001',[key])['reminders'],[])
        self.assertTrue(self.make_service().snapshot()['reminders'][0]['acknowledged_at'])

    def test_concurrent_windows_cannot_claim_the_same_event(self):
        self.events=[self.event()];self.service.tick()
        def claim(index):return self.make_service().claim('window-number-'+str(index),[])['reminders']
        with ThreadPoolExecutor(max_workers=4)as pool:results=list(pool.map(claim,range(8)))
        self.assertEqual(sum(len(rows)for rows in results),1)

    def test_same_live_window_can_reconcile_a_lost_response_but_restart_cannot_repeat_it(self):
        self.events=[self.event()];self.service.tick();self.service.claim('main-window-0001',[])
        result=self.service.claim('main-window-0001',[]);self.assertEqual(len(result['reminders']),1)
        self.assertEqual(result['recovered_ids'],[result['reminders'][0]['id']]);self.assertEqual(self.make_service().claim('main-restarted-0002',[])['reminders'],[])

    def test_stopped_service_does_not_read_or_deliver_and_background_io_is_bounded(self):
        from desk_companion.calendar_adapter import CalendarAdapter,CalendarError
        calls=[];stopped=[]
        adapter=CalendarAdapter(run=lambda args,timeout:(calls.append(timeout)or'{"ok":true,"data":{}}'),timeout_cap=5,cancelled=lambda:bool(stopped))
        self.assertEqual(adapter._call(['test']),{});self.assertEqual(calls,[5]);stopped.append(True)
        with self.assertRaises(CalendarError):adapter._call(['test'])
        self.assertEqual(calls,[5]);self.service.stop();self.assertEqual(self.service.tick()['state'],'stopped');self.assertEqual(self.calls,[])
        self.assertEqual(self.service.claim('main-window-0001',[])['reminders'],[])

    def test_reschedule_is_a_new_start_and_sleep_does_not_replay_past_events(self):
        self.events=[self.event()];self.service.tick();first=self.service.claim('main-window-0001',[])['reminders'][0]
        self.events[0]['start']=stamp(self.now+timedelta(minutes=8));self.service.tick()
        second=self.service.claim('main-window-0001',[])['reminders'];self.assertEqual(len(second),1);self.assertNotEqual(first['id'],second[0]['id'])
        self.now+=timedelta(hours=2);self.service.tick();self.assertEqual(self.service.claim('after-sleep-0001',[])['reminders'],[])

    def test_local_reminders_survive_disconnected_or_failed_remote_calendar(self):
        self.valid=False;self.events=[self.event()];result=self.service.tick()
        self.assertTrue(result['ok']);self.assertEqual(len(self.service.claim('main-window-0001',[])['reminders']),1)
        self.assertTrue(all(not refresh for _,refresh in self.calls))

    def test_all_day_cancelled_stale_and_unverified_are_filtered_but_recurrence_can_remind(self):
        self.remote=True
        remote=self.event('remote');remote.update(calendar_id='primary',eligible=False,editable=False,recurring_event_id='series')
        stale=copy.deepcopy(remote);stale.update(event_id='stale',checked_at=stamp(self.now-timedelta(minutes=6)))
        uncertain=copy.deepcopy(remote);uncertain.update(event_id='uncertain',verification='read_failed')
        all_day=self.event('day');all_day.update(start='2040-01-02',end='2040-01-03')
        cancelled=self.event('cancelled');cancelled['status']='cancelled'
        past=self.event('past');past['start']=stamp(self.now-timedelta(seconds=1))
        self.events=[remote,stale,uncertain,all_day,cancelled,past];result=self.service.tick()
        rows=self.service.claim('main-window-0001',[])['reminders'];self.assertEqual([row['event_id']for row in rows],['remote'])
        self.assertEqual(result['scan']['skipped']['stale_remote'],1);self.assertTrue(self.calls[0][1])

    def test_verified_remote_mapping_preserves_delivery_when_local_identity_appears(self):
        self.remote=True;remote=self.event('remote');remote['calendar_id']='primary';self.events=[remote]
        self.service.tick();first=self.service.claim('main-window-0001',[])['reminders'][0]
        local=self.event('local');local['remote']=dict(calendar_id='primary',event_id='remote');self.events=[local]
        self.service.tick();self.assertEqual(self.service.claim('pet-window-0002',[])['reminders'],[])
        current=self.service.claim('main-window-0001',[first['id']])['reminders'][0];self.assertEqual(current['id'],first['id']);self.assertEqual(current['calendar_id'],'tebb-local')

    def test_verified_alias_merge_preserves_an_existing_acknowledgement_and_audit(self):
        self.remote=True;local=self.event('local');remote=self.event('remote');remote['calendar_id']='primary'
        self.events=[local,remote];self.service.tick();rows=self.service.claim('main-window-0001',[])['reminders'];self.assertEqual(len(rows),2)
        acknowledged=next(row for row in rows if row['event_id']=='local');self.service.acknowledge('main-window-0001',[acknowledged['id']])
        local['remote']=dict(calendar_id='primary',event_id='remote');self.events=[local];self.service.tick()
        self.assertEqual(self.service.claim('main-window-0001',[row['id']for row in rows])['reminders'],[])
        snapshot=self.service.snapshot();self.assertEqual(len(snapshot['reminders']),2);self.assertEqual(len(snapshot['candidates']),1)
        self.assertEqual(sum(bool(row['merged_into'])for row in snapshot['reminders']),1)

    def test_actual_local_calendar_projection_reminds_without_changing_events_or_calling_cli(self):
        from desk_companion.work_board import WorkBoardService
        from desk_companion.scheduling import SchedulingService
        with patch.dict(os.environ,DESK_COMPANION_DATA_DIR=str(self.path.parent/'profile')):
            calendar=Mock();scheduling=SchedulingService(WorkBoardService(),calendar)
            created=scheduling.local.change(dict(type='create',request_id='create-local-reminder',summary='真实本地安排',
                start=stamp(self.now+timedelta(minutes=5)),end=stamp(self.now+timedelta(minutes=45)),item_id=''))
            self.assertTrue(created['ok'],created);before=scheduling.local.load()['events']
            service=CalendarReminderService(scheduling,path=self.path,clock=lambda:self.now,remote_connected=lambda:False)
            self.assertTrue(service.tick()['ok']);rows=service.claim('main-window-0001',[])['reminders'];self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['event_id'],created['event']['event_id']);self.assertEqual(scheduling.local.load()['events'],before);self.assertEqual(calendar.mock_calls,[])

    def test_failed_remote_read_retries_within_the_reminder_window(self):
        self.remote=True;self.valid=False;remote=self.event('remote');remote['calendar_id']='primary';self.events=[remote]
        self.service.tick();self.assertEqual(self.service.claim('main-window-0001',[])['reminders'],[])
        self.now+=timedelta(seconds=31);self.valid=True;self.service.tick()
        self.assertTrue(self.calls[-1][1]);self.assertEqual(len(self.service.claim('main-window-0001',[])['reminders']),1)

    def test_preference_is_independent_and_disabled_scan_does_not_read_calendar(self):
        self.assertTrue(self.service.save_settings(False)['ok']);self.events=[self.event()]
        self.assertEqual(self.service.tick()['state'],'disabled');self.assertEqual(self.calls,[])
        self.assertEqual(self.service.claim('main-window-0001',[])['reminders'],[])
        self.service.save_settings(True);self.service.tick();self.assertEqual(len(self.service.claim('main-window-0001',[])['reminders']),1)
        self.assertFalse(self.service.save_settings('false')['ok'])

    def test_reenable_or_sleep_requires_a_fresh_scan_before_new_delivery(self):
        self.events=[self.event()];self.service.tick();self.service.save_settings(False);self.service.save_settings(True)
        self.assertEqual(self.service.claim('main-window-0001',[])['reminders'],[])
        self.service.tick();self.now+=timedelta(minutes=2)
        self.assertEqual(self.service.claim('main-window-0001',[])['reminders'],[])
        self.service.tick();self.assertEqual(len(self.service.claim('main-window-0001',[])['reminders']),1)

    def test_malformed_record_is_preserved_without_overwriting_its_scan(self):
        self.events=[self.event()];self.service.tick();state=json.loads(self.path.read_text('utf-8'));next(iter(state['records'].values()))['active']='invalid'
        self.path.write_text(json.dumps(state),encoding='utf-8');before=self.path.read_bytes()
        self.assertFalse(self.service.tick()['ok']);self.assertFalse(self.service.snapshot()['ok']);self.assertEqual(self.path.read_bytes(),before)

    def test_cross_week_midnight_catchup_reads_both_weeks(self):
        self.now=datetime(2040,1,1,23,57,tzinfo=TZ) # Sunday
        while self.now.weekday()!=6:self.now-=timedelta(days=1)
        self.events=[self.event()];self.service.tick();self.assertEqual(len(self.calls),2)
        self.assertEqual(len(self.service.claim('main-window-0001',[])['reminders']),1)

    def test_scan_failure_never_delivers_old_pending_or_changes_source(self):
        self.events=[self.event()];before=copy.deepcopy(self.events);self.service.tick()
        def fail(*args,**kwargs):raise OSError('synthetic failure')
        self.service.scheduling=type('Broken',(),{'load_week':fail})();self.assertFalse(self.service.tick()['ok'])
        self.assertEqual(self.service.claim('main-window-0001',[])['reminders'],[]);self.assertEqual(self.events,before)

    def test_corrupt_state_is_preserved_and_ack_is_owned_and_idempotent(self):
        self.path.write_text('{broken',encoding='utf-8');self.assertFalse(self.service.snapshot()['ok']);self.assertFalse(self.service.tick()['ok'])
        self.assertEqual(self.path.read_text('utf-8'),'{broken');self.path.unlink()
        self.events=[self.event()];self.service.tick();row=self.service.claim('main-window-0001',[])['reminders'][0]
        self.assertFalse(self.service.acknowledge('pet-window-0002',[row['id']])['ok'])
        self.assertTrue(self.service.acknowledge('main-window-0001',[row['id']])['ok'])
        before=self.path.read_bytes();self.assertTrue(self.service.acknowledge('main-window-0001',[row['id']])['ok']);self.assertEqual(self.path.read_bytes(),before)


class ReminderSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_automation_does_not_block_reminders_and_both_loops_stop(self):
        from desk_companion.local_api.server import scheduled_jobs
        loop=asyncio.get_running_loop();shutdown=asyncio.Event();entered=threading.Event();release=threading.Event();calls=[]
        def automation():
            calls.append('automation');entered.set()
            if not release.wait(5):raise TimeoutError('synthetic release missing')
        def reminder():
            if not entered.wait(5):raise TimeoutError('automation did not start')
            calls.append('reminder');release.set();loop.call_soon_threadsafe(shutdown.set)
        host=SimpleNamespace(automation=SimpleNamespace(tick=automation),calendar_reminders=SimpleNamespace(tick=reminder))
        try:await asyncio.wait_for(scheduled_jobs(host,shutdown),5)
        finally:release.set();shutdown.set()
        self.assertEqual(calls,['automation','reminder'])
