"""Reference and acceptance checks shared by physical validation tools."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from pcap_smoke import compare_frames, generate, read_pcap, checksum
from wire_cleanup import defer_cancellation


@dataclass
class Reference:
    inputs: dict
    expected: dict
    stats: dict
    routes: Path
    route_count: int
    digests: dict
    hardware_expected: dict
    checksum_differences: list


def load_reference(path, dut_macs, peer_macs):
    """Use real upstream outputs; change Ethernet addresses only for the wire."""
    path = Path(path).resolve()
    result = json.loads((path/'result.json').read_text())
    count = result.get('routes')
    if (result.get('status') != 'PASS' or result.get('target') != 'upstream' or
            result.get('extended') is not True or type(count) is not int or not 5 <= count <= 1024):
        raise ValueError('Require a passing extended upstream PCAP reference (5..1024 routes)')
    if len(dut_macs) != 2 or len(peer_macs) != 2 or any(
            len(mac) != 6 or mac[0] & 1 or not any(mac) for mac in dut_macs+peer_macs):
        raise ValueError('Require two unicast MAC addresses for DUT and generator')
    inputs = {p: read_pcap(path/f'rx{p}.pcap') for p in (0, 1)}
    actual = {p: read_pcap(path/f'tx{p}.pcap') for p in (0, 1)}
    # Reconstruct the declared corpus to reject stale/mixed files. The expected
    # wire bytes below still come from the recorded upstream executable output.
    with tempfile.TemporaryDirectory() as td:
        check = Path(td)
        generated = generate(check, extended=True, route_count=count)
        for p in (0, 1):
            if inputs[p] != read_pcap(check/f'rx{p}.pcap'):
                raise ValueError('Reference input does not match its declared corpus')
        if (path/'routes-v4.cfg').read_bytes() != (check/'routes-v4.cfg').read_bytes():
            raise ValueError('Reference route file does not match its declared corpus')
        compare_frames(generated, actual)
        manifest = json.loads((check/'cases.json').read_text())
    if result.get('packets') != sum(map(len, actual.values())) or result.get('per_port') != {
            str(p): len(actual[p]) for p in (0, 1)}:
        raise ValueError('Reference result counts do not match its captures')
    stats = dict(software_rx=[0, 0], software_tx=[0, 0], software_dropped=0,
                 tx_dropped=0, hardware_forwarded=[0, 0])
    hardware_expected, differences, indices = {0: [], 1: []}, [], [0, 0]
    for p in (0, 1):
        cases = [c for c in manifest if c['ingress'] == p]
        for frame, case in zip(inputs[p], cases):
            egress = case['egress']
            offloaded = p != egress and frame[22] >= 2
            if offloaded:
                stats['hardware_forwarded'][p] += 1
            else:
                stats['software_rx'][p] += 1
                stats['software_tx'][egress] += 1
            # The generated multiset above was checked against actual upstream
            # output. Walk its declared case order to identify only offloaded
            # outputs. Never infer exceptions from the DUT capture being judged.
            upstream = generated[egress][indices[egress]]
            indices[egress] += 1
            output = bytearray(upstream)
            if offloaded:
                header = bytearray(output[14:34]); header[10:12] = b'\0\0'
                output[24:26] = checksum(header).to_bytes(2, 'big')
                if output[24:26] != upstream[24:26]:
                    differences.append(dict(case_id=case['id'], ingress=p, egress=egress,
                                            input_checksum=frame[24:26].hex(),
                                            upstream_checksum=upstream[24:26].hex(),
                                            hardware_checksum=output[24:26].hex()))
            hardware_expected[egress].append(peer_macs[egress]+dut_macs[egress]+bytes(output[12:]))
    expected = {p: [peer_macs[p]+dut_macs[p]+frame[12:] for frame in actual[p]] for p in (0, 1)}
    inputs = {p: [dut_macs[p]+peer_macs[p]+frame[12:] for frame in inputs[p]] for p in (0, 1)}
    names = ['result.json', 'routes-v4.cfg', 'rx0.pcap', 'rx1.pcap', 'tx0.pcap', 'tx1.pcap']
    digests = {name: hashlib.sha256((path/name).read_bytes()).hexdigest() for name in names}
    return Reference(inputs, expected, stats, path/'routes-v4.cfg', count, digests,
                     hardware_expected, differences)


def read_events(text):
    events = []
    for line in text.splitlines(keepends=True):
        if not line.endswith('\n') or not line.startswith('{'):
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError('Invalid application event')
        events.append(event)
    return events


def wait_ready(process, log, timeout):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'DUT exited before traffic ({process.returncode})')
        ready = [e for e in read_events(Path(log).read_text()) if e.get('event') == 'ready']
        if ready:
            if len(ready) != 1 or ready[0].get('backend') != 'doca':
                raise ValueError('Expected exactly one DOCA ready event')
            return ready[0]
        time.sleep(.02)
    raise RuntimeError('Timed out waiting for DOCA ready event')


def stop_process(process, timeout=10):
    with defer_cancellation():
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError('DUT failed to stop after SIGINT; forced termination')


def expected_stats(reference, checksum_policy):
    """Account separately for hardware forwarding and hardware-assisted lookup."""
    if checksum_policy not in ('upstream', 'hardware'): raise ValueError('Unknown checksum policy')
    stats = {key: value.copy() if isinstance(value, list) else value
             for key, value in reference.stats.items()}
    stats.update(hardware_lookups=[0, 0], software_hw_lookup=[0, 0])
    if checksum_policy == 'upstream':
        lookups = stats['hardware_forwarded']
        stats['hardware_forwarded'] = [0, 0]
        stats['hardware_lookups'] = lookups.copy()
        stats['software_hw_lookup'] = lookups.copy()
        for p in (0, 1):
            stats['software_rx'][p] += lookups[p]
            stats['software_tx'][p ^ 1] += lookups[p]
    return stats


def check_run(reference, actual, events, exit_code, log, capture_drops, checksum_policy='upstream'):
    if checksum_policy not in ('upstream', 'hardware'): raise ValueError('Unknown checksum policy')
    if exit_code or '[ERR]' in log or capture_drops != [0, 0]:
        raise ValueError('DUT exit, SDK error or packet capture loss prevents acceptance')
    if len(events) != 2 or events[0].get('event') != 'ready' or events[1].get('event') != 'stats':
        raise ValueError('Require exactly one ready event followed by one stats event')
    if events[0].get('backend') != 'doca' or events[0].get('routes') != reference.route_count:
        raise ValueError('DUT backend/route count does not match the reference')
    if events[0].get('checksum_policy') != checksum_policy:
        raise ValueError('DUT checksum policy does not match the requested policy')
    for key, expected in expected_stats(reference, checksum_policy).items():
        observed = events[1].get(key)
        values = observed if isinstance(observed, list) else [observed]
        if observed != expected or any(type(v) is not int or v < 0 for v in values):
            raise ValueError(f'Counter mismatch for {key}: expected {expected}, observed {observed}')
    if not any(reference.stats['hardware_forwarded']):
        raise ValueError('Empty hardware workload cannot establish hardware processing')
    compare_frames(reference.expected if checksum_policy == 'upstream' else reference.hardware_expected, actual)
