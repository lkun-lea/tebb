"""Versioned hand-offs for the external Codex development cycle (not product agents)."""
from jsonschema import Draft202012Validator


def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


TEXT = dict(type='string', minLength=1)
TEXTS = dict(type='array', items=TEXT)
EVIDENCE = dict(type='array', minItems=1, items=obj(dict(path=TEXT, observation=TEXT)))
CRITERION = obj(dict(id=TEXT, requirement=TEXT, verification=TEXT))
SCHEMAS = {
    'requirements': obj(dict(
        status=dict(type='string', enum=['ready', 'needs_input']), summary=TEXT, scope=TEXTS,
        non_goals=TEXTS, constraints={**TEXTS, 'description': '仅产品业务/兼容约束，不包含阶段角色权限或流程要求'}, questions=TEXTS,
        criteria=dict(type='array', items=CRITERION))),
    'develop': obj(dict(status=dict(type='string', enum=['ready', 'blocked']), summary=TEXT,
                        changes=TEXTS, tests=TEXTS, limitations=TEXTS)),
    'verify': obj(dict(
        contract_sha256=TEXT, candidate_sha=TEXT,
        checks=dict(type='array', minItems=1, items=obj(dict(
            criterion_id=TEXT, status=dict(type='string', enum=['pass', 'fail', 'unknown']),
            failure_type=dict(type='string', enum=['none', 'implementation', 'requirements', 'environment', 'evaluator']),
            evidence=EVIDENCE))), summary=TEXT)),
    'supervise': obj(dict(
        contract_sha256=TEXT, candidate_sha=TEXT,
        decision=dict(type='string', enum=['pass', 'revise', 'recover', 'needs_input', 'blocked']),
        failure_type=dict(type='string', enum=['none', 'implementation', 'requirements', 'environment', 'evaluator']),
        failed_criteria=TEXTS, evidence=EVIDENCE, reason=TEXT, next_action=TEXT,
        process_review=obj(dict(status=dict(type='string',enum=['healthy','improve','unknown']),summary=TEXT,
            findings=dict(type='array',items=obj(dict(observation_ids={**TEXTS,'minItems':1},problem=TEXT,
                action=TEXT,expected_result=TEXT,regression=TEXT))))))),
    'reflect': obj(dict(observations=TEXTS, proposals=dict(type='array',items=obj(dict(
        kind=dict(type='string',enum=['task','workflow']),
        owner=dict(type='string',enum=['develop','verify','verification_plan','maintenance']),
        observation_ids=TEXTS, action=TEXT, expected_result=TEXT, regression=TEXT))), validation_plan=TEXTS)),
}
SCHEMAS['verification_plan']=obj(dict(draft_sha256=TEXT,source_review_sha256=TEXT,
    items=dict(type='array',minItems=1,items=obj(dict(opinion_id=TEXT,criterion_ids=TEXTS,
        input=TEXT,entry=TEXT,expected=TEXT,negative_case=TEXT)))))
SCHEMAS['maintenance_review']=obj(dict(decision=dict(type='string',enum=['pass','revise','blocked']),
    reason=TEXT,defects=TEXTS,evidence=EVIDENCE))
SCHEMAS['supplement'] = SCHEMAS['verify']
SCHEMAS['diagnose'] = obj(dict(
    action=dict(type='string', enum=['repair', 'verify', 'refine', 'prepare', 'retry', 'revise_evaluator', 'needs_input', 'blocked']),
    binding=obj(dict(candidate_sha=dict(type=['string','null']), contract_sha256=dict(type=['string','null']),
                     acceptance_plan_sha256=TEXT, failure_fingerprint=TEXT)),
    failure_type=dict(type='string',enum=['implementation','environment','evaluator','requirements']),
    confirmed=dict(type='boolean'), affected_checks=TEXTS,
    reason=TEXT, next_action=TEXT, evidence=EVIDENCE))
SCHEMAS['evaluator_repair'] = SCHEMAS['develop']
SCHEMAS['evaluator_review'] = SCHEMAS['maintenance_review']
SCOPE_ROW = obj(dict(criterion_id=TEXT,
    disposition=dict(type='string', enum=['current', 'follow_up', 'unauthorized', 'unclear']),
    execution=dict(type='string', enum=['local', 'product_live', 'remote_ci', 'external_write']),
    source_quote=TEXT, basis=TEXT))
