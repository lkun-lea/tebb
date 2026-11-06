"""Lock export failures and source ownership must fail before task execution."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import python_dependencies as deps
from scripts.dev_cycle_environment import requirements


class PythonDependencyTests(unittest.TestCase):
    def test_runtime_export_rejects_stale_file_and_never_rewrites_in_check_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            target = root/'scripts/runtime-lock.txt'
            target.write_text('old\n')
            with patch.object(deps, 'runtime_export', return_value='current\n'):
                with self.assertRaisesRegex(ValueError, '过期'):
                    deps.export_runtime(root=root, check=True)
                self.assertEqual(target.read_text(), 'old\n')
                deps.export_runtime(root=root)
                deps.export_runtime(root=root, check=True)

    def test_failed_lock_export_keeps_previous_runtime_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            target = root/'scripts/runtime-lock.txt'
            target.write_text('previous\n')
            with patch.object(deps.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['uv'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    deps.export_runtime(root=root)
            self.assertEqual(target.read_text(), 'previous\n')

    def test_atlas_pin_requires_official_repository_and_full_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root/'pyproject.toml'
            for dependency in ['atlas', 'atlas @ git+https://example.invalid/Atlas.git@'+'a'*40,
                               'atlas @ git+https://github.com/lkun-lea/Atlas.git@main']:
                project.write_text('[project]\ndependencies=['+json.dumps(dependency)+']\n')
                with self.assertRaises(ValueError):
                    deps.atlas_ref(root)
            project.write_text('[project]\ndependencies=["atlas @ git+https://github.com/lkun-lea/Atlas.git@'+'a'*40+'"]\n')
            self.assertEqual(deps.atlas_ref(root), 'a'*40)

    def test_task_lock_excludes_explicit_source_owner_and_records_lock_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'project'; root.mkdir()
            (root/'uv.lock').write_text('first lock\n')
            owner = Path(directory)/'atlas'; owner.mkdir()
            (owner/'pyproject.toml').write_text('[project]\nname="atlas"\ndependencies=["sdk-fixture>=1"]\n')
            with patch('scripts.dev_cycle_environment.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'sdk-fixture==1\n')) as run:
                first = requirements(root, [owner])
                command = run.call_args.args[0]
                self.assertIn('--locked', command)
                self.assertEqual(command[command.index('--no-emit-package')+1], 'atlas')
                self.assertEqual(first['origin'], 'uv.lock')
                self.assertIn('sdk-fixture==1', first['text'])
                self.assertIn('sdk-fixture>=1', first['text'])
                (root/'uv.lock').write_text('changed lock\n')
                self.assertNotEqual(first['lock_sha256'], requirements(root, [owner])['lock_sha256'])

    def test_generic_project_does_not_install_a_distribution_over_explicit_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'project'; root.mkdir()
            (root/'pyproject.toml').write_text('[project]\ndependencies=["atlas @ git+https://example.invalid/Atlas.git@main", "other>=1"]\n')
            owner = Path(directory)/'atlas'; owner.mkdir()
            (owner/'pyproject.toml').write_text('[project]\nname="atlas"\ndependencies=["sdk-fixture>=1"]\n')
            plan = requirements(root, [owner])
            self.assertNotIn('git+', plan['text'])
            self.assertIn('other>=1', plan['text'])
            self.assertIn('sdk-fixture>=1', plan['text'])


if __name__ == '__main__':
    unittest.main()
