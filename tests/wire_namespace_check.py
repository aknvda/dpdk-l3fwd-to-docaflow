#!/usr/bin/env python3
"""Validate the wire harness with Linux veth pairs, never as DOCA evidence."""
import argparse
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import threading
import time

from pcap_smoke import compare_frames, packet
from wire_capture import capture_replay
from wire_smoke import packet_socket, packet_drops


def run_case(mode, generators, peers):
    inputs, expected, replies = {0: [], 1: []}, {0: [], 1: []}, {}
    for ingress in (0, 1):
        frame = packet('192.0.2.1', 124, ingress+1, 64,
                       bytes.fromhex(f'02000000002{ingress}'), bytes.fromhex(f'02000000003{ingress}'))
        # Fixture outputs are deliberately distinct from the inputs. This tests
        # capture/routing of bytes, not a software emulation of DOCA forwarding.
        egress = ingress ^ 1
        answer = bytes.fromhex(f'02000000003{egress}02000000002{egress}')+frame[12:-1]+b'X'
        inputs[ingress].append(frame)
        expected[egress].append(answer)
        replies[frame] = (egress, answer)
    sockets = [packet_socket(n) for n in generators]
    ends = [packet_socket(n) for n in peers]
    errors, seen = [], []
    stop = threading.Event()

    def fixture():
        try:
            while len(seen) < 2 and not stop.is_set():
                ready, _, _ = select.select(ends, [], [], .05)
                for sock in ready:
                    frame, address = sock.recvfrom(65536)
                    if address[2] == 4: continue
                    egress, answer = replies[frame]
                    if mode == 'wrong-port': egress ^= 1
                    ends[egress].send(answer)
                    seen.append(frame)
            if mode == 'late-duplicate' and not stop.wait(.10):
                ends[0].send(expected[0][0])
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=fixture, daemon=True)
    thread.start()
    try:
        actual = capture_replay(sockets, inputs, 100, .3, lambda: not errors)
        if any(packet_drops(sock) for sock in sockets): raise AssertionError('Capture overflow')
        thread.join(1)
        if errors: raise errors[0]
        assert len(seen) == 2 and not thread.is_alive()
        if mode == 'ordinary':
            compare_frames(expected, actual)
        else:
            try: compare_frames(expected, actual)
            except AssertionError: pass
            else: raise AssertionError(f'Harness accepted {mode}')
    finally:
        stop.set()
        thread.join(1)
        for sock in sockets+ends: sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Requires Linux root for an isolated temporary network namespace')
    if not args.inside:
        return subprocess.call(['unshare', '--net', '--', sys.executable,
                                str(Path(__file__).resolve()), '--inside'])
    # Refuse to set up fixtures in any namespace with existing non-loopback links.
    links = json.loads(subprocess.check_output(['ip', '-json', 'link', 'show'], text=True))
    if any(link['ifname'] != 'lo' for link in links):
        raise RuntimeError('Fixture requires a fresh empty network namespace')
    generators, peers = ['wg0', 'wg1'], ['wd0', 'wd1']
    for p in (0, 1):
        subprocess.run(['ip', 'link', 'add', generators[p], 'type', 'veth', 'peer', 'name', peers[p]], check=True)
        for name, mac in [(generators[p], f'02:00:00:00:00:3{p}'), (peers[p], f'02:00:00:00:00:2{p}')]:
            (Path('/proc/sys/net/ipv6/conf')/name/'disable_ipv6').write_text('1')
            subprocess.run(['ip', 'link', 'set', name, 'address', mac, 'up'], check=True)
    for mode in ['ordinary', 'late-duplicate', 'wrong-port']:
        run_case(mode, generators, peers)
    print(json.dumps(dict(status='HARNESS_PASS', cases=3,
                         scope='Linux veth packet I/O only; no DOCA or physical NIC validation')))
    return 0


if __name__ == '__main__': sys.exit(main())
