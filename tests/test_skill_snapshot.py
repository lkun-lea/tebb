import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.skill_snapshot import export_snapshot,snapshot


class SkillSnapshotTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.source=self.root/'source';self.source.mkdir();self.git('init','-b','main')
        self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        self.text=b'---\nname: fixture\ndescription: fixture instructions\n---\nUse actual tools.\n'
        skill=self.source/'skills/fixture/SKILL.md';skill.parent.mkdir(parents=True);skill.write_bytes(self.text)
        (self.source/'LICENSE').write_bytes(b'MIT fixture\n')
        self.git('add','--','skills','LICENSE');self.git('commit','-m','fixture')
        self.lock=self.root/'lock.json';self.write_lock()

    def git(self,*args,input=None):return subprocess.check_output(['git',*args],cwd=self.source,input=input,stderr=subprocess.PIPE)

    def write_lock(self):
        commit=self.git('rev-parse','HEAD').decode().strip()
        self.lock.write_text(json.dumps(dict(repository='lkun-lea/tebb-skills',commit=commit,files={p:hashlib.sha256(self.git('show',commit+':'+p)).hexdigest() for p in ('LICENSE','skills/fixture/SKILL.md')})),'utf-8')

    def test_uses_only_pinned_git_objects_despite_dirty_and_private_untracked_files(self):
        (self.source/'skills/fixture/SKILL.md').write_text('dirty instructions','utf-8')
        (self.source/'skills/private.json').write_text('must never export','utf-8')
        target=self.root/'export';value=export_snapshot(self.source,target,self.lock)
        self.assertEqual((target/'fixture/SKILL.md').read_bytes(),self.text)
        self.assertFalse((target/'private.json').exists())
        self.assertEqual(json.loads((target/'source.json').read_text('utf-8')),value)
        export_snapshot(self.source,target,self.lock)

    def test_custom_content_is_not_overwritten_and_all_targets_are_checked_before_writing(self):
        target=self.root/'existing';(target/'fixture').mkdir(parents=True)
        (target/'fixture/SKILL.md').write_text('user edit','utf-8')
        with self.assertRaises(ValueError):export_snapshot(self.source,target,self.lock)
        self.assertEqual((target/'fixture/SKILL.md').read_text('utf-8'),'user edit')
        self.assertFalse((target/'LICENSE').exists())

    def test_windows_checkout_line_endings_are_canonicalized_without_other_text_changes(self):
        target=self.root/'windows';(target/'fixture').mkdir(parents=True)
        (target/'fixture/SKILL.md').write_bytes(self.text.replace(b'\n',b'\r\n'))
        self.git('config','core.autocrlf','true')
        export_snapshot(self.source,target,self.lock)
        self.assertEqual((target/'fixture/SKILL.md').read_bytes(),self.text)

    def test_digest_wrong_commit_and_archive_links_fail_closed(self):
        value=json.loads(self.lock.read_text('utf-8'));value['files']['LICENSE']='0'*64;self.lock.write_text(json.dumps(value),'utf-8')
        with self.assertRaises(ValueError):snapshot(self.source,self.lock)
        self.write_lock();value=json.loads(self.lock.read_text('utf-8'));value['commit']='0'*40;self.lock.write_text(json.dumps(value),'utf-8')
        with self.assertRaises(subprocess.CalledProcessError):snapshot(self.source,self.lock)
        self.write_lock()
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            info=zipfile.ZipInfo('skills/fixture/SKILL.md');info.create_system=3;info.external_attr=0o120777<<16;z.writestr(info,b'../../private')
        with patch('scripts.skill_snapshot.subprocess.check_output',return_value=archive.getvalue()):
            with self.assertRaises(ValueError):snapshot(self.source,self.lock)
