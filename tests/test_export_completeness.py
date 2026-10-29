"""Export completeness regression tests (synthetic data only).

export() previously read identity, identity_revisions, decisions and
writing_samples through list_items' default 200-row page while the other
eight tables passed an explicit large limit, so any profile with more
than 200 rows in one of those tables exported a silently truncated
archive. These tests seed past that page size in all four tables.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from athenz.experience import ExperienceStore

ROWS = 205


class ExportCompletenessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ExperienceStore(Path(tmp.name) / 'private')
        self.addCleanup(self.store.close)

    def stored(self, table):
        return self.store.db.execute(
            f'SELECT count(*) FROM {table}').fetchone()[0]

    def test_export_includes_every_row_past_the_default_page(self):
        first = self.store.propose('knowledge', 'synthetic oldest identity',
                                   source='owner')
        for i in range(ROWS - 1):
            self.store.propose('knowledge', f'synthetic identity {i}',
                               source='owner')
        for i in range(ROWS):
            self.store.revise(first, f'synthetic revision {i}', 'seed')
        for i in range(ROWS):
            self.store.add_decision(f'synthetic scenario {i}', 'choice A',
                                    'synthetic rationale', source='owner')
            self.store.add_sample(f'synthetic sample {i}', source='owner')
        out = self.store.export()
        for table in ('identity', 'identity_revisions', 'decisions',
                      'writing_samples'):
            self.assertEqual(len(out[table]), self.stored(table), table)
            self.assertGreater(len(out[table]), 200, table)
        # The rows a truncated export dropped were the oldest ones.
        self.assertIn(first, [row['id'] for row in out['identity']])


if __name__ == '__main__':
    unittest.main()
