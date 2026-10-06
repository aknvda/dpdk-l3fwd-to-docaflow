#!/usr/bin/env bash
# Read-only inventory. No sudo, device binding, firmware or configuration changes.
set -u
if [[ "$(uname -s)" != Linux ]]; then
    printf 'Run this inventory on the Linux DUT.\n' >&2
    exit 2
fi
run() {
    printf '\n$'
    printf ' %q' "$@"
    printf '\n'
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 || printf '[command failed or requires additional access]\n'
    else
        printf '[tool unavailable]\n'
    fi
}
run date -u
run uname -a
run cat /etc/os-release
run lscpu
run lspci -nn
run free -h
run pkg-config --modversion libdpdk
run pkg-config --modversion doca-flow
run rdma link show
run devlink dev info
for device in /sys/bus/pci/devices/*; do
    [[ -d "$device/net" ]] || continue
    run devlink dev eswitch show "pci/${device##*/}"
done
run devlink port show
run ip -brief link
run sh -c 'ulimit -l'
run sh -c 'grep -E "Huge|MemTotal" /proc/meminfo'
for interface in /sys/class/net/*; do
    [[ -e "$interface/device" ]] || continue
    run ethtool -i "${interface##*/}"
    run ethtool "${interface##*/}"
    [[ ! -r "$interface/device/numa_node" ]] || run cat "$interface/device/numa_node"
done
