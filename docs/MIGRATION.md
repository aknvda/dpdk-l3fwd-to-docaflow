# IPv4 migration behavior

This milestone reimplements the forwarding path of pinned DPDK `examples/l3fwd`
with DOCA Flow 3.3. Upstream stays unchanged. It is not a translation of every
DPDK API or every `l3fwd` option.

| Upstream responsibility | Migration implementation |
| --- | --- |
| Route-file loading | `forward.c`: IPv4 prefixes /1 through /32, logical ports 0/1, maximum 1024 unique routes |
| `rte_lpm` destination lookup | `flow.c`: destination IPv4 LPM pipe per ingress port |
| MAC rewrite and TTL decrement | One rewrite entry per ingress, forwarding to the paired egress |
| Packet polling and transmit | `main.c`: DPDK queue 0 on each port for software exceptions |
| Rule setup | Synchronous errors plus per-entry asynchronous completion checks, bounded to two seconds per submitted entry |
| Device lifecycle | Explicit DOCA device open/probe, DPDK queues, flow ports and bidirectional pairing; teardown in reverse dependency order |

The DOCA pipeline on each ingress port is:

```text
root IPv4 admission -> destination LPM -> cross-port MAC/TTL rewrite -> paired port
         | miss              | miss or same-port hit
         +-------------------+----> catch-all RSS pipe -> software Rx/forward/Tx
```

RSS is the exception pipe's matching action. Miss actions point to that pipe;
they do not use RSS directly. Exceptions reach software before any rewrite,
so the application applies the TTL/MAC changes once.

The root admits untagged, unfragmented IPv4 packets with IHL 5, valid parser
L3/checksum flags and TTL 2..255. There are 254 TTL entries, one LPM entry per
route, one rewrite entry and one exception entry per ingress. Root matching,
LPM support and the combined actions must still be validated on the target NIC.
Entries are completed individually for bounded resource use; insertion is not
batched or optimized for control-plane throughput in this version.

The software backend uses the same route loader and packet rewrite code as the
DOCA exception path. It accepts only two **file-backed** PCAP virtual ports.
No physical probing or live-interface PCAP mode is allowed. Both backends use one
worker and one Rx/Tx queue per port. There is no ARP/ND, ICMP generation, neighbor
discovery, IPv6 forwarding, VLAN routing, dynamic route API or jumbo-frame support.
Next-hop MAC addresses must be supplied explicitly for a physical test.

## Semantics and boundaries

- Longest prefix wins; host bits in prefixes are normalized. Duplicate normalized
  prefixes are replaced by their last value. Empty/malformed files, /0, disabled
  output IDs and more than 1024 unique routes are rejected before device access.
- Route misses return to ingress, matching upstream. Same-port routes are
  software exceptions in this pipeline, so a workload's route distribution
  directly affects its achievable offload fraction.
- Software forwarding checks version, IHL and lengths. It drops non-IPv4,
  VLAN and structurally malformed/truncated frames; it does not validate IPv4
  header checksums. Well-formed IPv4 options and fragments
  take the software path, but their full upstream equivalence is not established.
- Software TTL 0/1 behavior preserves the pinned sample's wrap/decrement rather
  than adding router-style TTL expiry and ICMP. These inputs are excluded from
  hardware rewriting and are part of the software differential corpus.
- The upstream sample increments the stored IPv4 checksum word directly.
  The software backend preserves that little-endian behavior. **Hardware checksum
  equivalence remains an open acceptance gate.** Input checksum `0xfeff` becomes
  `0xffff` in upstream, whereas full recomputation produces `0x0000` (both encode
  a valid output). A valid noncanonical `0xffff` input produces `0x0000` upstream
  after TTL decrement, while correct recomputation gives `0x0100`. The root cannot
  distinguish these checksum values using its current match fields. They are
  included in the extended corpus, and hardware must not be called bytewise
  equivalent until its output and an explicit compatibility policy are verified.
- The original and migrated software programs pass a valid IPv4/UDP corpus.
  This does not imply equal behavior for every malformed frame, a full router
  implementation, or any proven hardware performance advantage.

## Installation failures and counters

Every inserted entry must receive a successful completion before `ready`.
Submission failure, callback failure, processing failure, missing completion or
unexpected completion count aborts setup. Per-port callback contexts remain alive
through port stop and flow destroy. SDK-supported pipes and entry APIs are used;
there is no emulated DOCA backend presented as hardware.

Each rewrite entry has a hardware packet counter. Statistics also report actual
software Rx/Tx, rejected frames and unsent Tx packets. Hardware counters may lag
traffic; stop offered traffic before collecting final snapshots and correlate
them with generator captures and physical counters. Finite PCAP validation uses
the complete declared observation window and compares bytes and multiplicity by
egress; it does not assess ordering, throughput or tail latency.
