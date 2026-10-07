# Validation requirements and acceptance gates

Status: the IPv4 migration builds against DOCA 3.3 and passes the full
1024-route / 2326-packet upstream corpus in software and on real hardware using
internal PHY loopback. The default policy uses hardware route metadata plus
software rewriting for exact upstream bytes; full hardware forwarding is an
explicit policy with ten documented checksum differences. Installation, teardown,
restart, counters and restoration are validated. External-wire interoperability,
performance and broader protocol/exception coverage remain separate experiments.
See [RESULTS.md](RESULTS.md) for measured results and the
[internal PHY runner](INTERNAL_LOOPBACK.md) for the passing end-to-end procedure.

## Completion of the IPv4 milestone

| Acceptance item | Disposition |
| --- | --- |
| Pinned upstream and migrated software packet comparison | Complete: 1024 routes, 2326 packets |
| Real-NIC exact upstream packet comparison | Complete: two consecutive internal PHY runs |
| Explicit full-offload policy | Complete under its documented checksum contract |
| Normal application startup without the loopback hook | Complete: both policies, 1024 routes; no traffic in this check |
| Rule completions, restart, counters and restoration | Complete for the documented tests; raw evidence retained privately |
| Reproducible migration instructions | [Focused guide](MIGRATION_GUIDE.md), source mapping and executable commands |

External links are not a remaining dependency for these completed acceptance
items. Broader packet, lifecycle, link and performance matrices below describe
additional claims that require their own tests; they are not evidence already
collected. In particular, exact mode performs CPU rewriting for every packet.

## External-wire lab and cable-free alternative

```text
Traffic generator port A <----> DUT port 0
Traffic generator port B <----> DUT port 1
Management/SSH uses separate interfaces.
```

This connectivity is needed for the external-wire fixture, not for all hardware
packet validation. The [internal PHY fixture](INTERNAL_LOOPBACK.md) exercises real
hardware forwarding without cables on the validated adapter. External paths are
still needed for link interoperability and performance claims. Functional tests can use any common
supported link speed. A 100GbE link is required only for a 100GbE performance claim.
Existing isolated switch paths or another reserved wired DUT/generator pair are
valid alternatives to new direct cables. See the
[operations request and justification](HARDWARE_TEST_REQUEST.md).

| Item | Requirement / proposed starting point |
| --- | --- |
| DUT | A dedicated Linux server with two available Ethernet ports on a supported NVIDIA device. Confirm LPM, rewrite, TTL/checksum and forwarding combinations with the exact SDK/device/mode before committing to a card. BlueField-3 or ConnectX-7 are candidate platforms to evaluate, not a blanket capability guarantee. |
| CPU/RAM | Suggested lab allocation: at least 8 available cores and 32 GB RAM, with reserved CPU cores and NUMA-local memory. These are project sizing suggestions, not vendor minimums. No GPU is required. |
| Software | One supported OS/kernel + DOCA-Host/SDK + NIC firmware combination. Ubuntu 24.04 is a candidate. Pin package versions after inventory. Build the DOCA application against its supported DPDK, not an arbitrary upstream ABI. |
| Traffic source | The validated internal PHY fixture uses only the DUT adapter. The external-wire runner uses a separate two-port adapter in the same Linux host. For performance, a separate Linux generator with two ports at the same link speed, or a hardware tester. It must generate and measure the aggregate bidirectional target rate. Cables/optics, MTU and FEC must match. A single generator host can terminate both directions. |
| Access | SSH, source/build access and dedicated interfaces; administrative access for driver installation, hugepages, device permissions and mode configuration. Firmware or mode changes are separate lab operations, not performed by the inventory script. |
| Measurements | Per-port packet/byte/error counters; generator sequence/loss tracking; hardware flow counters and completion status; CPU and memory accounting; saved configs, commands and software/firmware versions. Hardware timestamping or a calibrated tester is preferred for latency. |

A switch is optional for the direct-cable lab. A BlueField deployment also needs
management access to the DPU and a recorded operating mode. Decide whether the
control application runs on host CPU or BlueField Arm, and whether DOCA Flow uses
VNF or switch mode. Those decisions affect port and representor wiring.

Configure hugepages and sufficient locked memory for the hardware run. Record
page size, count and NUMA node; size to the workload instead of copying a fixed
allocation. Use the supported mlx5 driver stack. Do not blindly unbind mlx5
devices to vfio-pci: the mlx5 PMD uses a bifurcated kernel/userspace model.

## Gate 0: software baseline (passed)

Build the pinned, unmodified upstream l3fwd. The PCAP test sends 48 valid frames
across two virtual ingress ports, with /8, /16, /24 and /32 overlap plus misses.
Frame sizes are 60, 124, 508 and 1514 bytes in the capture, corresponding to
64, 128, 512 and 1518 bytes when a 4-byte Ethernet FCS is included.

