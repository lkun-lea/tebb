import os
import sys
import unittest
from argparse import Namespace
from unittest.mock import patch

from desk_companion.bridge import Bridge
from desk_companion.local_api.server import RPC_METHODS
from scripts import dev_cycle as cycle
from scripts.dev_cycle_acceptance import fingerprint
from scripts.dev_team import create, register
from tests import test_dev_cycle as fixtures


class DevelopmentPairTests(unittest.TestCase):
    setUp = fixtures.DevCycleTests.setUp

    def test_control_repairs_from_test_and_both_arms_reach_desktop(self):
        self.assertIn("development_team", RPC_METHODS)
        check = self.root / "check.py"
        check.write_text("""import json, pathlib, sys
passed = pathlib.Path('answer.txt').read_text() == '2'
kind = 'none' if passed else 'implementation'
pathlib.Path(sys.argv[1]).write_text(json.dumps(dict(status='pass' if passed else 'fail',
 failure_type=kind, checks=[dict(name='answer equals 2', passed=passed, failure_type=kind,
 observed=True, criterion_ids=['AC-01'])])))
""", "utf-8")
        issue, contract, plan = [self.root / name for name in ("issue.json","contract.json","plan.json")]
        cycle.write(issue, {"text":"Fix answer"})
        cycle.write(contract, dict(status="ready", summary="Fix answer", scope=["answer.txt"],
                    non_goals=[], constraints=[], questions=[],
                    criteria=[dict(id="AC-01", requirement="answer equals two", verification="read answer.txt")]))
        cycle.write(plan, dict(argv=[sys.executable,str(check),"{result}"],files={str(check):fingerprint(check)}))
        with patch.dict(os.environ, DESK_COMPANION_DATA_DIR=str(self.root/"profile")):
            create(Namespace(pair=self.task, repo=self.repo, issue=issue, contract=contract, plan=plan,
                             rounds=3,max_launches=12,openai_https=False,dependency_path=[],model="fixture"))
            for arm in ("direct","workflow"):
                actor = fixtures.Agents()
                state = cycle.Cycle(self.task/arm, actor).run()
                self.assertEqual("accepted",state["status"],state["reason"])
                if arm == "direct":
                    self.assertEqual(actor.calls,["develop","develop"])
            row = Bridge(None).development_team()["experiments"][0]
            self.assertTrue(all(arm["matched"] for arm in row["arms"].values()))
            self.assertEqual(row["arms"]["direct"]["rework"],1)
            self.assertEqual(row["arms"]["workflow"]["checks"][0]["passed"],True)
            self.assertFalse(row["arms"]["direct"]["usage_complete"])
            cycle.write(self.task/"workflow"/"issue.json", {"text":"different task"})
            self.assertFalse(Bridge(None).development_team()["experiments"][0]["arms"]["workflow"]["matched"])
            with self.assertRaises(ValueError):
                register(self.task)
