# Cable-free hardware validation

Internal PHY loopback returns each transmitted frame to the same NIC port's
receive path. The runner injects through Linux AF_PACKET, traverses the actual
DOCA admission/LPM/rewrite pipeline, and captures the returned egress frame.
Same-port and TTL exceptions traverse the actual application software path.
This is a functional test, not a throughput or latency benchmark.

## Requirements

- One exclusively reserved two-port DUT adapter, separate from management, with
  the SDK/driver/firmware admission described in [VALIDATION.md](VALIDATION.md).
- Both functions DOWN, unaddressed, MTU 1500, no active VFs or upper interfaces.
- MFT `mlxlink` and `mlxreg`, root privileges, internal PHY support reported by
  PPLR, and no pre-existing loopback configuration. The tested combination is
  ConnectX-6 Dx, firmware 22.48.1000, DOCA 3.3.0109 on Linux x86_64.
- A passing extended output directory from the real, pinned upstream l3fwd.
  Keep all configuration, logs and captures outside every Git checkout.

No generator adapter or external cable is required for this fixture. The runner
does not flash firmware, reset an adapter, change global networking, or allocate
hugepages. Exclusive reservation remains an operator prerequisite.

## Run

Create a private JSON file with exactly `doca_binary` (absolute executable path),
`dut_pci` (two reserved PCI function strings), and `cpu` (an available CPU number).
Use real values only in that private file. Set paths privately, then run:

```bash
: "${LAB_CONFIG:?}" "${UPSTREAM_REFERENCE:?}" "${PRIVATE_OUTPUT:?}"
python3 tests/wire_smoke.py --config "$LAB_CONFIG" \
  --reference "$UPSTREAM_REFERENCE" --output "$PRIVATE_OUTPUT" \
  --internal-loopback --preflight-only

# Strict upstream-byte comparison remains the default.
sudo python3 tests/wire_smoke.py --config "$LAB_CONFIG" \
  --reference "$UPSTREAM_REFERENCE" --output "$PRIVATE_OUTPUT" \
  --internal-loopback --allow-physical-ports

# Explicit alternative: canonical checksum on hardware-forwarded packets.
sudo python3 tests/wire_smoke.py --config "$LAB_CONFIG" \
  --reference "$UPSTREAM_REFERENCE" --output "$PRIVATE_OUTPUT" \
  --internal-loopback --allow-physical-ports --checksum-policy hardware
```

Read-only preflight checks port admission and reference provenance. Actual PHY
capability and disabled-loopback checks occur before enabling loopback during
execution. The default aggregate rate is 200 packets/s, with a three-second
post-send observation window. Capture sockets bind after port setup and before
traffic; binding while DOWN can retain a pending Linux AF_PACKET `ENETDOWN` error.

## Packet path and acceptance

```text
AF_PACKET injection -> local PHY loopback -> DOCA ingress admission/LPM
 -> hardware rewrite or software exception -> selected egress port Tx
 -> local PHY loopback -> test source-MAC guard -> kernel AF_PACKET capture
```

Input source markers differ from both DUT MACs. Output source MACs identify
returned rewritten frames, preventing recirculation. The test-only root guard
forwards to a non-root kernel-target pipe because DOCA 3.3 rejects that target
directly on a root pipe. The original admission pipe follows the guard's miss.
Normal application mode has neither test pipe.

Both contracts require exact complete frames per egress, multiplicity, expected
hardware/software counters, zero capture drops, zero changes in twelve NIC
error/discard counters and exact physical Rx/Tx counts for both loopback legs.
All reference packets remain in the test. No observed packet is normalized.

`upstream` compares against the unmodified real upstream output, after Ethernet
address adaptation. It correctly fails on ten known checksum cases in the
2326-packet corpus. `hardware` computes the expected canonical IPv4 checksum
only for packets independently classified as offloaded, before transmission.
Everything else, including software exception output, stays unchanged. The
result names the policy and includes `upstream_byte_equivalent: false`; a PASS
under `hardware` must never be described as exact upstream parity.

Artifacts retain input, strict upstream expected, hardware expected and actual
PCAPs; a per-case checksum difference list; reference and binary hashes; command,
SDK log, physical counters and restoration result. Any different checksum,
payload corruption, missing/extra frame, wrong port or unexpected counter fails.

On shutdown, the runner stops/reaps the application, closes sockets, brings ports
DOWN, disables PHY loopback, and restores/verifies per-port IPv6 settings, MTU,
MAC, identity and both default routes. Partial setup and SIGINT/SIGTERM follow
the same restoration path. SIGKILL, host failure or a crashed process can bypass
cleanup; independently inspect the reserved ports before restarting.

## Coverage boundary

This validates the real parser, route selection, actions, software exceptions and
delivery through the PHY return path. It does not validate cables/optics, remote
peer behavior, external link failure recovery, line rate, latency, full malformed
packet equivalence or a Vera/Substrate performance benefit. External-wire testing
can follow when that evidence is needed; it is not required to repeat this test.

Sources: [NVIDIA MFT mlxlink loopback controls](https://networking-docs.nvidia.com/mftswum/4350/mlxlink-utility),
the installed DOCA 3.3 `flow_fwd_target` sample and headers, and
[Linux 6.8 AF_PACKET notifier behavior](https://github.com/torvalds/linux/blob/v6.8/net/packet/af_packet.c).
