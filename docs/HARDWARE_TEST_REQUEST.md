# Hardware validation request for data-center operations

## Purpose and timing

Provide an isolated packet path to validate the migration from DPDK l3fwd to
NVIDIA DOCA Flow. The software build and offline packet tests already pass.
Final hardware acceptance requires packets to enter the NIC receive path, traverse
the installed DOCA rules and leave the expected physical port. Rule installation
alone cannot prove forwarding behavior, and PCAP virtual ports bypass the NIC.

This is a planned validation requirement, with no same-day cabling requirement.
Software work and cable-free device admission can continue before the traffic
path is available. Hardware acceptance remains incomplete until wire tests pass.

## Minimum resource request

- Two reserved DUT ports on one compatible NVIDIA adapter, with a separate
  management path and a supported SDK/firmware combination.
- Two generator/capture ports connected one-to-one to the DUT ports. Direct
  cables, existing isolated switch paths or an existing wired testbed all work.
- Any common supported link speed for functional testing, with matching optics,
  cabling and FEC. 100GbE is needed only if measuring 100GbE performance.
- Exclusive use of the selected test interfaces during the agreed window.
  Port labels and wiring details are supplied privately after reservation.

A local spare adapter can provide low-rate functional traffic and capture. Use a
separate generator host for throughput or latency claims to avoid shared-host
CPU, memory and PCIe interference. Firmware maintenance is a separate prerequisite
with its own device scope and recovery plan; installing cables does not authorize it.

## Tests and evidence delivered

Send finite synthetic IPv4 traffic in both directions and compare captured frames
against the pinned DPDK reference: egress selection, overlapping routes, route
misses, MAC rewrites, TTL, checksums, payload, loss and duplication. Exercise the
software exception path as well as the hardware path. Correlate physical captures
with DOCA hardware counters and application software counters to demonstrate which
packets were actually offloaded. Preserve failing edge cases in the report.

Start with low-rate correctness runs. Schedule rate sweeps only after they pass.
Record port state before testing and verify restoration afterward. Keep lab
identities, real addresses, topology and raw logs/captures outside GitHub.

The resulting evidence supports a hardware-validated migration claim. Until then,
the defensible result is a built application with verified software behavior and
explicitly unverified hardware forwarding and performance.
