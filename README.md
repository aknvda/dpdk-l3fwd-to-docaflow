# DPDK l3fwd to DOCA Flow

An incremental migration of the official DPDK `l3fwd` application to NVIDIA
DOCA Flow. Start with two-port IPv4 longest-prefix-match forwarding, preserve
the software baseline, then validate a hardware forwarding path against it.

**Current stage: baseline and validation infrastructure. The migrated DOCA
application is not implemented yet.** See [results](docs/RESULTS.md) for exactly
what has run, and [lab requirements](docs/VALIDATION.md) for the validation gates.

## Layout

| Path | Purpose |
| --- | --- |
| `upstream/dpdk` | Unmodified upstream submodule, v25.11.0 at `ed957165eadbe60a47d5ec223578cdd1c13d0bd9` |
| `configs/` | Shared route inputs, including overlapping IPv4 prefixes |
| `tests/` | Packet corpus, strict per-port PCAP comparison and negative tests |
| `containers/` | Linux build of upstream DPDK with the PCAP virtual driver |
| `scripts/lab_inventory.sh` | Read-only Linux testbed inventory |
| `docs/` | Design, requirements and measured results |

## Get the source and check the test harness

```bash
git clone --recurse-submodules https://github.com/aknvda/dpdk-l3fwd-to-docaflow.git
cd dpdk-l3fwd-to-docaflow
python3 -m unittest discover -s tests -v
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

## Hardware validation

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

The next implementation milestone will use the installed DOCA 3.3 API as the
initial target. Implement the LPM/MAC/TTL path and explicit software exceptions,
then run the shared corpus on physical links. Building an SDK sample alone does
not prove hardware capability or application equivalence.

## License

Original project code is BSD-3-Clause. Upstream retains its original notices
and licensing; see [THIRD_PARTY.md](THIRD_PARTY.md).
