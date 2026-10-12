"""Private-profile Setup glue remains opt-in and does not leak row content."""
from pathlib import Path
import unittest
from unittest.mock import patch
from athenz.profile_setup import ProfileSetupError, inspect_for_setup, format_for_setup


class ProfileSetupTests(unittest.TestCase):
    def test_requires_separate_confirmation_before_backend(self):
        with patch('athenz.profile_health.inspect_profile', side_effect=AssertionError('read')) as probe:
            for confirmed in (False, None, 1, 'yes'):
                with self.subTest(confirmed=confirmed):
                    with self.assertRaisesRegex(ProfileSetupError, 'confirmation'):
                        inspect_for_setup(Path('/synthetic-private'), confirmed=confirmed)
            probe.assert_not_called()

    def test_forwards_exact_home_with_permission(self):
        home = Path('/synthetic-private')
        returned = {'status': 'not-initialized', 'schema_version': None}
        with patch('athenz.profile_health.inspect_profile', return_value=returned) as probe:
            self.assertIs(inspect_for_setup(home, confirmed=True), returned)
        probe.assert_called_once_with(home, confirmed=True)

    def test_statuses_are_sanitized_and_no_untrusted_content_displays(self):
        statuses = ('not-initialized', 'ok', 'unavailable', 'integrity-failed')
        for status in statuses:
            with self.subTest(status=status):
                report = {'status': status, 'schema_version': 5,
                          'database_owner_only': True,
                          'private_text': 'DO-NOT-SHOW',
                          'path': '/private/canary'}
                text = format_for_setup(report)
                self.assertIn('SQLite schema version: 5', text)
                self.assertNotIn('DO-NOT-SHOW', text)
                self.assertNotIn('/private/canary', text)
                self.assertIn('NOT a restore test', text)

    def test_invalid_status_and_schema_cannot_inject_text(self):
        examples = [None, [], {'status': 'ok\nDO-NOT-SHOW'}, {'status': ['ok']},
                    {'status': 'ok', 'schema_version': '1\nDO-NOT-SHOW'},
                    {'status': 'ok', 'schema_version': True},
                    {'status': 'ok', 'schema_version': -1},
                    {'status': 'ok', 'database_owner_only': 'DO-NOT-SHOW'},
                    {'status': 'ok', 'database_owner_only': 1}]
        for report in examples:
            with self.subTest(report=report):
                with self.assertRaises(ProfileSetupError):
                    format_for_setup(report)

    def test_permission_observation_is_not_access_certification(self):
        text = format_for_setup({'status': 'ok', 'schema_version': 1, 'database_owner_only': False})
        self.assertIn('review file access restrictions', text)
        self.assertNotIn('validated', text.lower())


if __name__ == '__main__':
    unittest.main()
