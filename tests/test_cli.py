"""Set L3_APP to a compiled application to run CLI tests without probing NICs."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('L3_APP'), 'set L3_APP to the compiled executable')
class CliTests(unittest.TestCase):
    def run_app(self, *args):
        return subprocess.run([os.environ['L3_APP'], *args], text=True,
                              capture_output=True, timeout=5)

    def test_help_never_initializes_eal(self):
        result = self.run_app('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--backend', result.stdout)
        self.assertNotIn('EAL:', result.stderr)

    def test_config_check_reads_routes_without_device_access(self):
        result = self.run_app('--check-config', '--backend', 'software',
                              '--routes', str(ROOT/'configs/routes-v4.cfg'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"routes":5', result.stdout)
        self.assertNotIn('EAL:', result.stderr)

    def test_invalid_options_fail_before_eal(self):
        base = ['--check-config', '--backend', 'software',
                '--routes', str(ROOT/'configs/routes-v4.cfg')]
        for extra in (['--duration', 'nan'], ['--duration', '-1'],
                      ['--eth-dest', '0,garbage'], ['--eth-dest', '0,-1:00:00:00:00:01'],
                      ['--eth-dest', '0,0:00:00:00:00:01'], ['--backend', 'typo']):
            with self.subTest(extra=extra):
                result = self.run_app(*(base+extra))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('EAL:', result.stderr)

    def test_physical_mode_requires_explicit_opt_in(self):
        result = self.run_app('--', '--backend', 'doca', '--routes',
                              str(ROOT/'configs/routes-v4.cfg'),
                              '--device', '0000:00:01.0', '--device', '0000:00:01.1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--allow-physical-ports', result.stderr)
        self.assertNotIn('EAL:', result.stderr)

    def test_user_eal_device_allowlist_is_rejected(self):
        result = self.run_app('-a', '0000:00:01.0', '--', '--backend', 'software',
                              '--routes', str(ROOT/'configs/routes-v4.cfg'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('device probing', result.stderr)
        self.assertNotIn('EAL:', result.stderr)

    def test_internal_loopback_requires_doca_and_explicit_opt_in(self):
        base = ['--check-config', '--routes', str(ROOT/'configs/routes-v4.cfg'),
                '--internal-loopback-test']
        for extra in (['--backend', 'software'],
                      ['--backend', 'doca', '--device', '0000:00:01.0',
                       '--device', '0000:00:01.1']):
            result = self.run_app(*(base+extra))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('EAL:', result.stderr)
        result = self.run_app(*(base+['--backend', 'doca', '--device', '0000:00:01.0',
                                     '--device', '0000:00:01.1', '--allow-physical-ports']))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('EAL:', result.stderr)

    def test_checksum_policy_is_explicit_and_defaults_to_upstream(self):
        base = ['--check-config', '--routes', str(ROOT/'configs/routes-v4.cfg'), '--backend', 'doca',
                '--device', '0000:00:01.0', '--device', '0000:00:01.1']
        for extra, policy in [([], 'upstream'), (['--checksum-policy', 'upstream'], 'upstream'),
                              (['--checksum-policy', 'hardware'], 'hardware')]:
            result = self.run_app(*(base+extra))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"checksum_policy":"'+policy+'"', result.stdout)
            self.assertNotIn('EAL:', result.stderr)
        result = self.run_app(*(base+['--checksum-policy', 'ignore']))
        self.assertNotEqual(result.returncode, 0)
        result = self.run_app('--check-config', '--routes', str(ROOT/'configs/routes-v4.cfg'),
                              '--backend', 'software', '--checksum-policy', 'hardware')
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
