import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

import pcap_smoke
from pcap_smoke import compare_frames


class CaptureComparisonTests(unittest.TestCase):
    def test_reordering_is_allowed_but_ports_are_preserved(self):
        compare_frames({0: [b'a', b'b'], 1: [b'c']},
                       {0: [b'b', b'a'], 1: [b'c']})

    def test_loss_duplicates_corruption_and_wrong_port_fail(self):
        expected = {0: [b'a', b'b'], 1: [b'c']}
        for actual in ({0: [], 1: []}, {0: [b'a'], 1: [b'c']},
                       {0: [b'a', b'b', b'b'], 1: [b'c']},
                       {0: [b'a', b'x'], 1: [b'c']},
                       {0: [b'a'], 1: [b'b', b'c']}):
            with self.subTest(actual=actual), self.assertRaises(AssertionError):
                compare_frames(expected, actual)

    def test_delayed_duplicate_is_observed_before_pass(self):
        # A real subprocess emits the correct corpus, then duplicates one frame.
        # Stop-on-expected-count incorrectly reports success before the duplicate.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'fake-dut'
            binary.write_text('''#!/usr/bin/env python3
import signal, sys, time
from pathlib import Path
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
outputs = [Path(arg.split('tx_pcap=')[1]) for arg in sys.argv if 'tx_pcap=' in arg]
for port, output in enumerate(outputs):
    output.write_bytes((output.parent / f'expected{port}.pcap').read_bytes())
time.sleep(0.3)
raw = outputs[0].read_bytes()
# The first expected frame is 60 bytes plus a 16-byte record header.
with outputs[0].open('ab') as stream:
    stream.write(raw[24:24+16+60])
while True:
    time.sleep(1)
''')
            binary.chmod(0o755)
            argv = ['pcap_smoke.py', '--binary', str(binary),
                    '--output', str(root/'captures'), '--timeout', '1']
            with patch('sys.argv', argv), patch.object(
                    pcap_smoke.os, 'sched_getaffinity', return_value={0}, create=True):
                with self.assertRaisesRegex(AssertionError, 'unexpected=1'):
                    pcap_smoke.main()
            self.assertEqual(list((root/'captures').glob('*/result.json')), [])


if __name__ == '__main__':
    unittest.main()
