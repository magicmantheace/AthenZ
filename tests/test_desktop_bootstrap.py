"""First-launch SQLite initialization precedes concurrent UI workers."""
import concurrent.futures
from pathlib import Path
import tempfile
import unittest

from athenz.desktop import bootstrap_private_home
from athenz.desktop_tasks import DesktopTasks
from athenz.desktop import DesktopService
from athenz.scheduler import ProposalScheduler
from athenz.experience import ExperienceStore


class BootstrapTests(unittest.TestCase):
    def test_first_launch_migrates_before_desktop_background_reads(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / 'fresh'
            bootstrap_private_home(home)
            baseline = ExperienceStore(home)
            try:
                expected_schema = baseline.db.execute('PRAGMA user_version').fetchone()[0]
            finally:
                baseline.close()
            def read(kind):
                if kind == 0:
                    return DesktopTasks(home).list_tasks()
                if kind == 1:
                    return DesktopService(home).pending()
                if kind == 2:
                    return ProposalScheduler(home).list()
                store = ExperienceStore(home)
                try:
                    return store.db.execute('PRAGMA user_version').fetchone()[0]
                finally:
                    store.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                observed = list(pool.map(read, (i % 4 for i in range(24))))
            self.assertTrue(all(x == expected_schema for i,x in enumerate(observed) if i%4 == 3))
            self.assertEqual(observed[0], [])
            self.assertEqual(observed[2], [])


if __name__ == '__main__':
    unittest.main()
