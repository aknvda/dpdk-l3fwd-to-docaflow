import copy
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from wire_capture import capture_replay
from wire_ports import admit_ports, isolated_ports, private_run_dir, wait_links, LinkUnavailable
from wire_smoke import load_config, check_nic_deltas, nic_counters

# Fixed mlx5 physical counter contract, independent of the production parser.
ERROR_COUNTERS = ('rx_crc_errors_phy', 'rx_in_range_len_errors_phy',
                  'rx_out_of_range_len_phy', 'rx_oversize_pkts_phy',
                  'rx_symbol_err_phy', 'rx_unsupported_op_phy', 'rx_discards_phy',
                  'tx_discards_phy', 'tx_errors_phy', 'rx_undersize_pkts_phy',
                  'rx_fragments_phy', 'rx_jabbers_phy')


def physical_snapshot(packets):
    return [dict(rx_packets_phy=packets, tx_packets_phy=packets,
                 **dict.fromkeys(ERROR_COUNTERS, 0)) for _ in range(4)]


class PortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.devices = ['0000:01:00.0', '0000:01:00.1', '0000:02:00.0', '0000:02:00.1']
        self.names = ['dut0', 'dut1', 'gen0', 'gen1']
        self.links = []
        (self.root/'class/net').mkdir(parents=True)
        for i, (pci, name) in enumerate(zip(self.devices, self.names)):
            dev = self.root/'bus/pci/devices'/pci
            net = dev/'net'/name
            net.mkdir(parents=True)
            (dev/'sriov_numvfs').write_text('0')
            (net/'device').symlink_to(dev)
            (self.root/'class/net'/name).symlink_to(net)
            self.links.append(dict(ifname=name, ifindex=i+10, flags=['BROADCAST'], mtu=1500,
                                   address=f'02:00:00:00:00:{i+1:02x}', addr_info=[]))

    def admit(self):
        return admit_ports(self.devices[:2], self.names[2:], self.root, self.links)

    def test_admits_only_two_distinct_isolated_adapters(self):
        self.assertEqual([p['name'] for p in self.admit()], self.names)
        for links in [self.links[:3], self.links+[]]:
            bad = copy.deepcopy(links)
            if len(bad) == 4:
                bad[3]['addr_info'] = [{'family': 'inet6'}]
            with self.assertRaises(ValueError):
                admit_ports(self.devices[:2], self.names[2:], self.root, bad)
        for field, value in [('flags', ['UP']), ('mtu', 9000), ('mtu', 1400)]:
            old = self.links[0][field]
            self.links[0][field] = value
            with self.assertRaises(ValueError): self.admit()
            self.links[0][field] = old
        with self.assertRaises(ValueError):
            admit_ports(self.devices[:2], self.names[:2], self.root, self.links)

    def test_sibling_vfs_and_upper_interfaces_rejected(self):
        vf = self.root/'bus/pci/devices'/self.devices[2]/'sriov_numvfs'
        vf.write_text('1')
        with self.assertRaises(ValueError): self.admit()

        vf.write_text('0')
        upper = self.root/'class/net/gen0/upper_bridge'
        upper.touch()
        with self.assertRaises(ValueError): self.admit()
        upper.unlink()
        self.links[3]['flags'].append('UP')
        with self.assertRaises(ValueError): self.admit()

    def test_internal_loopback_admits_only_isolated_dut(self):
        self.links[2]['flags'].append('UP')  # Unrelated generator is not selected.
        states = admit_ports(self.devices[:2], None, self.root, self.links)
        self.assertEqual([s['name'] for s in states], self.names[:2])
        self.links[1]['flags'].append('UP')
        with self.assertRaises(ValueError):
            admit_ports(self.devices[:2], None, self.root, self.links)

    def test_private_output_rejects_git_tree(self):
        (self.root/'.git').mkdir()
        with self.assertRaises(ValueError): private_run_dir(self.root/'artifacts')
        (self.root/'.git').rmdir()
        path = private_run_dir(self.root/'private')
        self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_cleanup_runs_on_partial_setup_and_cancellation(self):
        states = self.admit()
        for fail_at in [None, 'dut1']:
            control = FakeControl(states, fail_at)
            with self.assertRaises((KeyboardInterrupt, OSError)):
                with isolated_ports(states, control):
                    control.set_up(states[2], True)
                    raise KeyboardInterrupt()
            self.assertEqual(control.disabled, {name: 0 for name in self.names})
            self.assertFalse(any(control.up.values()))

    def test_restoration_failure_is_not_silent(self):
        states = self.admit()
        control = FakeControl(states)
        with self.assertRaisesRegex(RuntimeError, 'restore'):
            with isolated_ports(states, control):
                control.bad_identity = True

    def test_down_failure_still_restores_ipv6_and_other_ports(self):
        states = self.admit()
        control = FakeControl(states)
        original = control.set_up

        def set_up(state, value):
            if state['name'] == 'gen1' and not value:
                raise OSError('injected port-down failure')
            original(state, value)
        control.set_up = set_up
        with self.assertRaisesRegex(RuntimeError, 'port-down failure'):
            with isolated_ports(states, control):
                for state in states: control.set_up(state, True)
        self.assertEqual(control.disabled, {name: 0 for name in self.names})
        self.assertTrue(control.up['gen1'])  # The failed action is still reported.
        self.assertFalse(any(control.up[name] for name in self.names if name != 'gen1'))

    def test_missing_link_and_dead_dut_fail(self):
        with self.assertRaises(LinkUnavailable):
            wait_links(self.admit(), .03, lambda: True, lambda state: False)
        with self.assertRaises(RuntimeError):
            wait_links(self.admit(), 1, lambda: False, lambda state: True)

    def test_config_rejects_unknown_keys_and_unavailable_cpu(self):
        import sys
        path = self.root/'config.json'
        config = dict(doca_binary=sys.executable, dut_pci=self.devices[:2],
                      generator_interfaces=self.names[2:], cpu=2)
        with patch('wire_smoke.os.sched_getaffinity', return_value={2}, create=True):
            path.write_text(json.dumps(config))
            self.assertEqual(load_config(path)['cpu'], 2)
            for key, value in [('cpu', 3), ('extra', True), ('dut_pci', 'wrong')]:
                path.write_text(json.dumps(dict(config, **{key: value})))
                with self.assertRaises(ValueError): load_config(path)

    def test_nic_counters_must_cover_all_four_ports(self):
        from types import SimpleNamespace
        ref = SimpleNamespace(inputs={0: [b'a'], 1: [b'b']}, expected={0: [b'c'], 1: [b'd']})
        zero, one = physical_snapshot(0), physical_snapshot(1)
        self.assertEqual(len(check_nic_deltas(zero, one, ref)), 4)
        for before, after in [(zero, zero), (one, zero), ([], []), (zero, one[:3])]:
            with self.assertRaises(ValueError): check_nic_deltas(before, after, ref)

    def test_nic_errors_discards_resets_and_missing_counters_fail(self):
        from types import SimpleNamespace
        ref = SimpleNamespace(inputs={0: [b'a'], 1: [b'b']}, expected={0: [b'c'], 1: [b'd']})
        zero, one = physical_snapshot(0), physical_snapshot(1)
        for key in ERROR_COUNTERS:
            for port in range(4):
                after = copy.deepcopy(one)
                after[port][key] = 1
                with self.subTest(key=key, port=port), self.assertRaises(ValueError):
                    check_nic_deltas(zero, after, ref)
        before = copy.deepcopy(zero)
        before[0]['rx_crc_errors_phy'] = 10
        with self.assertRaises(ValueError): check_nic_deltas(before, one, ref)
        missing = copy.deepcopy(one)
        del missing[2]['tx_discards_phy']
        with self.assertRaises(ValueError): check_nic_deltas(zero, missing, ref)

    def test_nic_snapshot_retains_required_errors_and_rejects_missing(self):
        counters = physical_snapshot(7)[0]
        output = '\n'.join(f'    {key}: {value}' for key, value in counters.items())+'\n'
        with patch('wire_smoke.subprocess.check_output', return_value=output):
            self.assertEqual(nic_counters(self.admit(), self.root, 'before'), [counters]*4)
        missing = output.replace('    rx_crc_errors_phy: 0\n', '')
        with patch('wire_smoke.subprocess.check_output', return_value=missing):
            with self.assertRaises(ValueError): nic_counters(self.admit(), self.root, 'after')


