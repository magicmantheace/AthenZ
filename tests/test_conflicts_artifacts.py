import sqlite3
import tempfile
import unittest
from pathlib import Path

from athenz.experience import ExperienceStore
from athenz.prompting import build_messages
from athenz.cli import main


class DisputeArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'private'
        self.s = ExperienceStore(self.home)
        self.addCleanup(self.s.close)

    def test_dispute_quarantines_both_and_owner_resolves(self):
        a = self.s.observe('Python formatter', 'Use tabs in Python files', tags=['python'], source='owner:example')
        b = self.s.observe('Python formatter', 'Use four spaces in Python files', tags=['python'], source='owner:example')
        self.s.review_episode(a, 'approved')
        self.s.review_episode(b, 'approved')
        self.assertEqual(len(self.s.relevant_episodes('python formatter')), 2)
        dispute = self.s.dispute(a, b, 'Explicitly inconsistent style instructions')
        self.assertEqual(self.s.relevant_episodes('python formatter'), [])
        self.assertNotIn('four spaces', str(build_messages(self.s, 'python formatter', 'agent')))
        self.assertNotIn('Use tabs', str(build_messages(self.s, 'python formatter', 'twin')))
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.dispute(a, b, 'Cannot double-add')
        with self.assertRaises(ValueError):
            self.s.resolve_dispute(dispute, 999)
        self.assertTrue(self.s.resolve_dispute(dispute, b))
        self.assertFalse(self.s.resolve_dispute(999, b))
        self.assertNotIn('Use tabs', str(self.s.relevant_episodes('python formatter')))
        self.assertIn('four spaces', str(self.s.relevant_episodes('python formatter')))
        with self.assertRaises(ValueError):
            self.s.resolve_dispute(dispute, b)

    def test_evidence_fingerprint_detects_tampering_no_file_contents_in_db(self):
        pid = self.s.new_proposal('/example', 'Inspect synthetic parser', [{'path': 'sample.py'}], 'record')
        self.s.update_proposal(pid, 'proposed', 'applied')
        run_id = self.s.record_test(pid, 'unittest', 0, 'passed', 'files-hash', 'review test')
        path = Path(self.temp.name) / 'test-results.txt'
        path.write_text('synthetic output without private data')
        ref = self.s.record_artifact(run_id, 'unit-results', path)
        self.assertTrue(self.s.verify_artifact(ref, path))
        self.assertEqual(self.s.db.execute('SELECT size_bytes FROM evidence_artifacts').fetchone()[0], path.stat().st_size)
        self.assertNotIn('synthetic output', str(self.s.export()))
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.record_artifact(run_id, 'unit-results', path)
        path.write_text('changed')
        self.assertFalse(self.s.verify_artifact(ref, path))
        self.assertEqual(self.s.approved_experiences(query='parser'), [])
        with self.assertRaises(ValueError):
            self.s.record_artifact(run_id, '../secret', path)
        with self.assertRaises(ValueError):
            self.s.record_artifact(999, 'other-artifact', path)
        self.s.forget_runtime('proposals', pid)
        self.assertEqual(self.s.list_items('evidence_artifacts'), [])

    def test_source_purge_cascades_open_dispute(self):
        a = self.s.observe('Python formatter', 'Use tabs', tags=['python'], source='owner', source_ref='one')
        b = self.s.observe('Python formatter', 'Use spaces', tags=['python'], source='owner', source_ref='two')
        self.s.review_episode(a, 'approved')
        self.s.review_episode(b, 'approved')
        self.s.dispute(a, b, 'inconsistent')
        self.s.purge_source('owner', 'one')
        self.assertEqual(self.s.list_items('episode_disputes'), [])
        self.assertEqual(len(self.s.relevant_episodes('python formatter')), 1)

    def test_cli_dispute_and_artifact_commands(self):
        a = self.s.observe('Python formatter', 'Use tabs', tags=['python'], source='owner')
        b = self.s.observe('Python formatter', 'Use spaces', tags=['python'], source='owner')
        self.s.review_episode(a, 'approved')
        self.s.review_episode(b, 'approved')
        main(['--home', str(self.home), 'dispute', str(a), str(b), '--reason', 'inconsistent'])
        main(['--home', str(self.home), 'resolve-dispute', '1', str(b)])
        self.assertEqual(len(self.s.relevant_episodes('python formatter')), 1)


if __name__ == '__main__':
    unittest.main()
