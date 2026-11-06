"""Scope recovery and sandbox launch regressions; no real model calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from scripts import dev_cycle as cycle
from scripts import dev_cycle_protocol as protocol
from scripts.dev_cycle_protocol import check_scope
from scripts.dev_cycle_runtime import ProgressMonitor, write_json


# Only source passages used by the gates, the hashed draft and full review.
# The current model format adds an explicit empty omissions array to this data.
PACKET = {'issue': {'text': '- 定位实际日志 URL 与既有工具来源/引用解析链，畸形、不完整或含控制字符的候选必须有界忽略/标注，不可使日志读取、预算进展或独立审阅整体抛异常。\n'
                   '- 日志仍是非可信项目输出，不将普通日志中的链接升级为正文来源、运行成功或源码完整性证明；保留原字节/文本用于诊断，不擅自改原日志。\n'
                   '- 复用现有来源规范化及调用观测接口，不新增Agent或旁路，不降低独立审阅和实际停止验收条件。\n'
                   '\n'
                   '验收：保留原Flask日志中的实际URL反例，覆盖无效IPv6/ANSI控制字符/正常HTTP及合法IPv6、模型日志可读、未知操作不变、独立审阅可继续；完整受影响回归与精确CI。修复后新代码另预定一次有限真实回归，不能重写先前超时/失败。无真实飞书写入，不重放旧unknown创建，不重启daemon、不改冻结0.4.1。',
           'url': 'https://github.com/liukun158959-beep/tebb/issues/208'},
 'draft_contract': {'status': 'ready',
                    'summary': '工具来源解析：畸形日志URL不得使读取与独立审阅异常',
                    'scope': ['真实Flask日志及JSON转义中的有效URL正确提取；畸形IPv6、端口及控制字符不使整体来源和引用审阅异常。',
                              '正常HTTP与合法IPv6仍有效；未知来源别名不能提升未读链接，普通日志不能升级正文证据，原日志保持。',
                              '复用现有来源、调用观测与独立审阅接口，不新增Agent或旁路。'],
                    'non_goals': ['产品live、远端CI与发布'],
                    'constraints': ['只面向当前目标版本；不新增依赖、不降低功能与权限边界。'],
                    'questions': [],
                    'criteria': [{'id': 'AC-01',
                                  'requirement': '真实Flask日志及JSON转义中的有效URL正确提取；畸形IPv6、端口及控制字符不使整体来源和引用审阅异常。',
                                  'verification': '公开业务接口的正反例、实际回执及固定相关模块本地回归：tests.test_web_sources、tests.test_web_snapshots、tests.test_feedback_worker'},
                                 {'id': 'AC-02',
                                  'requirement': '正常HTTP与合法IPv6仍有效；未知来源别名不能提升未读链接，普通日志不能升级正文证据，原日志保持。',
                                  'verification': '公开业务接口的正反例、实际回执及固定相关模块本地回归：tests.test_web_sources、tests.test_web_snapshots、tests.test_feedback_worker'},
                                 {'id': 'AC-03',
                                  'requirement': '复用现有来源、调用观测与独立审阅接口，不新增Agent或旁路。',
                                  'verification': '公开业务接口的正反例、实际回执及固定相关模块本地回归：tests.test_web_sources、tests.test_web_snapshots、tests.test_feedback_worker'}]},
 'execution_scope': {'goal': '实现issue当前功能语义；只做已固定的本地受影响层验收，无产品live或远端写入。'}}
ORIGINAL_REVIEW = {'draft_sha256': 'ffebad9423632447fe567903c422dc1cfe4bd611553d32051ff09890589ce278',
 'decision': 'revise',
 'criteria': [{'criterion_id': 'AC-01',
               'disposition': 'current',
               'execution': 'local',
               'source_quote': '畸形、不完整或含控制字符的候选必须有界忽略/标注',
               'basis': 'URL提取及畸形输入处理属于当前修复；JSON转义与端口反例属于原目标内的验收细化。'},
              {'criterion_id': 'AC-02',
               'disposition': 'current',
               'execution': 'local',
               'source_quote': '日志仍是非可信项目输出，不将普通日志中的链接升级为正文来源、运行成功或源码完整性证明；保留原字节/文本用于诊断，不擅自改原日志。',
               'basis': '正常URL有效性、来源信任边界及原日志保留均在授权范围内；未知来源别名反例可作为边界细化。'},
              {'criterion_id': 'AC-03',
               'disposition': 'current',
               'execution': 'local',
               'source_quote': '复用现有来源规范化及调用观测接口，不新增Agent或旁路，不降低独立审阅和实际停止验收条件。',
               'basis': '复用既有接口且不新增Agent或旁路符合当前要求，固定三个模块的本地回归符合执行范围。'},
              {'criterion_id': 'GAP-01',
               'disposition': 'current',
               'execution': 'local',
               'source_quote': '不可使日志读取、预算进展或独立审阅整体抛异常。',
               'basis': '草稿仅明确来源和引用审阅不异常，未承接日志读取、预算进展及独立审阅可继续的调用链验收；verification_plan为空。'},
              {'criterion_id': 'GAP-02',
               'disposition': 'current',
               'execution': 'local',
               'source_quote': '保留原Flask日志中的实际URL反例',
               'basis': '草稿提到真实Flask日志，但未明确保留并覆盖原日志中的实际URL反例；泛化有效URL提取不足以承接该要求。'},
              {'criterion_id': 'GAP-03',
               'disposition': 'current',
               'execution': 'local',
               'source_quote': '未知操作不变',
               'basis': '该明确验收要求未被承接；未知来源别名不能提升未读链接不等同于未知操作行为不变。'}],
 'deferred': ['远端精确CI属于后续执行，不阻断本轮本地交付。', '修复后的有限真实回归、实机SDK与产品真实模型验收属于后续；先前超时或失败记录不得改写。', '发布属于后续，不作为本轮门槛。'],
 'reason': '草稿范围均属当前授权，但遗漏明确验收要求。请在契约或verification_plan中补齐日志可读与预算进展、独立审阅继续、原Flask实际URL反例及未知操作不变；无需前移后续真实或远端验收。',
 'omissions': []}


class ScopeRecoveryTests(unittest.TestCase):
    def setUp(self):
        evidence = os.environ.get('DEV_CYCLE_EVIDENCE_DIR')
        self.temp = tempfile.TemporaryDirectory(dir=evidence)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.task = self.root / 'task'
        self.packet = deepcopy(PACKET)
        self.original = deepcopy(ORIGINAL_REVIEW)
        self.draft = deepcopy(self.packet['draft_contract'])
        self.calls = []
        self.payloads = []
        # Substitute only filesystem/Git transport. All gates and transitions run normally.
        def git(repo, *args):
            return str(self.repo) if args == ('rev-parse', '--show-toplevel') else 'candidate' if args == ('rev-parse', 'HEAD') else ''
        def clone(source, destination, sha):
            destination.mkdir()
        for name, replacement in [('git', git), ('clone', clone), ('worktree_fingerprint', lambda _: 'unchanged')]:
            mock = patch.object(cycle, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(cycle.Cycle, 'snapshot', return_value='candidate')
        mock.start()
        self.addCleanup(mock.stop)
        self.second_report = None

    def initialize(self, confirmed=True, launches=12):
        self.calls.clear()
        self.payloads.clear()
        return cycle.initialize(self.repo, self.task, self.packet['issue'],
            purpose='historical_replay', goal=self.packet['execution_scope']['goal'], launches=launches,
            confirmed_contract=self.draft if confirmed else None)

    def executor(self, *, stage, record, **kwargs):
        self.calls.append(stage)
        payload = cycle.read(record / 'packet.json')
        self.payloads.append((stage, payload))
        (record / 'events.jsonl').write_text(json.dumps(dict(type='thread.started', thread_id='fixture')) + '\n' +
            json.dumps(dict(type='turn.completed', usage=dict(input_tokens=10, output_tokens=2))), 'utf-8')
        if stage == 'requirements':
            return deepcopy(self.draft)
        if stage == 'scope_review':
            if self.calls.count(stage) == 1:
                return deepcopy(self.original)
            if self.second_report is not None:
                return deepcopy(self.second_report)
            return dict(draft_sha256=payload['draft_sha256'], decision='aligned',
                criteria=deepcopy(self.original['criteria'][:3]), omissions=[], deferred=deepcopy(self.original['deferred']), reason='Plan carries all original opinions')
        if stage == 'verification_plan':
            rows=payload['source_review']['criteria']+payload['source_review']['omissions']
            return dict(draft_sha256=payload['draft_sha256'],source_review_sha256=payload['source_review_sha256'],
                items=[dict(opinion_id=r['criterion_id'],criterion_ids=['AC-01'],input='invalid URL',entry='extract URL',expected='bounded rejection',negative_case='never promote log evidence')for r in rows])
        if stage == 'develop':
            return dict(status='ready', summary='substitute', changes=['substitute'], tests=['substitute'], limitations=[])
        if stage == 'verify':
            proof = record / 'evidence' / 'proof.txt'
            proof.parent.mkdir()
            proof.write_text('substitute evidence', 'utf-8')
            return dict(contract_sha256=payload['contract_sha256'], candidate_sha=payload['candidate_sha'], summary='substitute',
                checks=[dict(criterion_id=c['id'], status='pass', failure_type='none',
                    evidence=[dict(path=str(proof), observation='substitute')]) for c in payload['contract']['criteria']])
        if stage == 'supervise':
            return dict(contract_sha256=payload['contract_sha256'], candidate_sha=payload['candidate_sha'],
                decision='pass', failure_type='none', failed_criteria=[], evidence=payload['verification']['checks'][0]['evidence'],
                reason='substitute', next_action='reflect',process_review=dict(status='healthy',summary='fixture process',findings=[]))
        if stage == 'reflect':
            return dict(observations=[], proposals=[], validation_plan=[])
        self.fail('Unexpected stage ' + stage)

    def step(self):
        return cycle.Cycle(self.task, self.executor).run(one_stage=True)

    def test_original_fixture_reaches_development_only_after_independent_rereview(self):
        self.initialize()
        state = self.step()
        self.assertEqual(state['stage'], 'verification_plan', state)
        self.assertEqual(state['scope_revisions'], 1)
        self.assertEqual(state['round'], 0)
        self.assertEqual(state['launches'], 1)
        self.assertEqual(cycle.read(self.task / 'attempt-01-scope_review' / 'result.json'), self.original)
        normalized = cycle.read(self.task / 'attempt-01-scope_review' / 'normalized-scope.json')
        self.assertEqual(normalized['decision'], 'revise')
        self.assertEqual(normalized['criteria'], self.original['criteria'][:3])
        self.assertEqual(normalized['omissions'], self.original['criteria'][3:])
        self.assertEqual(normalized['reason'], self.original['reason'])
        self.assertEqual(normalized['deferred'], self.original['deferred'])
        check_scope(self.draft, normalized, self.packet['issue'], self.packet['execution_scope'])
        self.assertEqual(state['verification_plan'], [])
        self.assertEqual(state['plan_review'], normalized)
        state=self.step()
        self.assertEqual(state['stage'],'scope_review')
        plan=state['verification_plan'][0]
        self.assertEqual(plan['source_review_sha256'],cycle.digest(normalized))
        self.assertEqual({i['opinion_id']for i in plan['items']},{c['criterion_id']for c in self.original['criteria']})
        checkpoint = cycle.read(self.task / 'state.json')
        self.assertIsNone(checkpoint['pending'])
        state = self.step()  # New controller instance; same task and shared budget.
        self.assertEqual(state['stage'], 'develop', state)
        self.assertEqual(state['contract'], self.draft)
        self.assertEqual(state['contract_sha256'], cycle.digest(self.draft))
        self.assertEqual(cycle.read(self.task / 'draft-contract-0.json'), self.draft)
        self.assertEqual(state['launches'], 3)
        self.assertEqual(self.calls, ['scope_review', 'verification_plan', 'scope_review'])
        # This fixture substitutes Git transport; success now exports within supervise.
        with patch.object(cycle.subprocess,'check_output',return_value=b'fixture diff') as export:
            for _ in range(3):
                state = self.step()
        export.assert_called_once_with(['git','-C',str(self.task/'work'),'diff','--binary','candidate','candidate'],timeout=120)
        self.assertEqual((self.task/'accepted.patch').read_bytes(),b'fixture diff')
        self.assertEqual(state['pending_outcome'], 'accepted', state)
        for stage, payload in self.payloads:
            if stage in {'scope_review', 'develop', 'verify', 'supervise'} and payload.get('verification_plan'):
                self.assertEqual(payload['verification_plan'], state['verification_plan'])
        self.assertEqual(state['round'], 1)
        self.assertEqual(state['launches'], 6)

    def test_unconfirmed_draft_uses_same_lossless_recovery(self):
        self.initialize(confirmed=False)
        self.step()
        state = self.step()
        self.assertEqual(state['stage'], 'verification_plan', state)
        self.step()
        state = self.step()
        self.assertEqual(state['stage'], 'develop', state)
        self.assertEqual(self.calls, ['requirements', 'scope_review', 'verification_plan', 'scope_review'])
        self.assertEqual(state['contract'], self.draft)

    def test_arbitrary_additional_opinions_are_all_preserved(self):
        extra = deepcopy(self.original['criteria'][-1])
        extra.update(criterion_id='boundary-note/arbitrary', basis='Another complete independent opinion')
        self.original['criteria'].append(extra)
        self.initialize()
        state = self.step()
        self.assertEqual(state['stage'], 'verification_plan', state)
        self.assertEqual(state['plan_review']['criteria']+state['plan_review']['omissions'],self.original['criteria'])
        state=self.step()
        self.assertEqual(state['verification_plan'][0]['items'][-1]['opinion_id'],extra['criterion_id'])

    def test_structured_omissions_keep_all_opinions_and_reject_collisions(self):
        self.original['omissions'] = self.original['criteria'][3:]
        self.original['criteria'] = self.original['criteria'][:3]
        self.initialize()
        state = self.step()
        self.assertEqual(state['stage'], 'verification_plan', state)
        self.assertEqual(state['plan_review'],self.original)
        state=self.step()
        self.assertEqual(len(state['verification_plan'][0]['items']),6)
        for collision in (self.original['criteria'][0], self.original['omissions'][0]):
            bad = deepcopy(self.original)
            bad['omissions'].append(deepcopy(collision))
            with self.assertRaises(ValueError):
                protocol.normalize_scope_review(self.draft, bad, self.packet['issue'], self.packet['execution_scope'])

    def test_normalization_is_lossless_idempotent_and_never_loosens_strict_gate(self):
        raw = deepcopy(self.original)
        with self.assertRaisesRegex(ValueError, '覆盖全部条件'):
            check_scope(self.draft, raw, self.packet['issue'], self.packet['execution_scope'])
        normalized = protocol.normalize_scope_review(self.draft, raw, self.packet['issue'], self.packet['execution_scope'])
        self.assertEqual(raw, self.original)
        self.assertEqual(protocol.normalize_scope_review(self.draft, normalized, self.packet['issue'], self.packet['execution_scope']), normalized)
        for key in ('draft_sha256', 'decision', 'deferred', 'reason'):
            self.assertEqual(normalized[key], raw[key])

    def test_unknown_fields_and_unresolved_decisions_are_not_silently_dropped(self):
        for mode in ('unknown_field', 'needs_input', 'blocked'):
            with self.subTest(mode=mode):
                self.task = self.root / mode
                self.initialize()
                raw = deepcopy(self.original)
                if mode == 'unknown_field':
                    raw['criteria'][-1]['additional_opinion'] = 'Must not be dropped'
                else:
                    raw['decision'] = mode
                self.original, previous = raw, self.original
                state = self.step()
                self.original = previous
                self.assertEqual(state['status'], 'needs_input' if mode == 'needs_input' else 'blocked')
                self.assertFalse(state['verification_plan'])
                self.assertNotIn('develop', self.calls)

    def test_readonly_source_mutation_is_not_recovered(self):
        self.initialize()
        with patch.object(cycle, 'worktree_fingerprint', side_effect=['before', 'before', 'after']):
            state = self.step()
        self.assertEqual(state['status'], 'blocked', state)
        self.assertIn('修改了源码', state['reason'])
        self.assertFalse(state['verification_plan'])

    def test_duplicate_or_missing_original_and_duplicate_extra_are_rejected(self):
        for mode in ('missing', 'duplicate', 'duplicate_extra'):
            with self.subTest(mode=mode):
                report = deepcopy(self.original)
                if mode == 'missing':
                    report['criteria'].pop(0)
                else:
                    report['criteria'].append(deepcopy(report['criteria'][0 if mode == 'duplicate' else -1]))
                self.task = self.root / mode
                self.initialize()
                self.original, previous = report, self.original
                state = self.step()
                self.original = previous
                self.assertEqual(state['status'], 'blocked')
                self.assertFalse(state['verification_plan'])
                self.assertNotIn('develop', self.calls)

    def test_forged_extra_quote_and_wrong_draft_hash_are_rejected(self):
        for mode in ('quote', 'hash', 'joined_source'):
            with self.subTest(mode=mode):
                report = deepcopy(self.original)
                if mode == 'hash':
                    report['draft_sha256'] = 'forged'
                else:
                    report['criteria'][-1]['source_quote'] = ('not present in original' if mode == 'quote' else
                        self.packet['issue']['url'] + '\n' + self.packet['execution_scope']['goal'])
                self.task = self.root / mode
                self.initialize()
                self.original, previous = report, self.original
                state = self.step()
                self.original = previous
                self.assertEqual(state['status'], 'blocked')
                self.assertFalse(state['verification_plan'])

    def test_unauthorized_unclear_or_downstream_extras_never_enter_automatic_plan(self):
        for disposition, execution in [('unauthorized', 'local'), ('unclear', 'local'), ('follow_up', 'product_live'), ('current', 'external_write')]:
            with self.subTest(disposition=disposition, execution=execution):
                self.task = self.root / (disposition + execution)
                self.initialize()
                self.original['criteria'][-1].update(disposition=disposition, execution=execution)
                state = self.step()
                self.assertEqual(state['status'], 'blocked', state)
                self.assertFalse(state['verification_plan'])
                self.assertNotIn('develop', self.calls)
                self.assertEqual(cycle.read(self.task / 'attempt-01-scope_review' / 'result.json'), self.original)

    def test_aligned_with_extra_opinions_cannot_bypass_rereview(self):
        self.original['decision'] = 'aligned'
        self.initialize()
        state = self.step()
        self.assertEqual(state['status'], 'blocked')
        self.assertNotIn('develop', self.calls)

    def test_repeated_revise_is_bounded_and_does_not_duplicate_plan(self):
        self.initialize()
        state = self.step()
        self.assertEqual(state['stage'], 'verification_plan', state)
        self.second_report = deepcopy(self.original)
        self.step()
        state = self.step()
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(len(state['verification_plan']), 1)
        self.assertEqual(state['launches'], 3)
        self.assertNotIn('develop', self.calls)

    def test_recovery_shares_cli_budget_and_reserves_reflection(self):
        self.initialize(launches=5)
        for _ in range(5):
            state = self.step()
        self.assertEqual(state['status'], 'exhausted', state)
        self.assertEqual(state['launches'], 5)
        self.assertEqual(self.calls, ['scope_review', 'verification_plan', 'scope_review', 'develop', 'reflect'])

    def test_new_version_and_old_records_remain_byte_identical(self):
        state = self.initialize()
        self.assertEqual(state['version'], cycle.VERSION)
        active = cycle.Cycle(self.task, self.executor)
        for version in range(1, cycle.VERSION):
            state['version'] = version
            cycle.write(self.task / 'state.json', state)
            before = {p: p.read_bytes() for p in self.task.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ValueError, '历史任务只读'):
                cycle.Cycle(self.task, self.executor)
            with self.assertRaisesRegex(ValueError, '历史任务只读'):
                cycle.recover(self.task, acknowledge=True)
            with self.assertRaisesRegex(ValueError, '历史任务只读'):
                active.run(one_stage=True)
            with patch.object(sys, 'argv', ['dev_cycle', 'prepare', str(self.task), '--offline']):
                self.assertEqual(cycle.main(), 2)
            with patch.object(sys, 'argv', ['dev_cycle', 'cancel', str(self.task)]):
                self.assertEqual(cycle.main(), 2)
            self.assertEqual({p: p.read_bytes() for p in self.task.rglob('*') if p.is_file()}, before)


class RecoveryLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('DEV_CYCLE_EVIDENCE_DIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_all_model_schemas_are_strict_and_omissions_are_required(self):
        def strict(schema):
            self.assertIn('type', schema)
            if schema['type'] == 'object':
                self.assertIs(schema['additionalProperties'], False)
                self.assertCountEqual(schema['required'], schema['properties'])
                for child in schema['properties'].values():
                    strict(child)
            elif schema['type'] == 'array':
                strict(schema['items'])
        for stage, schema in protocol.SCHEMAS.items():
            with self.subTest(stage=stage):
                strict(schema)
        missing = deepcopy(ORIGINAL_REVIEW)
        del missing['omissions']
        with self.assertRaises(cycle.ValidationError):
            protocol.validate('scope_review', missing)

    def test_each_stage_keeps_its_sandbox_and_only_current_evidence_root(self):
        source = self.root / 'isolated source'
        source.mkdir()
        task = self.root / 'task'
        task.mkdir()
        (task/'work').mkdir()
        script = self.root / 'capture_cli.py'
        script.write_text('''import json, pathlib, sys
sys.stdin.read()
args = sys.argv[1:]
pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps(args), encoding='utf-8')
''', 'utf-8')
        adapter = cycle.Codex(sys.executable, [str(script)])
        writable = {'develop', 'verify', 'supplement', 'evaluator_repair'}
        for stage in protocol.SCHEMAS:
            with self.subTest(stage=stage):
                record = task / stage
                record.mkdir()
                cwd=source
                if stage=='evaluator_repair':
                    cwd=task/'oracle-draft';cwd.mkdir()
                args = adapter(stage=stage, prompt='fixture', cwd=cwd, record=record, session=None,
                               task_folder=task, started=lambda *_: None, check_seconds=.1)
                self.assertEqual(args[args.index('--sandbox')+1],
                                 'workspace-write' if stage in writable else 'read-only')
                settings = dict(args[i+1].split('=', 1) for i, arg in enumerate(args) if arg == '-c')
                if stage in writable:
                    evidence = (task/'development-artifacts'/stage if stage == 'develop' else record/'evidence').resolve()
                    self.assertEqual(tomllib.loads('v='+settings['sandbox_workspace_write.writable_roots'])['v'],
                                     [str(evidence)])
                    self.assertEqual(settings['sandbox_workspace_write.network_access'], 'false')
                    if stage=='evaluator_repair':
                        self.assertEqual(json.loads(settings['shell_environment_policy.set.DEV_CYCLE_SOURCE_ROOT']),str((task/'work').resolve()))
                else:
                    self.assertNotIn('sandbox_workspace_write.writable_roots', settings)
                    self.assertNotIn('sandbox_mode', settings)
                self.assertNotIn('--add-dir', args)
                self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
                self.assertEqual(cycle.read(record/'schema.json'), protocol.SCHEMAS[stage])

    def test_new_and_resumed_turns_write_current_evidence_progress_and_source_audit(self):
        task = self.root / 'task with spaces'
        source = task / 'work'
        source.mkdir(parents=True)
        (source / 'candidate.py').write_text('VALUE = 6\n', 'utf-8')
        script = self.root / 'fake_cli.py'
        script.write_text('''import json, os, pathlib, subprocess, sys, tomllib
args = sys.argv[1:]
sys.stdin.read()
settings = {}
for i, arg in enumerate(args):
    if arg == '-c':
        key, value = args[i+1].split('=', 1)
        settings[key] = tomllib.loads('value='+value)['value']
# Emulate the observed CLI: resumed turns do not inherit additional roots.
roots = [pathlib.Path.cwd()]
roots.extend(pathlib.Path(p) for p in settings.get('sandbox_workspace_write.writable_roots', []))
if '--add-dir' in args:
    roots.append(pathlib.Path(args[args.index('--add-dir')+1]))
evidence = pathlib.Path(os.environ['DEV_CYCLE_EVIDENCE_DIR'])
audit = pathlib.Path(os.environ['DEV_CYCLE_IMPORT_LOG'])
for path in (evidence, audit):
    if not any(path == root or root in path.parents for root in roots):
        raise PermissionError('resumed evidence root missing: '+str(path))
assert settings.get('sandbox_mode', 'workspace-write') == 'workspace-write'
probe = subprocess.run([os.environ['DEV_CYCLE_PYTHON'], '-c', 'import candidate; assert candidate.VALUE == 6'],
                       capture_output=True, text=True)
if probe.returncode:
    raise RuntimeError(probe.stderr)
(evidence/'check.txt').write_text('candidate import passed', encoding='utf-8')
checkpoint = evidence/'progress.json.tmp'
checkpoint.write_text(json.dumps({'completed':['candidate import'], 'current':'handoff', 'next':'verify',
                                  'blocker':None, 'evidence':[str(evidence/'check.txt')]}), encoding='utf-8')
os.replace(checkpoint, evidence/'progress.json')
output = pathlib.Path(args[args.index('-o')+1])
output.write_text(json.dumps({'argv':args, 'evidence_dir':str(evidence), 'audit':str(audit)}), encoding='utf-8')
print(json.dumps({'type':'thread.started', 'thread_id':'same-developer'}), flush=True)
''', 'utf-8')
        adapter = cycle.Codex(sys.executable, [str(script)])
        snapshots = {}
        for turn, session in enumerate((None, 'same-developer'), 1):
            record = task / f'attempt-{turn:02d}-develop'
            record.mkdir()
            try:
                result = adapter(stage='develop', prompt='fixture', cwd=source, record=record, session=session,
                                 task_folder=task, started=lambda *_: None, check_seconds=.1, silence_seconds=2)
            except RuntimeError as exc:
                # Keep a simulated permission failure readable after temp cleanup.
                raise RuntimeError((record/'stderr.log').read_text('utf-8')) from exc
            args = result['argv']
            settings = dict(args[i+1].split('=', 1) for i, arg in enumerate(args) if arg == '-c')
            evidence = Path(result['evidence_dir'])
            if session:
                self.assertEqual(tomllib.loads('v='+settings['sandbox_mode'])['v'], 'workspace-write')
                self.assertEqual(tomllib.loads('v='+settings['sandbox_workspace_write.writable_roots'])['v'],
                                 [str(evidence.resolve())])
                self.assertEqual(settings['sandbox_workspace_write.network_access'], 'false')
                self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
                self.assertNotIn('--add-dir', args)
                self.assertEqual(args[:3], ['exec', 'resume', session])
                self.assertNotIn('--sandbox', args)
            self.assertEqual(cycle.read(evidence/'progress.json')['completed'], ['candidate import'])
            self.assertEqual((evidence/'check.txt').read_text('utf-8'), 'candidate import passed')
            rows = [json.loads(line) for p in Path(result['audit']).glob('*.jsonl') for line in p.read_text('utf-8').splitlines()]
            self.assertTrue(any(row['module'] == 'candidate' and row['allowed'] is True and
                                row['checkout'] == str(source.resolve()) for row in rows))
            self.assertTrue(all(p.read_bytes() == data for p, data in snapshots.items()))
            snapshots.update({p: p.read_bytes() for p in evidence.rglob('*') if p.is_file()})


class ProgressEvidenceRootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('DEV_CYCLE_EVIDENCE_DIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.task = self.root / 'task with spaces'
        self.source = self.task / 'work'
        self.source.mkdir(parents=True)
        self.record = self.task / 'attempt-02-develop'
        self.record.mkdir()
        self.evidence = self.task / 'development-artifacts' / self.record.name
        self.evidence.mkdir(parents=True)
        self.monitor = ProgressMonitor(self.record, self.source, 0, 0, task_folder=self.task)
        # Same assignment as Codex.__call__, outside the stage record and source.
        self.monitor.evidence_dir = self.evidence
        self.monitor.started = self.monitor.last_feedback = 100
        self.checkpoint = dict(completed=['probe ran'], current='handoff', next='verify',
                               blocker=None, evidence=[])

    def checkpoint_for(self, proof, now):
        self.checkpoint['evidence'] = [str(proof)]
        write_json(self.evidence / 'progress.json', self.checkpoint)
        return self.monitor.checkpoint(now)

    def test_current_artifact_is_verified_but_claims_and_timestamps_are_not_progress(self):
        proof = self.evidence / 'proof.json'
        proof.write_text('{"turn":2,"value":"v6-resume-proof"}', 'utf-8')
        result = self.checkpoint_for(proof, 101)
        self.assertTrue(result['verified'], result)
        self.assertEqual(result['evidence'][0]['path'], str(proof.resolve()))
        self.assertEqual(self.monitor.last_progress, 101)
        self.checkpoint.update(completed=['another claim'], current='still working', timestamp=200)
        stat = proof.stat()
        os.utime(proof, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
        repeated = self.checkpoint_for(proof, 102)
        self.assertEqual(repeated['evidence'], result['evidence'])
        self.assertEqual(self.monitor.last_progress, 101)
        self.assertEqual(self.monitor.last_feedback, 101)
        proof.write_text('{"turn":2,"value":"new actual output"}', 'utf-8')
        changed = self.checkpoint_for(proof, 103)
        self.assertNotEqual(changed['evidence'], result['evidence'])
        self.assertEqual(self.monitor.last_progress, 103)

    def test_other_rounds_tasks_missing_files_and_claims_are_rejected(self):
        forbidden = [
            self.task / 'development-artifacts' / 'attempt-01-develop' / 'proof.json',
            self.task / 'development-artifacts' / (self.record.name + '-other') / 'proof.json',
            self.task / 'attempt-01-develop' / 'evidence' / 'proof.json',
            self.root / 'other-task' / 'development-artifacts' / self.record.name / 'proof.json',
            self.task / 'state-sentinel.json',
        ]
        for path in forbidden:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('existing but outside current roots', 'utf-8')
        snapshots = {path: path.read_bytes() for path in forbidden}
        # Resolve traversal before containment; neither directory is a file.
        forbidden += [self.evidence / '..' / 'attempt-01-develop' / 'proof.json',
                      self.evidence / 'missing.json', self.evidence, self.evidence / 'nested']
        forbidden[-1].mkdir()
        for path in forbidden:
            with self.subTest(path=path):
                result = self.checkpoint_for(path, 101)
                self.assertFalse(result['verified'], result)
                self.assertIn('error', result)
                self.assertIsNone(self.monitor.last_progress)
                self.assertEqual(self.monitor.last_feedback, 100)
        self.checkpoint['evidence'] = []
        write_json(self.evidence / 'progress.json', self.checkpoint)
        self.assertFalse(self.monitor.checkpoint(102)['verified'])
        self.assertIsNone(self.monitor.last_progress)
        self.assertEqual(self.monitor.last_feedback, 100)
        self.assertEqual({path: path.read_bytes() for path in snapshots}, snapshots)


if __name__ == '__main__':
    unittest.main()