The checker compares complete output frames and multiplicity per egress port:
MAC rewrites, TTL 64 -> 63, IPv4 checksum, payload, loss, duplication and wrong
port all matter. A route miss must return to its ingress port. Captures are
unordered multisets; this smoke test does not validate per-flow ordering.
Collect for the entire declared observation window (default 30 seconds including
startup), then stop the application and compare final captures. Reaching the
expected packet count early is not a reason to stop collecting.
PCAP virtual ports do not exercise mlx5, DMA, offload, link rates or NIC parsing.

The extended software test adds TTL/checksum boundaries and route-table scaling
through the pinned upstream limit: `--extended --route-count 1024`. This is
functional route coverage, not a hardware-capacity or throughput measurement.

## Gate 1: device and SDK admission (control plane and internal PHY traffic passed)

1. Save the read-only inventory and map PCI addresses, port IDs, physical links,
   PF/VF/SF/representors, NUMA nodes and application CPU affinity.
2. Build and run the installed SDK's basic forwarding and LPM examples. Record
   actual support or rejection of the intended action combination on the device.
3. Confirm the chosen pipeline installs and completes successfully on every
   programming queue. Check both synchronous returns and each asynchronous
   completion. A returned entry handle alone is insufficient.
4. Send traffic and correlate generator counts, physical port counts and flow
   counters. Allow the documented counter update interval. Count software
   exceptions explicitly; low CPU utilization alone does not prove offload.

