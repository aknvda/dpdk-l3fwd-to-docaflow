"""Explicit, reversible MFT internal PHY loopback for isolated DUT ports."""
from contextlib import contextmanager
import re
import subprocess

from wire_cleanup import defer_cancellation
from wire_common import load_reference
from wire_ports import HostControl


class PhyControl:
    def __init__(self, directory):
        self.directory = directory
        self.host = HostControl()
        self.sequence = 0

    def run(self, state, command):
        self.host.identity(state)
        result = subprocess.run(command, text=True, capture_output=True, timeout=20)
        self.sequence += 1
        (self.directory/f'phy-{self.sequence}.txt').write_text(result.stdout+result.stderr)
        result.check_returncode()
        return result.stdout

    def state(self, state):
        text = self.run(state, ['mlxreg', '-d', state['pci'], '--reg_name', 'PPLR',
                                '--get', '--indexes', 'local_port=1'])
        fields = dict(re.findall(r'^\s*(lb_en|lb_cap)\s*\|\s*(0x[0-9a-fA-F]+)\s*$', text, re.M))
        if set(fields) != {'lb_en', 'lb_cap'}: raise ValueError('Unrecognized PPLR response')
        return int(fields['lb_en'], 16), int(fields['lb_cap'], 16)

    def set(self, state, enable):
        self.run(state, ['mlxlink', '-d', state['pci'], '--loopback', 'PH' if enable else 'NO'])
        if self.state(state)[0] != (2 if enable else 0):
            raise RuntimeError('PHY loopback change did not take effect')

    def down(self, state): self.host.set_up(state, False)


@contextmanager
def internal_phy(states, control):
    # Complete admission before any change. Preserve an existing loopback owner.
    for state in states:
        enabled, capability = control.state(state)
        if enabled != 0 or not capability & 2:
            raise ValueError('Require disabled loopback with advertised internal PHY support')
    changed = []
    try:
        for state in states:
            changed.append(state)  # A failed command may still have changed hardware.
            control.set(state, True)
        yield
    finally:
        with defer_cancellation():
            errors = []
            for state in reversed(changed):
                for operation, args in [(control.down, (state,)), (control.set, (state, False))]:
                    try: operation(*args)
                    except Exception as error: errors.append(str(error))
            if errors: raise RuntimeError('Failed to restore PHY loopback: '+'; '.join(errors))


def loopback_reference(path, macs):
    reference = load_reference(path, macs, macs)
    # Distinct locally administered source markers distinguish injected inputs
    # from rewritten outputs, including same-port misses and TTL exceptions.
    markers = []
    candidate = 1
    while len(markers) < 2:
        marker = b'\x02\x00'+candidate.to_bytes(4, 'big')
        candidate += 1
        if marker not in macs: markers.append(marker)
    reference.inputs = {p: [frame[:6]+markers[p]+frame[12:] for frame in reference.inputs[p]]
                        for p in (0, 1)}
    return reference


def check_loopback_deltas(before, after, reference):
    from wire_smoke import PACKET_COUNTERS, ERROR_COUNTERS
    if len(before) != 2 or len(after) != 2: raise ValueError('Require both DUT counter snapshots')
    deltas = []
    for p, (first, last) in enumerate(zip(before, after)):
        for snapshot in (first, last):
            if any(type(snapshot.get(key)) is not int or snapshot[key] < 0
                   for key in PACKET_COUNTERS+ERROR_COUNTERS):
                raise ValueError('Missing or invalid required physical NIC counter')
        delta = {key: last[key]-first[key] for key in PACKET_COUNTERS+ERROR_COUNTERS}
        legs = len(reference.inputs[p])+len(reference.expected[p])
        if any(delta[key] != legs for key in PACKET_COUNTERS):
            raise ValueError('PHY counters do not match both loopback legs of the corpus')
        if any(delta[key] != 0 for key in ERROR_COUNTERS):
            raise ValueError('Physical NIC error/discard counters changed during loopback')
        deltas.append(delta)
    return deltas
