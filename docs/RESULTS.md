# Verified results

2026-10-06. Sanitized report: host identifiers, network addresses, device serials
and raw inventories are intentionally kept outside the repository.

| Check | Result |
| --- | --- |
| Upstream source | Unmodified DPDK v25.11.0, `ed957165eadbe60a47d5ec223578cdd1c13d0bd9` |
| Native Linux build | PASS: full source build including l3fwd and PCAP PMD, x86_64, GCC 13.3.0 |
| Actual l3fwd packet test | PASS: 48/48 packets, 20 on egress 0 and 28 on egress 1; exact frame bytes and counts; 30-second observation window |
| Harness regression tests | PASS: 3 tests on macOS and Linux, including loss, duplicates, corruption, wrong port and delayed duplicate output |
| Application linked to packaged DPDK | Builds against `25.11.0+doca2601.2`; PCAP replay unavailable because this installation omits the PCAP PMD. The passing replay uses the separate upstream source build. |
| Installed DOCA LPM sample | Builds against DOCA Flow 3.3.0109 and its packaged DPDK; no physical execution |
| Container recipe | Linux ARM build succeeded. End-to-end container replay was not established; the local runtime later returned an executable-format error. Use the validated native Linux path for the current baseline. |
| Migrated DOCA application | Not implemented yet |
| Hardware offload / throughput / latency | Not tested; no performance claim |

## Reproducing the passing baseline

From the repository root on a Linux system with the development dependencies:

```bash
meson setup build/dpdk upstream/dpdk -Dplatform=generic -Dexamples=l3fwd \
  -Dtests=false -Denable_drivers=net/pcap -Dmax_numa_nodes=1
ninja -C build/dpdk -j4
python3 -m unittest discover -s tests -v
python3 tests/pcap_smoke.py --binary build/dpdk/examples/dpdk-l3fwd
```

The recorded result was:

```json
{
  "status": "PASS",
  "scope": "DPDK IPv4 PCAP only; no DOCA or performance validation",
  "observation_seconds": 30,
  "packets": 48,
  "per_port": {"0": 20, "1": 28}
}
```

This covers the configured prefix overlap and miss cases for valid IPv4/UDP
traffic with TTL 64, four packet sizes and two virtual ingress ports. It does
not establish malformed-packet behavior, fragmentation, per-flow ordering,
NIC parser behavior, DOCA action support, scalability or speedup.

The review found a premature-stop bug in the test harness: seeing the expected
packet count could hide later duplicates. A real-subprocess regression failed
before the fix and passed afterward. The final harness observes the full
declared interval before comparing captures, and the real baseline was rerun
after that change.