SCHEMAS['scope_review'] = obj(dict(
    draft_sha256=TEXT, decision=dict(type='string', enum=['aligned', 'revise', 'needs_input', 'blocked']),
    # Omissions are review opinions, not contract criteria or permission grants.
    criteria=dict(type='array', items=SCOPE_ROW), omissions=dict(type='array', items=SCOPE_ROW),
    deferred=TEXTS, reason=TEXT))

ROLES = {
    'requirements': '''你是需求对齐者。读取原始 issue、仓库约定和相关现行实现，输出可验证的本次契约。
execution_scope 是本次已确定的执行边界。原issue中的后续批次、关联issue、发布安排不自动成为本次交付条件。
只保留当前目标的必要行为和受影响层本地回归；把下游安排写入non_goals，不扩大真实模型/SDK或外部执行授权。
若提供scope_feedback，只修正指出的需求草稿问题，保留本次原始业务标准，不通过删掉真实需求刷分。
用户已授权采用讨论中的推荐方案，现有明确需求沿用授权，不重复确认。
每个条件使用唯一稳定编号 AC-01 等，并说明实际验证方式；不要凭空要求无关能力。
constraints 只保存产品必须保持的业务、接口或兼容约束。你的只读权限、禁止提交等角色要求不得写进产品契约。
关键需求矛盾或授权缺口输出 needs_input 与具体问题，不猜测、不自行降低标准。
只读，不改文件、不执行产品外部写入，不提交、推送、关闭 issue 或发布。''',
    'develop': '''你是开发者。只实现当前契约及本轮失败条件；先阅读现行代码、约定与复用点。
完成实现、定向自测和冗余检查，记录命令、实际结果和未验证范围；受影响层完整回归由独立验收负责。
不要为了通过测试降低契约、删除失败用例或把跳过当通过。测试需要的固定替身允许正常新增。
你在隔离副本中，主仓库未提交修改不可用；缺少必要配置/依赖如实 blocked。
可修改本次源代码；不得修改本流程的规则/调度器来提高自己的评分。
不得 git commit/push、修改 git 配置、关闭 issue、发消息、发布、使用真实业务外部写入。
候选提交由调度程序保存。修复轮先检查当前文件与原回执，禁止盲目重放先前操作。''',
    'verify': '''你是独立验收者。按当前契约逐项核对指定候选提交，先自己阅读实现再参考已有说明。
你负责独立核对受影响层回归及必要行为/构建证据。controller_test_receipt是控制器在同候选运行的原始回执，需核对绑定、原始输出与实际业务观察；存在该回执时，不重复运行已完成的整套测试或再次尝试同环境已证实受限的命令。缺失或矛盾才定向补验。
优先使用交接包中的差异和验证入口，不重复广泛探索。证据文件保存在环境变量 DEV_CYCLE_EVIDENCE_DIR。
每项 evidence 使用对象 {"path":"证据文件的纯绝对路径","observation":"观察及结论"}；不得把说明或冒号拼进 path。
stdout 的一句“通过”不能代替证据。
只写证据目录及忽略的构建产物，不修改源文件、测试、契约或评分标准。
不能仅用开发者自报/HTTP200/非空响应证明业务完成。缺前置是 environment，判定器矛盾是 evaluator，
需求缺失是 requirements，实现不满足明确条件才是 implementation。未知和条件跳过不能标 pass。
不得 commit/push、调用真实外部写入、关闭 issue、发布或更改流程。输出全部验收条件各一次。
contract_sha256 和 candidate_sha 必须逐字复制本轮提供值。''',
    'supplement': '''你是验收材料补交者，候选与契约均已冻结。这不是新开发轮，也不是重新采样评分。
只修正 gate_errors 指出的格式、条件覆盖或证据缺口，输出完整验收报告；证据 path 与 observation 分开。
保留此前有效条件的原 status 和 failure_type，不把失败/未知改成通过。缺失条件无证据则标 unknown。
优先复用 existing_evidence；只对明确缺失的证据进行最小只读采集，不能重跑已完成的整套验收。
新增证据只写 DEV_CYCLE_EVIDENCE_DIR，不改旧证据、源码、测试、契约或评分器，不提交/推送或外部写入。
不得绕过版本不一致或源码篡改。contract_sha256/candidate_sha 逐字复制提供值。任务共只允许一次补交。''',
    'supervise': '''你是监督者。只读提供的产品契约、验收矩阵、代码差异、证据摘要和程序门禁结果，核对验收是否对应用户要求。
默认直接依据交接包判断；仅发现具体矛盾/缺口时按 evidence_index 中确切路径回查原证据。
禁止重新扫描目录、重复读全部日志、运行测试/构建或重新验收；需要新增证据时 recover 并说明具体缺口。
不得直接修改代码、契约或测试，不修改评分、不增加预算。只能对当前候选和契约给出分流建议。
全部明确条件有真实通过证据才建议 pass；实现问题 revise；需求缺口 needs_input；环境/验收器异常 recover。
evidence 使用 {"path":"证据文件的纯绝对路径","observation":"观察及结论"}，说明不得拼进 path。
修复说明必须可操作，不能只说“再试一次”。
保留原始失败；不得把环境错误、判定器错误当作产品失败后要求开发重写。
contract_sha256 和 candidate_sha 必须逐字复制本轮提供值。''',
    'reflect': '''你是独立反思者。程序自动登记失败观察，未替你总结失败原因。
failure_observations.total 大于0时必须主动观测：使用 observer_command 加 --ids O-编号 批量读取相关原始证据。
优先读取 failed_check 与 revision，或 handoff_rejected/stage_error；每次最多3个观察、6000字节，通常1次，最多3次。
需要更多索引时用 --offset/--limit 分页；内容续读用 --source-offset，命令异常可用 --output-only --tail 直接查看原始输出末段。
读取截断/改变/缺失则保持未知，不得据此断言根因。
根据实际断言、命令退出和原始输出判读失败。verifier的classification是模型分类，不是已证明的因果。
每条因果结论引用实际读取的 O-编号及证据，区分已观察事实、推测和未知。无法证实的外部修改/网络/注入原因不猜测。
无失败观察时默认不使用工具。禁止扫描目录、重读全量任务历史或重复测试。
current_capabilities仅表示已有实现，不代表本轮有效；原始证据显示失效时应提出机制修复，不能只重复能力名称。不能把故障注入直接归因于缺少生产规则。没有可避免的问题就给简短观察和空 proposals/validation_plan。
用事实指出可避免的返工、误判或交接缺口；每个优化建议写清证据与验证办法。
成功任务也可无改进建议；不得为了写反思虚构问题。只提出建议，不修改任何流程规则或产品代码。
禁止继续开发、调用外部写入、提交或发布。''',
}
ROLES['scope_review'] = '''你是现有监督角色在开发前的独立范围审查者，不运行测试、不扫描代码。
只审阅原issue、execution_scope和draft_contract，逐项映射全部验收条件，各一次。
source_quote 必须逐字摘录原issue或execution_scope中的当前目标，不可引用草稿自证。
每项说明是current/follow_up/unauthorized/unclear，及实际执行类别local/product_live/remote_ci/external_write。
关联issue中当前交付必需的规则属于current；后续批次和发布计划不自动阻断本次本地开发。
角色权限与历史回放的读取限制已由execution_scope/role_policy约束，不要求写入产品契约，不因缺少重复权限条款而revise。
只有全部条件属于当前授权且没有遗漏明确需求才能aligned；草稿扩大范围或遗漏真实要求则revise并明确反馈。
真实歧义needs_input，确实必需但当前未授权的执行blocked。deferred记录非阻断的后续事项，不静默删标准。
不得修改草稿或契约，不新增权限或调用预算。draft_sha256逐字复制输入。'''

