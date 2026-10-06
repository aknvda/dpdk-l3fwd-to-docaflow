# Verified results

2026-10-06. Sanitized report: host identifiers, network addresses, device serials
and raw inventories are intentionally kept outside the repository.

Implementation source: `b01012e` (IPv4 backends and tests). The expanded packet
runs preceded the final strict MAC-argument validation change; both builds and
all CLI tests were rerun afterward, followed by a passing 48-packet software
smoke test. That change does not alter packet processing or generated fixtures.

| Check | Result |
| --- | --- |
| Upstream source | Unmodified DPDK v25.11.0, `ed957165eadbe60a47d5ec223578cdd1c13d0bd9` |
| Native Linux build | PASS: full source build including l3fwd and PCAP PMD, x86_64, GCC 13.3.0 |
| Actual l3fwd packet test | PASS: 48/48 packets, 20 on egress 0 and 28 on egress 1; exact frame bytes and counts; 30-second observation window |
| Harness and CLI tests | PASS: all 8 Python tests on Linux against each migrated executable, including loss/duplicates/corruption/wrong-port/delayed output and rejection before device probing |
| Application linked to packaged DPDK | Builds against `25.11.0+doca2601.2`; PCAP replay unavailable because this installation omits the PCAP PMD. The passing replay uses the separate upstream source build. |
| Installed DOCA LPM sample | Builds against DOCA Flow 3.3.0109 and its packaged DPDK; no physical execution |
| Container recipe | Linux ARM build succeeded. End-to-end container replay was not established; the local runtime later returned an executable-format error. Use the validated native Linux path for the current baseline. |
| Migrated DOCA application | PASS: compiles/links against DOCA Flow 3.3.0109 and packaged DPDK 25.11.0+doca2601.2, GCC 13.3.0; warnings treated as errors |
| Migrated software application | PASS: compiles/links against the same upstream DPDK 25.11.0 source build used for the baseline |
| C tests | PASS: 4 suites in the DOCA build (forwarding core, EAL admission, device admission, completion fault injection); 3 in the software build |
| Sanitizers | PASS: portable forwarding, EAL admission and device admission suites with AddressSanitizer and UBSan on macOS ARM and Linux x86_64 |
| Extended packet comparison | PASS: both real upstream and migrated software executables produced all 2326 expected frames across 1024 routes, 1140 on egress 0 and 1186 on egress 1; 30-second window per run |
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

The original 48-packet baseline result was:

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

## Migrated application validation

The build and test commands are in [README.md](../README.md). Both executables
were then run with `--extended --route-count 1024`. Each produced:

```json
{
  "status": "PASS",
  "routes": 1024,
  "extended": true,
  "observation_seconds": 30,
  "packets": 2326,
  "per_port": {"0": 1140, "1": 1186}
}
```

The extended corpus covers the base overlap/miss cases at TTL 0, 1, 2, 64 and
255 and four frame sizes, four checksum boundaries for each base destination,
and 1019 additional /32 routes exercised from both ingress ports. Route tables
and inputs are deterministic. The complete frame bytes and multiplicity are
checked per output port; the comparison does not infer success from packet
counts alone.
The input PCAPs and generated route files were verified byte-identical between
the runs, and the two applications' final captures were also compared directly
as per-port frame multisets: PASS.

DOCA completion tests inject immediate submission failure, processing failure,
callback failure, no callback, extra callback, successful completion and deletion
callbacks. They exercise the production completion gate through the actual SDK
ABI, with the processing function wrapped. No physical DOCA ports are opened by
these tests, so they do not prove that the pipes can be installed on a NIC.

Independent code review identified unsupported direct RSS miss actions and an
unwanted MTU reset. The implementation now chains misses through an RSS exception
pipe, preserves the existing MTU and rejects jumbo MTUs before configuration.
The final SDK builds and software packet runs include those corrections.

Hardware admission, link wiring, permission to use the reserved ports, generator
capture and line-rate capacity have not been established. The checksum boundaries
also expose an explicit hardware-equivalence question described in
[MIGRATION.md](MIGRATION.md). This report establishes a built implementation and
software corpus parity, not a completed hardware migration acceptance test.
