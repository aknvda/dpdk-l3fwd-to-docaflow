"""Controller-level cleanup tests; all physical boundaries are replaced."""
from contextlib import ExitStack
from pathlib import Path
import signal
from itertools import product
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_wire_runner import FakeControl
from wire_smoke import execute


class LifecycleTests(unittest.TestCase):
    def test_signal_during_stop_or_restoration_finishes_cleanup(self):
        for phase, signum in product(('stop', 'restore'), (signal.SIGINT, signal.SIGTERM)):
            with self.subTest(phase=phase, signum=signum), tempfile.TemporaryDirectory() as td:
                directory = Path(td)
                routes = directory/'reference.cfg'
                routes.write_text('synthetic route fixture')
                states = [dict(name=f'port{p}', mac=f'02:00:00:00:00:{p+1:02x}')
                          for p in range(4)]
                process = Mock()
                process.exited = False
                process.poll.side_effect = lambda: 0 if process.exited else None
                order = []

                def wait(**_kwargs):
                    if phase == 'stop': signal.raise_signal(signum)
                    process.exited = True
                    order.append('reaped')
                    return 0
                process.wait.side_effect = wait
                control = FakeControl(states)
                original = control.set_up
                signalled = False

                def set_up(state, value):
                    nonlocal signalled
                    if not value:
                        order.append('restore')
                        if phase == 'restore' and not signalled:
                            signalled = True
                            signal.raise_signal(signum)
                    original(state, value)
                control.set_up = set_up
                reference = SimpleNamespace(inputs={0: [b'a'], 1: [b'b']},
                                            expected={0: [b'c'], 1: [b'd']}, routes=routes,
                                            route_count=5, digests={})
                args = SimpleNamespace(config=None, reference=None, preflight_only=False,
                                       allow_physical_ports=True, startup_timeout=1,
                                       link_timeout=1, pps=200, settle=3)
                config = dict(doca_binary=sys.executable, cpu=0, generator_interfaces=['port2', 'port3'],
                              dut_pci=['0000:01:00.0', '0000:01:00.1'])
                sockets = [Mock(), Mock()]
                socket_count = 0

                def open_socket(_name):
                    nonlocal socket_count
                    self.assertIn('linked', order, 'Bind after link setup to avoid stale ENETDOWN')
                    sock = sockets[socket_count]
                    socket_count += 1
                    return sock
                replacements = dict(load_config=Mock(return_value=config),
                                    admit_ports=Mock(return_value=states),
                                    load_reference=Mock(return_value=reference),
                                    HostControl=Mock(return_value=control),
                                    ip_json=Mock(return_value=[]),
                                    packet_socket=Mock(side_effect=open_socket),
                                    wait_ready=Mock(return_value={'routes': 5, 'checksum_policy': 'upstream'}),
                                    wait_links=Mock(side_effect=lambda *_: order.append('linked')),
                                    packet_drops=Mock(return_value=0),
                                    capture_replay=Mock(), nic_counters=Mock(return_value=[]),
                                    check_nic_deltas=Mock(return_value=[]))
                with ExitStack() as stack:
                    # A regression must fail a test, not terminate its process.
                    previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
                    stack.callback(signal.signal, signal.SIGTERM, previous)
                    for name, value in replacements.items():
                        stack.enter_context(patch('wire_smoke.'+name, value))
                    stack.enter_context(patch('wire_smoke.os.geteuid', return_value=0, create=True))
                    stack.enter_context(patch('wire_smoke.subprocess.Popen', return_value=process))
                    result = execute(args, directory)
                self.assertTrue(process.exited, 'DUT must exit before restoring interfaces')
                self.assertLess(order.index('reaped'), order.index('restore'))
                self.assertEqual(result['status'], 'FAIL')
                self.assertTrue(result['restored'])
                self.assertFalse(any(control.up.values()))
                self.assertEqual(list(control.disabled.values()), [0, 0, 0, 0])
                for sock in sockets: sock.close.assert_called_once()


if __name__ == '__main__': unittest.main()
