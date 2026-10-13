"""Sanitized opt-in local NVIDIA inventory; no physical GPU required."""
import json
import subprocess
import unittest
from unittest.mock import patch

from athenz.hardware import HardwareProbeError, gpu_report, cuda_compute_report


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



class CudaComputeTests(unittest.TestCase):
    def test_no_torch_import_without_owner_confirmation(self):
        with patch.dict('sys.modules', {'torch': None}):
            with self.assertRaisesRegex(HardwareProbeError, 'confirm'):
                cuda_compute_report()
        with patch('athenz.hardware.cuda_compute_report',
                   side_effect=AssertionError('unexpected CUDA request')):
            from athenz.preflight import installation_report
            report = installation_report()
        self.assertFalse(any(x['name'] == 'cuda-small-compute' for x in report['checks']))

    def test_missing_pytorch_has_sanitized_status(self):
        with patch.dict('sys.modules', {'torch': None}):
            result = cuda_compute_report(confirmed=True)
        self.assertEqual(result['status'], 'pytorch-unavailable')
        self.assertFalse(result['cuda_compute_observed'])
        self.assertFalse(result['training_validated'])

    def test_fake_cuda_tensor_calculation_and_doctor(self):
        from types import SimpleNamespace
        class Tensor:
            def __init__(self, value): self.value = value
            def __mul__(self, n): return Tensor(self.value * n)
            def sum(self): return Tensor(self.value * 256)
            def item(self): return self.value
        fake = SimpleNamespace(
            float32='float32',
            cuda=SimpleNamespace(is_available=lambda: True,
                                 device_count=lambda: 1,
                                 synchronize=lambda **kwargs: None),
            ones=lambda shape, **kw: Tensor(1))
        with patch.dict('sys.modules', {'torch': fake}):
            observed = cuda_compute_report(confirmed=True)
            self.assertTrue(observed['cuda_compute_observed'])
            from athenz.preflight import installation_report
            doctor = installation_report(probe_cuda=True, confirmed=True)
            self.assertTrue(next(x for x in doctor['checks']
                                 if x['name'] == 'cuda-small-compute')['ok'])
        self.assertFalse(doctor['hardware_validated'])
        self.assertFalse(observed['training_validated'])
        self.assertNotIn('cuda:0', json.dumps(observed))

    def test_cuda_availability_probe_exception_is_not_a_compute_success(self):
        from types import SimpleNamespace
        def raise_driver_error():
            raise RuntimeError('PRIVATE-LOCAL-CUDA-PATH')
        fake = SimpleNamespace(cuda=SimpleNamespace(is_available=raise_driver_error))
        with patch.dict('sys.modules', {'torch': fake}):
            info = cuda_compute_report(confirmed=True)
        self.assertFalse(info['cuda_runtime_available'])
        self.assertFalse(info['cuda_compute_observed'])
        self.assertNotIn('PRIVATE', json.dumps(info))

    def test_failed_cuda_kernel_never_exposes_driver_diagnostics(self):
        from types import SimpleNamespace
        fake = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1),
            float32='float32',
            ones=lambda *args, **kwargs:
                (_ for _ in ()).throw(RuntimeError('PRIVATE-NVIDIA-GPU-UUID')))
        with patch.dict('sys.modules', {'torch': fake}):
            result = cuda_compute_report(confirmed=True)
        self.assertEqual(result['status'], 'cuda-compute-failed')
        self.assertFalse(result['cuda_compute_observed'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_doctor_cuda_probe_is_separately_confirmed(self):
        from athenz.preflight import installation_report
        with self.assertRaisesRegex(HardwareProbeError, 'confirm'):
            installation_report(probe_cuda=True)

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

    def test_cli_wires_explicit_cuda_consent_without_running_probe(self):
        from athenz.preflight import main
        expected = {'schema': 1, 'checks': [], 'hardware_validated': False}
        with patch('athenz.preflight.installation_report',
                   return_value=expected) as report, \
             patch('builtins.print') as display:
            main(['--probe-cuda', '--confirm'])
        report.assert_called_once_with(probe_ollama=False, probe_gpu=False,
                                       probe_cuda=True, confirmed=True)
        self.assertEqual(json.loads(display.call_args.args[0]), expected)

    def test_requires_confirmation_via_readiness_entrypoint(self):
        from athenz.preflight import installation_report
        with self.assertRaisesRegex(HardwareProbeError, 'confirm'):
            installation_report(probe_gpu=True)


if __name__ == '__main__':
    unittest.main()
