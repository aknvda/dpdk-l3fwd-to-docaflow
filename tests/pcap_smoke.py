#!/usr/bin/env python3
"""Exercise the real l3fwd binary with finite PCAP inputs; no NIC is required.

This is a narrow IPv4 functional test, not a benchmark or a DOCA emulator.
PCAP lengths exclude Ethernet FCS, preamble and inter-packet gap.
"""
import argparse
from collections import Counter
import ipaddress
import json
import math
import os
from pathlib import Path
import signal
import struct
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEST_MACS = [bytes.fromhex('020000000010'), bytes.fromhex('020000000011')]
PCAP_MACS = [bytes.fromhex('027063617000'), bytes.fromhex('027063617001')]
# Independent expectations: do not compute expected ports with the DUT parser.
CASES = [('10.9.0.1', 0), ('10.1.9.1', 1), ('10.1.2.4', 0),
         ('10.1.2.3', 1), ('192.0.2.10', 1), ('203.0.113.1', None)]


def compare_frames(expected, actual):
    """Compare bytes and multiplicity per port, independent of capture order."""
    if not any(expected.values()):
        raise AssertionError('empty expected corpus cannot establish correctness')
    if set(expected) != set(actual):
        raise AssertionError('capture port set differs')
    for port in expected:
        want, got = Counter(expected[port]), Counter(actual[port])
        if want != got:
            raise AssertionError(
                f'port {port}: missing={sum((want-got).values())}, '
                f'unexpected={sum((got-want).values())}')


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack(f'!{len(data)//2}H', data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return (~total) & 0xffff


def packet(dst, size, ident, ttl, dst_mac, src_mac):
    payload = (f'l3fwd-case-{ident:04d}'.encode() + bytes(size))[:size-42]
    udp = struct.pack('!HHHH', 10000+ident, 20000, len(payload)+8, 0) + payload
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, len(udp)+20, ident, 0,
                     ttl, 17, 0, ipaddress.ip_address('198.51.100.1').packed,
                     ipaddress.ip_address(dst).packed)
    ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
    return dst_mac + src_mac + b'\x08\x00' + ip + udp