ROLES['scope_review'] += '''\nverification_plan承载原目标内的验收细化；它与产品契约共同审阅。
已确认契约不必改写措辞：若原目标内的边界/反例已由计划承接，应aligned，不要求再次改产品契约。
criteria只映射草案现有编号各一次。遗漏要求使用omissions逐项保留完整来源、判断及basis，不用额外编号混入criteria。
有未承接的omissions不能aligned；复审必须逐条核对verification_plan中的原始意见与断言，未解决则继续revise。
先读carryover、源码来源、阶段职责属于工作指令，不要求补进产品验收条件。'''

ROLES['diagnose'] = '''你是异常诊断者。只读当前原始报告、来源回执与观察索引，先明确已证实事实及未知部分。
context是当前故障入口。不要因为出现timeout或stream错误就断言网络根因；读取真实错误、触发预算、时间线和进展证据。
普通命令、工具参数、材料读取问题优先在原阶段解决，不新建任务或重置预算。
action: repair修复当前目标内的实现；verify仅在原始证据证明验收器/夹具/材料问题且给出具体修正方法时重新验收；
revise_evaluator用于需要修改已冻结客观验收器的已确认错误；交给隔离作者、冻结正负例校准和独立审查，不要求产品开发者修改判定器。
refine细化原要求的可验证边界而不降低标准；prepare通过控制器标准依赖准备恢复环境；
retry仅用于resume_stage已记录的只读模型进程异常退出，确认原进程结束且原始记录支持重试；不能重放开发或未知业务副作用。
needs_input仅用于确需用户信息/新授权；blocked仅用于无法继续且没有可执行恢复路径。
evidence必须指向当前任务真实存在的原始证据。next_action必须具体，不能只要求同条件重复运行。
binding逐字复制diagnosis_binding，确认当前候选、契约、验收器及本次故障。affected_checks使用正式验收条件ID。
confirmed只表示原始证据已确认原因；未知不能伪装为已确认。只有独立验收已将相关条件明确判为implementation失败时才可repair；客观报告的implementation标签不能单独授权返工。判定争议先verify或revise_evaluator。
environment_capabilities中同环境已记录的限制不要重复探测；优先使用控制器测试回执及已证实可用的入口。
不得改源码、测试、原始证据、契约、任务状态、流程或评分。不得执行外部写入。'''

