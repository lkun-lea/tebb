"""Evidence gates only: no model, Git writes, or development cycle execution."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.dev_cycle import Cycle, digest, write
from scripts.dev_cycle_feedback import supplement_delta


class EvidenceBatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=os.environ.get('DEV_CYCLE_EVIDENCE_DIR'))
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        self.verify = self.folder / 'verify'
        self.root = self.verify / 'evidence'
        self.root.mkdir(parents=True)
        self.log = self.root / 'missing.log'
        self.doc = self.root / 'empty.md'
        self.doc.touch()
        self.proof = self.root / 'valid.txt'
        self.proof.write_text('original evidence', encoding='utf-8')
        self.contract = dict(criteria=[dict(id=ident, requirement=ident, verification='read evidence')
                                      for ident in ('AC-LOG', 'AC-DOC')])
        self.report = dict(contract_sha256=digest(self.contract), candidate_sha='candidate',
                           checks=[dict(criterion_id=ident, status='pass', failure_type='none',
                                        evidence=[dict(path=str(path), observation='fixture')])
                                   for ident, path in [('AC-LOG', self.log), ('AC-DOC', self.doc)]],
                           summary='original scores')
        self.report['checks'][1]['evidence'].append(dict(path=str(self.proof), observation='valid'))
        self.cycle = Cycle.__new__(Cycle)
        self.cycle.folder = self.folder
        self.cycle.state = dict(contract=self.contract, contract_sha256=digest(self.contract),
                               candidate_sha='candidate', rounds=[{}], supplements_used=0,
                               attempts=[dict(stage='verify')], pending=0, round=1)
        self.cycle.save = Mock()

    def rejection(self, report=None, roots=None):
        with self.assertRaises(ValueError) as raised:
            self.cycle.gate_verification(report or self.report, roots or [self.root])
        return str(raised.exception)

    def test_all_references_report_reasons_and_criteria_before_supplement(self):
        message = self.rejection()
        self.assertIn(str(self.log), message)
        self.assertIn(str(self.doc), message)
        self.assertIn('AC-LOG', message)
        self.assertIn('AC-DOC', message)
        self.assertIn('文件不存在', message)
        self.assertIn('文件为空', message)
        self.assertNotIn(str(self.proof), message)
        self.cycle.route_supplement(ValueError(message))
        state = self.cycle.state
        self.assertEqual(state['stage'], 'supplement')
        self.assertEqual(state['rounds'][-1]['gate_errors'], [message])
        self.assertEqual(state['attempts'][0]['gate_error'], message)

    def test_fixing_log_still_rejects_document_then_all_fixes_pass(self):
        original = copy.deepcopy(self.report)
        self.rejection()
        self.log.write_text('log repaired', encoding='utf-8')
        message = self.rejection()
        self.assertNotIn(str(self.log), message)
        self.assertIn(str(self.doc), message)
        self.doc.write_text('document repaired', encoding='utf-8')
        self.cycle.gate_verification(self.report, [self.root])
        self.assertEqual(self.report, original)
        self.assertFalse(supplement_delta(self.contract, original, self.report)['valid_score_changes'])

    def prepare_supplement(self, *, fix_document):
        """Exercise the actual supplement branch with only executor/IO boundaries stubbed."""
        state = self.cycle.state
        current = state['rounds'][-1]
        message = self.rejection()
        self.cycle.route_supplement(ValueError(message))
        current.update(verification=self.verify.name, verify_evidence_roots=[str(self.root)])
        write(self.verify / 'result.json', self.report)
        issue, scope, plan = dict(text='fixture'), dict(external_writes=False), None
        state.update(issue_sha256=digest(issue), execution_scope=scope,
                     execution_scope_sha256=digest(scope), acceptance_plan=plan,
                     acceptance_plan_sha256=digest(plan), acceptance_history=[])
        for name, value in [('issue.json', issue), ('execution-scope.json', scope),
                            ('acceptance-initial.json', dict(plan=plan, sha256=digest(plan))),
                            ('contract.json', self.contract)]:
            write(self.folder / name, value)
        record = self.folder / 'supplement'
        new_root = record / 'evidence'
        new_root.mkdir(parents=True)
        log = new_root / 'fixed.log'
        log.write_text('replacement log', encoding='utf-8')
        report = copy.deepcopy(self.report)
        report['checks'][0]['evidence'][0]['path'] = str(log)
        if fix_document:
            doc = new_root / 'fixed.md'
            doc.write_text('replacement document', encoding='utf-8')
            report['checks'][1]['evidence'][0]['path'] = str(doc)
        self.cycle.invoke = Mock(return_value=(report, record))
        self.cycle.payload = Mock(return_value={})
        self.cycle.check_review = Mock()
        self.cycle.after_verification = Mock()
        return report, record, message

    def test_supplement_receives_complete_list_and_rechecks_unfixed_reference(self):
        _, _, message = self.prepare_supplement(fix_document=False)
        with self.assertRaises(ValueError) as raised:
            self.cycle.step('supplement')
        self.assertIn(str(self.doc), str(raised.exception))
        self.assertNotIn(str(self.log), str(raised.exception))
        self.assertEqual(self.cycle.invoke.call_args.args[2]['gate_errors'], [message])
        self.assertEqual(self.cycle.state['supplements_used'], 1)
        self.cycle.after_verification.assert_not_called()

    def test_supplement_all_fixed_passes_without_changing_scores_or_old_evidence(self):
        report, record, _ = self.prepare_supplement(fix_document=True)
        before = self.proof.read_bytes()
        self.cycle.step('supplement')
        self.assertEqual(self.cycle.state['rounds'][-1]['verification'], record.name)
        self.assertEqual(self.proof.read_bytes(), before)
        self.assertEqual(self.doc.stat().st_size, 0)
        self.assertFalse(supplement_delta(self.contract, self.report, report)['valid_score_changes'])
        self.cycle.after_verification.assert_called_once_with()

    def test_supplement_rechecks_all_submitted_references(self):
        self.prepare_supplement(fix_document=True)
        # Replace a previously valid slot: it was absent from the first failure list.
        self.cycle.invoke.return_value[0]['checks'][1]['evidence'][1]['path'] = str(
            self.root / 'new-missing.txt')
        with self.assertRaisesRegex(ValueError, 'new-missing.txt'):
            self.cycle.step('supplement')
        self.cycle.after_verification.assert_not_called()

    def test_supplement_cannot_change_valid_scores(self):
        report, _, _ = self.prepare_supplement(fix_document=True)
        report['checks'][0].update(status='fail', failure_type='implementation')
        with self.assertRaisesRegex(ValueError, '补交改变合法评分'):
            self.cycle.step('supplement')
        self.cycle.after_verification.assert_not_called()

    def test_scope_absolute_directory_and_empty_checks_remain_enforced(self):
        outside = self.folder / 'outside.txt'
        outside.write_text('outside scope', encoding='utf-8')
        directory = self.root / 'directory'
        directory.mkdir()
        names = ['relative.log', str(outside), str(directory), str(self.doc)]
        report = dict(evidence=[dict(path=name, observation='cannot authorize path') for name in names])
        with self.assertRaises(ValueError) as raised:
            self.cycle.evidence(report, self.root)
        message = str(raised.exception)
        for name in names:
            self.assertIn(name, message)
        for reason in ('非绝对路径', '超出允许证据范围', '不是普通文件', '文件为空'):
            self.assertIn(reason, message)
        self.cycle.evidence(dict(evidence=[dict(path=str(outside), observation='sealed receipt')]),
                            self.root, allowed_files={outside.resolve()})
        self.assertIn(str(outside), self.rejection(dict(self.report, checks=[
            dict(c, evidence=[dict(path=str(outside), observation='directory allowlist is insufficient')])
            for c in self.report['checks']]), [self.root]))

    def test_filesystem_error_does_not_hide_later_reference(self):
        original = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == self.log:
                raise OSError('fixture resolution failure')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'resolve', resolve):
            message = self.rejection()
        self.assertIn('fixture resolution failure', message)
        self.assertIn(str(self.doc), message)

    def test_binding_and_missing_checks_still_rejected(self):
        with self.assertRaisesRegex(ValueError, '当前契约/候选'):
            self.cycle.gate_verification(dict(self.report, candidate_sha='wrong'), [self.root])
        with self.assertRaisesRegex(ValueError, '缺失、重复'):
            self.cycle.gate_verification(dict(self.report, checks=self.report['checks'][:1]), [self.root])


if __name__ == '__main__':
    unittest.main()
