# Physical IPv4 packet validation

`tests/wire_smoke.py` compares a two-port DOCA DUT with output captured from
unmodified upstream l3fwd. It uses two generator ports on a separate adapter in
the same Linux host. This is a bounded, low-rate functional test. It does not
measure throughput, latency, maximum route capacity or Vera/Substrate scaling.

The implemented harness has passed portable tests and real Linux packet-socket
tests in an isolated network namespace. Physical startup and no-link cleanup
have been exercised. **Physical packet equivalence has not passed yet:** the
last physical run found no carrier on the reserved test links. See [RESULTS.md](RESULTS.md).

## Prerequisites

- Build both the pinned upstream PCAP baseline and the DOCA application as in
  [README.md](../README.md). The DOCA build uses SDK 3.3 and its matching DPDK.
- Reserve two DUT functions on one supported adapter and two generator ports on
  a different adapter in the same host. Connect generator port 0 to DUT port 0
  and generator port 1 to DUT port 1, directly or through isolated switch paths.
  Keep management on another adapter. Any common supported link speed suffices.
- All interfaces on both reserved adapters must initially be DOWN, unaddressed,
  without upper/master interfaces or active VFs. All four test ports must have
  MTU 1500. Exclusive ownership is required; the checks cannot discover every
  other process or network namespace using an adapter.
- Use Linux, Python 3.10+, `ip`, `ethtool`, raw-socket privileges and device access
  (the physical runner requires root). Configure sufficient hugepages and locked
  memory beforehand. Reserve a CPU for the DUT. The runner requests 128 MiB of
  DPDK memory and uses a unique, in-memory EAL instance.
- The NIC driver must expose `rx_packets_phy` and `tx_packets_phy` via
  `ethtool -S`, plus every required error/discard counter listed below. Missing
  counters prevent acceptance. Keep IPv4/IPv6 address management and other network configuration
  services away from the reserved ports during the test.

The runner does not flash firmware, change adapter modes, rebind drivers or
allocate hugepages. Its admission does not replace the lab reservation and
release-matched SDK/firmware checks in [VALIDATION.md](VALIDATION.md).

## Generate the actual upstream reference

Choose an existing private directory **outside every Git checkout**. Real lab
configuration, inventory, logs and captures must stay there. The runner rejects
an output directory inside a checkout, including an ignored directory.
Credentials, if needed by a separate lab access helper, remain in the ignored
repository-root `.env` with mode `0600`; this runner does not read passwords.

```bash
: "${PRIVATE_RESULTS:?Set a private directory outside Git}"
python3 tests/pcap_smoke.py --binary build/dpdk/examples/dpdk-l3fwd \
  --extended --route-count 1024 --output "$PRIVATE_RESULTS/reference"
```

Use the exact `run-*` directory printed by a passing invocation as
`UPSTREAM_REFERENCE` below. A generated-only run is not a passing reference.
The wire loader requires `target: upstream`, `extended: true`, 5–1024 routes,
matching input/route files, exact upstream output frames and consistent result
counts. It regenerates the declared corpus to detect mixed or edited files and
records SHA-256 hashes. This is an integrity check within a trusted local
workflow, not an attestation of an untrusted executable or result file.

Only the twelve Ethernet address bytes are adapted to the actual port MACs.
IPv4 addresses, TTL, checksum, payload and frame multiplicity remain unchanged.
The checksum boundaries described in [MIGRATION.md](MIGRATION.md) are included;
a hardware checksum difference fails acceptance and requires an explicit
compatibility decision or implementation change.

## Configure and execute

Create a private JSON file outside the repository with exactly these keys.
Replace the placeholders with the reserved devices and the absolute executable
path; do not commit the resulting configuration.

```json
{
  "doca_binary": "/absolute/path/to/build/doca/l3fwd-docaflow",
  "dut_pci": ["DUT_PCI_0", "DUT_PCI_1"],
  "generator_interfaces": ["GENERATOR_IF_0", "GENERATOR_IF_1"],
  "cpu": 2
}
```

The CPU must be available in the process affinity mask. PCI functions use full
lowercase PCI notation. Array order defines port 0 and port 1. Both DUT ports
must expose exactly one kernel interface. First run read-only admission:

```bash
: "${LAB_CONFIG:?}" "${UPSTREAM_REFERENCE:?}" "${PRIVATE_RESULTS:?}"
python3 tests/wire_smoke.py --config "$LAB_CONFIG" \
  --reference "$UPSTREAM_REFERENCE" --output "$PRIVATE_RESULTS/wire" \
  --preflight-only
```

