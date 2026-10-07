# IPv4 DOCA Flow Implementation Plan

> Historical planning record. The two-port IPv4 functional migration is now
> implemented and validated. Use the [focused migration guide](../../MIGRATION_GUIDE.md)
> and [verified results](../../RESULTS.md) for current behavior, commands and coverage.
> The default now combines hardware lookup with exact software rewriting; full
> forwarding offload is an explicit policy. Original planning text below is
> retained as history, not an active list of remaining work.

> For agentic workers: use superpowers:executing-plans for inline execution and a final independent review.

**Goal:** Implement a runnable two-port IPv4 migration with a real DOCA backend
and a differential-testable software backend.

**Architecture:** Shared portable C routes and packet logic, DPDK runtime,
DOCA root/LPM/rewrite pipes and explicit software exceptions. Keep device
configuration and private lab information out of the repository.

**Tech Stack:** C11, DOCA 3.3, DPDK 25.11, Meson, Python standard-library tests.

**Spec:** ../specs/2026-10-06-ipv4-implementation.md

## Global Constraints

- Keep upstream unchanged. No physical probes before configuration validation.
- No private lab identifiers or raw inventories in Git.
- No hardware/performance success claim based on compilation or software tests.

## Review Focus

- Truncated/malformed packets cannot cause out-of-bounds access.
- Invalid/duplicate prefixes cannot silently produce different route tables.
- RSS exceptions must not receive a second TTL decrement or MAC rewrite.
- Failed asynchronous installation cannot produce READY or a success exit.
- EAL probing and cleanup must preserve unrelated/management interfaces.

### Task 1: C forwarding core

Files: `src/forward.[ch]`, `tests/test_forward.c`, `meson.build`.
Interfaces: route table loader/lookup and in-place IPv4 frame forwarding.
- [ ] Add tests for prefix overlap, duplicate replacement, bad config, misses,
      MAC/TTL/checksum behavior, truncation and unsupported headers; observe RED.
- [ ] Implement core; compile with warnings and run unit tests with sanitizers.
      Expected: all tests pass without sanitizer errors.
- [ ] Commit the tested core.

### Task 2: DPDK application and DOCA pipes

Files: `src/main.c`, `src/flow.[ch]`, `src/device.[ch]`, `meson_options.txt`.
Consumes Task 1 route and frame interfaces. Produces `l3fwd-docaflow` executable.
- [ ] Add CLI rejection/differential tests and observe missing-backend failure.
- [ ] Implement explicit backend selection, safe device admission, DPDK queues,
      software Rx/Tx, DOCA pipeline, completion accounting and cleanup.
- [ ] Build against real installed SDK and run software PCAP differential tests.
      Expected: exact corpus parity; no physical interfaces touched.
- [ ] Commit application and tests.

### Task 3: validation and publication

Files: `README.md`, `docs/RESULTS.md`, `docs/VALIDATION.md`, test runner scripts.
- [ ] Run expanded corpus and negative CLI tests, inspect build warnings.
- [ ] Run physical admission/traffic tests only if safe lab access is available;
      otherwise state the exact missing evidence and retain the runnable backend.
- [ ] Request independent code review, fix material findings with regression tests.
- [ ] Publish sanitized documentation and reviewed implementation branch; verify
      remote SHA and repository description remain correct.