For DPDK-managed DOCA ports, the documented HWS setting is `dv_flow_en=2`.
DOCA LPM needs a preceding root pipe. Validate pairing/forwarding for both
directions in the selected mode. See the [DOCA Flow guide](https://networking-docs.nvidia.com/doca/archive/3-5-0/doca-flow).

The implemented application uses host-side VNF/HWS, not switch mode or
representors. It requires two PCI functions on the same reserved adapter, with
one kernel network interface per selected function.
Interfaces on every function of that adapter must be DOWN, unaddressed, free
of upper/master interfaces and have no active VFs. The application preserves
the configured MTU, supports MTU <= 1500 and returns opened physical ports to
administrative DOWN during normal or failed-startup cleanup, including a probe
failure that releases its DPDK handle. SIGINT/SIGTERM cancellation is checked during
startup and while waiting for rule completions. An in-progress SDK call must return
before cleanup can run. SIGKILL or a crash can bypass cleanup; inspect the reserved
interfaces before another attempt. Interface renaming/replacement during a run is
unsupported; an identity mismatch fails restoration rather than touching a new device.
It does not install drivers, flash
firmware, allocate hugepages, change operating mode or unbind the kernel driver.
Checks use the current network namespace and sysfs; exclusive ownership and
other namespaces/processes still require a lab reservation check.

Installing the SDK and successfully probing mlx5 are not enough to admit a DUT.
Check the release-matched firmware matrix and then actually start a DOCA port.
For example, the [DPDK 25.11 HWS requirements](https://doc.dpdk.org/guides-25.11/nics/mlx5.html#hardware-steering)
list firmware `xx.35.1012` as the minimum; the SDK's supported combination may
require a newer version. Firmware flashing and reset require a separate maintenance
plan with a matching PSID, verified vendor image, recovery access and a bounded
device scope. Keep real inventory, image metadata and maintenance commands private.

If startup fails, save stderr and the exit code. A capability-query rejection
before port creation is different from an unsupported pipe/action combination
after port creation. Neither may produce a passing hardware result or a `ready`
event. Confirm both ports return DOWN and management connectivity remains intact.

Use a **separate two-port TRex stateless generator** for repeatable traffic,
captures and subsequent rate sweeps. TRex's upstream documentation lists mlx5
ConnectX-5/6 support; verify the exact release/card/firmware combination and
generator rate before making a capacity claim. For initial low-rate functional
work, two unused adapters in one server can form a direct-cable loop between
DUT and generator, with disjoint CPUs and NUMA-local memory. Shared PCIe/CPU/memory
resources make that arrangement unsuitable for an unqualified performance claim.
See the [TRex upstream manual](https://github.com/cisco-system-traffic-generator/trex-core/blob/master/doc/trex_book.asciidoc).

The implemented [wire runner](WIRE_VALIDATION.md) performs the following replay
sequence and checks exact hardware/software counters against the upstream corpus.
For physical replay, replace the synthetic input destination MACs with the DUT
port MACs and the expected source/destination MACs with the configured DUT/peer
MACs. Keep the synthetic IP routing inputs unchanged. Start capture before sending
traffic, begin only after the application's `ready` event, observe the complete
window, and compare complete frames and per-port multiplicity. Retain the raw
capture and configuration privately. Do not remove failing checksum cases to
make hardware parity pass; record a compatibility decision explicitly.

## Gate 2: functional equivalence (documented corpus passed; expansion matrix)

| Cases | Required evidence |
| --- | --- |
| Valid IPv4 forwarding | Same route/config/packet corpus, same egress selection and packet bytes after accounting for explicitly configured port MACs. Both directions and a hardware-parser run. |
| Prefix boundaries | Overlaps, /1 and /32, prefix boundaries, absent routes, disabled outputs. Establish /0 support on both backends before adding a default-route case; do not assume support. |
| Packet exceptions | TTL 0/1, checksum carry, bad checksum, bad version/IHL/length, truncated frames, IP options, fragmentation, non-IP and IPv6. First characterize upstream; document each admit/fallback/drop decision. Do not assume l3fwd is a full RFC router. |
| Load-dependent correctness | Bursts, multiple queues and per-flow sequences; no unexpected loss, duplication, corruption, cross-port leakage or within-flow reordering at a declared offered rate. |
| Rule lifecycle | Add/delete/replacement under traffic, overlap after deletion, completion timeout/failure, capacity exhaustion, application restart and cleanup. Define packet behavior during changes and check recovery. |
| Link/device failures | Link down/up, unavailable port and clean restart. No silent success or stale rules. Destructive reset tests require a dedicated maintenance window. |

The initial upstream application loads routes at startup; dynamic rule operations
are a later DOCA control-plane test, not an existing upstream API parity claim.
The documented IPv4 corpus has passed software and hardware comparison. A broader
equivalence claim requires the expanded tests above; no such claim is made here.

## Gate 3: performance (after Gates 1 and 2)

Run sequential A/B tests on the same DUT, ports, route table and traffic inputs.
Hold link speed, MTU, FEC, CPU frequency policy, CPU/NUMA affinity, queue count,
packet mix and counter instrumentation constant. Record any unavoidable change
(including baseline DPDK versus the SDK's packaged DPDK). Separate CPU software
forwarding from hardware-forwarding results explicitly.

Proposed first matrix:

- Frames: 64/128/512/1518 bytes including FCS, then a precisely recorded mix.
- Direction: unidirectional, then simultaneous bidirectional.
- Offered load: sweep through saturation; report the highest rate meeting a
  stated loss threshold, not just the generator's configured rate.
- Routes: 16, 256, 1024; traffic 5-tuples: 1, 1K, 100K independently.
- Software workers: 1, 2, 4 and 8 where hardware/NUMA topology permits.
- Exceptions: 0%, 1%, 10% and 100% of traffic, with the same defined policy.
- At least 5 measured trials per point, with a proposed 10-second warm-up and
  60-second measurement. Retain all trials and report spread, not just the best.

Measure Mpps, Gb/s, packet loss, p50/p99/p99.9 latency, process and system CPU,
cycles/packet where meaningful, resident/hugepage memory, and exception counts.
Report host and DPU CPU separately if both are used. State whether Gb/s includes
FCS, preamble and inter-packet gap. Validate the generator's capacity first.
Round-trip latency and one-way latency are distinct; one-way measurements need
an appropriate common/synchronized clock or a suitable tester.

Measure control-plane installation time from submission through successful
completion of every entry, plus entries/second and failures. Sweep insertion
batch size separately from packet throughput. This upstream pin hard-codes
`L3FWD_LPM_MAX_RULES` to 1024; larger route-table experiments need a documented
baseline change and resource sizing, not just a larger configuration file.

## Gate 4: larger scale / multiplexing (later experiment)

Sweep route count, active traffic flows, and isolated application/tenant instances
as separate axes. For a multiplexing experiment, define the ratio
explicitly (for example, N isolated instances per M pinned physical cores), run
each ratio on every comparison arm, and hold aggregate offered load constant for
the isolation experiment. Also run a separate fixed-load-per-instance experiment
to find aggregate saturation. Record isolation mechanism, scheduler settings,
overcommit, rule budgets, throughput per instance, fairness and tail latency.

This is a proposed experimental design; scaling benefits remain unmeasured.
First prove correctness at low scale; then increase until a measured resource
limit is reached. More instances alone do not create more independent LPM routes.

## Reproducibility record

Every physical run must retain: repository commit/submodule SHA, compiler and build
options, SDK/DPDK/driver/firmware versions, OS/kernel, NIC model and mode, topology,
CPU/NUMA/queue layout, hugepages, routes and traffic seeds, launch commands,
completion/error logs, counter snapshots, raw captures, per-trial metrics and the
pass/fail criteria used. Store raw inventories and lab results outside this
repository. Publish only sanitized summaries: no private hostnames, real network
addresses, device serial numbers, internal topology, secrets or customer traffic.
Packet fixtures use synthetic addresses unrelated to the physical lab.

Sources checked 2026-10-06:

- [DPDK 25.11 l3fwd guide](https://doc.dpdk.org/guides-25.11/sample_app_ug/l3_forward.html)
- [Pinned l3fwd source](https://github.com/DPDK/dpdk/tree/ed957165eadbe60a47d5ec223578cdd1c13d0bd9/examples/l3fwd)
- [DOCA 3.3 documentation](https://docs.nvidia.com/doca-documentation-v3-3-0.pdf) (implemented API target; installed headers/samples also checked)
- [DOCA 3.5 supported stack matrix](https://networking-docs.nvidia.com/doca/archive/3-5-0/general-support)
- [DOCA 3.5 release notes](https://networking-docs.nvidia.com/doca/archive/3-5-0/doca-release-notes)
- [mlx5 PMD guide](https://doc.dpdk.org/guides-25.11/nics/mlx5.html)
