"""Process concerns remain visible even when product evidence passes."""
import json
from pathlib import Path
import unittest

from scripts.dev_cycle import Cycle, read
from scripts.dev_cycle_protocol import validate
from tests import test_dev_cycle as fixtures


class ProcessAgents(fixtures.Agents):
    def __init__(self, *, invalid_observation=False):
        super().__init__()
        self.invalid_observation=invalid_observation

    def __call__(self, **kwargs):
        result=super().__call__(**kwargs)
        stage=kwargs['stage']
        packet=self.payloads[-1][1]
        if stage=='verify':
            # A real rejected reference is later repaired by the ordinary supplement.
            result['checks'][0]['evidence'][0]['path']=str(kwargs['cwd']/'missing.txt')
        if stage=='supervise':
            rows=packet['workflow_quality']['failure_observations']['items']
            ident=next(row['id']for row in rows if row['kind']=='handoff_rejected')
            result['process_review']=dict(status='improve',summary='Avoidable evidence handoff repair',findings=[dict(
                observation_ids=['O-not-real']if self.invalid_observation else[ident],
                problem='Valid product needed an evidence-reference repair',action='Validate all references before handoff',
                expected_result='Fewer report supplements',regression='Reject all invalid references together')])
        return result


class ProcessReviewTests(unittest.TestCase):
    setUp=fixtures.DevCycleTests.setUp
    init=fixtures.DevCycleTests.init

    def test_product_pass_and_process_improvement_are_independent(self):
        self.init()
        actor=ProcessAgents()
        state=Cycle(self.task,executor=actor).run()
        self.assertEqual(state['status'],'accepted')
        self.assertEqual(actor.calls.count('develop'),1)
        self.assertEqual(actor.calls.count('supervise'),1)
        self.assertEqual(actor.calls.count('supplement'),1)
        review=state['rounds'][0]['process_review']
        self.assertTrue(review['valid'])
        self.assertEqual(review['report']['status'],'improve')
        supervision=next(p for stage,p,_ in actor.payloads if stage=='supervise')
        self.assertEqual(supervision['workflow_quality']['metrics']['report_supplements'],1)
        self.assertNotIn('reflect',actor.calls)
        self.assertEqual(state['reflection']['source'],'supervise')
        index=read(self.task/state['reflection']['report']/'observation-index.json')
        self.assertIn('workflow_assessment',[row['kind']for row in index['observations']])
        proposals=read(self.task/'improvement-candidates.json')['items']
        self.assertEqual(len(proposals),1)
        self.assertEqual(proposals[0]['origin'],'supervisor')
        self.assertTrue(proposals[0]['evidence_valid'])
        self.assertEqual(read(self.task/'improvement-dispatch.json')['jobs'][0]['status'],'queued')
        raw_reflection=read(self.task/state['reflection']['report']/'result.json')
        self.assertEqual(raw_reflection['process_review'],review['report'])
        before=list(actor.calls)
        repeated=Cycle(self.task,executor=actor).run()
        self.assertEqual(repeated['status'],'accepted')
        self.assertEqual(actor.calls,before)
        self.assertEqual(read(self.task/'improvement-candidates.json')['items'],proposals)

    def test_invalid_process_reference_is_visible_without_product_rework(self):
        self.init()
        state=Cycle(self.task,executor=ProcessAgents(invalid_observation=True)).run()
        self.assertEqual(state['status'],'accepted')
        review=state['rounds'][0]['process_review']
        self.assertFalse(review['valid'])
        self.assertEqual(state['reflection']['source'],'reflect')
        self.assertIn('unknown observations',' '.join(review['errors']))
        self.assertEqual(read(Path(review['path']))['report'],review['report'])
        self.assertEqual(read(self.task/'improvement-candidates.json')['items'],[])

    def test_supervision_requires_separate_process_report(self):
        with self.assertRaises(Exception):
            validate('supervise',dict(contract_sha256='c',candidate_sha='s',decision='pass',failure_type='none',
                failed_criteria=[],evidence=[dict(path='proof',observation='seen')],reason='pass',next_action='finish'))


if __name__=='__main__':unittest.main()