ROLES['evaluator_repair'] = '''你是验收器修订作者。根据原始争议修复判定器，业务需求、候选与校准控制保持冻结。
只修改当前工作目录内editable_files列出的文件；不得新增/删除文件或修改校准器、源码、旧验收器、旧证据、契约和控制器。
必须保留正确行为通过、错误行为失败的判定强度；不得以返回固定成功、删除断言或改需求解决失败。正负例由控制器执行并交独立审查。
所有过程记录写DEV_CYCLE_EVIDENCE_DIR，输出ready或具体blocked，不提交推送、不调用外部服务。'''
ROLES['evaluator_review'] = '''你是验收器修订的独立审查者。只读原始需求、原始故障、旧新判定器差异及冻结正负例校准原始证据。
确认修订对准已证实的判定/执行问题，且原目标、正确行为、错误关联等负例标准未放宽。校准通过不是充分条件，还需审查语义。
只写审查证据，禁止修改候选、验收器、控制、需求或旧报告，不重跑整套验收。无法证实则revise或blocked，只有证据完整才pass。
证据使用实际绝对路径，不提交推送或外部写入。'''

ROLES['supervise'] += '''\n明确的实现缺陷revise；可由环境准备、验收修正或原需求内细化解决的失败recover，交给内部诊断。
不要把这些可恢复问题直接blocked。真正需要用户信息/授权才needs_input。'''


CURRENT_TARGET_POLICY = '''用户确定的开发策略：只面向当前需求与目标版本，不兼容旧版本。
不新增或维持仅服务旧版本的适配层、旧协议回退、双轨实现、双写或迁移分支。
接口变化同步修改当前调用方、测试与文档，清理本次被替代的旧实现；现存旧代码/旧测试不自动构成兼容需求。
当前需求仍使用的调用链、明确业务行为、权限与用户数据边界继续遵守；不扩大为无关重构或删除。
需求与验收均使用这一策略，不为历史版本增加条件；明确契约若与该策略实质冲突，应指出冲突而非静默降标准。'''
for _stage in ('requirements', 'scope_review', 'develop', 'verify', 'supplement', 'supervise', 'diagnose','evaluator_repair','evaluator_review'):
    ROLES[_stage] = CURRENT_TARGET_POLICY + '\n' + ROLES[_stage]

PROGRESS_POLICY = '''本任务不因阶段耗时自动终止；轮数和CLI调用总数仍受控制器限制。
开发、验收、补交在实现完成、自测完成、长命令前后，将进展原子保存到DEV_CYCLE_EVIDENCE_DIR/progress.json：
{"completed":["具体完成事项"],"current":"当前操作","next":"下一步","blocker":null,"evidence":["本阶段可核对文件的绝对路径"]}。
过程记录只写DEV_CYCLE_EVIDENCE_DIR，不放进候选源码。不要只回复“仍在处理”。
只读阶段通过具体进展消息和既有只读命令反馈，不为写检查点改变只读权限。
在安全节点读取同目录progress-request.json并更新具体成果；当前单次exec不会因这个请求自动插入一条模型消息。
最终仍输出本阶段schema交接，检查点和进程存活均不代表验收通过。
Python测试使用DEV_CYCLE_PYTHON或PATH中的任务Python；不得使用宿主绝对解释器绕过来源校验。
缺少依赖如实报告环境缺口，不回退主工作区的editable安装。
读取UTF-8 JSON证据时使用Python json.load并选择需要的字段，或明确Get-Content -Encoding UTF8。
避免一次打印完整大日志；可按观察ID和字节游标有界续读，截断不代表源文件缺失，不用乱码推断根因。'''
for _stage in ROLES:
    ROLES[_stage] = PROGRESS_POLICY + '\n' + ROLES[_stage]


