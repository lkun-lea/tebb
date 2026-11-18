"""Normal product worker with a bounded, synthetic external-tool registry.

Used only by the isolated eval harness. The official Pi loop, model admission,
TaskManager, usage/debug records and final product checks remain unchanged.
"""
import json
from unittest.mock import patch
from atlas import Toolkit
from desk_companion.chat import assistant
from desk_companion.infrastructure.paths import data_root
from desk_companion.tasks.worker import main

original_build=assistant.build_agent


def build(host):
    agent=original_build(host);agent.tools=Toolkit()
    def receipt(name,args,result):
        from desk_companion.tasks.task_budgets import current
        path=data_root()/('pi-tools-'+current().task+'.jsonl')
        with path.open('a',encoding='utf-8')as stream:stream.write(json.dumps(dict(tool=name,arguments=args,result=result))+'\n')
        return result
    def calculate(args):return receipt('web_fixture_sum',args,dict(ok=True,total=args['a']+args['b']))
    def check(args):return receipt('project_fixture_check',args,dict(ok=args['total']==18,checked=args['total']==18,total=args['total']))
    def unused(args):return receipt('github_fixture_unused',args,dict(ok=False,error='Unneeded fixture called'))
    for name,description,parameters,callback in [
        ('web_fixture_sum','隔离只读求和服务',dict(type='object',properties=dict(a=dict(type='integer'),b=dict(type='integer')),required=['a','b'],additionalProperties=False),calculate),
        ('project_fixture_check','隔离项目结果检查',dict(type='object',properties=dict(total=dict(type='integer')),required=['total'],additionalProperties=False),check),
        ('github_fixture_unused','本任务不需要的隔离只读工具',dict(type='object',properties={},additionalProperties=False),unused)]:
        agent.tools.register(name=name,description=description,parameters=parameters,func=callback,isReadOnly=True)
    return agent


if __name__=='__main__':
    with patch.object(assistant,'build_agent',build):main()
