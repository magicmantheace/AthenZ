"""Owner-authorized Setup GPU probe; no physical GPU or window required."""
from __future__ import annotations

import unittest
from unittest import mock

from athenz.desktop import DesktopError, owner_requested_readiness


class OwnerSetupReadinessTests(unittest.TestCase):
    def test_default_preflight_cannot_query_gpu_or_ollama(self):
        with mock.patch('athenz.preflight.installation_report', return_value={'checks': []}) as check:
            self.assertEqual(owner_requested_readiness(), {'checks': []})
        check.assert_called_once_with(probe_ollama=False, probe_gpu=False, confirmed=False)

    def test_gpu_requires_separate_confirmation_before_backend(self):
        with mock.patch('athenz.preflight.installation_report') as check:
            with self.assertRaisesRegex(DesktopError, 'GPU probe confirmation'):
                owner_requested_readiness(probe_gpu=True)
        check.assert_not_called()

    def test_gpu_permission_is_not_inherited_from_ollama(self):
        with mock.patch('athenz.preflight.installation_report', return_value={'checks': []}) as check:
            owner_requested_readiness(probe_ollama=True)
        check.assert_called_once_with(probe_ollama=True, probe_gpu=False, confirmed=False)

    def test_confirmed_gpu_probe_is_only_optional_inventory(self):
        response = {'schema': 1, 'checks': [{'name': 'nvidia-vram', 'ok': True,
                    'note': 'Observed 1 local NVIDIA GPU; CUDA/training NOT validated'}],
                    'hardware_validated': False, 'startup_authorized': False}
        with mock.patch('athenz.preflight.installation_report', return_value=response) as check:
            result = owner_requested_readiness(probe_gpu=True, gpu_confirmed=True)
        check.assert_called_once_with(probe_ollama=False, probe_gpu=True, confirmed=True)
        self.assertFalse(result['hardware_validated'])
        self.assertFalse(result['startup_authorized'])

    def test_unrelated_confirmation_cannot_trigger_gpu_inventory(self):
        with mock.patch('athenz.preflight.installation_report', return_value={'checks': []}) as check:
            owner_requested_readiness(gpu_confirmed=True)
        check.assert_called_once_with(probe_ollama=False, probe_gpu=False, confirmed=False)


if __name__ == '__main__':
    unittest.main()
