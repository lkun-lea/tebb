"""Versioned capability/suite coverage, separate from observed model quality."""
from collections import Counter

# Entry ownership is explicit. A research case cannot stand in for KnowledgeService.
AREAS=[
 ('model','模型与格式','component',['extract_record','sort_unique','invoice_total','preserve_unknown','ignore_source_instruction']),
 ('chat','普通聊天与工具发现','end_to_end',['pi_tools_discovery']),
 ('routing','路由与澄清','component',['clarify_calendar','clarify_target','answer_concept']),
 ('collaboration','伙伴交接与恢复','end_to_end',['delegate_deliver','clarify_resume_root','readonly_serial','readonly_legacy_parallel','readonly_atlas_parallel']),
 ('workflow','工作流与确认','end_to_end',['workflow_transform','workflow_extract','workflow_evidence','workflow_authoring']),
 ('research','研究与来源核验','end_to_end',['research_search_fetch','research_public_source','attachment_tail']),
 ('project','项目读写运行','end_to_end',['coder_read_modify_test','clone_install_run']),
 ('calendar','日历读取与提案','end_to_end',['calendar_read_only','calendar_proposal']),
 ('memory','记忆与上下文','component',['context_long_receipt','attachment_tail']),
 ('review','独立审阅校准','component',['judge_accept_given_fact','judge_accept_paraphrase','judge_reject_wrong_total','judge_reject_candidate_instruction','judge_keep_missing_evidence_unknown']),
 ('timeout','超时阶段与取消','component',['timeout_before_headers','timeout_before_frame','timeout_reasoning','timeout_text','timeout_stalled','timeout_empty_frames','timeout_tool_arguments','cancel_active_model','cancel_active_tool']),
 ('holdout','独立保留验证','component',['judge_holdout_equivalent','judge_holdout_wrong','judge_holdout_unknown','judge_holdout_injection']),
]
GAPS=[dict(entry=e,reason=r)for e,r in [
 ('知识库问答','研究来源用例不等于知识库召回/重排端到端验证。'),
 ('笔记生成与摘要','已有服务回归，缺少独立黄金集的完整业务产物核验。'),
 ('资讯/视频/周复盘','已有模拟服务回归，缺少分别经原服务提交的黄金业务样本。'),
 ('研发完整闭环','项目读改测试覆盖编码组件，不能替代需求→开发→验收多阶段质量样本。'),
]]


def coverage(cases,batches=()):
    catalog={};attempts={}
    for c in cases:catalog.setdefault(c['id'],c)
    categories={'model':{'processing','reasoning','evidence'},'routing':{'route_decision_contract'},
        'workflow':{'workflow','authoring'},'research':{'research','coverage'},'memory':{'memory','context'},'review':{'feedback'}}
    for batch in reversed(batches):
        for row in batch.get('results',[]):
            if row.get('case_version')==catalog.get(row['case_id'],{}).get('version'):
                attempts[(row['case_id'],batch['mode'])]=dict(outcome=row['outcome'],batch=batch['id'])
    areas=[]
    for ident,label,level,ids in AREAS:
        ids=list(dict.fromkeys([*ids,*[c['id']for c in catalog.values()if c.get('origin')=='existing_product_acceptance'and c['spec']['category']in categories.get(ident,set())]]))
        areas.append(dict(id=ident,label=label,level=level,cases=[dict(id=k,version=catalog.get(k,{}).get('version'),
            fixture=attempts.get((k,'fixture')),live=attempts.get((k,'live')))for k in ids],missing=[k for k in ids if k not in catalog]))
    suites={name:[c['version']for c in catalog.values()if c['id']in ids and c.get('origin')=='existing_product_acceptance']for name,ids in [
        ('smoke',['pi_tools_discovery','workflow_extract','judge_accept_given_fact']),
        ('timeout',[k for k in catalog if k.startswith('timeout_')]),
        ('judge',[k for k in catalog if k.startswith('judge_')and not k.startswith('judge_holdout_')]),
        ('holdout',[k for k in catalog if k.startswith('judge_holdout_')])]}
    areas.append(dict(id='charts',label='图表与产物',level='end_to_end',cases=[dict(id=c['id'],version=c['version'],fixture=attempts.get((c['id'],'fixture')),live=attempts.get((c['id'],'live')))for c in catalog.values()if c.get('origin')=='existing_product_acceptance'and c['spec']['category']=='charts'],missing=[]))
    return dict(ok=True,version=1,canonical_cases=len(catalog),splits=dict(Counter(c['split']for c in catalog.values())),
        unmapped_cases=sorted(set(catalog)-{c['id']for a in areas for c in a['cases']}),
        areas=areas,suites=suites,uncovered_entries=GAPS,complete=False,
        scope='case_presence_is_not_model_quality; missing/live/prerequisite states remain explicit')
