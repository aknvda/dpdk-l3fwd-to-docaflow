# DPDK l3fwd to DOCA Flow

An incremental migration of the official DPDK `l3fwd` application to NVIDIA
DOCA Flow. Start with two-port IPv4 longest-prefix-match forwarding, preserve
the software baseline, then validate a hardware forwarding path against it.

**Current stage: IPv4 implementation and repeatable physical validation runner.**
The application has a DOCA Flow 3.3 backend and a DPDK software backend. Physical
DOCA rule installation and teardown pass through 1024 routes. The physical runner
checks upstream packet bytes, hardware/software counters and port restoration.
Physical packet equivalence and performance remain unverified; the last physical
run was blocked by absent link carrier. See
[migration behavior](docs/MIGRATION.md), [results](docs/RESULTS.md) and
[lab requirements](docs/VALIDATION.md) for the exact boundaries.

## Layout

| Path | Purpose |
| --- | --- |
| `upstream/dpdk` | Unmodified upstream submodule, v25.11.0 at `ed957165eadbe60a47d5ec223578cdd1c13d0bd9` |
| `configs/` | Shared route inputs, including overlapping IPv4 prefixes |
| `src/` | IPv4 routes/forwarding, DPDK runtime, DOCA pipes and device admission |
| `tests/` | Packet corpus, PCAP/wire validation, isolation and negative tests |
| `containers/` | Linux build of upstream DPDK with the PCAP virtual driver |
| `scripts/lab_inventory.sh` | Read-only Linux testbed inventory |
| `docs/` | Design, requirements and measured results |

## Get the source and check the test harness

```bash
git clone --recurse-submodules https://github.com/aknvda/dpdk-l3fwd-to-docaflow.git
cd dpdk-l3fwd-to-docaflow
python3 -m unittest discover -s tests -v
bash scripts/test_core.sh  # C compiler with AddressSanitizer/UBSan required
python3 tests/pcap_smoke.py --generate-only
```

The generator creates a fresh run directory under `artifacts/pcap/`. It does
not execute DPDK or establish correctness by itself. Python 3.10+ is sufficient;
the harness has no third-party Python dependencies.

## Build and run the original application

On Linux, build the pinned DPDK source with the PCAP driver:

```bash
# Requires GCC, Meson, Ninja, pkg-config, pyelftools, libnuma-dev and libpcap-dev.
meson setup build/dpdk upstream/dpdk -Dplatform=generic -Dexamples=l3fwd \
  -Dtests=false -Denable_drivers=net/pcap -Dmax_numa_nodes=1
ninja -C build/dpdk -j4
python3 tests/pcap_smoke.py --binary build/dpdk/examples/dpdk-l3fwd
```

Alternatively, with a compatible installed DPDK development package, build the
application against that package:

```bash
export PKG_CONFIG_PATH=/opt/mellanox/dpdk/lib/x86_64-linux-gnu/pkgconfig
export LD_LIBRARY_PATH=/opt/mellanox/dpdk/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
make -C upstream/dpdk/examples/l3fwd -j2
python3 tests/pcap_smoke.py --binary upstream/dpdk/examples/l3fwd/build/l3fwd
```

The `/opt/mellanox` paths are installation-specific; use your SDK's actual
directories. This keeps the application source pinned but links the host's DPDK;
record `pkg-config --modversion libdpdk` with every result. The PCAP PMD must be
built/installed. The smoke test uses `--no-pci --no-huge`, takes no physical NIC,
and requires no root privileges. Some vendor packages omit the PCAP PMD; use
the source build above if `net_pcap` cannot be probed. The harness uses `--relax-rx-offload`
because the PCAP PMD cannot provide the checksum offloads requested by default.

Alternatively, the Containerfile builds DPDK itself from the pinned source:

```bash
podman build -f containers/Containerfile.baseline -t localhost/dpdk-l3fwd-baseline:25.11 .
podman run --rm -v "$PWD:/work" localhost/dpdk-l3fwd-baseline:25.11
```

Docker can use the same file/commands with `docker` substituted for `podman`.
The runtime must provide Linux and a matching CPU architecture. See the results
file for the container verification boundary in this session.

Successful tests produce `result.json`, `command.json`, `cases.json`, input and
output PCAPs, and `l3fwd.log`. A mismatch or early application exit fails the run.
No PASS result is written before packet comparison succeeds. The DUT runs for
a declared 30-second observation window including startup (`--timeout` to change
it). Correctness claims are bounded to that window, not unlimited future output.