class FakeControl:
    def __init__(self, states, fail_at=None):
        self.disabled = {s['name']: 0 for s in states}
        self.up = {s['name']: False for s in states}
        self.fail_at = fail_at
        self.bad_identity = False

    def identity(self, state):
        if self.bad_identity: raise RuntimeError('Interface identity changed')

    def read_ipv6(self, state): return self.disabled[state['name']]

    def set_ipv6(self, state, value):
        if self.fail_at == state['name'] and value == 1:
            self.fail_at = None
            raise OSError('injected sysctl failure')
        self.disabled[state['name']] = value

    def set_up(self, state, value): self.up[state['name']] = value
    def verify(self, state):
        self.identity(state)
        if self.up[state['name']]: raise RuntimeError('Still UP')


class CaptureTests(unittest.TestCase):
    def test_replay_observes_late_duplicate_and_both_ports(self):
        pairs = [socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM) for _ in (0, 1)]
        for pair in pairs:
            for sock in pair: self.addCleanup(sock.close)
        packets = {0: [b'input0'], 1: [b'input1']}

        def reply():
            self.assertEqual(pairs[0][1].recv(100), b'input0')
            pairs[0][1].send(b'output0')
            self.assertEqual(pairs[1][1].recv(100), b'input1')
            pairs[1][1].send(b'output1')
            time.sleep(.04)
            pairs[0][1].send(b'output0')
        thread = threading.Thread(target=reply, daemon=True)
        thread.start()
        actual = capture_replay([p[0] for p in pairs], packets, 100, .1, lambda: True)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(actual, {0: [b'output0', b'output0'], 1: [b'output1']})

    def test_dut_exit_stops_replay(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.addCleanup(a.close); self.addCleanup(b.close)
        with self.assertRaises(RuntimeError):
            capture_replay([a, b], {0: [b'x'], 1: [b'y']}, 100, .1, lambda: False)


if __name__ == '__main__': unittest.main()