`PREFLIGHT` checks configuration and saves private reference artifacts. It does
not start DOCA, alter interfaces or test packets. After reserving the ports:

```bash
sudo python3 tests/wire_smoke.py --config "$LAB_CONFIG" \
  --reference "$UPSTREAM_REFERENCE" --output "$PRIVATE_RESULTS/wire" \
  --allow-physical-ports
```

Capture sockets open before DUT startup. Traffic starts only after the DOCA
`ready` event and carrier on all four ports. The runner sends the complete
corpus at 200 aggregate packets/s by default (`--pps`, range 1–1000), then
continues capture for three seconds (`--settle`, range 3–60). It never stops
because the expected packet count was reached. Startup and link waits are
bounded (`--startup-timeout` and `--link-timeout`).

The runner temporarily disables IPv6 on only the four selected interfaces to
prevent automatic link-local addresses, then restores the saved settings.
It stops the DUT with SIGINT, restores all four interfaces DOWN and verifies
identity, MTU, MAC, absence of addresses and the default management route.
Ordinary exceptions and SIGINT/SIGTERM enter cleanup. Signals received while
stopping the DUT or restoring interfaces are deferred until that cleanup phase
finishes, then reported as cancellation. A failed restoration step does not skip
the remaining steps or ports; errors still prevent acceptance. SIGKILL, a host crash or
a stuck SDK may prevent clean teardown; inspect the reserved devices before
retrying. Restoration failure prevents PASS even if packets matched.

## Acceptance and private evidence

A physical `PASS` requires all of the following:

- Complete byte-for-byte frame multisets on each egress, with no missing,
  duplicate, corrupted or wrong-port frames during the observation window.
- Exact expected hardware cross-port and software exception Rx/Tx counts;
  no application drops, capture drops, SDK errors or unsuccessful DUT exit.
- Physical Rx/Tx counter deltas on every DUT/generator port covering the corpus,
  and zero deltas for all required NIC error/discard counters.
- Successful interface/settings restoration after the DUT exits.

The driver must expose these error/discard counters on every port:

```text
rx_crc_errors_phy          rx_in_range_len_errors_phy
rx_out_of_range_len_phy     rx_oversize_pkts_phy
rx_symbol_err_phy           rx_unsupported_op_phy
rx_discards_phy             tx_discards_phy
tx_errors_phy               rx_undersize_pkts_phy
rx_fragments_phy            rx_jabbers_phy
```

These are the physical-port counters defined by the
[Linux v6.8 mlx5 driver](https://github.com/torvalds/linux/blob/v6.8/drivers/net/ethernet/mellanox/mlx5/core/en_stats.c#L773).
Any change, including a counter reset, prevents PASS. Missing counters fail
explicitly; there is no silent reduced-coverage mode. Packet totals remain
lower bounds, separate from the exact application/capture checks and the zero
error/discard gate. Driver availability must be verified on the actual testbed.

`result.json` is written after cleanup. Exit 0 means `PASS` or the explicitly
requested `PREFLIGHT`; callers must also inspect `status`. Missing carrier
produces `BLOCKED`, `traffic_sent: false` and exit 2. A mismatch or other error
produces `FAIL` and exit 2. Both BLOCKED and FAIL are non-acceptance results.

Each mode-0700 run directory retains reference hashes, copied routes, adapted
input/expected PCAPs, actual captures, inventory and, for physical execution,
command, executable hash, DUT log, capture-loss counts and available NIC counter
snapshots. Record the repository/submodule revision, package/firmware versions,
CPU/NUMA layout and topology alongside these artifacts as specified in
[VALIDATION.md](VALIDATION.md). Raw logs can contain confidential identifiers.

The corpus uses unordered frame multisets and a finite observation window.
It does not establish per-flow ordering, malformed-packet parity, sustained
line-rate behavior, multi-queue scaling or dynamic rule updates. Those remain
separate acceptance gates.

## Test the harness without physical ports

```bash
python3 -m unittest discover -s tests -v
sudo python3 tests/wire_namespace_check.py
```

The second command launches a fresh temporary network namespace, creates two
veth pairs and exercises the same AF_PACKET capture/replay code used by the
physical runner. It checks ordinary byte delivery, delayed duplicates and
wrong-port detection. Its only successful status is `HARNESS_PASS`, explicitly
scoped to Linux packet I/O. The fixture is not a DOCA emulator and its success
is not hardware forwarding evidence. The namespace disappears when the process
exits; no host physical interfaces are used.
