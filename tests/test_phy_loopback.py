"""The PHY control contract is exercised without changing any real interface."""
import json
from pathlib import Path
import tempfile
import unittest

from phy_loopback import internal_phy, loopback_reference, check_loopback_deltas
from pcap_smoke import generate, write_pcap
from wire_smoke import PACKET_COUNTERS, ERROR_COUNTERS


class FakePhy:
    def __init__(self, fail=None, enabled=0, capable=2):
        self.values = [enabled, enabled]
        self.capable = capable
        self.calls = []
        self.fail = fail

    def state(self, s): return self.values[s['index']], self.capable

    def set(self, s, enable):
        i = s['index']
        self.calls.append((i, enable))
        self.values[i] = 2 if enable else 0
        if (i, enable) == self.fail: raise RuntimeError('uncertain command outcome')

    def down(self, s): self.calls.append(('down', s['index']))


class PhyTests(unittest.TestCase):
    states = [{'index': 0}, {'index': 1}]

    def test_partial_enable_and_interruption_restore_both_ports(self):
        for fail in [(1, True), None]:
            control = FakePhy(fail=fail)
            with self.assertRaises((RuntimeError, KeyboardInterrupt)):
                with internal_phy(self.states, control):
                    raise KeyboardInterrupt()
            self.assertEqual(control.values, [0, 0])
            self.assertIn((0, False), control.calls)
            self.assertIn((1, False), control.calls)

    def test_busy_or_unsupported_rejected_without_mutation(self):
        for control in [FakePhy(enabled=2), FakePhy(capable=1)]:
            with self.assertRaises(ValueError):
                with internal_phy(self.states, control): self.fail('must reject')
            self.assertEqual(control.calls, [])

    def test_failed_restore_does_not_skip_other_port(self):
        control = FakePhy(fail=(1, False))
        with self.assertRaisesRegex(RuntimeError, 'restore'):
            with internal_phy(self.states, control): pass
        self.assertEqual(control.values, [0, 0])
        self.assertIn((0, False), control.calls)

    def test_both_physical_legs_required(self):
        class Ref:
            inputs = {0: [1, 2], 1: [3]}
            expected = {0: [1], 1: [2, 3]}
        before = [{key: 0 for key in PACKET_COUNTERS+ERROR_COUNTERS} for _ in (0, 1)]
        after = [dict(s, rx_packets_phy=3, tx_packets_phy=3) for s in before]
        check_loopback_deltas(before, after, Ref())
        after[0]['rx_packets_phy'] = 2
        with self.assertRaises(ValueError): check_loopback_deltas(before, after, Ref())
        after[0]['rx_packets_phy'] = 3
        after[1]['rx_discards_phy'] = 1
        with self.assertRaises(ValueError): check_loopback_deltas(before, after, Ref())


class LoopbackReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        expected = generate(self.path, extended=True)
        for p in (0, 1): write_pcap(self.path/f'tx{p}.pcap', expected[p])
        (self.path/'result.json').write_text(json.dumps(dict(
            status='PASS', target='upstream', routes=5, extended=True,
            packets=288, per_port={'0': 120, '1': 168})))

    def test_loopback_markers_cannot_hit_capture_guard(self):
        dut = [bytes.fromhex('020000000020'), bytes.fromhex('020000000021')]
        for macs in [dut, [bytes.fromhex('020000000001'), dut[1]]]:
            ref = loopback_reference(self.path, macs)
            for p in (0, 1):
                for frame in ref.inputs[p]:
                    self.assertNotIn(frame[6:12], macs)
                    self.assertEqual(frame[:6], macs[p])
                for frame in ref.expected[p]: self.assertEqual(frame[:12], macs[p]*2)
            self.assertEqual(ref.stats['hardware_forwarded'], [48, 32])


if __name__ == '__main__': unittest.main()
