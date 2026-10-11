"""Synthetic local-branch handoff, no remote push or real Docker."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from athenz.experience import ExperienceStore
from athenz.publishing import publish_local_branch
from athenz.sequencer import SequenceController, SequenceError
from athenz.worker import Worker


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class Model:
    def generate(self, messages, **kwargs):
        files = json.loads(messages[-1]['content'])['files']
        return json.dumps({'summary': 'synthetic', 'changes': [
            {'path': path, 'new_content': f'def {path[:-3]}():\n    return 42\n'} for path in files]})


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Test Only')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        for f in ('one.py', 'two.py'):
            (self.repo / f).write_text('x = 0\n')
        (self.repo / 'tests').mkdir()
        (self.repo/'tests'/'test_foo.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_true(self): self.assertTrue(True)\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'original')
        self.base=git(self.repo,'rev-parse','HEAD')
        self.store=ExperienceStore(self.root/'private')
        self.addCleanup(self.store.close)
        self.ctl=SequenceController(Worker(self.store))
        self.ctl.start('task', self.repo, 'Fix both', [['one.py'],['two.py']])
        for _ in range(2):
            r=self.ctl.prepare('task', Model())
            self.ctl.apply('task',r['sha256'])
            self.ctl.syntax('task')
            self.ctl.advance('task')

    def passing(self):
        original=subprocess.run
        def mock_docker(argv,*args,**kwargs):
            if argv[0]=='docker':
                return subprocess.CompletedProcess(argv,0,'test passed','')
            return original(argv,*args,**kwargs)
        with mock.patch('athenz.verification.shutil.which',return_value='/usr/bin/docker'), \
             mock.patch('athenz.verification.subprocess.run',side_effect=mock_docker):
            self.ctl.verify_container('task',image='python@sha256:'+'a'*64)
        return self.ctl.export('task')

    def test_publishes_local_only_and_survives_restart(self):
        with self.assertRaises(SequenceError):
            publish_local_branch(self.ctl,'task','0'*64)
        b=self.passing()
        with self.assertRaises(SequenceError):
            publish_local_branch(self.ctl,'task','f'*64)
        published=publish_local_branch(self.ctl,'task',b['sha256'])
        self.assertTrue(published['branch'].startswith('athenz/task-'))
        self.assertFalse(published['remote_pushed'])
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),self.base)
        self.assertEqual(git(self.repo,'status','--porcelain=v1'),'')
        self.assertEqual(git(self.repo,'show',published['branch']+':one.py'),
                         'def one():\n    return 42')
        self.assertEqual(git(self.repo,'show',published['branch']+':two.py'),
                         'def two():\n    return 42')
        self.assertEqual(published,publish_local_branch(self.ctl,'task',b['sha256']))
        reopened=ExperienceStore(self.root/'private')
        self.addCleanup(reopened.close)
        self.assertEqual(published,publish_local_branch(
            SequenceController(Worker(reopened)),'task',b['sha256']))
        self.ctl.cancel('task',discard_changes=True)
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),self.base)
        self.assertEqual(git(self.repo,'status','--porcelain=v1'),'')
        self.assertEqual(git(self.repo,'show',published['branch']+':one.py'),
                         'def one():\n    return 42')

    def test_rejects_sytnax_only_and_dirty_workspace(self):
        b=self.ctl.export('task')
        with self.assertRaises(SequenceError):
            publish_local_branch(self.ctl,'task',b['sha256'])
        self.ctl.cancel('task',discard_changes=True)

    def test_ref_collision_blocks_unrelated_commit(self):
        b=self.passing()
        branch='refs/heads/athenz/task-'+b['sha256'][:12]
        git(self.repo,'update-ref',branch,self.base)
        with self.assertRaisesRegex(SequenceError,'collision'):
            publish_local_branch(self.ctl,'task',b['sha256'])
        self.assertEqual(git(self.repo,'rev-parse',branch),self.base)
        self.ctl.cancel('task',discard_changes=True)


if __name__=='__main__':
    unittest.main()
