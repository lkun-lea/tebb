"""Native project-team integration; scripted model decisions, real file writes and Python processes."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from desk_companion import project_workspace
from desk_companion.collaboration import transaction
from desk_companion.collaboration_worker import execute
from desk_companion import task_budgets
from tests import test_collaboration as fixtures


class NativeTeamTests(unittest.TestCase):
    setUp = fixtures.CollaborationTests.setUp
    tearDown = fixtures.CollaborationTests.tearDown

    def action(self, **values):
        return self.service.action(dict(request_id=uuid.uuid4().hex, **values))["state"]

    def test_cancel_missing_receipt_and_failed_recheck_do_not_submit_new_work(self):
        parent=dict(development_task=True,parent=None)
        checker=dict(state="failed",integration_verification=True)
        for status,commands,already in [("cancelled",["check"],False),("failed",[],False),("failed",["check"],True)]:
            with self.subTest(status=status,already=already):
                self.assertFalse(self.service._repair_integration({},dict(parent,integration_repair=already),
                    [dict(checker,state=status,integration_failure=commands)]))
        self.assertFalse(self.work.requests)

    def test_restart_defect_repaired_and_rechecked_within_original_root(self):
        folder=Path(self.temp.name)/"orders"
        folder.mkdir()
        storage=folder/"storage.py"
        storage.write_text("def record(path,key): return 0\n", "utf-8")
        (folder/"order.py").write_text("from storage import record\nimport sys\nprint(record(*sys.argv[1:]))", "utf-8")
        command="python check_restart.py"
        (folder/"checks.py").write_text(
            "import subprocess,sys,tempfile,pathlib\n"
            "def check(count):\n with tempfile.TemporaryDirectory() as temp:\n"
            "  for _ in range(count):\n   value=subprocess.check_output([sys.executable,'-B','order.py',str(pathlib.Path(temp)/'db'),'order-1'],text=True).strip()\n"
            "   assert value=='1', 'duplicate order after restart: '+value\n", "utf-8")
        for script,count in [("check_first",1),("check_restart",2)]:
            (folder/(script+".py")).write_text("from checks import check\ncheck("+str(count)+")", "utf-8")

        self.action(type="add_coder")
        state=self.action(type="open_folder_project",primary=str(folder))
        project=next(c["project_id"] for c in state["conversations"] if c["id"]==state["selected"])
        group=self.action(type="group",project_id=project,title="订单开发",members=["tebb","coder","research"])["selected"]
        with transaction(self.service.path) as (db,_):
            next(a for a in db["agents"] if a["id"]=="research")["tools"]=["工作区读取","终端"]
        action=dict(type="send",conversation=group,strategy="delegate",mode="task",
                    development_task=True,text="让重复订单在进程重启后仍只结算一次")
        with self.assertRaises(ValueError):self.action(**action)
        project_workspace.save(str(folder),[],True,True,project_id=project)
        root=self.action(**action)["runs"][-1]["id"]
        self.service.tick()
        from desk_companion.task_budgets import Ledger
        with transaction(self.service.path) as (db,_):
            budget=Ledger().read(next(r for r in db['runs'] if r['id']==root)['budget_id'])
        self.assertEqual(budget['tier'],'coding')
        self.assertEqual(budget['hard_time_ms'],600_000)
        self.chat.complete(next(iter(self.chat.items)),json.dumps(dict(mode="task",instructions=action["text"],strategy="direct")))
        self.service.tick()
        def take(kind,role=None):
            for _ in range(12):
                self.service.tick()
                for task,req in self.work.requests.items():
                    if req["kind"]==kind and (role is None or req["role"]["id"]==role) and self.work.items[task]["state"]=="queued":
                        return task,req
            self.fail("未调度 "+str((kind,role,self.service.snapshot()["state"]["runs"])))
        def run_command(cmd,*args):
            assert cmd in ("python check_first.py",command)
            run=subprocess.run([sys.executable,"-B",cmd.split()[1]],cwd=folder,capture_output=True,text=True)
            return dict(command=cmd,state="failed" if run.returncode else "succeeded",exit_code=run.returncode,output=run.stderr,changes=[])
        def worker(task,req,steps):
            events=[];log=[]
            class Model:
                on_tool_delta=None
                def chat(_,messages,tools,on_delta):
                    log.append(messages)
                    names={t['function']['name'] for t in tools or []}
                    if 'workspace_read' in names:
                        self.assertTrue({'workspace_search','workspace_read_symbol'} <= names)
                        self.assertEqual('workspace_patch' in names,'workspace_write' in names)
                        read=next(t['function'] for t in tools if t['function']['name']=='workspace_read')
                        self.assertEqual('open_question' in read['parameters']['properties'],'workspace_patch' in names)
                        if req.get('integration_verification'):
                            self.assertNotIn('workspace_patch',names)
                    scope=task_budgets.current()
                    if scope:
                        phase=scope.phase()
                        call,_=scope.ledger.reserve_call(scope.task,20,phase=phase)
                        scope.ledger.settle(scope.task,call,dict(prompt_tokens=20,completion_tokens=8))
                        if phase=='finish':
                            self.assertFalse(tools)
                    if steps:
                        tool,args=steps.pop(0)
                        return dict(message=dict(role="assistant",tool_calls=[dict(id=str(len(log)),type="function",function=dict(name=tool,arguments=json.dumps(args)))]),usage={})
                    return dict(message=dict(content="本轮已执行，结果见命令回执。"),usage={})
            try:
                with patch.object(project_workspace,"run",side_effect=run_command):
                    execute(req,lambda k,d:events.append((k,d)),llm=Model())
                self.work.complete(task,"本轮已执行，结果见命令回执。")
            except Exception as exc:
                if not any(k=="integration_failure" for k,d in events):raise
                self.work.complete(task,str(exc),state="failed")
            self.work.items[task]["events"].extend(dict(seq=i+4,kind=k,data=d) for i,(k,d) in enumerate(events))
            return log
        prefix="from pathlib import Path\nimport json\ndef record(path,key):\n p=Path(path); d=json.loads(p.read_text()) if p.exists() else {}\n "
        end="\n p.write_text(json.dumps(d)); return d[key]\n"
        def implementation(task,req,edit):
            rev=project_workspace.read("main","storage.py",config=req["workspace"])["revision"]
            name,args=edit
            steps=[]
            if name=='workspace_patch':
                steps=[('workspace_read_symbol',dict(path='storage.py',symbol='record')),
                       ('workspace_read',dict(path='checks.py',open_question='重启检查如何比较两次余额？'))]
            log=worker(task,req,steps+[(name,dict(path="storage.py",revision=rev,**args)),
                                       ("workspace_run",dict(command="python check_first.py"))])
            if name=='workspace_patch':
                self.assertTrue(any('next_step' in str(m.get('content')) for batch in log for m in batch if m.get('role')=='tool'))
                starts=[e['data'] for e in self.work.items[task]['events'] if e['kind']=='tool_start']
                self.assertEqual([e['open_question'] for e in starts if 'open_question' in e],['重启检查如何比较两次余额？'])
            return log
        task,writer=take("task","coder")
        self.assertFalse(any(r['kind']=='plan' for r in self.work.requests.values()))
        # Reproduce the real stall after implementation and a successful command.
        # New work must stop, but one tool-free handoff can still feed the checker.
        ledger=task_budgets.Ledger()
        with transaction(self.service.path) as (db,_):
            budget_id=next(r['budget_id'] for r in db['runs'] if r['id']==root)
        ledger.bind(budget_id,task,purpose='task')
        observe=task_budgets.record_workspace_check
        def plateau(result,changes):
            observe(result,changes)
            for _ in range(3):
                ident,_=ledger.reserve_call(task,12)
                ledger.settle(task,ident,dict(prompt_tokens=12,completion_tokens=8))
        with task_budgets.installed(task),patch.object(task_budgets,'record_workspace_check',side_effect=plateau):
            implementation(task,writer,("workspace_write",dict(text=prefix+"d[key]=1+d.get(key,0)"+end+"# previous: d[key]=1+d.get(key,0)\n")))
        self.assertEqual(sum(c['phase']=='finish' for c in ledger.read(budget_id)['calls'].values()),1)
        self.assertEqual(run_command("python check_first.py")["exit_code"],0)
        self.assertNotEqual(run_command(command)["exit_code"],0)
        task,qa=take("task","research")
        self.assertTrue(qa["integration_verification"])
        self.assertIn("storage.py",qa["handoffs"][0]["workspace_observation"]["files"])
        worker(task,qa,[("workspace_run",dict(command=command))])
        task,fix=take("task","coder")
        proof=fix["handoffs"][0]["workspace_observation"]["checks"][0]
        self.assertEqual(proof["exit_code"],1)
        self.assertIn("duplicate order",proof["failure_output"])
        implementation(task,fix,("workspace_patch",dict(symbol="record",old="d[key]=1+d.get(key,0)",new="d.setdefault(key,1)")))
        task,qa=take("task","research")
        self.assertEqual(qa["required_rechecks"],[command])
        worker(task,qa,[("workspace_run",dict(command=command))])
        task,final=take("task","tebb")
        self.assertTrue(any(h.get("workspace_observation",{}).get("checks") for h in final["handoffs"]))
        self.work.complete(task,"已按同一命令复查。")
        self.service.tick()
        with transaction(self.service.path) as (db,_):
            chain=[r for r in db["runs"] if r["id"]==root or r["parent"]==root]
            self.assertEqual(next(r for r in chain if r["id"]==root)["state"],"succeeded")
            self.assertEqual(len({r["budget_id"] for r in chain}),1)
            self.assertEqual(sum(r["state"]=="failed" for r in chain),1)
        public=self.service.snapshot()["state"]["runs"]
        self.assertEqual(next(r for r in public if r["id"]==root)["chain"]["state"],"succeeded")
