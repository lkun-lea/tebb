"""Narrow model tools: shared discovery, fixture start, owned evidence and cancellation."""
from desk_companion.evaluation.self_test import catalog, OPERATIONS
from desk_companion.local_api.worker_rpc import call

HINT='需要自测或验收产品能力时，先用 self_test_catalog 发现合同，再按目录启动隔离模拟并读取原批次报告；模拟通过不等于真实模型、界面或外部服务通过。'


def specs(request=None):
    def invoke(operation,args):
        import os
        if os.environ.get('TEBB_EVAL_CANCEL_FILE')and operation in {'start','cancel'}:
            raise ValueError('评测任务内不能启动或干预嵌套自测。')
        if request is not None:
            task_id=request['task_id'];run_id=request['collab_run']
        else:
            from desk_companion.tasks.task_budgets import current
            scope=current()
            if scope is None:raise ValueError('自测工具须由实际产品任务调用。')
            task_id=scope.task;run_id=''
        return call('agent_self_test',dict(operation=operation,payload=args,task_id=task_id,run_id=run_id))
    def spec(name,description,properties,required,implementation,readonly):
        return dict(type='function',function=dict(name=name,description=description,parameters=dict(type='object',
            properties=properties,required=required,additionalProperties=False)),implementation=implementation,read_only=readonly)
    inspect_properties={k:v for op in ('get','report','diagnose','trace','debug_call')for k,v in OPERATIONS[op].items()}
    inspect_properties['operation']=dict(type='string',enum=['get','report','diagnose','trace','debug_call'])
    def inspect(args):return invoke(args['operation'],{k:v for k,v in args.items()if k!='operation'})
    return [
        spec('self_test_catalog','发现 Agent 自测、调试与验收能力，读取固定用例、参数 Schema、前置条件、缺口和调用步骤；只发现，不运行。',{},[],lambda _:catalog(),True),
        spec('self_test_start','按 self_test_catalog 的 capability 启动隔离模拟自测，固定一份样本与期限；request_id 至少8字符，同一请求复用原编号核对，失败不自动重跑。不调用真实模型或写真实外部服务。',
             OPERATIONS['start'],['capability','request_id'],lambda args:invoke('start',args),False),
        spec('self_test_inspect','读取本任务创建的自测批次进度、验收报告、分阶段超时诊断、执行图或脱敏调用证据。先 get/report；trace 另需 case_id，debug_call 再需 call_id，sample 默认1。不读取任意路径。',
             inspect_properties,['operation','ident'],inspect,True),
        spec('self_test_cancel','停止本任务创建的隔离自测批次；继续查询原编号确认取消与资源收尾，不取消其他业务任务。',
             OPERATIONS['cancel'],['ident'],lambda args:invoke('cancel',args),False),
    ]
