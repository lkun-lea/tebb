"""Real Python parent/child provenance and progress monitoring; no model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

import psutil

from scripts.dev_cycle import Codex
from scripts.dev_cycle_runtime import ProgressMonitor, progress, python_environment, verify_imports, write_json
from scripts.dev_cycle_observation import build_index, observe
from scripts.dev_cycle_environment import prepare_environment, preflight_environment, requirements


def fixture_wheel(directory):
    """A normal wheel with a native-style .pth and a colliding namespace directory."""
    directory.mkdir(exist_ok=True)
    path=directory/'cycle_fixture-1.0-py3-none-any.whl'
    metadata='cycle_fixture-1.0.dist-info'
    files={'cycle_fixture.py':'VALUE=7\n', 'native_bin/native_probe.py':'VALUE=8\n',
           'native_bin/scripts/foreign_only.py':'raise RuntimeError("foreign code executed")\n',
           'cycle_fixture.pth':'native_bin\nimport cycle_bootstrap\n',
           'cycle_bootstrap.py':'from pathlib import Path\nPath(__file__).with_name("bootstrap-ran").touch()\n',
           metadata+'/METADATA':'Metadata-Version: 2.1\nName: cycle-fixture\nVersion: 1.0\n',
           metadata+'/WHEEL':'Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}
    files[metadata+'/RECORD']=''.join(name+',,\n' for name in [*files,metadata+'/RECORD'])
    with zipfile.ZipFile(path,'w')as wheel:
        for name,body in files.items():wheel.writestr(name,body)
    return path


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.record=self.root/'attempt';self.record.mkdir();(self.record/'evidence').mkdir()

    def monitor(self):
        process=psutil.Process()
        monitor=ProgressMonitor(self.record,self.source,process.pid,process.create_time(),check_seconds=1,silence_seconds=3)
        monitor.started=monitor.last_feedback=100
        return monitor

    def test_silent_but_alive_process_requests_feedback_once_without_stopping(self):
        monitor=self.monitor()
        for now in [104,105]:
            result=monitor.sample(now=now)
            self.assertEqual(result['state'],'needs_check')
            self.assertTrue(result['process_alive'])
        self.assertEqual(len((self.root/'notifications.jsonl').read_text('utf-8').splitlines()),1)
        self.assertTrue((self.record/'evidence'/'progress-request.json').exists())

    def test_vague_messages_and_repeated_claims_do_not_reset_progress(self):
        monitor=self.monitor()
        (self.record/'events.jsonl').write_text(json.dumps(dict(type='item.completed',item=dict(type='agent_message',text='still working')))+'\n','utf-8')
        checkpoint=dict(completed=['claimed'],current='working',next='continue',evidence=[],blocker=None)
        write_json(self.record/'evidence'/'progress.json',checkpoint)
        self.assertEqual(monitor.sample(now=104)['state'],'needs_check')
        proof=self.record/'evidence'/'test.log';proof.write_text('actual test output','utf-8')
        checkpoint['evidence']=[str(proof)];write_json(self.record/'evidence'/'progress.json',checkpoint)
        self.assertEqual(monitor.sample(now=105)['state'],'progress_observed')
        checkpoint['current']='a different unsubstantiated claim';checkpoint['time']=108
        write_json(self.record/'evidence'/'progress.json',checkpoint)
        self.assertEqual(monitor.sample(now=109)['state'],'needs_check')
        self.assertEqual(monitor.last_progress,105)

    def test_partial_events_are_not_lost_and_commands_are_distinct_from_delivery(self):
        monitor=self.monitor();path=self.record/'events.jsonl'
        line=json.dumps(dict(type='item.started',item=dict(id='c1',type='command_execution')))
        path.write_text(line,'utf-8')
        self.assertEqual(monitor.sample(now=101)['active_commands'],0)
        with path.open('a',encoding='utf-8')as stream:stream.write('\n')
        self.assertEqual(monitor.sample(now=102)['state'],'executing')
        with path.open('a',encoding='utf-8')as stream:
            stream.write(json.dumps(dict(type='item.completed',item=dict(id='c1',type='command_execution',exit_code=1)))+'\n')
        result=monitor.sample(now=103)
        self.assertEqual(result['active_commands'],0)
        self.assertIsNone(result['last_progress_at'])

    def test_progress_rechecks_monitor_liveness_without_mutating_task(self):
        monitor=self.monitor();monitor.sample(now=time.time()-10)
        state=dict(status='running',stage='develop',round=1,launches=1,max_launches=12,max_rounds=3,
                   attempts=[dict(directory=self.record.name,status='running')])
        write_json(self.root/'state.json',state)
        before=(self.root/'state.json').read_bytes()
        self.assertEqual(progress(self.root)['monitor']['state'],'monitor_stale_or_process_missing')
        self.assertEqual(before,(self.root/'state.json').read_bytes())

    def test_clean_python_parent_and_child_use_checkout_without_executing_editable_hooks(self):
        (self.source/'owned.py').write_text('VALUE=42\n','utf-8')
        foreign=self.root/'foreign';foreign.mkdir()
        marker=self.root/'editable-hook-ran'
        (foreign/'host-editable.pth').write_text('import pathlib; pathlib.Path('+repr(str(marker))+').touch()\n','utf-8')
        env=python_environment(self.root/'python-env',self.source,self.record,[foreign])
        child='import owned; print(owned.__file__)'
        code='import owned,subprocess,sys,json; print(json.dumps([owned.__file__,subprocess.check_output([sys.executable,"-c",'+repr(child)+'],text=True).strip(),sys.prefix]))'
        result=subprocess.run([env['DEV_CYCLE_PYTHON'],'-c',code],env=env,cwd=foreign,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        values=json.loads(result.stdout)
        self.assertEqual(Path(values[0]),self.source/'owned.py');self.assertEqual(values[0],values[1])
        self.assertEqual(Path(values[2]),self.root/'python-env')
        self.assertFalse(marker.exists())
        verify_imports(self.record)
        self.assertGreaterEqual(len(list((self.record/'evidence'/'imports').glob('*.jsonl'))),2)

    def test_source_guard_blocks_wrong_checkout_even_when_sys_path_is_overridden(self):
        (self.source/'owned.py').write_text('VALUE=42\n','utf-8')
        foreign=self.root/'foreign';foreign.mkdir();(foreign/'owned.py').write_text('VALUE=0\n','utf-8')
        env=python_environment(self.root/'python-env',self.source,self.record)
        code='import sys;sys.path.insert(0,'+repr(str(foreign))+');import owned'
        result=subprocess.run([env['DEV_CYCLE_PYTHON'],'-c',code],env=env,cwd=foreign,capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('source mismatch',result.stderr)
        with self.assertRaisesRegex(ValueError,'源码来源'):
            verify_imports(self.record)
        write_json(self.record/'artifacts.json',dict(evidence_dir=str(self.record/'evidence')))
        state=dict(attempts=[dict(stage='verify',round=1,status='failed',directory=self.record.name)])
        index=build_index(self.root,state)
        mismatch=next(row for row in index['observations']if row['kind']=='source_mismatch')
        write_json(self.root/'observation-index.json',index)
        raw=observe(self.root,[mismatch['id']])
        self.assertIn('"allowed":false',raw['observations'][0]['sources'][0]['content'])

    def test_real_executor_outlives_silence_threshold_and_still_returns_result(self):
        fixture=self.root/'fake_codex.py'
        fixture.write_text('import json,sys,time,pathlib\nsys.stdin.read()\ntime.sleep(.7)\npathlib.Path(sys.argv[sys.argv.index("-o")+1]).write_text(json.dumps({"done":True}))\n','utf-8')
        # Adapter creates the evidence directory itself.
        (self.record/'evidence').rmdir()
        result=Codex(sys.executable,[str(fixture)])(stage='develop',prompt='fixture',cwd=self.source,record=self.record,
                 session=None,started=lambda *_:None,check_seconds=.05,silence_seconds=.1)
        self.assertTrue(result['done'])
        self.assertTrue((self.root/'notifications.jsonl').exists())
        self.assertEqual(json.loads((self.record/'monitor.json').read_text('utf-8'))['state'],'exited')

    def test_unwritable_audit_never_disables_source_guard_at_python_startup(self):
        (self.source/'owned.py').write_text('VALUE=42\n','utf-8')
        env=python_environment(self.root/'python-env',self.source,self.record)
        code='''import sys
from unittest.mock import patch
import dev_cycle_import_guard as guard
with patch('pathlib.Path.mkdir',side_effect=PermissionError('read-only artifacts')):
    guard.install([])
    try:
        import owned
    except ImportError as exc:
        assert 'audit unavailable' in str(exc)
    else:
        raise AssertionError('an unaudited project import was allowed')
assert 'owned' not in sys.modules
print('guard remained active')
'''
        result=subprocess.run([env['DEV_CYCLE_PYTHON'],'-c',code],env=env,cwd=self.source,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('guard remained active',result.stdout)

    def test_namespace_search_is_allowed_but_foreign_child_never_executes(self):
        scripts=self.source/'scripts';scripts.mkdir();(scripts/'owned.py').write_text('VALUE=42\n','utf-8')
        foreign=self.root/'foreign';(foreign/'scripts').mkdir(parents=True)
        marker=self.root/'foreign-executed'
        (foreign/'scripts'/'other.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()','utf-8')
        env=python_environment(self.root/'python-env',self.source,self.record,[foreign])
        code='''import scripts.owned,scripts,json
print(json.dumps(dict(value=scripts.owned.VALUE,paths=list(scripts.__path__))))
try:
    import scripts.other
except ImportError:
    pass
else:
    raise AssertionError('foreign child allowed')
'''
        result=subprocess.run([env['DEV_CYCLE_PYTHON'],'-c',code],env=env,cwd=self.source,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout);self.assertEqual(value['value'],42)
        self.assertIn(str(foreign/'scripts'),value['paths'])
        self.assertFalse(marker.exists())
        with self.assertRaisesRegex(ValueError,'导入已拒绝'):verify_imports(self.record)

    def test_installed_wheel_initialization_and_child_provenance_work_without_host_packages(self):
        (self.source/'requirements.txt').write_text('cycle-fixture==1.0\n','utf-8')
        scripts=self.source/'scripts';scripts.mkdir();(scripts/'owned.py').write_text('VALUE=42\n','utf-8')
        wheels=self.root/'wheels';fixture_wheel(wheels)
        manifest=prepare_environment(self.root/'python-env',self.source,self.record,wheelhouse=wheels,offline=True)
        self.assertIn(['cycle-fixture','1.0'],manifest['distributions'])
        checked=preflight_environment(self.root/'python-env',self.source,self.record)
        self.assertEqual(checked['result']['prefix'],checked['result']['child']['prefix'])
        env=python_environment(self.root/'python-env',self.source,self.record)
        code='import native_probe,cycle_fixture,scripts.owned,sys,json;print(json.dumps(dict(value=[native_probe.VALUE,cycle_fixture.VALUE,scripts.owned.VALUE],path=sys.path)))'
        result=subprocess.run([env['DEV_CYCLE_PYTHON'],'-c',code],env=env,cwd=self.source,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout);self.assertEqual(value['value'],[8,7,42])
        self.assertNotIn(str(Path(sys.executable).parent/'Lib/site-packages'),value['path'])
        self.assertTrue(list((self.root/'python-env').rglob('bootstrap-ran')))
        verify_imports(self.record)

    def test_foreign_regular_package_cannot_shadow_project_namespace(self):
        (self.source/'scripts').mkdir();(self.source/'scripts/owned.py').write_text('VALUE=42\n','utf-8')
        foreign=self.root/'foreign';(foreign/'scripts').mkdir(parents=True)
        marker=self.root/'foreign-executed'
        (foreign/'scripts/__init__.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()','utf-8')
        env=python_environment(self.root/'python-env',self.source,self.record,[foreign])
        result=subprocess.run([env['DEV_CYCLE_PYTHON'],'-c','import scripts.owned'],env=env,cwd=self.source,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(marker.exists())
        self.assertIn('source mismatch',result.stderr)

    def test_dependency_preparation_can_resume_same_plan_after_offline_failure(self):
        (self.source/'requirements.txt').write_text('cycle-fixture==1.0\n','utf-8')
        wheels=self.root/'wheels';wheels.mkdir()
        first=self.root/'first';first.mkdir()
        with self.assertRaisesRegex(ValueError,'依赖安装失败'):
            prepare_environment(self.root/'python-env',self.source,first,wheelhouse=wheels,offline=True)
        self.assertTrue((first/'install.log').stat().st_size)
        fixture_wheel(wheels)
        prepare_environment(self.root/'python-env',self.source,self.record,wheelhouse=wheels,offline=True)
        self.assertEqual(preflight_environment(self.root/'python-env',self.source,self.record)['status'],'ready')
        (self.source/'requirements.txt').write_text('cycle-fixture==2.0\n','utf-8')
        with self.assertRaisesRegex(ValueError,'清单或校验器'):
            python_environment(self.root/'python-env',self.source,self.record)

    def test_preflight_failure_is_observable_without_a_model(self):
        (self.source/'requirements.txt').write_text('missing-package-for-fixture==1\n','utf-8')
        record=self.root/'environment'/'preflight-001'
        with self.assertRaisesRegex(ValueError,'先运行'):
            preflight_environment(self.root/'python-env',self.source,record)
        index=build_index(self.root,dict(attempts=[]))
        row=next(r for r in index['observations']if r['kind']=='environment_preflight')
        self.assertEqual(row['stage'],'environment')
        write_json(self.root/'observation-index.json',index)
        raw=observe(self.root,[row['id']])
        self.assertIn('blocked',raw['observations'][0]['sources'][0]['content'])

    def test_development_plan_uses_project_and_source_dependencies_not_release_runtime_lock(self):
        (self.source/'pyproject.toml').write_text('[project]\ndependencies=["cycle-fixture==1.0"]\n','utf-8')
        (self.source/'scripts').mkdir()
        (self.source/'scripts/runtime-lock.txt').write_text('release-only-package==9.0\n','utf-8')
        dependency=self.root/'atlas';dependency.mkdir()
        (dependency/'pyproject.toml').write_text('[project]\ndependencies=["sdk-fixture==2.0"]\n','utf-8')
        plan=requirements(self.source,[dependency])
        self.assertIn('cycle-fixture==1.0',plan['text'])
        self.assertIn('sdk-fixture==2.0',plan['text'])
        self.assertNotIn('release-only-package',plan['text'])


if __name__=='__main__':
    unittest.main()
