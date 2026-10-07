# Verified results

Updated 2026-10-07. Sanitized report: host identifiers, network addresses, device serials
and raw inventories are intentionally kept outside the repository.

## Internal PHY end-to-end result

Two consecutive cable-free runs passed the full **1024-route / 2326-packet**
corpus under the explicit `hardware` checksum contract, on ConnectX-6 Dx firmware
22.48.1000 with DOCA 3.3.0109 and packaged DPDK. **Exact upstream byte parity
fails:** ten offloaded checksum boundary cases differ, as detailed below. No
packet was omitted, and the strict test remains the default.

| Measurement, each run | Result |
| --- | --- |
| Captured egress frames | 1140 on port 0, 1186 on port 1; all full bytes match the selected contract |
| Hardware-forwarded packets by ingress | 557 / 542 (1099 total) |
| Software Rx by ingress | 606 / 621 |
| Software Tx by egress | 598 / 629 (1227 total) |
| Software drops / unsent Tx / capture drops | All zero |
| Physical Rx and Tx on port 0 | 2303 each: 1163 injected inputs + 1140 returned outputs |
| Physical Rx and Tx on port 1 | 2349 each: 1163 injected inputs + 1186 returned outputs |
| Twelve NIC error/discard counter deltas | All zero on both ports |
| Shutdown and restart | Both exits 0; no SDK errors; PHY loopback disabled and interface settings/default routes restored |
| Regression tests | 37 Python tests against each Linux executable, no skips; 6 DOCA and 4 software C suites pass |

The strict run delivered every packet with the expected hardware/software counts,
but failed byte comparison: four checksum differences on egress 0 and six on
egress 1. Five cases transform input `feff` into hardware `0000` versus upstream
`ffff`; both outputs are valid one's-complement encodings. Five cases transform
valid input `ffff` into hardware `0100` versus upstream `0000`; the upstream
output checksum is invalid after the TTL change.

The separate `hardware` contract independently calculates canonical checksums
only for offloaded packets, before replay, and requires exact equality for all
other bytes and all software-path packets. Results explicitly record
`upstream_byte_equivalent: false`. This confirms actual hardware forwarding with
a documented compatibility difference; it does not establish exact equivalence
or authorize silently replacing the strict contract in downstream acceptance.
See [INTERNAL_LOOPBACK.md](INTERNAL_LOOPBACK.md) for reproducible commands.

The test hook uses two additional pipes per port to terminate returned frames in
the kernel. External cables, optics, peer interoperability, line rate, latency
and Vera/Substrate benefits remain unmeasured.

## Earlier baseline and control-plane evidence

