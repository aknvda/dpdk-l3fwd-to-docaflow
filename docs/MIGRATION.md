# IPv4 migration behavior

The validated IPv4 milestone reimplements the forwarding path of pinned DPDK `examples/l3fwd`
with DOCA Flow 3.3. Upstream stays unchanged. It is not a translation of every
DPDK API or every `l3fwd` option.

| Upstream responsibility | Migration implementation |
| --- | --- |
| Route-file loading | `forward.c`: IPv4 prefixes /1 through /32, logical ports 0/1, maximum 1024 unique routes |
| `rte_lpm` destination lookup | `flow.c`: destination IPv4 LPM pipe per ingress port |
| MAC rewrite and TTL decrement | Default: exact upstream software rewrite using hardware-selected egress; explicit hardware policy: one rewrite entry per ingress forwarding to paired egress |
| Packet polling and transmit | `main.c`: DPDK queue 0 on each port for hardware-assisted packets and exceptions |
| Rule setup | Synchronous errors plus per-entry asynchronous completion checks, bounded to two seconds per submitted entry |
| Device lifecycle | Explicit DOCA device open/probe, DPDK queues, flow ports and bidirectional pairing; teardown in reverse dependency order |

The default `--checksum-policy upstream` pipeline on each ingress port is:

```text
root IPv4 admission -> destination LPM -> counted egress metadata + RSS
         | miss              | miss or same-port hit          |
         +-------------------+----> exception RSS             |
                                       |                     |
                                  software LPM        metadata egress
                                       +----------+----------+
                                                  |
                              exact upstream MAC/TTL/checksum rewrite -> Tx
```

The metadata path leaves packet bytes untouched and avoids a second LPM lookup.
The application validates the metadata marker and output port before using it.
Packets without valid route metadata use the software LPM path. Every packet is
rewritten and transmitted by the CPU in this mode, including hardware route hits.
The validation runner requires exact nonzero hardware lookup and consumed
metadata counts, so losing metadata cannot silently pass as hardware assistance.

Explicit `--checksum-policy hardware` replaces the counted metadata/RSS branch
with MAC/TTL rewrite and paired-port forwarding. Eligible cross-port packets then
bypass software; misses, same-port routes and parser/TTL exceptions use software.
RSS is a matching action, never a direct miss action. Both modes rewrite once.

The root admits untagged, unfragmented IPv4 packets with IHL 5, valid parser
L3/checksum flags and TTL 2..255. There are 254 TTL entries, one LPM entry per
route, one rewrite or metadata entry and one exception entry per ingress. Root matching,
LPM support and the combined actions have passed internal PHY validation on the
reported device/SDK combination; admit other combinations independently.
Entries are completed individually for bounded resource use; insertion is not
batched or optimized for control-plane throughput in this version.

The software backend uses the same route loader and packet rewrite code as the
DOCA exception path. It accepts only two **file-backed** PCAP virtual ports.
No physical probing or live-interface PCAP mode is allowed. Both backends use one
worker and one Rx/Tx queue per port. There is no ARP/ND, ICMP generation, neighbor
discovery, IPv6 forwarding, VLAN routing, dynamic route API or jumbo-frame support.
Next-hop MAC addresses must be supplied explicitly for a physical test.

For the implementation sequence and executable validation procedure, see the
[focused migration guide](MIGRATION_GUIDE.md).

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
  Default `upstream` policy preserves that native-endian behavior through software
  rewriting, including checksum edge cases. The validated target is little-endian
  Linux x86_64. The software backend accepts only this policy.
- Explicit `hardware` policy uses the NIC TTL/checksum action. Input checksum
  `0xfeff` becomes `0xffff` in upstream versus canonical `0x0000` in hardware;
  both outputs are valid. Valid noncanonical input `0xffff` becomes `0x0000`
  upstream after TTL decrement (invalid checksum) versus hardware `0x0100`.
  These ten differences across 2326 packets remain in the corpus. The runner
  selects the same policy in the application and acceptance check; strict mode
  uses unchanged upstream bytes. Hardware mode independently computes canonical
  checksums only for offloaded packets before replay and checks every other byte
  and all software outputs against upstream. Hardware-mode PASS does not mean
  exact upstream compatibility.
- The original and migrated software programs pass a valid IPv4/UDP corpus.
  This does not imply equal behavior for every malformed frame, a full router
  implementation, or any proven hardware performance advantage.

## Internal loopback test hook

`--internal-loopback-test` requires the DOCA backend and physical-port opt-in.
It adds a root source-MAC guard and a non-root kernel capture pipe. Returned
packets with the egress port's source MAC terminate in the kernel; injected
packets with distinct marker source MACs enter the existing IPv4 pipeline.
The test runner temporarily enables internal PHY loopback on each reserved DUT
port and restores it afterward. The application does not configure PHY loopback.
Normal runs do not create these two test pipes. See [INTERNAL_LOOPBACK.md](INTERNAL_LOOPBACK.md).

## Installation failures and counters

Every inserted entry must receive a successful completion before `ready`.
Submission failure, callback failure, processing failure, missing completion or
unexpected completion count aborts setup. Per-port callback contexts remain alive
through port stop and flow destroy. SDK-supported pipes and entry APIs are used;
there is no emulated DOCA backend presented as hardware.

Each rewrite or metadata entry has a hardware packet counter. `hardware_forwarded`
counts full offload and is zero in upstream policy. `hardware_lookups` counts
hardware-assisted cross-port decisions and is zero in hardware policy.
`software_hw_lookup` counts packets whose validated hardware-selected egress was
actually used by software. Statistics also report software Rx/Tx, rejected frames
and unsent Tx packets. Hardware counters may lag
traffic; stop offered traffic before collecting final snapshots and correlate
them with generator captures and physical counters. Finite PCAP validation uses
the complete declared observation window and compares bytes and multiplicity by
egress; it does not assess ordering, throughput or tail latency.