## Build and test the migrated application

For software validation, first build upstream DPDK using the source-build command
above. Link the migration to that same build, retaining its PCAP and mempool PMDs:

```bash
PKG_CONFIG_PATH="$PWD/build/dpdk/meson-uninstalled" \
  meson setup build/software -Ddoca=disabled \
  -Dpcap_driver_dir="$PWD/build/dpdk/drivers"
ninja -C build/software
meson test -C build/software --print-errorlogs
L3_APP="$PWD/build/software/l3fwd-docaflow" python3 -m unittest discover -s tests -v
python3 tests/pcap_smoke.py --binary build/software/l3fwd-docaflow --target software

# The same extended inputs and route table run through both real executables:
python3 tests/pcap_smoke.py --binary build/dpdk/examples/dpdk-l3fwd \
  --extended --route-count 1024
python3 tests/pcap_smoke.py --binary build/software/l3fwd-docaflow --target software \
  --extended --route-count 1024
```

The software backend performs a simple linear LPM lookup and is a correctness
reference, not a throughput-optimized replacement for upstream `rte_lpm`.

For the DOCA backend, use the **DOCA 3.3 development packages and their matching
DPDK**. Other SDK major/minor versions are not admitted by this build yet:

```bash
PKG_CONFIG_PATH=/opt/mellanox/dpdk/lib/x86_64-linux-gnu/pkgconfig \
  meson setup build/doca -Ddoca=enabled
ninja -C build/doca
meson test -C build/doca --print-errorlogs
L3_APP="$PWD/build/doca/l3fwd-docaflow" python3 -m unittest discover -s tests -v
build/doca/l3fwd-docaflow --backend software --routes configs/routes-v4.cfg --check-config
```

These checks do not probe physical ports. The DOCA test suite includes injected
completion failures and timeouts; it does not simulate hardware forwarding.

## Hardware validation

Use the [physical packet runner](docs/WIRE_VALIDATION.md) for the reproducible
upstream-to-DOCA comparison on two reserved adapters in one Linux host. It includes
read-only preflight, paced replay, full-frame comparison and automatic cleanup.
The manual command below is a startup/control-plane check.

```bash
bash scripts/lab_inventory.sh > /path/outside/this/repo/lab-inventory.txt
```

Choose an existing private destination outside the checkout. Review the inventory
before sharing it; it contains host and device identifiers. Keep raw lab inventories
outside the repository; do not commit hostnames, real network addresses, serial
numbers, or internal topology. A physical run additionally requires an isolated
two-port DUT path,
a suitable traffic source and the SDK/device admission checks in
[VALIDATION.md](docs/VALIDATION.md).

Physical mode uses VNF/HWS and two explicitly selected PCI functions on one
adapter; it does not configure switch mode or representors. The application
rejects adapters with UP/IP-configured interfaces, upper/master interfaces or
active VFs, preserves the configured MTU, and rejects jumbo MTUs. These checks
do not replace exclusive reservation and a topology/ownership check.

Set the following variables privately to the reserved DUT ports, CPU and
generator destination MACs. Keep SSH settings and any needed credentials in
`.env` at the repository root, with permissions set to `0600`. Both `.env` and
`.env.*` are excluded by `.gitignore` and `.dockerignore`; keep them untracked.
The application itself does not use passwords.

```bash
: "${DUT_PCI_0:?}" "${DUT_PCI_1:?}" "${DUT_CPU:?}" "${PEER_MAC_0:?}" "${PEER_MAC_1:?}"
sudo build/doca/l3fwd-docaflow --lcores "0@${DUT_CPU}" -- --backend doca \
  --routes configs/routes-v4.cfg --device "$DUT_PCI_0" --device "$DUT_PCI_1" \
  --allow-physical-ports --eth-dest "0,$PEER_MAC_0" --eth-dest "1,$PEER_MAC_1" \
  --duration 60
```

Do not run this command against management interfaces. Only begin traffic after
the JSON `ready` event; a failed setup exits without it. Stop the generator and
allow counter refresh before the application exits. The final JSON reports
software Rx/Tx/drop counts and hardware cross-port forwarding counter snapshots
indexed by ingress port. A snapshot alone is not proof of end-to-end delivery.

## License

Original project code is BSD-3-Clause. Upstream retains its original notices
and licensing; see [THIRD_PARTY.md](THIRD_PARTY.md).