Implementation source: `b01012e` (IPv4 backends and tests). The expanded packet
runs preceded the final strict MAC-argument validation change; both builds and
all CLI tests were rerun afterward, followed by a passing 48-packet software
smoke test. That change does not alter packet processing or generated fixtures.
Startup diagnostics, cancellation and interface restoration: `3077dd6`; both
builds, all C/Python suites, portable sanitizers and the three physical failure
scenarios below were verified for this revision.
Dependency-ordered DOCA teardown: `35e1edc`; both builds, 6 DOCA C suites,
4 software C suites and 8 Python tests against each executable pass. The physical
admission and restart results below use this revision.
Physical test runner: `f7cebfd`, with Linux socket integration and the unnamed
Unix socket address correction in `e3d3cb3`. The 2026-10-06 wire-runner evidence
below was collected before that correction; all 24 Python tests against each
executable and both C suites were then rerun and passed with it. The namespace
fixture passed before the correction. Final runner hardening is in `95e5052`.
On 2026-10-07, all 29 Python tests passed against each Linux executable, all
6 DOCA and 4 software C suites passed, and the namespace and physical no-link
tests were repeated. Native source, configuration and test files were verified
to match the tested checkout (`c685d0b`, which adds documentation to `95e5052`).

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
| C tests | PASS: 6 suites in the DOCA build (forwarding core, EAL admission, device admission, kernel interface restoration, completion fault injection, paired-port/pipe cleanup); 4 in the software build |
| Sanitizers | PASS: portable forwarding, EAL admission, device admission and kernel interface restoration suites with AddressSanitizer and UBSan on macOS ARM and Linux x86_64 |
| Extended packet comparison | PASS: both real upstream and migrated software executables produced all 2326 expected frames across 1024 routes, 1140 on egress 0 and 1186 on egress 1; 30-second window per run |
| Physical startup admission | PASS after separately approved firmware maintenance: DOCA 3.3.0109, packaged DPDK, ConnectX-6 Dx firmware 22.48.1000, VNF/HWS; all application pipes and entry completions accepted with 5 and 1024 routes |
| Physical teardown and restart | PASS: two consecutive 1024-route runs reached ready, read counters and exited 0 without SDK error messages; both test ports returned DOWN with MTUs and management route preserved |
| Failure cleanup on physical adapter | PASS after correction: both admitted ports returned to administrative DOWN, MTUs preserved, management route unchanged |
| Extended upstream reference for wire replay | PASS: fresh actual upstream run, 1024 routes and 2326 complete output frames |
| Wire reference, isolation, process and capture tests | PASS: all 29 Python tests against each compiled executable on Linux, no skips; includes cancellation during cleanup and rejection of changed or missing NIC error counters |
| Linux packet-socket integration | HARNESS_PASS on final runner: real AF_PACKET/veth checks in a temporary network namespace; ordinary delivery, delayed duplicate rejection and wrong-port rejection; no DOCA emulation |
| Required physical counter availability | PASS: both packet counters and all twelve error/discard counters available on each of four reserved ports |
| Physical runner with absent links | BLOCKED on final runner: 1024-route DOCA ready, no carrier, no traffic sent, DUT exit 0 with no SDK errors and all four reserved interfaces/settings restored |
| Hardware forwarding / throughput / latency | Hardware forwarding now covered by internal PHY result above; throughput and latency remain unmeasured |

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

The initial privileged physical startup attempt on isolated ports exposed
`BAD_PARAM_ERR` for the HCA capability query with `op_mod=0x41`, followed by
`Failed to get hws cap`. The error occurs during port creation, before the
application's LPM or rewrite rules can be evaluated. The tested firmware predates
the HWS minimum documented by the pinned DPDK release. This is an admission
failure, not evidence of a working offload path or proof that an upgrade alone
will validate every action combination.

The initial failure also showed that mlx5 port stop leaves Linux's administrative
UP flag set. Cleanup now restores the captured kernel interfaces independently of
DPDK port handles, after SDK/DPDK teardown. It also handles ordinary startup
cancellation. Kernel restoration and cancellation regression tests failed before
the fixes and passed afterward. SDK warnings/errors and the failing API expression are now
reported to stderr; retain these raw logs privately because SDK messages can
contain device identifiers.

Three cleanup scenarios were also exercised against the isolated physical adapter:
the actual firmware rejection, a test-injected error after real probing and ethdev
release, and test-injected SIGTERM during real probing. All exited unsuccessfully
without READY and restored both interfaces DOWN, preserved MTUs and preserved the
management route. These are failure-path tests, not forwarding tests.

After separately approved firmware maintenance, the DUT ran firmware 22.48.1000
on both functions. The unchanged pipeline then installed successfully. This
cleared the earlier capability-query failure, while exposing a teardown problem:
the SDK reported busy groups even though the process returned success. Flushing
all paired ports before stopping them was insufficient on its own. Retaining
each pipe handle and explicitly destroying root, LPM, rewrite and exception pipes
in dependency order removed those errors. All ports are flushed before any port
is stopped. SDK-boundary regressions cover incoming pipe references, paired-port
references, every partial pipeline creation prefix and continued cleanup after
a port-stop error; the regressions failed before the fixes.

