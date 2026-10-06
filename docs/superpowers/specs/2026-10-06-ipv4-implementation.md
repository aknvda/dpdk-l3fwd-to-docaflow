# IPv4 migration implementation

Implement the already selected two-port IPv4 LPM milestone against DOCA 3.3.
The application remains C and retains DPDK packet I/O for software forwarding.
Preserve the pinned upstream source and its existing baseline test.

## Components and behavior

- A portable C core loads the upstream `Raddress/prefix port` route format,
  performs longest-prefix lookup, and implements the admitted IPv4 packet
  contract. Route misses return to ingress. Duplicate prefixes use the last
  configured route. Invalid configuration is rejected before device operations.
- A DPDK executable has explicit `software` and `doca` backends. Software mode
  supports PCAP virtual ports for differential tests against upstream. It is a
  test/control path, not evidence of hardware offload.
- In DOCA mode a root classifier admits untagged, unfragmented IPv4 headers
  without options, valid parser/checksum state and TTL >= 2. An LPM pipe selects
  an egress rewrite pipe for cross-port routes. The rewrite changes source and
  destination MAC and decrements TTL. Hardware checksum behavior must be verified
  with physical packet captures. Same-port routes and misses reach DPDK RSS
  without prior packet modification. Root misses also reach the software path.
- Software supports safe untagged IPv4 forwarding; unsupported L2/IPv6 and
  malformed/truncated frames are counted and dropped. Exact upstream parity is
  claimed only for the documented admitted corpus, not all malformed inputs or
  a complete router. No ARP, ICMP generation, IPv6, VLAN, tunnel or dynamic-route
  feature is implied.
- Rule submission must finish successfully on both ports before READY. Counters
  distinguish software forwarding/drops and hardware entry hits. Failed setup
  returns an error and tears down partially created resources.

## Device safety and privacy

No hostnames, real network addresses, serials or internal topology in Git.
Physical use requires two explicitly supplied PCI devices and an explicit
physical-port opt-in. Reject configured network interfaces on those devices,
including management interfaces, before probing them. Use a restricted EAL
allowlist for deferred DOCA probing; never discover every physical port by
default. Do not change firmware, interface addressing, eswitch mode or drivers.
Only run hardware traffic after an isolated topology and access are confirmed.

## Verification

Test route parsing/overlaps/misses and packet boundaries with C unit tests and
sanitizers. Run the same finite PCAP corpus through upstream and the new C
software backend, comparing complete per-port outputs. Build the real DOCA
backend against installed headers/libraries; do not substitute mock headers.
Record hardware insertion/traffic/performance as pending until actually tested.
