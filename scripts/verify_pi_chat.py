"""Authenticated chat -> real worker/Pi tool loop -> isolated persisted memory.

Only synthetic local provider traffic and temporary profile writes. No live model or Feishu.
"""
import asyncio
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_workflow import main
from scripts.smoke_release import ModelServer
from desk_companion.local_api.worker_rpc import request as rpc_request
from desk_companion.tasks.manager import TERMINAL


class ChatProvider(ModelServer):
    requests=[]
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(data)
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        def frame(delta,finish=None):
            self.wfile.write(('data: '+json.dumps(dict(id='isolated-chat',model=data['model'],object='chat.completion.chunk',created=1,
                choices=[dict(index=0,delta=delta,finish_reason=finish)]))+'\n\n').encode());self.wfile.flush()
        if any(m['role']=='tool'for m in data['messages']):
            tool=next(m for m in reversed(data['messages'])if m['role']=='tool')
            assert '已记下' in tool['content'],tool
            frame(dict(content='已记下：你喜欢四十。'));frame({},'stop')
        elif any('第二轮' in str(m.get('content',''))for m in data['messages']if m['role']=='user'):
            assert any(m['role']=='assistant'and'你喜欢四十' in str(m.get('content',''))for m in data['messages'])
            frame(dict(content='四十。'));frame({},'stop')
        else:
            frame(dict(reasoning_content='Checking the explicit isolated memory request.'))
            frame(dict(tool_calls=[dict(index=0,id='remember-original',type='function',function=dict(name='remember_fact',
                arguments=json.dumps(dict(text='我喜欢四十',quote='我喜欢四十'),ensure_ascii=False)))]))
            frame({},'tool_calls')
        self.wfile.write(('data: '+json.dumps(dict(choices=[],usage=dict(prompt_tokens=13,completion_tokens=7,total_tokens=20)))+'\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


async def verify(port, token, model_port):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def http(path, payload=None):
        request=urllib.request.Request(f'http://127.0.0.1:{port}'+path,
            data=json.dumps(payload).encode()if payload is not None else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with opener.open(request,timeout=90)as response:return json.load(response)
    async def rpc(method,args=None):
        result=await asyncio.to_thread(rpc_request,port,token,method,args,timeout=30)
        assert result['ok'],result
        return result
    await rpc('save_model_network',dict(payload=dict(mode='direct')))
    await rpc('save_model_entry',dict(payload=dict(base_url=f'http://127.0.0.1:{model_port}/v1',model='glm-5-chat-fixture',api_key='isolated-only')))
    session=(await rpc('new_chat_session'))['session_id']
    async def run(request_id,text):
        command=dict(request_id=request_id,text=text,session_id=session,sampling=dict(reasoning_effort='max',temperature=.3,top_p=.8))
        accepted=await asyncio.to_thread(http,'/v1/runs',command)
        replay=await asyncio.to_thread(http,'/v1/runs',command)
        assert accepted['run_id']==replay['run_id']
        for _ in range(350):
            snapshot=await asyncio.to_thread(http,'/v1/runs/'+accepted['run_id'])
            if snapshot['task']['state'] in TERMINAL:break
            await asyncio.sleep(.2)
        assert snapshot['task']['state']=='succeeded',snapshot
        return accepted['run_id'],snapshot
    first,one=await run('pi-chat-first-0001','请记住：我喜欢四十。')
    second,two=await run('pi-chat-second-0002','第二轮：我喜欢什么数字？')
    assert one['task']['answer']=='已记下：你喜欢四十。',one
    budget=(await rpc('get_agent_task',dict(task_id=first,focus=False)))['task']['task_budget']
    assert budget['consumed']['tool_calls']==1,budget
    assert two['task']['answer']=='四十。',two
    facts=(await rpc('load_memory'))['facts']
    matching=[f for f in facts if f['text']=='我喜欢四十']
    assert len(matching)==1 and matching[0]['state']=='active',facts
    history=(await rpc('load_chat_log'))['items']
    assert len(history)==4,history
    assert [r['role']for r in history]==['user','pet','user','pet']
    assert history[1]['react_loops']==2 and history[-1]['react_loops']==1
    calls=(await rpc('list_debug_calls'))['items']
    assert len(calls)==3,calls
    memory_source_verified=False
    for call in calls:
        detail=await rpc('get_debug_call',dict(call_id=call['id']))
        assert detail['meta']['transport']=='pi'and detail['call']['state']=='complete'
        sources=detail['meta']['sources']
        assert sources['status']=='captured'
        if detail['call']['task_id']==second:
            references=[segment.get('source')or{}for row in sources['messages']for segment in row.get('sources',[])]
            assert any(reference.get('id')==matching[0]['id']for reference in references),sources
            memory_source_verified=True
    assert memory_source_verified
    assert len(ChatProvider.requests)==3
    assert len([e for e in one['events']if e['kind']=='tool_start'])==1
    return dict(ok=True,transport='pi-agent-core',task_ids=[first,second],session=session,model_requests=3,
        memory_fact_id=matching[0]['id'],actual_local_memory_writes=1,history_rows=4,memory_source_verified=True,
        call_ids=[r['id']for r in calls],real_model=False,real_external_writes=False)


if __name__=='__main__':main(verify,ChatProvider)
