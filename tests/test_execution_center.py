import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from desk_companion.observability.tool_monitor import ToolMonitor,ToolRequest
from desk_companion.observability.usage_store import UsageStore
from desk_companion.observability.usage_observer import invoke_tool
from desk_companion.observability.execution_center import ExecutionCenter
from desk_companion.pi_runtime.tool_loading import ToolLoading,SEARCH,LOAD


def spec(name,description='fixture definition'):
    return dict(name=name,description=description,parameters=dict(type='object',properties={},additionalProperties=False))


class ExecutionCenterTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.directory=Path(folder.name)
        env=patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder.name);env.start();self.addCleanup(env.stop)
        self.tools=ToolMonitor();self.usage=UsageStore()

    def test_stable_versions_append_order_restore_and_revocation(self):
        specs=[spec('web_fetch'),spec('project_read')]
        a=ToolLoading(specs,session='s',root='r',store=self.tools)
        self.assertEqual([s['name']for s in a.specs()],[SEARCH,LOAD])
        self.assertEqual([t['name']for t in a.execute(SEARCH,dict(query='project'),'search-1')['tools']],['project_read'])
        a.execute(LOAD,dict(names=['project_read']),'load-1')
        prefix=a.specs();a.execute(LOAD,dict(names=['web_fetch']),'load-2')
        self.assertEqual(a.specs()[:len(prefix)],prefix)
        b=ToolLoading(specs,session='s',root='r',store=self.tools)
        self.assertEqual(b.loaded,['project_read','web_fetch'])
        self.assertEqual(a.specs(),b.specs())
        c=ToolLoading([spec('web_fetch','changed schema version')],session='s',root='new-root',store=self.tools)
        self.assertEqual(c.loaded,[])
        with self.assertRaises(ValueError):c.execute(LOAD,dict(names=['project_read']),'revoked')
        self.assertNotIn('project_read',str(c.execute(SEARCH,dict(query='project'),'search-2')))

    def test_request_rejection_and_business_failure_are_distinct_from_attempt(self):
        with ToolRequest('web_fetch',ident='deny',metadata=dict(root='r',task='t'))as request:
            request.reject('budget_denied')
        with ToolRequest('project_read',ident='actual',metadata=dict(root='r',task='t')):
            invoke_tool('project_read',lambda:'{"ok":false,"error":"api_key=do-not-store"}')
        events=self.tools.events()
        self.assertEqual(sum(e['phase']=='attempt'for e in events),1)
        self.assertEqual(sum(e['phase']=='intercept'for e in events),1)
        self.assertEqual(self.usage.rows()[0]['state'],'failed')
        self.assertNotIn('do-not-store',json.dumps(events))
        self.assertNotIn('api_key',json.dumps(events))

    def test_event_dedup_cannot_rebind_and_pagination_is_gap_free(self):
        for i in range(5):self.tools.event('request',ident='e'+str(i),tool='x',root='r')
        self.tools.event('request',ident='e0',tool='x',root='r')
        with self.assertRaises(ValueError):self.tools.event('request',ident='e0',tool='y',root='r')
        first=self.tools.events(root='r',limit=2);second=self.tools.events(root='r',after=first[-1]['seq'],limit=3)
        self.assertEqual([e['id']for e in first+second],['e0','e1','e2','e3','e4'])
        with self.assertRaises(ValueError):self.tools.event('attempt',arguments={'key':'secret'})

    def test_graph_keeps_owner_state_missing_usage_and_actual_model_tool_edge(self):
        now=time.time()-1
        self.usage.begin('m','model',dict(root='task:r',task='physical',model='fixture'),now=now)
        self.usage.begin('t','tool',dict(root='task:r',task='physical',tool='web_fetch',parent_call='m'),now=now)
        self.usage.update('t',state='returned')
        source=lambda:dict(tasks=[dict(id='task:r',state='failed',created=now,completion='unverified')],attempts=[dict(id='physical',root='task:r',state='failed',created=now)])
        center=ExecutionCenter(self.usage,self.tools,source,lambda _:dict(nodes=[],edges=[],task_bindings={}))
        graph=center.locate('physical')
        self.assertEqual(next(n for n in graph['nodes']if n['id']=='m')['state'],'unknown')
        self.assertEqual(next(n for n in graph['nodes']if n['id']=='task:r')['state'],'failed')
        self.assertIn(dict(id='m>t',source='m',target='t',relation='model_tool'),graph['edges'])
        self.assertEqual(graph['acceptance']['state'],'unverified')
        self.assertFalse(graph['coverage']['history_inferred'])
        self.assertNotIn('cost_cny',next(n for n in graph['nodes']if n['id']=='m'))

    def test_task_type_filters_real_observations_without_counting_children_as_roots(self):
        now=time.time()-1
        for ident,root,purpose in [('one','task:r','research'),('two','task:r','research'),('three','task:other','summary')]:
            self.usage.begin(ident,'model',dict(root=root,task=ident,model='fixture',purpose=purpose),now=now)
        sources=lambda:dict(tasks=[dict(id=root,kind='task',state='succeeded',created=now)for root in ('task:r','task:other')],attempts=[])
        center=ExecutionCenter(self.usage,self.tools,sources)
        value=center.list(filters=dict(purpose='research'))
        self.assertEqual([r['id']for r in value['items']],['task:r'])
        self.assertEqual(value['kinds']['task'],1)
