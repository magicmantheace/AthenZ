"""Explicit local candidate/competitor review and stale-proof adjudication."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.conflict_review import (ConflictReviewError, adjudicate, main,
                                    preview, MAX_CONFLICTS)
from athenz.experience import ExperienceStore


class ConflictReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / 'private'
        store = ExperienceStore(self.home)
        self.original = store.observe('Editor indentation', 'Use tabs in code',
                                      tags=['python', 'style'], source='synthetic:owner', source_ref='v1')
        store.review_episode(self.original, 'approved')
        self.new = store.observe('Editor indentation', 'Use spaces in code',
                                 tags=['python', 'style'], source='synthetic:owner', source_ref='v2')
        store.close()

    def test_no_consent_cannot_open_database_or_expose_private_content(self):
        with patch('athenz.conflict_review._existing_home', side_effect=AssertionError('private read')):
            with self.assertRaisesRegex(ConflictReviewError, 'confirm'):
                preview(self.home, self.new)
            with self.assertRaisesRegex(ConflictReviewError, 'confirm'):
                adjudicate(self.home, self.new, digest='f'*64, decision='keep-both')

    def test_full_record_review_and_topical_hint_without_semantic_claim(self):
        record = preview(self.home, self.new, confirmed=True)
        self.assertEqual(record['candidate']['detail'], 'Use spaces in code')
        self.assertEqual(record['overlapping_approved'][0]['episode']['detail'], 'Use tabs in code')
        self.assertEqual(record['overlapping_approved'][0]['shared_tags'], ['python', 'style'])
        self.assertFalse(record['semantic_contradiction_proven'])
        self.assertTrue(record['private_data_in_output'])
        self.assertEqual(len(record['review_sha256']), 64)

    def test_digest_invalidates_on_provenance_content_and_new_overlap(self):
        before = preview(self.home, self.new, confirmed=True)
        store = ExperienceStore(self.home)
        with store.db:
            store.db.execute('UPDATE episodes SET source_ref=? WHERE id=?', ('changed', self.original))
        store.close()
        with self.assertRaisesRegex(ConflictReviewError, 'stale'):
            adjudicate(self.home, self.new, digest=before['review_sha256'], decision='keep-both', confirmed=True)
        fresh = preview(self.home, self.new, confirmed=True)
        store = ExperienceStore(self.home)
        competitor = store.observe('Another style', 'Use 2 spaces', tags=['style'], source='synthetic')
        store.review_episode(competitor, 'approved')
        store.close()
        with self.assertRaisesRegex(ConflictReviewError, 'stale'):
            adjudicate(self.home, self.new, digest=fresh['review_sha256'], decision='keep-both', confirmed=True)

    def test_supersede_requires_exact_reviewed_predecessor_and_disarms_old(self):
        digest = preview(self.home, self.new, confirmed=True)['review_sha256']
        with self.assertRaisesRegex(ConflictReviewError, 'reviewed approved overlap'):
            adjudicate(self.home, self.new, digest=digest, decision='supersede',
                       predecessor_id=999, confirmed=True)
        ok = adjudicate(self.home, self.new, digest=digest, decision='supersede',
                        predecessor_id=self.original, confirmed=True)
        self.assertTrue(ok['review_hash_verified'])
        store = ExperienceStore(self.home)
        try:
            self.assertEqual(store.db.execute('SELECT status FROM episodes WHERE id=?', (self.original,)).fetchone()[0], 'rejected')
            row = store.db.execute('SELECT status,supersedes_id FROM episodes WHERE id=?', (self.new,)).fetchone()
            self.assertEqual(tuple(row), ('approved', self.original))
            events = [r[0] for r in store.db.execute('SELECT operation FROM events ORDER BY id')]
            self.assertIn('superseded', events)
        finally:
            store.close()
        with self.assertRaisesRegex(ConflictReviewError, 'pending'):
            adjudicate(self.home, self.new, digest=digest, decision='supersede',
                       predecessor_id=self.original, confirmed=True)

    def test_keep_both_never_auto_rejects_predecessor(self):
        digest = preview(self.home, self.new, confirmed=True)['review_sha256']
        result = adjudicate(self.home, self.new, digest=digest, decision='keep-both', confirmed=True)
        self.assertTrue(result['approved_without_automatic_resolution'])
        store = ExperienceStore(self.home)
        try:
            self.assertEqual(store.db.execute('SELECT status FROM episodes WHERE id=?', (self.original,)).fetchone()[0], 'approved')
        finally:
            store.close()

    def test_reject_candidate_preserves_existing_approved(self):
        digest = preview(self.home, self.new, confirmed=True)['review_sha256']
        adjudicate(self.home, self.new, digest=digest, decision='reject', confirmed=True)
        store = ExperienceStore(self.home)
        try:
            statuses = [r[0] for r in store.db.execute('SELECT status FROM episodes ORDER BY id')]
            self.assertEqual(statuses, ['approved', 'rejected'])
        finally:
            store.close()

    def test_declared_supersession_must_match_owner_decision(self):
        store = ExperienceStore(self.home)
        another = store.observe('New formatter', 'Use spaces', tags=['style'],
                                source='synthetic', supersedes_id=self.original)
        store.close()
        digest = preview(self.home, another, confirmed=True)['review_sha256']
        with self.assertRaisesRegex(ConflictReviewError, 'already names'):
            adjudicate(self.home, another, digest=digest, decision='keep-both', confirmed=True)

    def test_pending_declared_supersession_can_be_rejected_without_touching_old(self):
        store = ExperienceStore(self.home)
        pending = store.observe('Different indentation', 'Ignore the suggestion',
                                tags=['style'], source='synthetic', supersedes_id=self.original)
        store.close()
        digest = preview(self.home, pending, confirmed=True)['review_sha256']
        adjudicate(self.home, pending, digest=digest, decision='reject', confirmed=True)
        store = ExperienceStore(self.home)
        try:
            self.assertEqual(store.db.execute('SELECT status FROM episodes WHERE id=?', (pending,)).fetchone()[0], 'rejected')
            self.assertEqual(store.db.execute('SELECT status FROM episodes WHERE id=?', (self.original,)).fetchone()[0], 'approved')
        finally:
            store.close()

    def test_invalid_inputs_and_missing_db_fail_closed(self):
        for bogus in ('F'*64, '../bad', '', '0'*63):
            with self.assertRaises(ConflictReviewError):
                adjudicate(self.home, self.new, digest=bogus, decision='reject', confirmed=True)
        with self.assertRaises(ConflictReviewError):
            adjudicate(self.home, self.new, digest='0'*64, decision='supersede', confirmed=True)
        missing = self.home.parent / 'absent'
        with self.assertRaises(ConflictReviewError):
            preview(missing, self.new, confirmed=True)
        self.assertFalse(missing.exists())

    def test_cli_preview_is_explicit_and_decision_response_omits_private_text(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main(['--home', str(self.home), 'preview', str(self.new), '--confirm'])
        result = json.loads(output.getvalue())
        self.assertTrue(result['private_data_in_output'])
        output = io.StringIO()
        with redirect_stdout(output):
            main(['--home', str(self.home), 'decide', str(self.new), 'reject',
                  '--sha256', result['review_sha256'], '--confirm'])
        self.assertNotIn('Use tabs', output.getvalue())
        self.assertNotIn('Use spaces', output.getvalue())
        self.assertTrue(json.loads(output.getvalue())['review_hash_verified'])


if __name__ == '__main__':
    unittest.main()
