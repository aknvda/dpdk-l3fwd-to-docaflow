# Bootstrap implementation plan

Goal: establish an executable upstream baseline and an actionable lab contract.
Architecture: unmodified upstream submodule plus independent test/configuration
files; DOCA application follows once the target SDK and device are selected.
Tech: C (DPDK), Python standard library (packet fixtures), Linux containers.
Spec: ../specs/2026-10-06-l3fwd-migration-design.md

Global constraints: preserve upstream licensing; no SDK redistribution; do not
equate software PCAP testing with hardware offload or performance validation.

## Task 1: upstream and build

Pin v25.11 to its full commit ID. Add a Linux Containerfile building l3fwd and
the PCAP PMD. Build it with Podman. Expected: actual l3fwd executable, exit 0.

## Task 2: packet validation

Add a strict capture comparator with negative tests for loss, duplication,
wrong port and byte corruption. Then implement generation/replay of shared
IPv4 fixtures into the actual baseline. Expected: deterministic packet counts
and exact expected frames on both egress ports. Save command/log/results.
Interfaces: configs/*.cfg selects routes used by fixtures; tests/pcap_smoke.py
executes the container-built application.

## Task 3: lab requirements and publish

Document supported-stack selection, minimum physical lab, correctness gates,
hardware installation checks and fair performance/scale experiments. Record
actual local evidence. Create a private repository in the confirmed personal
GitHub account and push the initial milestone. Verify owner, privacy and SHA.

## Review focus

Check packet tests cannot pass with empty captures, duplicate or misrouted
frames. Check subprocess cleanup, fixture checksums and advertised limitations.
Check docs distinguish implemented tooling from proposed hardware tests.
