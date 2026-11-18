"""Controlled SSE failures through the actual Pi transport and original budgets."""
import json
import time
from desk_companion.tasks.task_budgets import budgeted_operation,current


def respond(handler,scenario):
    try:
        if scenario=='before_headers':time.sleep(2)
        handler.send_response(200);handler.send_header('Content-Type','text/event-stream');handler.end_headers()
        if scenario in {'before_headers','before_frame'}:time.sleep(2);return
        started=time.monotonic()
        ordinal=0
        while time.monotonic()-started<2:
            delta=dict(reasoning_content='合成推理片段')if scenario in {'reasoning','stalled'}else dict(content='x')if scenario=='text'else{}
            if scenario=='tool_arguments':
                delta=dict(tool_calls=[dict(index=0,id='synthetic',type='function',function=dict(name='synthetic_never_executed',arguments='{'))])if ordinal==0 else dict(tool_calls=[dict(index=0,function=dict(arguments=' '))])
            handler.wfile.write(('data: '+json.dumps(dict(choices=[dict(index=0,delta=delta,finish_reason=None)]))+'\n\n').encode());handler.wfile.flush()
            ordinal+=1
            time.sleep(2 if scenario=='stalled'else .04)
    except (OSError,ConnectionError):pass  # The injected deadline owns this disconnect.


@budgeted_operation('timeout_probe','simple')
def execute(spec,model,*,progress=lambda _:None):
    from atlas.llm import ChatOptions
    from desk_companion.pi_runtime.inference import PiInference
    from desk_companion.observability.usage_store import UsageStore
    from desk_companion.observability.timeout_diagnostics import diagnose
    task=current().task
    progress(dict(task_id=task,task_ids=[task],execution_kind='component_operation',stage='transport_probe'))
    error=None
    try:
        with PiInference(model,timeout=1.5)as llm:llm.chat([dict(role='system',content='Synthetic timeout probe.'),dict(role='user',content=spec['prompt'])],options=ChatOptions())
    except Exception as exc:error=type(exc).__name__
    rows=[r for r in UsageStore().rows(task=task)if r['kind']=='model']
    diagnosis=diagnose(rows[0])if len(rows)==1 else None
    verified=bool(diagnosis and diagnosis['timeout']and diagnosis['kind']==spec['expected']['kind'])
    return dict(task_id=task,task_ids=[task],execution_kind='component_operation',expected_fault=True,
        outcome='success'if verified else'failed',error_kind=error,
        evidence=dict(verified=verified,expected=spec['expected']['kind'],diagnosis=diagnosis,scope='injected_fault_handling_not_business_delivery'))
