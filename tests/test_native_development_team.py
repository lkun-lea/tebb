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
        def implementation(task,req,expression):
            rev=project_workspace.read("main","storage.py",config=req["workspace"])["revision"]
            return worker(task,req,[("workspace_write",dict(path="storage.py",text=prefix+expression+end,revision=rev)),
                                    ("workspace_run",dict(command="python check_first.py"))])
        task,writer=take("task","coder")
        self.assertFalse(any(r['kind']=='plan' for r in self.work.requests.values()))
        implementation(task,writer,"d[key]=1+d.get(key,0)")
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
        implementation(task,fix,"d.setdefault(key,1)")
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
