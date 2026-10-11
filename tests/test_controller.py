"""Synthetic task lifecycle; never calls Ollama, Docker or remote Git."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from athenz.controller import CodingController, ControllerError, proposal_digest
from athenz.experience import ExperienceStore
from athenz.worker import Worker


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


class FakeModel:
    def __init__(self, invalid_once=False, bad_plan=False):
        self.invalid_once = invalid_once
        self.bad_plan = bad_plan
        self.prompts = []
        self.proposals = 0

    def generate(self, messages, **kwargs):
        obj = json.loads(messages[-1]['content'])
        self.prompts.append(obj)
        if 'authorized_files' in obj:
            if self.bad_plan:
                return json.dumps({'steps': [1, 'invalid']})
            return json.dumps({'steps': ['Inspect functions', 'Correct arithmetic', 'Verify syntax'],
                               'rationale': 'Repair synthetic math'})
        self.proposals += 1
        calc = 'def add(a, b):\n    return a + b\n'
        if self.invalid_once and self.proposals == 1:
            calc = 'def broken(:\n    return 3\n'
        return json.dumps({'summary': 'Correct arithmetic', 'changes': [
            {'path': 'calc.py', 'new_content': calc},
            {'path': 'util.py', 'new_content': 'def sub(a, b):\n    return a - b\n'}]})


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'original'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        git(self.repo, 'config', 'user.name', 'Synthetic')
        (self.repo / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (self.repo / 'util.py').write_text('def sub(a, b):\n    return a + b\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'baseline')
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        self.worker = Worker(self.store)
        self.ctl = CodingController(self.worker)
        self.worker.begin('math', self.repo, 'Fix incorrect math helpers')

    def plan(self, model):
        return self.ctl.plan('math', ['calc.py', 'util.py'], model)

    def test_full_review_gated_multifile_flow_and_restart(self):
        model = FakeModel()
        plan = self.plan(model)
        self.assertEqual(plan['phase'], 'planned')
        self.assertEqual(model.prompts[0]['authorized_files'], ['calc.py', 'util.py'])
        with self.assertRaises(ControllerError):
            self.ctl.apply('math', 'bad')
        review = self.ctl.prepare('math', model)
        self.assertIn('+    return a + b', review['diff'])
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        with self.assertRaises(ControllerError):
            self.ctl.apply('math', '0'*64)
        self.assertNotIn('return a + b', (self.repo / 'calc.py').read_text())
        self.assertEqual(self.ctl.apply('math', review['sha256']), 2)
        reopened = ExperienceStore(self.root / 'private')
        self.addCleanup(reopened.close)
        ctl = CodingController(Worker(reopened))
        self.assertEqual(ctl.status('math')['phase'], 'applied')
        self.assertEqual(ctl.syntax('math')['phase'], 'syntax_passed')
        patch = ctl.export('math')
        self.assertEqual(patch['verification'], 'syntax-only')
        self.assertEqual(hashlib.sha256(Path(patch['path']).read_bytes()).hexdigest(), patch['sha256'])
        self.assertEqual(ctl.status('math')['phase'], 'exported')
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        self.worker.cleanup('math', discard_changes=True)
        self.assertTrue(Path(patch['path']).exists())
        with self.assertRaises(Exception):
            ctl.status('math')

    def test_syntax_failure_reverts_then_reproposes_with_fresh_approval(self):
        model = FakeModel(invalid_once=True)
        self.ctl.plan('math', ['calc.py', 'util.py'], model, max_retries=2)
        first = self.ctl.prepare('math', model)
        self.ctl.apply('math', first['sha256'])
        status = self.ctl.syntax('math')
        self.assertEqual(status['phase'], 'retry_needed')
        ws = Path(self.worker.resume('math')['state']['workspace'])
        self.assertEqual(git(ws, 'status', '--porcelain=v1'), '')
        self.assertEqual(self.ctl.status('math')['attempts'], 1)
        second = self.ctl.prepare('math', model)
        self.assertNotEqual(first['sha256'], second['sha256'])
        self.assertIn('invalid syntax', model.prompts[-1]['previous_syntax_failure'])
        with self.assertRaises(ControllerError):
            self.ctl.apply('math', first['sha256'])
        self.ctl.apply('math', second['sha256'])
        self.assertEqual(self.ctl.syntax('math')['phase'], 'syntax_passed')
        self.worker.cleanup('math', discard_changes=True)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')

    def test_plan_rejects_invalid_and_unsafe_scope(self):
        with self.assertRaises(ValueError):
            self.ctl.plan('math', ['../credentials'], FakeModel())
        with self.assertRaises(ControllerError):
            self.ctl.plan('math', ['calc.py'], FakeModel(bad_plan=True))
        self.assertNotIn('controller', self.worker.resume('math')['state'])

    def test_plan_and_proposal_are_not_actions(self):
        model = FakeModel()
        self.plan(model)
        self.ctl.prepare('math', model)
        ws = Path(self.worker.resume('math')['state']['workspace'])
        self.assertEqual(git(ws, 'status', '--porcelain=v1'), '')
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        with self.assertRaises(ControllerError):
            self.ctl.export('math')
        self.worker.cleanup('math')

    def test_prepare_recovers_proposal_created_before_controller_transition(self):
        model = FakeModel()
        self.plan(model)
        pid = self.worker.propose('math', model, ['calc.py', 'util.py'])
        out = self.ctl.prepare('math', model)
        self.assertEqual(out['proposal_id'], pid)
        self.assertEqual(model.proposals, 1)
        self.worker.cleanup('math')

    def test_digest_canonical_and_rejects_changed_content(self):
        row = [{'path':'a.py','before':'1','after':'2'}]
        first = proposal_digest(json.dumps(row))
        self.assertEqual(first, proposal_digest(json.dumps(row, indent=2)))
        self.assertNotEqual(first, proposal_digest(json.dumps([{'path':'a.py','before':'1','after':'3'}])))


if __name__ == '__main__':
    unittest.main()

class RecoveryTests(unittest.TestCase):
    """Additional recovery paths use synthetic Git and no outside services."""
    setUp = ControllerTests.setUp
    plan = ControllerTests.plan
    def test_crash_after_retry_undo_can_prepare_again(self):
        model = FakeModel(invalid_once=True)
        self.plan(model)
        review = self.ctl.prepare('math', model)
        self.ctl.apply('math', review['sha256'])
        # Simulate checkpoint persistence of the failure followed by undo,
        # then a process terminating before its phase transition.
        self.ctl._transition('math', 'applied', last_failure='invalid syntax at line 1')
        self.worker.retry('math', max_retries=2)
        store2 = ExperienceStore(self.root / 'private')
        self.addCleanup(store2.close)
        ctl2 = CodingController(Worker(store2))
        result = ctl2.prepare('math', model)
        self.assertEqual(result['phase'], 'awaiting_review')
        self.assertEqual(model.proposals, 2)
        self.worker.cleanup('math')

    def test_crash_after_review_export_keeps_immutable_bundle(self):
        model = FakeModel()
        self.plan(model)
        review = self.ctl.prepare('math', model)
        self.ctl.apply('math', review['sha256'])
        self.ctl.syntax('math')
        # Simulate Worker.export_review() succeeding before the controller
        # records its final phase.
        original = self.worker.export_review('math')
        duplicate = self.ctl.export('math')
        self.assertEqual(original, duplicate)
        self.assertEqual(self.ctl.status('math')['phase'], 'exported')
        self.worker.cleanup('math', discard_changes=True)

    def test_apply_recovery_refuses_tampered_workspace(self):
        model = FakeModel()
        self.plan(model)
        review = self.ctl.prepare('math', model)
        self.ctl.apply('math', review['sha256'])
        self.ctl._transition('math', 'awaiting_review')  # interrupted checkpoint
        workspace = Path(self.worker.resume('math')['state']['workspace'])
        (workspace / 'calc.py').write_text('TAMPERED = True\n')
        with self.assertRaises(ControllerError):
            self.ctl.apply('math', review['sha256'])
        self.assertEqual(self.ctl.status('math')['phase'], 'awaiting_review')
        self.worker.cleanup('math', discard_changes=True)
