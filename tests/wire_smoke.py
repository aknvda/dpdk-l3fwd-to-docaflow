#!/usr/bin/env python3
"""Compare a reserved two-port DOCA DUT with an actual upstream PCAP reference.

Same-host, low-rate functional validation only. Raw artifacts must remain private.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import sys

from pcap_smoke import write_pcap
from wire_capture import capture_replay
from wire_common import check_run, load_reference, read_events, stop_process, wait_ready
from wire_ports import (HostControl, LinkUnavailable, admit_ports, ip_json,
                        isolated_ports, private_run_dir, wait_links)


def load_config(path):
    config = json.loads(Path(path).read_text())
    if not isinstance(config, dict) or set(config) != {'doca_binary', 'dut_pci', 'generator_interfaces', 'cpu'}:
        raise ValueError('Config requires exactly doca_binary, dut_pci, generator_interfaces and cpu')
    if any(not isinstance(config[k], list) or any(not isinstance(x, str) for x in config[k])
           for k in ['dut_pci', 'generator_interfaces']):
        raise ValueError('Devices and interfaces must be string arrays')
    if type(config['cpu']) is not int or config['cpu'] not in os.sched_getaffinity(0):
        raise ValueError('DUT CPU must be available in the current CPU affinity mask')
    binary = Path(config['doca_binary']).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('DOCA binary must be an executable file')
    config['doca_binary'] = str(binary)
    return config


def packet_socket(name):
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4*1024*1024)
        sock.bind((name, 0))
        return sock
    except BaseException:
        sock.close()
        raise


def packet_drops(sock):
    # Linux PACKET_STATISTICS: packet count and capture drops, reset on read.
    return struct.unpack('II', sock.getsockopt(263, 6, 8))[1]


def nic_counters(states, directory, label):
    counters = []
    for i, state in enumerate(states):
        output = subprocess.check_output(['ethtool', '-S', state['name']], text=True, timeout=10)
        (directory/f'{label}-nic-{i}.txt').write_text(output)
        values = {k: int(v) for k, v in re.findall(r'^\s*(rx_packets_phy|tx_packets_phy):\s*(\d+)\s*$',
                                                 output, re.MULTILINE)}
        if len(values) != 2:
            raise ValueError('NIC must expose rx_packets_phy and tx_packets_phy counters')
        counters.append(values)
    return counters


def check_nic_deltas(before, after, reference):
    if len(before) != 4 or len(after) != 4:
        raise ValueError('Require physical counter snapshots for all four ports')
    deltas = []
    for i, (first, last) in enumerate(zip(before, after)):
        p = i % 2
        rx = len(reference.inputs[p]) if i < 2 else len(reference.expected[p])
        tx = len(reference.expected[p]) if i < 2 else len(reference.inputs[p])
        delta = {key: last[key]-first[key] for key in first}
        if delta['rx_packets_phy'] < rx or delta['tx_packets_phy'] < tx:
            raise ValueError('Physical NIC counter deltas do not cover the complete corpus')
        deltas.append(delta)
    return deltas


def execute(args, directory):
    config = load_config(args.config)
    states = admit_ports(config['dut_pci'], config['generator_interfaces'])
    macs = [bytes.fromhex(s['mac'].replace(':', '')) for s in states]
    reference = load_reference(args.reference, macs[:2], macs[2:])
    (directory/'inventory.json').write_text(json.dumps(states, indent=2)+'\n')
    (directory/'reference-hashes.json').write_text(json.dumps(reference.digests, indent=2)+'\n')
    # Own the route file used by this run; avoid a later edit to the reference.
    (directory/'routes-v4.cfg').write_bytes(reference.routes.read_bytes())
    for p in (0, 1):
        write_pcap(directory/f'input{p}.pcap', reference.inputs[p])
        write_pcap(directory/f'expected{p}.pcap', reference.expected[p])
    if args.preflight_only:
        return dict(status='PREFLIGHT', scope='read-only admission; no packet test', routes=reference.route_count)
    if not args.allow_physical_ports or os.geteuid() != 0:
        raise ValueError('Physical execution requires root and --allow-physical-ports')
    control = HostControl()
    ipv6_before = [control.read_ipv6(s) for s in states]
    route_before = ip_json('route', 'show', 'default')
    result = dict(status='FAIL', scope='physical IPv4 functional test; no performance claim',
                  routes=reference.route_count, traffic_sent=False, restored=False)
    command = [config['doca_binary'], '--lcores', f"0@{config['cpu']}", '-m', '128',
               '--in-memory', '--file-prefix', directory.name, '--no-telemetry', '--',
               '--backend', 'doca', '--routes', str(directory/'routes-v4.cfg'),
               '--device', config['dut_pci'][0], '--device', config['dut_pci'][1],
               '--allow-physical-ports', '--eth-dest', '0,'+states[2]['mac'],
               '--eth-dest', '1,'+states[3]['mac']]
    (directory/'command.json').write_text(json.dumps(command, indent=2)+'\n')
    result['binary_sha256'] = hashlib.sha256(Path(config['doca_binary']).read_bytes()).hexdigest()
    actual, drops = {0: [], 1: []}, [0, 0]
    log = directory/'doca.log'
    try:
        with isolated_ports(states, control):
            sockets, process = [], None
            try:
                for state in states[2:]: sockets.append(packet_socket(state['name']))
                with log.open('w') as stream:
                    process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                               start_new_session=True)
                    ready = wait_ready(process, log, args.startup_timeout)
                    if ready.get('routes') != reference.route_count:
                        raise ValueError('DUT loaded a different route count')
                    for state in states[2:]: control.set_up(state, True)
                    wait_links(states, args.link_timeout, lambda: process.poll() is None)
                    before = nic_counters(states, directory, 'before')
                    result['traffic_sent'] = True  # Conservative: replay may fail after a partial send.
                    capture_replay(sockets, reference.inputs, args.pps, args.settle,
                                   lambda: process.poll() is None, actual)
                    drops = [packet_drops(s) for s in sockets]
                    after = nic_counters(states, directory, 'after')
                    result['nic_deltas'] = check_nic_deltas(before, after, reference)
            finally:
                try:
                    if process is not None: result['exit_code'] = stop_process(process)
                finally:
                    for sock in sockets: sock.close()
        text = log.read_text()
        events = read_events(text)
        check_run(reference, actual, events, result['exit_code'], text, drops)
        result.update(status='PASS', packets=sum(map(len, actual.values())), counters=events[1])
    except LinkUnavailable as error:
        result.update(status='BLOCKED', error=str(error))
    except (Exception, KeyboardInterrupt) as error:
        result.update(status='FAIL', error=str(error) or 'Interrupted')
    finally:
        for p in (0, 1): write_pcap(directory/f'capture{p}.pcap', actual[p])
        result['capture_drops'] = drops
        try:
            for state, ipv6 in zip(states, ipv6_before):
                control.verify(state)
                if control.read_ipv6(state) != ipv6: raise RuntimeError('IPv6 setting was not restored')
            if ip_json('route', 'show', 'default') != route_before:
                raise RuntimeError('Default management route changed')
            result['restored'] = True
        except Exception as error:
            result.update(status='FAIL', restoration_error=str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='private JSON configuration')
    parser.add_argument('--reference', type=Path, required=True, help='passing extended upstream PCAP run directory')
    parser.add_argument('--output', type=Path, required=True, help='private directory outside Git')
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--allow-physical-ports', action='store_true')
    parser.add_argument('--pps', type=float, default=200, help='aggregate offered packets/s, 1..1000')
    parser.add_argument('--settle', type=float, default=3, help='post-send capture/counter settling seconds, >=3')
    parser.add_argument('--startup-timeout', type=float, default=45)
    parser.add_argument('--link-timeout', type=float, default=15)
    args = parser.parse_args()
    if sys.platform != 'linux': parser.error('Physical replay requires Linux')
    if not math.isfinite(args.pps) or not 1 <= args.pps <= 1000: parser.error('--pps must be 1..1000')
    if not math.isfinite(args.settle) or not 3 <= args.settle <= 60: parser.error('--settle must be 3..60')
    if any(not math.isfinite(v) or not 0 < v <= 300 for v in [args.startup_timeout, args.link_timeout]):
        parser.error('Timeouts must be finite and in (0,300]')
    def interrupted(_signum, _frame): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    directory = private_run_dir(args.output)
    print(f'Private artifacts: {directory}', flush=True)
    try:
        result = execute(args, directory)
    except (Exception, KeyboardInterrupt) as error:
        result = dict(status='FAIL', error=str(error) or 'Interrupted', traffic_sent=False)
    (directory/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
    return 0 if result['status'] in ('PASS', 'PREFLIGHT') else 2


if __name__ == '__main__': sys.exit(main())
