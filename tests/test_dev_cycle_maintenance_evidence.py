"""Exact pre-review trust manifests for the path categories observed in #216."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import dev_cycle_improvement as improvement
from scripts import dev_cycle as cycle
from tests import test_dev_cycle_v7 as fixtures


class EvidenceManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.snapshot=self.root/'maintenance/job/review-1';self.validation=self.root/'maintenance/job/validation-1'
        self.developer=self.root/'maintenance/job/attempt-01-develop';self.developer.mkdir(parents=True)
        def file(name):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('original evidence','utf-8');return path
        self.code=file('maintenance/job/review-1/scripts/dev_cycle.py')
        self.result=file('maintenance/job/validation-1/regression/result.json')
        self.proposal=file('intake/attempt-06-reflect/observation-index.json')
        self.artifact=file('maintenance/job/development-artifacts/attempt-01-develop/evidence-index.json')
        self.history=file('r1/intake/improvement-jobs/job.json')
        self.sibling=file('intake/attempt-06-reflect/unapproved.json')
        self.job=dict(proposal=dict(evidence_index=[self.ref(self.proposal)]));self.policy={}

    def ref(self,path):return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def manifest(self):return improvement.review_evidence_manifest(self.job,self.policy,self.snapshot,self.validation,self.developer)
    def review(self,*paths):return dict(evidence=[dict(path=str(path),observation='read original')for path in paths])

    def test_proposal_and_developer_original_paths_are_precisely_allowed(self):
        manifest=self.manifest()
        improvement.check_review_evidence(self.review(self.proposal,self.artifact,self.code,self.result),manifest)
        self.assertNotIn(str(self.history),manifest['allowed_files'])
        self.assertNotIn(str(self.sibling),manifest['allowed_files'])

    def test_unlisted_historical_and_sibling_paths_rejected(self):
        self.job['proposal']['action']='May read history '+str(self.history)
        manifest=self.manifest()
        for path in [self.history,self.sibling]:
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'未预封存'):improvement.check_review_evidence(self.review(path),manifest)

    def test_proposal_and_developer_tampering_rejected(self):
        for path in [self.proposal,self.artifact]:
            manifest=self.manifest();old=path.read_bytes();path.write_text('tampered','utf-8')
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'哈希改变'):improvement.check_review_evidence(self.review(path),manifest)
            path.write_bytes(old)

    def test_candidate_file_added_after_review_seal_rejected(self):
        manifest=self.manifest();late=self.snapshot/'new.txt';late.write_text('late','utf-8')
        with self.assertRaisesRegex(ValueError,'未预封存'):improvement.check_review_evidence(self.review(late),manifest)

    def test_explicit_historical_hash_is_required_and_preserved(self):
        self.policy['historical_evidence']=[self.ref(self.history)];manifest=self.manifest()
        improvement.check_review_evidence(self.review(self.history),manifest)
        self.history.write_text('altered history','utf-8')
        with self.assertRaisesRegex(ValueError,'哈希改变'):improvement.check_review_evidence(self.review(self.history),manifest)

    def test_all_failures_report_paths_and_reasons_before_partial_repair(self):
        manifest=self.manifest();original=self.artifact.read_bytes();self.artifact.write_bytes(b'');self.proposal.unlink()
        report=self.review(self.artifact,self.proposal,self.history)
        with self.assertRaises(ValueError)as rejected:improvement.check_review_evidence(report,manifest)
        errors=json.loads(str(rejected.exception).split('：',1)[1])
        self.assertIn(dict(path=str(self.artifact),reason='空文件'),errors)
        self.assertIn(dict(path=str(self.proposal),reason='不存在'),errors)
        self.assertIn(dict(path=str(self.history),reason='未预封存'),errors)
        self.artifact.write_bytes(original)
        with self.assertRaises(ValueError)as remaining:improvement.check_review_evidence(report,manifest)
        errors=json.loads(str(remaining.exception).split('：',1)[1]);self.assertFalse(any(e['path']==str(self.artifact)for e in errors))
        self.assertTrue(any(e['path']==str(self.proposal)for e in errors))
        self.proposal.write_text('original evidence','utf-8')
        improvement.check_review_evidence(self.review(self.artifact,self.proposal),manifest)


class EvidenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.MaintenanceTests('test_no_evidence_never_launches_maintenance')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def actor(self,**kw):
        result=self.fixture.actor(**kw)
        if kw['stage']=='develop':
            artifact=kw['record'].parent/'development-artifacts'/kw['record'].name/'evidence-index.json'
            artifact.parent.mkdir(parents=True,exist_ok=True)
            cycle.write(artifact,dict(original=True));self.artifact=artifact
        else:
            packet=json.loads(kw['prompt'].split('\n')[-1]);self.packet=packet
            allowed={entry['path']for entry in packet['allowed_evidence']}
            self.assertIn(str(self.fixture.raw),allowed);self.assertIn(str(self.artifact),allowed)
            result['evidence'] += [dict(path=str(self.fixture.raw),observation='proposal original'),dict(path=str(self.artifact),observation='developer original')]
        return result

    def test_real_execution_adopts_with_sealed_proposal_and_developer_evidence(self):
        f=self.fixture;out=improvement.dispatch(f.task,f.policy,self.actor)
        self.assertEqual(out[0]['status'],'adopted',out)
        adopted=cycle.read(Path(out[0]['path']))['release']
        self.assertIn(str(f.raw),adopted['evidence_seal']);self.assertIn(str(self.artifact),adopted['evidence_seal'])
        self.artifact.write_text('later tampering','utf-8')
        with self.assertRaisesRegex(ValueError,'审查证据变化'):improvement.selected_release(f.policy)

    def test_manifest_tampering_cannot_adopt(self):
        f=self.fixture
        def actor(**kw):
            result=self.actor(**kw)
            if kw['stage']=='maintenance_review':Path(self.packet['evidence_manifest']).write_text('{}','utf-8')
            return result
        out=improvement.dispatch(f.task,f.policy,actor)
        self.assertIn('maintenance_review',f.calls)
        self.assertEqual(out[0]['status'],'blocked');self.assertFalse((Path(f.policy['root'])/'active-release.json').exists())

    def test_unsealed_review_reference_cannot_adopt(self):
        f=self.fixture;unlisted=f.root/'historical-job.json';unlisted.write_text('{}','utf-8')
        def actor(**kw):
            result=self.actor(**kw)
            if kw['stage']=='maintenance_review':result['evidence'].append(dict(path=str(unlisted),observation='not pre-authorized'))
            return result
        out=improvement.dispatch(f.task,f.policy,actor)
        self.assertIn('maintenance_review',f.calls)
        self.assertEqual(out[0]['status'],'blocked');self.assertFalse((Path(f.policy['root'])/'active-release.json').exists())


if __name__=='__main__':unittest.main()
