import json
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

from pcap_smoke import generate, read_pcap, write_pcap
from wire_common import load_reference, check_run, wait_ready, stop_process

DUT = [bytes.fromhex('020000000020'), bytes.fromhex('020000000021')]
PEER = [bytes.fromhex('020000000030'), bytes.fromhex('020000000031')]


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        expected = generate(self.path, extended=True)
        for p in (0, 1):
            write_pcap(self.path/f'tx{p}.pcap', expected[p])
        self.result = dict(status='PASS', target='upstream', routes=5, extended=True,
                           packets=288, per_port={'0': 120, '1': 168})
        self.save_result()

    def save_result(self):
        (self.path/'result.json').write_text(json.dumps(self.result))

    def test_mac_adaptation_preserves_every_other_byte(self):
        reference = load_reference(self.path, DUT, PEER)
        for p in (0, 1):
            for before, after in zip(read_pcap(self.path/f'rx{p}.pcap'), reference.inputs[p]):
                self.assertEqual(after, DUT[p]+PEER[p]+before[12:])
            for before, after in zip(read_pcap(self.path/f'tx{p}.pcap'), reference.expected[p]):
                self.assertEqual(after, PEER[p]+DUT[p]+before[12:])
        self.assertEqual(reference.stats['hardware_forwarded'], [48, 32])
        self.assertEqual(reference.stats['software_rx'], [96, 112])
        self.assertEqual(reference.stats['software_tx'], [88, 120])

    def test_incomplete_or_non_upstream_reference_rejected(self):
        for key, value in [('status', 'FAIL'), ('target', 'software'), ('extended', False),
                           ('routes', 1025), ('packets', 0)]:
            old = self.result[key]
            self.result[key] = value
            self.save_result()
            with self.assertRaises((ValueError, AssertionError)):
                load_reference(self.path, DUT, PEER)
            self.result[key] = old

    def test_modified_input_routes_and_output_rejected(self):
        for name in ['rx0.pcap', 'tx1.pcap', 'routes-v4.cfg']:
            path = self.path/name
            before = path.read_bytes()
            path.write_bytes(before[:-1]+bytes([before[-1] ^ 1]))
            with self.assertRaises((ValueError, AssertionError)):
                load_reference(self.path, DUT, PEER)
            path.write_bytes(before)

    def test_counter_and_capture_failures_cannot_pass(self):
        ref = load_reference(self.path, DUT, PEER)
        events = [dict(event='ready', backend='doca', routes=5), dict(event='stats', **ref.stats)]
        check_run(ref, ref.expected, events, 0, '', [0, 0])
        for key in ref.stats:
            wrong = json.loads(json.dumps(events))
            if isinstance(wrong[1][key], list):
                wrong[1][key][0] += 1
            else:
                wrong[1][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_run(ref, ref.expected, wrong, 0, '', [0, 0])
        for exit_code, log, drops in [(1, '', [0, 0]), (0, '[DOCA][ERR] bad', [0, 0]),
                                       (0, '', [0, 1])]:
            with self.assertRaises(ValueError):
                check_run(ref, ref.expected, events, exit_code, log, drops)
        for bad_events in [events[1:], events[:1], events+events, []]:
            with self.assertRaises(ValueError):
                check_run(ref, ref.expected, bad_events, 0, '', [0, 0])
        duplicate = {p: list(v) for p, v in ref.expected.items()}
        duplicate[0].append(duplicate[0][0])
        with self.assertRaises(AssertionError):
            check_run(ref, duplicate, events, 0, '', [0, 0])


class ProcessTests(unittest.TestCase):
    def test_readiness_timeout_and_early_exit(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td)/'app.log'
            for code in ['import time; time.sleep(10)', 'raise SystemExit(7)']:
                with log.open('w') as stream:
                    p = subprocess.Popen([sys.executable, '-c', code], stdout=stream, stderr=stream)
                    try:
                        with self.assertRaises(RuntimeError):
                            wait_ready(p, log, .1)
                    finally:
                        stop_process(p)
                self.assertIsNotNone(p.poll())

    def test_cancellation_during_real_child_wait_reaps_child(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td)/'app.log'
            code = ('import signal,sys,time; signal.signal(signal.SIGINT,lambda *_:sys.exit(0)); '
                    "print('{\"event\":\"ready\",\"backend\":\"doca\",\"routes\":5}',flush=True); time.sleep(10)")
            with log.open('w') as stream:
                process = subprocess.Popen([sys.executable, '-c', code], stdout=stream, stderr=stream)
                try:
                    wait_ready(process, log, 2)
                    wait = process.wait

                    def interrupted_wait(*args, **kwargs):
                        signal.raise_signal(signal.SIGINT)
                        return wait(*args, **kwargs)
                    with patch.object(process, 'wait', side_effect=interrupted_wait):
                        with self.assertRaises(KeyboardInterrupt): stop_process(process)
                    self.assertEqual(process.poll(), 0)
                finally:
                    if process.poll() is None: process.kill()
                    process.wait(timeout=2)

    def test_ready_requires_live_process_and_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td)/'app.log'
            code = 'import time; print(\'{"event":"ready","backend":"doca","routes":5}\',flush=True); time.sleep(10)'
            with log.open('w') as stream:
                p = subprocess.Popen([sys.executable, '-c', code], stdout=stream, stderr=stream)
                try:
                    self.assertEqual(wait_ready(p, log, 2)['routes'], 5)
                finally:
                    stop_process(p)


if __name__ == '__main__':
    unittest.main()
