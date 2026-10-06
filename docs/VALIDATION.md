# Validation requirements and acceptance gates

Status: this is the lab plan. The implemented PCAP test covers a small valid
IPv4 corpus only. No DOCA hardware result is claimed. See RESULTS.md for runs.

## Minimum physical lab

```text
Traffic generator port A <----> DUT port 0
Traffic generator port B <----> DUT port 1
Management/SSH uses separate interfaces.
```

| Item | Requirement / proposed starting point |
| --- | --- |
| DUT | A dedicated Linux server with two available Ethernet ports on a supported NVIDIA device. Confirm LPM, rewrite, TTL/checksum and forwarding combinations with the exact SDK/device/mode before committing to a card. BlueField-3 or ConnectX-7 are candidate platforms to evaluate, not a blanket capability guarantee. |
| CPU/RAM | Suggested lab allocation: at least 8 available cores and 32 GB RAM, with reserved CPU cores and NUMA-local memory. These are project sizing suggestions, not vendor minimums. No GPU is required. |
| Software | One supported OS/kernel + DOCA-Host/SDK + NIC firmware combination. Ubuntu 24.04 is a candidate. Pin package versions after inventory. Build the DOCA application against its supported DPDK, not an arbitrary upstream ABI. |
| Traffic source | A separate Linux generator with two ports at the same link speed, or a hardware tester. It must generate and measure the aggregate bidirectional target rate. Cables/optics, MTU and FEC must match. A single generator host can terminate both directions. |
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

## Gate 0: software baseline (implemented harness)

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

## Gate 1: device and SDK admission (to implement/run)

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

## Gate 2: functional equivalence (to expand/run on both implementations)

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
Full equivalence requires these expanded tests; passing Gate 0 is not sufficient.

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
as separate axes. If comparing a Vera + Substrate deployment, define the ratio
explicitly (for example, N isolated instances per M pinned physical cores), run
each ratio on every comparison arm, and hold aggregate offered load constant for
the isolation experiment. Also run a separate fixed-load-per-instance experiment
to find aggregate saturation. Record isolation mechanism, scheduler settings,
overcommit, rule budgets, throughput per instance, fairness and tail latency.

This is a proposed experimental design, not evidence of a Vera/Substrate benefit.
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
- [DOCA 3.5 supported stack matrix](https://networking-docs.nvidia.com/doca/archive/3-5-0/general-support)
- [DOCA 3.5 release notes](https://networking-docs.nvidia.com/doca/archive/3-5-0/doca-release-notes)
- [mlx5 PMD guide](https://doc.dpdk.org/guides-25.11/nics/mlx5.html)