def check_scope(draft, report, issue, boundary):
    validate('scope_review', report)
    import hashlib
    import json
    expected = hashlib.sha256(json.dumps(draft, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if report['draft_sha256'] != expected:
        raise ValueError('范围审查不属于当前需求草稿')
    ids = [row['criterion_id'] for row in report['criteria']]
    if len(ids) != len(set(ids)) or set(ids) != {row['id'] for row in draft['criteria']}:
        raise ValueError('范围审查必须覆盖全部条件且不得重复')
    omissions = report['omissions']
    all_ids = ids + [row['criterion_id'] for row in omissions]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError('遗漏意见编号不得重复或冒充既有条件')
    def strings(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for v in value.values() for s in strings(v)]
        if isinstance(value, list):
            return [s for v in value for s in strings(v)]
        return []
    original = strings(issue) + [boundary['goal']]
    for row in report['criteria'] + omissions:
        if not row['source_quote'].strip() or not any(row['source_quote'] in source for source in original):
            raise ValueError('范围审查引用不是原始任务中的逐字来源')
    if report['decision'] == 'aligned' and omissions:
        raise ValueError('遗漏意见尚未承接，必须修订后独立复审')
    if report['decision'] == 'aligned' and any(row['disposition'] != 'current' or row['execution'] != 'local' for row in report['criteria']):
        raise ValueError('范围审查试图将后续事项或未授权执行放行为当前需求')


def normalize_scope_review(draft, report, issue, boundary):
    """Losslessly separate extra opinions; never infer mappings or change a decision.

    The raw result remains the controller's evidence. Missing/duplicate original
    criteria, invalid sources and false alignment still fail the regular gate.
    """
    from copy import deepcopy
    validate('scope_review', report)
    required = {row['id'] for row in draft['criteria']}
    normalized = deepcopy(report)
    extra = [row for row in normalized['criteria'] if row['criterion_id'] not in required]
    if extra:
        normalized['criteria'] = [row for row in normalized['criteria'] if row['criterion_id'] in required]
        normalized['omissions'] = normalized['omissions'] + extra
    check_scope(draft, normalized, issue, boundary)
    return normalized


def validate(stage, value):
    Draft202012Validator(SCHEMAS[stage]).validate(value)
    if stage == 'requirements':
        ids = [c['id'] for c in value['criteria']]
        if len(ids) != len(set(ids)):
            raise ValueError('重复验收条件编号')
        if value['status'] == 'ready' and value['questions']:
            raise ValueError('未解决问题不能标记 ready')
        if value['status'] == 'ready' and not ids:
            raise ValueError('ready 必须至少有一条可核对验收条件')
    return value


def verify_binding(contract, contract_hash, candidate, verification):
    validate('verify', verification)
    if verification['contract_sha256'] != contract_hash or verification['candidate_sha'] != candidate:
        raise ValueError('验收证据不属于当前契约/候选提交')
    required = {c['id'] for c in contract['criteria']}
    checks = verification['checks']
    ids = [c['criterion_id'] for c in checks]
    if len(ids) != len(set(ids)) or set(ids) != required:
        raise ValueError('验收条件缺失、重复或包含未知条件')
    failed = sorted(c['criterion_id'] for c in checks if c['status'] != 'pass')
    if any(c['status'] == 'pass' and c['failure_type'] != 'none' for c in checks):
        raise ValueError('通过项不能同时记录故障')
    return failed


def verdict(contract, contract_hash, candidate, verification, supervision):
    """A model recommendation cannot bypass deterministic gates."""
    failed = verify_binding(contract, contract_hash, candidate, verification)
    validate('supervise', supervision)
    if supervision['contract_sha256'] != contract_hash or supervision['candidate_sha'] != candidate:
        raise ValueError('监督结论不属于当前契约/候选提交')
    if set(supervision['failed_criteria']) != set(failed):
        raise ValueError('监督遗漏或增加了失败条件')
    decision = supervision['decision']
    if decision == 'pass':
        if failed or supervision['failure_type'] != 'none':
            raise ValueError('存在未通过条件，拒绝假通过')
        return 'accepted', failed
    kinds = {c['failure_type'] for c in verification['checks'] if c['status'] != 'pass'}
    if decision == 'revise':
        if not failed or kinds != {'implementation'} or supervision['failure_type'] != 'implementation':
            raise ValueError('只允许明确实现缺陷进入自动修复')
        return 'revise', failed
    if decision == 'recover':
        if not failed or not kinds.intersection({'environment', 'evaluator', 'requirements'}):
            raise ValueError('恢复必须对应明确的未通过条件及可恢复分类')
        return 'recover', failed
    return ('needs_input' if decision == 'needs_input' else 'blocked'), failed

ROLES['verification_plan'] = """你是验收计划作者。将source_review全部既有条件和遗漏意见落实成具体输入、执行入口、可观察预期与失败反例，不复制“需要补充”等待办。opinion_id引用原意见编号；criterion_ids只绑定draft_contract已有编号，每条意见一次。保持需求、来源和权限不变，不运行测试、不改源码。逐字复制两个来源哈希；计划将由独立范围审查复核。"""
ROLES['verification_plan'] += "\n收到reflection_followup时，执行其action并核对previous_plans与最新source_review，不重复提交已被拒绝的计划。"
ROLES['maintenance_review'] = """你是未来流程维护的独立审查者。核对原始失败、改动、红绿回归和真实案例比较。只读，不改任何源、证据或评分。确认改动对准流程原因且没有删标准或绕过权限。未完成验证不能pass；用具体证据给出pass/revise/blocked。"""
ROLES['reflect'] += """
proposals必须区分task和workflow。task交develop/verify/verification_plan执行；workflow交maintenance，说明需要改变的调度/协议机制。每条写原始observation_ids、可执行action、expected_result及可复现regression。不能将“补齐本次材料”冒充流程修复，也不能把已有能力当作已证明有效。没有证据时不虚构提案。"""
ROLES['verify'] += """
verification_plan.items.opinion_id仅是审查意见标识，不是评分编号。checks严格只列contract.criteria中的id各一次，将计划项目证据归到绑定的criterion_ids。按实际改动调用链扩展回归，固定模块不是最大范围；测试冲突保留原断言和实际行为，明确区分事实与归因。"""
ROLES['reflect'] += "\n任务提案owner必须属于task_context.allowed_task_owners。已有候选后的夹具、材料与测试执行问题交verify；verification_plan仅负责开发前的范围计划。无可执行任务上下文时只保留工作流提案及未知，不能虚构任务续跑。"
ROLES['develop'] += "\n收到reflection_followup时，先读取其action及task_actions中的实现问题，结合previous核对原始失败；不能只重复旧supervision.next_action。"
ROLES['verify'] += "\n优先核对previous_verification给出的确切报告和证据路径，以及reflection_followup/recovery_context中的待验证事项。旧报告属于旧候选，只能指导本轮，不能直接当作新候选通过证据。不要递归枚举任务目录或python-env；需要源码时只在当前候选中检索，避开环境目录与目录链接。"

ROLES['reflect'] += """优先观测termination_trigger对应的真实终止门禁，再关联较早失败检查；临时探针红测试不自动等于终止原因。gate_facts只是带来源的差异事实，仍需读取原始观察判读原因。"""
ROLES['supervise'] += """\n同时独立评价流程：process_review 与产品 decision 分开。产品通过不能推导流程健康；流程需优化不能单独导致产品 revise/recover。
读取 workflow_quality 中的实际用量、补交、恢复、重复验收和失败观察。只有具体证据支持时标 improve，findings 引用已有 observation_ids，说明机制问题、维护动作、预期收益和固定回归；缺证据标 unknown。已解决的交接拒绝仍可说明流程缺陷。
只在核对具体流程异常时使用 observer_command 读取相关原始观察，不重跑产品测试。重复验收不等于重复完整测试，模型用量缺失不填零，缺同条件对照不宣称节省。
healthy 不包含待改进 findings；improve 至少包含一项。产品通过且流程评估有效时，本报告同时作为结束反思，控制器直接导出维护提案，不再启动第二个反思模型。流程维护面向未来隔离版本，不改本轮规则或业务标准。"""
ROLES['reflect'] += "\nprocess_reviews 是监督对流程的独立评估及其来源；核对关联原始观察后处理已指出的问题，避免因产品最终通过而遗漏。它是模型意见，不是已证明的根因；有效工作流问题生成 maintenance 提案，相同机制合并。"
