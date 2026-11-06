"""Exercise real Windows 8.3 aliases without weakening the evidence allowlist."""
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from scripts.dev_cycle import Codex
from scripts import dev_cycle_improvement as improvement


@unittest.skipUnless(os.name == 'nt', 'Windows 8.3 path identity')
class WindowsEvidencePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tebb evidence long path ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        buffer = ctypes.create_unicode_buffer(32768)
        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        get_short.restype = ctypes.c_uint
        count = get_short(str(self.root), buffer, len(buffer))
        self.assertTrue(count)
        self.short = Path(buffer.value)
        if self.short == self.root:
            self.skipTest('Volume does not provide a distinct 8.3 alias')
        self.assertEqual(self.short.resolve(), self.root)

    def manifest(self):
        snapshot = self.root/'candidate'; snapshot.mkdir()
        proof = snapshot/'proof.txt'; proof.write_text('sealed evidence', 'utf-8')
        manifest = improvement.review_evidence_manifest(
            dict(proposal=dict(evidence_index=[])), {}, snapshot,
            self.root/'validation', self.root/'attempt-develop')
        return proof, manifest

    def test_sealed_file_accepts_short_alias_but_not_siblings_or_changed_content(self):
        proof, manifest = self.manifest()
        alias = self.short/proof.relative_to(self.root)
        review = dict(evidence=[dict(path=str(alias), observation='same physical file')])
        improvement.check_review_evidence(review, manifest)
        sibling = proof.with_name('unapproved.txt'); sibling.write_bytes(proof.read_bytes())
        with self.assertRaisesRegex(ValueError, '未预封存'):
            improvement.check_review_evidence(dict(evidence=[dict(path=str(self.short/sibling.relative_to(self.root)))]), manifest)
        proof.write_text('changed after sealing', 'utf-8')
        with self.assertRaisesRegex(ValueError, '哈希改变'):
            improvement.check_review_evidence(review, manifest)

    def test_junction_to_sealed_file_is_rejected_before_alias_resolution(self):
        import _winapi
        proof, manifest = self.manifest()
        junction = self.root/'linked-candidate'
        _winapi.CreateJunction(str(proof.parent), str(junction))
        with self.assertRaisesRegex(ValueError, '链接'):
            improvement.check_review_evidence(dict(evidence=[dict(path=str(junction/proof.name))]), manifest)

    def test_new_and_resumed_cli_receive_the_same_canonical_evidence_root(self):
        source = self.root/'source'; source.mkdir()
        fixture = self.root/'cli.py'
        fixture.write_text('''import json,os,pathlib,sys
sys.stdin.read()
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(dict(argv=sys.argv[1:],evidence_dir=os.environ['DEV_CYCLE_EVIDENCE_DIR'])))
''', 'utf-8')
        adapter = Codex(sys.executable, [str(fixture)])
        for stage, session in [('verify', None), ('develop', None), ('develop', 'same-session')]:
            record = self.short/('attempt-'+stage+('-resume' if session else ''))
            record.mkdir()
            result = adapter(stage=stage, prompt='fixture', cwd=self.short/'source', record=record,
                             task_folder=self.short, session=session, started=lambda *_: None,
                             check_seconds=.1, silence_seconds=2)
            evidence = str(Path(result['evidence_dir']).resolve())
            self.assertEqual(result['evidence_dir'], evidence)
            self.assertIn('sandbox_workspace_write.writable_roots='+json.dumps([evidence]), result['argv'])
            self.assertEqual(json.loads((record/'artifacts.json').read_text('utf-8'))['evidence_dir'], evidence)


if __name__ == '__main__':
    unittest.main()