With the final teardown implementation, a 5-route run and two consecutive
1024-route runs each reached `ready`, returned counter snapshots and exited 0
without SDK error messages. The two 1024-route runs also verified administrative
DOWN, unchanged MTUs, no addresses on test ports and an unchanged management
route afterward. The SDK still emits queue-depth adaptation and already-detached
device warnings; those are retained in the private logs. This is evidence of
control-plane admission, bounded route installation and restart, not a route
installation performance benchmark or a maximum NIC capacity measurement.

No packets were sent in those early startup runs: the spare links reported no cable and both hardware
and software packet counters were zero. Link wiring, generator capture and
line-rate capacity remain open. An existing isolated switch path or another
wired testbed can substitute for new direct cables; functional testing does not
require 100GbE. See [HARDWARE_TEST_REQUEST.md](HARDWARE_TEST_REQUEST.md).
Subsequent internal PHY runs, reported at the top of this document, establish
hardware forwarding and the exact checksum compatibility boundary described in
[MIGRATION.md](MIGRATION.md).

## Repeatable physical packet runner

[WIRE_VALIDATION.md](WIRE_VALIDATION.md) documents the upstream-reference and
physical replay commands. The runner uses captured output from an actual
passing upstream run, verifies that inputs and routes match the declared corpus,
and changes only Ethernet MAC addresses for the physical topology. It checks
complete frame bytes, hardware/software counters, capture drops and physical
port counter deltas. Checksum edge cases are retained unchanged.

The real Linux packet-socket fixture passed three cases: ordinary delivery,
detection of a delayed duplicate and rejection of a frame on the wrong port.
It exercises the same capture/replay function in an isolated veth namespace;
its result is explicitly `HARNESS_PASS`, not a DOCA or physical NIC result.
The first full Linux unit run then exposed an unnamed Unix socket address of
`None`; the capture code now examines outgoing-packet metadata only for tuple
addresses. The real socketpair regression failed before that fix. Both native
24-test Python runs and both C suites passed afterward.

The physical runner's read-only admission succeeded. Its subsequent execution
reached the DOCA `ready` event with 1024 routes, timed out waiting for the absent
links and returned `BLOCKED` with exit 2. `traffic_sent` was false and `restored`
was true. The DUT exited 0 with no SDK error messages and zero packet counters.
Independent before/after checks confirmed all four reserved ports DOWN and
unaddressed with MTU 1500, restored per-interface IPv6 settings, unchanged default
management route, unchanged physical packet counters and unchanged free hugepage
counts. No physical packet forwarding claim follows from these cleanup checks.

The physical acceptance path still needs connected links. It must pass exact
packet bytes and both offload/exception counters before hardware equivalence
can be claimed; throughput and latency need their own subsequent experiments.

### Post-review hardening (2026-10-07)

Revision `95e5052` fixes three issues found during independent branch review:
cancellation during DUT wait or interface restoration, a failed port-down action
skipping IPv6 restoration, and physical NIC error/discard counters not affecting
acceptance. SIGINT/SIGTERM are now deferred through each cleanup phase, every
restoration step is attempted, and the documented required NIC error/discard
counters must have zero deltas. Missing counters also prevent PASS.

The regressions failed before the fixes. The final local suite passed 24 tests
with five compiled-executable checks skipped (29 total). It includes controller
cleanup with SIGINT and SIGTERM during both shutdown phases, actual child-process
reaping, failed port-down restoration, and counter-error injection on every port.

After lab access was restored on 2026-10-07, the final revision passed all
29 tests against each compiled Linux executable with no skips, all 6 DOCA and
4 software C suites, and the three real AF_PACKET namespace cases. All fourteen
required physical counters were present on each of the four reserved ports.

The final physical execution installed all 1024 routes and reached `ready`,
then returned `BLOCKED` because the test links had no carrier. It sent no traffic,
exited the DUT with code 0 and no SDK errors, and restored all four interfaces.
Independent before/after snapshots confirmed identical interface state, IPv6
settings, IPv4 and IPv6 default routes, physical packet/error/discard counters
and free hugepage counts. No DUT process remained. These results validate the
runner's native execution and no-link cleanup. Later internal PHY tests establish
hardware forwarding without external connectivity; external-wire and performance
coverage remain open.
