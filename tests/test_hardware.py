"""Sanitized opt-in local NVIDIA inventory; no physical GPU required."""
import json
import subprocess
import unittest
from unittest.mock import patch

from athenz.hardware import HardwareProbeError, gpu_report


class HardwareTests(unittest.TestCase):
    def test_no_probe_without_confirm_and_timeout_is_bounded(self):
        with patch('athenz.hardware.shutil.which', side_effect=AssertionError('no host query')):
            with self.assertRaisesRegex(HardwareProbeError, 'confirm'):
                gpu_report()
        with self.assertRaisesRegex(HardwareProbeError, 'timeout'):
            gpu_report(confirmed=True, timeout=0)

    def test_missing_nvidia_is_safe_not_training_certified(self):
        with patch('athenz.hardware.shutil.which', return_value=None):
            info = gpu_report(confirmed=True)
        self.assertFalse(info['gpu_detected'])
        self.assertEqual(info['status'], 'nvidia-smi-not-found')
        self.assertFalse(info['cuda_validated'])
        self.assertFalse(info['training_validated'])

    def test_sanitized_12gb_gpu_probe_does_not_expose_model_identity(self):
        def fake(argv, **opts):
            self.assertEqual(argv, ['/trusted/nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader,nounits'])
            self.assertEqual(opts['timeout'], 8)
            self.assertFalse(opts['shell'])
            return subprocess.CompletedProcess(argv, 0, '12288\n', 'secret serial SN-123')
        with patch('athenz.hardware.shutil.which', return_value='/trusted/nvidia-smi'), \
             patch('athenz.hardware.subprocess.run', side_effect=fake):
            info = gpu_report(confirmed=True)
        self.assertEqual(info['memory_mib'], [12288])
        self.assertTrue(info['gpu_detected'])
        self.assertEqual(info['gpu_count'], 1)
        self.assertFalse(info['training_validated'])
        self.assertNotIn('serial', json.dumps(info).lower())
        self.assertNotIn('SN-123', json.dumps(info))

    def test_invalid_data_or_timeout_does_not_disclose_stdout_stderr(self):
        with patch('athenz.hardware.shutil.which', return_value='/bin/nvidia-smi'):
            for output in ('GPU0: 12288 MiB\n', '-3\n', '123456789\n', '14\n', 'secret\n'):
                with self.subTest(output=output), patch('athenz.hardware.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output, 'private')):
                    self.assertEqual(gpu_report(confirmed=True)['status'], 'malformed-inventory')
            with patch('athenz.hardware.subprocess.run', side_effect=subprocess.TimeoutExpired('gpu', 8)):
                info = gpu_report(confirmed=True)
                self.assertEqual(info['status'], 'local-query-unavailable')
                self.assertNotIn('gpu', str(info.get('message', '')))

    def test_multiple_gpus_and_command_failure(self):
        with patch('athenz.hardware.shutil.which', return_value='/bin/nvidia-smi'), \
             patch('athenz.hardware.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '8192\n12288\n', '')):
            info = gpu_report(confirmed=True)
            self.assertEqual(info['gpu_count'], 2)
        with patch('athenz.hardware.shutil.which', return_value='/bin/nvidia-smi'), \
             patch('athenz.hardware.subprocess.run', return_value=subprocess.CompletedProcess([], 2, 'private-path', 'private-error')):
            info = gpu_report(confirmed=True)
            self.assertEqual(info['status'], 'local-query-unavailable')
            self.assertNotIn('private', json.dumps(info))


class HardwareCLITests(unittest.TestCase):
    def test_default_readiness_does_not_call_hardware_probe(self):
        from athenz.preflight import installation_report
        with patch('athenz.hardware.gpu_report', side_effect=AssertionError('unexpected probe')):
            r = installation_report()
        self.assertFalse(any(check['name'] == 'nvidia-vram' for check in r['checks']))

    def test_explicit_cli_readiness_scrubs_hardware_identity(self):
        from athenz.preflight import installation_report
        with patch('athenz.hardware.gpu_report', return_value={
                'gpu_detected':True, 'gpu_count':1,'memory_mib':[12288]} ) as gpu:
            r = installation_report(probe_gpu=True, confirmed=True)
        gpu.assert_called_once_with(confirmed=True)
        details = [x for x in r['checks'] if x['name'] == 'nvidia-vram'][0]
        self.assertTrue(details['ok'])
        self.assertIn('12288 MiB', details['note'])
        self.assertFalse(r['hardware_validated'])

    def test_requires_confirmation_via_readiness_entrypoint(self):
        from athenz.preflight import installation_report
        with self.assertRaisesRegex(HardwareProbeError, 'confirm'):
            installation_report(probe_gpu=True)


if __name__ == '__main__':
    unittest.main()