def write_pcap(path, frames):
    with path.open('wb') as stream:
        stream.write(struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for index, frame in enumerate(frames):
            stream.write(struct.pack('<IIII', 1, index, len(frame), len(frame)))
            stream.write(frame)


def read_pcap(path):
    raw = path.read_bytes()
    if len(raw) < 24:
        raise ValueError(f'truncated PCAP header: {path}')
    orders = {b'\xd4\xc3\xb2\xa1': '<', b'\x4d\x3c\xb2\xa1': '<',
              b'\xa1\xb2\xc3\xd4': '>', b'\xa1\xb2\x3c\x4d': '>'}
    endian = orders.get(raw[:4])
    if endian is None or struct.unpack(endian+'I', raw[20:24])[0] != 1:
        raise ValueError(f'expected classic Ethernet PCAP: {path}')
    frames, offset = [], 24
    while offset < len(raw):
        if len(raw)-offset < 16:
            raise ValueError(f'truncated record header: {path}')
        _, _, captured, original = struct.unpack(endian+'IIII', raw[offset:offset+16])
        offset += 16
        if captured != original or captured > len(raw)-offset:
            raise ValueError(f'truncated frame: {path}')
        frames.append(raw[offset:offset+captured])
        offset += captured
    return frames


def generate(directory, extended=False, route_count=5):
    expected, manifest = {0: [], 1: []}, []
    routes = (ROOT/'configs/routes-v4.cfg').read_text()
    cases = list(CASES)
    for index in range(route_count-5):
        dst = str(ipaddress.IPv4Address('10.128.0.0') + index)
        routes += f'R{dst}/32 {index % 2}\n'
        cases.append((dst, index % 2))
    (directory/'routes-v4.cfg').write_text(routes)
    ident = 0
    for ingress in (0, 1):
        inputs = []
        for case, (dst, route_port) in enumerate(cases):
            sizes = (60, 124, 508, 1514) if case < len(CASES) else (124,)
            ttls = (0, 1, 2, 64, 255) if extended and case < len(CASES) else (64,)
            for size, ttl in ((size, ttl) for size in sizes for ttl in ttls):
                egress = ingress if route_port is None else route_port
                frame = packet(dst, size, ident, ttl, PCAP_MACS[ingress],
                               bytes.fromhex('020000000099'))
                inputs.append(frame)
                output = bytearray(frame)
                output[:12] = DEST_MACS[egress] + PCAP_MACS[egress]
                output[22] = (ttl-1) % 256
                # Pinned x86/ARM little-endian l3fwd increments the stored word.
                # The differential run independently checks that this oracle
                # matches the real upstream executable, including carry cases.
                old = int.from_bytes(frame[24:26], 'little')
                output[24:26] = ((old+1) % 65536).to_bytes(2, 'little')
                expected[egress].append(bytes(output))
                manifest.append(dict(id=ident, ingress=ingress, egress=egress,
                                     dst=dst, ttl=ttl, frame_bytes_without_fcs=size))
                ident += 1
        if extended:
            # Both representations of one's-complement zero are valid on input.
            # Upstream's raw increment differs from RFC checksum correction for
            # the 0xffff representation. Keep this edge visible to HW validation.
            for dst, route_port in CASES:
                egress = ingress if route_port is None else route_port
                frame = bytearray(packet(dst, 60, 0, 64, PCAP_MACS[ingress],
                                         bytes.fromhex('020000000099')))
                base_checksum = int.from_bytes(frame[24:26], 'big')
                for target in (0, 0xfeff, 0xff00, 0xffff):
                    # Adjust the ID field using one's-complement arithmetic.
                    # The other header words stay unchanged.
                    frame[18:20] = ((base_checksum-target) % 65535).to_bytes(2, 'big')
                    encoding = target.to_bytes(2, 'big')
                    frame[24:26] = encoding
                    assert checksum(frame[14:34]) == 0
                    inputs.append(bytes(frame))
                    output = bytearray(frame)
                    output[:12] = DEST_MACS[egress] + PCAP_MACS[egress]
                    output[22] = 63
                    old = int.from_bytes(encoding, 'little')
                    output[24:26] = ((old+1) % 65536).to_bytes(2, 'little')
                    expected[egress].append(bytes(output))
                    manifest.append(dict(id=ident, ingress=ingress, egress=egress,
                                         dst=dst, checksum_boundary=encoding.hex()))
                    ident += 1
        write_pcap(directory / f'rx{ingress}.pcap', inputs)
    for port, frames in expected.items():
        write_pcap(directory / f'expected{port}.pcap', frames)
    (directory / 'cases.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--target', choices=('upstream', 'software'), default='upstream',
                        help='application CLI; software selects the migrated DPDK backend')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/pcap')
    parser.add_argument('--generate-only', action='store_true')
    parser.add_argument('--extended', action='store_true', help='include TTL and checksum boundaries')
    parser.add_argument('--route-count', type=int, default=5, help='5..1024; add synthetic /32 routes')
    parser.add_argument('--timeout', type=float, default=30,
                        help='observation window in seconds, including startup (default: 30)')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be positive')
    if not 5 <= args.route_count <= 1024:
        parser.error('--route-count must be in 5..1024')
    if not args.generate_only and (not args.binary or not hasattr(os, 'sched_getaffinity')):
        parser.error('run on Linux with --binary, or use --generate-only')
    directory = args.output.resolve() / ('run-'+uuid.uuid4().hex[:12])
    directory.mkdir(parents=True)
    print(f'Artifacts: {directory}', flush=True)
    expected = generate(directory, args.extended, args.route_count)
    if args.generate_only:
        print(f'Generated {sum(map(len, expected.values()))} input packets and expected outputs; no DUT executed.')
        return
    cpu = min(os.sched_getaffinity(0))
    command = [str(args.binary.resolve()), '--lcores', f'0@{cpu}',
               '--no-huge', '--no-pci', '--no-telemetry', '-m', '256']
    for port in (0, 1):
        command += ['--vdev', f'net_pcap{port},rx_pcap={directory}/rx{port}.pcap,'
                    f'tx_pcap={directory}/tx{port}.pcap']
    if args.target == 'upstream':
        command += ['--', '-p', '0x3', '--config', '(0,0,0),(1,0,0)',
                '--lookup=lpm', '--mode=poll', '--no-numa', '--parse-ptype',
                '--relax-rx-offload',
                '--rule_ipv4', str(directory/'routes-v4.cfg'),
                '--rule_ipv6', str(ROOT/'configs/routes-v6.cfg')]
    else:
        command += ['--', '--backend', 'software', '--routes', str(directory/'routes-v4.cfg')]
    command += ['--eth-dest', '0,02:00:00:00:00:10',
                '--eth-dest', '1,02:00:00:00:00:11']
    (directory/'command.json').write_text(json.dumps(command, indent=2)+'\n')
    # Observe the entire declared window: reaching the expected count early must
    # not hide later duplicate or unexpected packets. Then close captures cleanly.
    deadline = time.monotonic() + args.timeout
    with (directory/'l3fwd.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'l3fwd exited early ({process.returncode}); see {directory}/l3fwd.log')
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError('l3fwd did not stop after SIGINT')
    if process.returncode != 0:
        raise RuntimeError(f'l3fwd exit code {process.returncode}; see {directory}/l3fwd.log')
    actual = {p: read_pcap(directory/f'tx{p}.pcap') for p in (0, 1)}
    compare_frames(expected, actual)
    result = dict(status='PASS', target=args.target,
                  scope='DPDK IPv4 PCAP only; no DOCA or performance validation',
                  routes=args.route_count, extended=args.extended,
                  observation_seconds=args.timeout,
                  packets=sum(map(len, actual.values())),
                  per_port={p: len(frames) for p, frames in actual.items()})
    (directory/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
