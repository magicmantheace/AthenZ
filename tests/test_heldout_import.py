"""Synthetic held-out batch import tests. No real owner cases, no model."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from athenz.experience import ExperienceStore
from athenz.heldout_import import (HeldoutImportError, import_batch,
                                   load_batch, screen_batch)

LONG = ('When the workshop delivery truck breaks down on the morning of a '
        'large pour, what is the best first move for the crew lead?')
LONG_VARIANT = ('When the workshop delivery truck breaks down on the morning '
                'of a large pour, what is the best first move for a crew lead?')


def case(scenario, choice='Call the customer', options=None, **kw):
    return {'scenario': scenario, 'choice': choice,
            'rationale': 'Synthetic rationale',
            'options': options or ['Call the customer', 'Wait quietly'],
            **kw}


class HeldoutImportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'private'
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)

    def count(self, split='test'):
        return self.store.db.execute(
            'SELECT count(*) FROM decisions WHERE split=?', (split,)).fetchone()[0]

    def test_dry_run_validates_and_writes_nothing(self):
        report = import_batch(self.store, [case(LONG)], split='test')
        self.assertTrue(report['dry_run'])
        self.assertEqual(report['imported'], 0)
        self.assertEqual(self.count(), 0)

    def test_confirmed_import_inserts_pending_cases(self):
        report = import_batch(self.store, [case(LONG), case(
            'A supplier offers a discount that expires before the paperwork '
            'can be checked against the original quote terms today.',
            choice='Wait quietly',
        )], split='test', confirmed=True)
        self.assertEqual(report['imported'], 2)
        self.assertFalse(report['approved'])
        rows = self.store.db.execute(
            "SELECT status,split,source FROM decisions").fetchall()
        self.assertTrue(all(r['status'] == 'pending' for r in rows))
        self.assertTrue(all(r['split'] == 'test' for r in rows))
        self.assertTrue(all(r['source'] == 'owner:heldout-import' for r in rows))

    def test_train_split_is_refused(self):
        with self.assertRaisesRegex(HeldoutImportError, 'calibration or test'):
            import_batch(self.store, [case(LONG)], split='train', confirmed=True)

    def test_choice_outside_options_refused_for_whole_batch(self):
        bad = case('An entirely separate synthetic scenario about winter '
                   'tire storage for the spare work truck fleet.',
                   choice='Not an option')
        with self.assertRaises(HeldoutImportError):
            import_batch(self.store, [case(LONG), bad], split='test', confirmed=True)
        self.assertEqual(self.count(), 0)

    def test_exact_duplicate_against_existing_decision_refused(self):
        self.store.add_decision(LONG, 'Call the customer', 'earlier',
                                source='owner', options=['Call the customer', 'Wait quietly'])
        with self.assertRaisesRegex(HeldoutImportError, 'duplicate'):
            screen_batch(self.store, [case(LONG.lower())])

    def test_within_batch_duplicate_refused(self):
        with self.assertRaisesRegex(HeldoutImportError, 'duplicate'):
            screen_batch(self.store, [case(LONG), case(LONG.upper())])

    def test_near_duplicate_against_approved_train_case_refused(self):
        self.store.add_decision(LONG, 'Call the customer', 'earlier',
                                source='owner', approved=True,
                                options=['Call the customer', 'Wait quietly'])
        with self.assertRaisesRegex(HeldoutImportError, 'near-duplicate'):
            screen_batch(self.store, [case(LONG_VARIANT)])

    def test_contained_phrase_against_existing_decision_refused(self):
        self.store.add_decision(
            'the workshop delivery truck breaks down on the morning of a large pour',
            'Call the customer', 'earlier', source='owner',
            options=['Call the customer', 'Wait quietly'])
        with self.assertRaisesRegex(HeldoutImportError, 'contains'):
            screen_batch(self.store, [case(LONG)])

    def test_load_batch_rejects_malformed_and_oversized(self):
        path = Path(self.home) / 'batch.json'
        path.write_text('{"not": "a list"}')
        with self.assertRaises(HeldoutImportError):
            load_batch(path)
        path.write_text(json.dumps([case(LONG)] * 201))
        with self.assertRaisesRegex(HeldoutImportError, '1-200'):
            load_batch(path)
        path.write_text(json.dumps([{'scenario': 'x'}]))
        with self.assertRaisesRegex(HeldoutImportError, 'case 0'):
            load_batch(path)

    def test_errors_never_echo_scenario_text(self):
        secret = 'UNIQUE-SCENARIO-TEXT-4417 that must not leak into errors'
        dup = case(f'{secret} plus enough extra words to matter here today')
        self.store.add_decision(dup['scenario'], 'Call the customer', 'earlier',
                                source='owner', options=dup['options'])
        with self.assertRaises(HeldoutImportError) as caught:
            screen_batch(self.store, [dup])
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, json.dumps(
            import_batch(self.store, [case(LONG)], split='test')))


if __name__ == '__main__':
    unittest.main()
