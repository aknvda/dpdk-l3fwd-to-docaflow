# Optional external-wire validation request for data-center operations

## Purpose and timing

Provide an isolated external packet path for an optional follow-up to the
completed two-port IPv4 migration. Real-NIC internal PHY tests already establish
exact upstream bytes in the default hardware-assisted policy and full forwarding
offload under its explicit checksum contract. See [the results](RESULTS.md).

External links add evidence for optics/cables, a peer NIC and link behavior, and
are needed for external throughput/latency claims. They are not a blocker for the
completed functional milestone or its [migration guide](MIGRATION_GUIDE.md).
No same-day operations work is required for that milestone.

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
packets used hardware lookup or full forwarding offload under the selected policy. Preserve failing edge cases in the report.

Start with low-rate correctness runs. Schedule rate sweeps only after they pass.
Record port state before testing and verify restoration afterward. Keep lab
identities, real addresses, topology and raw logs/captures outside GitHub.

The resulting evidence would extend the existing internal PHY result to external
wire interoperability. The explicit hardware policy retains its documented
checksum differences; the default policy already matches the tested upstream bytes. Performance remains a separate, controlled measurement.
