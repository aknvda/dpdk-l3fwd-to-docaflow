"""Admission and reversible interface changes for a reserved physical test."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

PCI = re.compile(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]')
INTERFACE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}')


class LinkUnavailable(RuntimeError):
    pass


def ip_json(*args):
    return json.loads(subprocess.check_output(['ip', '-json', *args], text=True, timeout=5))


def admit_ports(dut_pci, generators, sysfs=Path('/sys'), links=None):
    if (len(dut_pci) != 2 or len(set(dut_pci)) != 2 or
            any(not PCI.fullmatch(p) for p in dut_pci) or dut_pci[0][:-1] != dut_pci[1][:-1]):
        raise ValueError('Require two distinct DUT functions on the same adapter')
    if len(generators) != 2 or len(set(generators)) != 2 or any(
            not INTERFACE.fullmatch(n) for n in generators):
        raise ValueError('Require two distinct generator interface names')
    sysfs = Path(sysfs)
    by_name = {x['ifname']: x for x in (ip_json('addr', 'show') if links is None else links)}
    names = []
    for pci in dut_pci:
        net = sysfs/'bus/pci/devices'/pci/'net'
        entries = list(net.iterdir())
        if len(entries) != 1: raise ValueError('Require one kernel interface per DUT function')
        names.append(entries[0].name)
    names += generators
    if len(set(names)) != 4: raise ValueError('DUT and generator interfaces must be disjoint')
    devices = [(sysfs/'class/net'/n/'device').resolve(strict=True).name for n in names]
    if devices[:2] != dut_pci or any(not PCI.fullmatch(p) for p in devices):
        raise ValueError('Require physical PCI network interfaces')
    if devices[2][:-1] != devices[3][:-1] or devices[0][:-1] == devices[2][:-1]:
        raise ValueError('Generator must use a separate two-port adapter')
    # Inspect every function on either adapter, including unselected siblings.
    for prefix in {p[:-1] for p in devices}:
        for dev in (sysfs/'bus/pci/devices').glob(prefix+'*'):
            if (dev/'physfn').exists(): raise ValueError('Selected adapter includes a VF')
            vf = dev/'sriov_numvfs'
            if vf.exists() and int(vf.read_text()) != 0:
                raise ValueError('Adapter has active virtual functions')
            for net in (dev/'net').glob('*'):
                info = by_name.get(net.name)
                path = sysfs/'class/net'/net.name
                if not info or 'UP' in info['flags'] or info.get('addr_info'):
                    raise ValueError('Every interface on reserved adapters must be DOWN and unaddressed')
                if (path/'master').exists() or list(path.glob('upper_*')):
                    raise ValueError('Reserved adapter has an enslaved/upper interface')
    states = []
    for i, name in enumerate(names):
        info = by_name[name]
        if info['mtu'] != 1500: raise ValueError('The reference corpus requires MTU 1500 on all test ports')
        mac = bytes.fromhex(info['address'].replace(':', ''))
        if len(mac) != 6 or mac[0] & 1 or not any(mac): raise ValueError('Invalid Ethernet MAC')
        states.append(dict(name=name, index=info['ifindex'], mtu=info['mtu'],
                           mac=info['address'], pci=devices[i], role='dut' if i < 2 else 'generator'))
    return states


def private_run_dir(base):
    base = Path(base).resolve()
    if any((p/'.git').exists() for p in (base, *base.parents)):
        raise ValueError('Raw wire artifacts must be outside every Git checkout')
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = base/('wire-'+uuid.uuid4().hex[:12])
    path.mkdir(mode=0o700)
    return path


class HostControl:
    def identity(self, state):
        base = Path('/sys/class/net')/state['name']
        if int((base/'ifindex').read_text()) != state['index'] or (base/'device').resolve().name != state['pci']:
            raise RuntimeError('Interface identity changed; refusing to modify replacement')

    def ipv6_path(self, state):
        return Path('/proc/sys/net/ipv6/conf')/state['name']/'disable_ipv6'

    def read_ipv6(self, state): return int(self.ipv6_path(state).read_text())

    def set_ipv6(self, state, value):
        self.identity(state)
        self.ipv6_path(state).write_text(str(value))

    def set_up(self, state, value):
        self.identity(state)
        subprocess.run(['ip', 'link', 'set', 'dev', state['name'], 'up' if value else 'down'],
                       check=True, timeout=5)

    def verify(self, state):
        self.identity(state)
        info = ip_json('addr', 'show', 'dev', state['name'])[0]
        if 'UP' in info['flags'] or info['addr_info'] or info['mtu'] != state['mtu'] or info['address'] != state['mac']:
            raise RuntimeError('Interface state was not restored')


@contextmanager
def isolated_ports(states, control=None):
    control = control or HostControl()
    saved = []
    try:
        for state in states:
            control.identity(state)
            value = control.read_ipv6(state)
            saved.append((state, value))  # Record before the first mutation.
            control.set_ipv6(state, 1)  # Prevent auto-created link-local addresses.
        yield control
    finally:
        errors = []
        for state, value in reversed(saved):
            try:
                control.set_up(state, False)
                control.set_ipv6(state, value)
                control.verify(state)
                if control.read_ipv6(state) != value: raise RuntimeError('IPv6 setting changed')
            except Exception as error:
                errors.append(str(error))
        if errors: raise RuntimeError('Failed to restore reserved interfaces: '+'; '.join(errors))


def carrier(state):
    try: return (Path('/sys/class/net')/state['name']/'carrier').read_text().strip() == '1'
    except OSError: return False


def wait_links(states, timeout, alive, link=carrier):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if not alive(): raise RuntimeError('DUT exited while waiting for links')
        if all(link(state) for state in states): return
        time.sleep(.02)
    raise LinkUnavailable('Reserved test links did not become active; no traffic was sent')
