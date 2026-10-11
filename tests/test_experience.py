"""Synthetic-only tests for v0.3 memory, evidence and checkpoint lifecycles."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from athenz.cli import main
from athenz.experience import ExperienceStore
from athenz.prompting import build_messages


class EpisodicMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.s = ExperienceStore(self.home)
        self.addCleanup(self.s.close)

    def test_reviewed_only_relevant_and_mode_separation(self):
        x = self.s.observe('Python unit tests', 'Always mock unstable network requests',
                           tags=['python', 'tests'], source='owner:synthetic', source_ref='sample')
        self.assertEqual(self.s.relevant_episodes('python tests'), [])
        self.assertNotIn('unstable network', str(build_messages(self.s, 'python tests', 'agent')))
        self.assertTrue(self.s.review_episode(x, 'approved'))
        self.assertEqual(len(self.s.relevant_episodes('python tests')), 1)
        self.assertEqual(self.s.relevant_episodes('Minecraft mods'), [])
        self.assertIn('unstable network', str(build_messages(self.s, 'python tests', 'agent')))
        self.assertNotIn('unstable network', str(build_messages(self.s, 'Minecraft mods', 'agent')))
        self.assertIn('unstable network', str(build_messages(self.s, 'python tests', 'twin')))

    def test_conflict_review_supersession_and_revoke(self):
        original = self.s.observe('Formatting Python', 'Use tabs in Python',
                                  tags=['python', 'format'], source='owner:synthetic')
        self.s.review_episode(original, 'approved')
        second = self.s.observe('Formatting Python', 'Use four spaces in Python',
                                tags=['python', 'format'], source='owner:synthetic',
                                supersedes_id=original)
        self.assertEqual(self.s.potential_conflicts(second)[0]['id'], original)
        self.assertIn('tabs', str(self.s.relevant_episodes('format python')))
        self.s.review_episode(second, 'approved')
        self.assertTrue(self.s.review_episode(second, 'approved'))  # idempotent
        self.assertNotIn('tabs', str(self.s.relevant_episodes('format python')))
        self.assertIn('four spaces', str(self.s.relevant_episodes('format python')))
        self.s.review_episode(second, 'rejected')
        self.assertEqual(self.s.relevant_episodes('format python'), [])

    def test_erasure_and_source_purge_remove_contents_not_metadata(self):
        self.s.observe('Confidential prototype', 'synthetic-secret-123',
                       tags=['prototype'], source='import:synthetic', source_ref='a')
        self.s.observe('Other prototype', 'retained',
                       tags=['prototype'], source='import:synthetic', source_ref='b')
        self.assertEqual(self.s.purge_source('import:synthetic', 'a')['episodes'], 1)
        self.assertNotIn('synthetic-secret-123', str(self.s.export()))
        self.assertEqual(len(self.s.list_items('episodes')), 1)
        self.assertFalse(self.s.forget_episode(999))
        self.assertTrue(self.s.forget_episode(self.s.list_items('episodes')[0]['id']))
        self.assertNotIn('retained', str(self.s.export()))
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.db.execute('DELETE FROM events')

    def test_checkpoint_cas_reload_and_no_execution(self):
        cid = self.s.checkpoint('code_task', 'Inspect Python repository',
                                {'command': 'THIS IS UNTRUSTED DATA'}, status='paused')
        self.assertEqual(self.s.get_checkpoint('code_task')['revision'], 1)
        with self.assertRaises(ValueError):
            self.s.checkpoint('code_task', 'Do something else', {}, status='running')
        self.s.checkpoint('code_task', 'Inspect Python repository', {'step': 2},
                          status='running', expected_revision=1)
        with self.assertRaises(ValueError):
            self.s.checkpoint('code_task', 'Stale worker', {}, expected_revision=1)
        reopened = ExperienceStore(self.home)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get_checkpoint('code_task')['state'], {'step': 2})
        self.assertEqual(reopened.get_checkpoint('code_task')['id'], cid)
        with self.assertRaises(ValueError):
            self.s.checkpoint('code_task', 'Oversized', {'a': 'x' * 17000}, expected_revision=2)
        self.assertTrue(self.s.forget_checkpoint('code_task'))
        self.assertIsNone(reopened.get_checkpoint('code_task'))

    def test_approved_procedures_only_current_passing_test_and_relevant(self):
        pid = self.s.new_proposal('/synthetic', 'Fix python parser', [{'path': 'parser.py'}], 'proposal')
        self.s.update_proposal(pid, 'proposed', 'applied')
        self.s.record_test(pid, 'unit', 0, 'Passed unit test', 'file-sha', 'Verify parser regression tests')
        eid = self.s.list_items('experiences')[0]['id']
        self.s.set_review('experiences', eid, 'approved')
        self.assertIn('parser', str(self.s.approved_experiences(query='python parser')))
        self.assertNotIn('parser', str(self.s.approved_experiences(query='Minecraft farming')))
        self.s.record_test(pid, 'unit', 0, 'Passed again', 'file-sha', 'New test result')
        self.assertEqual(self.s.approved_experiences(query='python parser'), [])
        eid2 = self.s.list_items('experiences')[0]['id']
        self.s.set_review('experiences', eid2, 'approved')
        self.assertEqual(len(self.s.approved_experiences(query='python parser')), 1)
        self.s.update_proposal(pid, 'applied', 'undone')
        self.assertEqual(self.s.approved_experiences(query='python parser'), [])

    def test_cli_observe_review_recall_checkpoint(self):
        main(['--home', str(self.home), 'observe', 'Python checks', 'Use test doubles',
              '--tag', 'python', '--source-ref', 'cli-example'])
        main(['--home', str(self.home), 'review-episode', '1', 'approved'])
        self.assertEqual(len(self.s.relevant_episodes('python checks')), 1)
        main(['--home', str(self.home), 'checkpoint-save', 'devtask', 'Fix bug',
              '--state-json', '{"step": 1}', '--status', 'paused'])
        self.assertEqual(self.s.get_checkpoint('devtask')['state'], {'step': 1})


if __name__ == '__main__':
    unittest.main()
