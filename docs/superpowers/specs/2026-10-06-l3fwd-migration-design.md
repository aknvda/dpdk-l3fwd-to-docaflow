# l3fwd to DOCA Flow: initial migration design

> Historical planning record. The two-port IPv4 functional migration is now
> implemented and validated. Use the [focused migration guide](../../MIGRATION_GUIDE.md)
> and [verified results](../../RESULTS.md) for current behavior, commands and coverage.
> The default now combines hardware lookup with exact software rewriting; full
> forwarding offload is an explicit policy. Original planning text below is
> retained as history, not an active list of remaining work.

The accepted starting application is the official DPDK `examples/l3fwd`.
Keep upstream unchanged and pinned, and begin with IPv4 LPM in poll mode
on two ports. This repository is the working home for the migration.

## First deliverable

Pin upstream DPDK v25.11 source in a submodule. Build the actual C application
in Linux and establish packet-level regression fixtures with the PCAP PMD.
Document the hardware lab and migration contract before binding implementation
to a specific DOCA release and NIC. The upstream pin is a software reference;
it is not a claim of ABI compatibility with a DOCA-packaged DPDK.

The initial corpus is Ethernet/IPv4/UDP, without VLAN, options or fragmentation,
TTL >= 2, overlapping routes, two ingress ports, and route misses. Compare
egress port, complete frame bytes, counts, destination/source MAC rewrite,
TTL and IPv4 checksum. Ignore capture timestamps and packet ordering across
flows. A future ordering test will use explicit per-flow sequence numbers.

## Intended hardware path

Root classification -> IPv4 LPM -> MAC rewrite and TTL/checksum update -> port.
Use a software path for packets outside the admitted fast-path contract.
Confirm actual parser and action combinations against the selected SDK/device.
Do not assume DOCA Flow is a replacement for DPDK's entire packet I/O layer.
Rule submission is not readiness: verify asynchronous completion and traffic
counters before reporting offload success.

Preserve upstream behavior, including route misses returning to ingress. Do not
silently add router features (ARP, ICMP generation, TTL-expiry handling, routing
protocols) or normalize malformed packets differently. Characterize those cases
on the chosen upstream build before extending the equivalence claim.

## Boundaries

No DOCA binary or hardware-performance claim belongs to the bootstrap milestone.
No customer source is needed for this open-source experiment. Later application
assessment needs route/flow configuration, hot-path source, exception behavior,
deployment topology and representative traffic. ACL, IPv6, NAT, tunnels and
multi-tenant scale follow a correct two-port IPv4 baseline.
