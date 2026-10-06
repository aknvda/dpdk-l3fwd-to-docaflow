/* SPDX-License-Identifier: BSD-3-Clause */
#include "forward.h"
#include "flow.h"
#include "device.h"
#include "options.h"
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <signal.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <rte_eal.h>
#include <rte_ethdev.h>
#include <rte_mbuf.h>
#include <rte_version.h>

static volatile sig_atomic_t stop_requested;
static void stop_handler(int signal_number) { (void)signal_number; stop_requested = 1; }
static double seconds(void)
{
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return time.tv_sec + time.tv_nsec / 1e9;
}

static void usage(void)
{
    puts("l3fwd-docaflow [EAL options] -- --backend software|doca --routes FILE\n"
         "  --eth-dest PORT,MAC          next-hop MAC for logical port 0 or 1\n"
         "  --duration SECONDS           stop after this interval; default until SIGINT\n"
         "  --check-config               validate configuration without EAL/device access\n"
         "  --device DOMAIN:BUS:SLOT.FUNC two explicit PCI functions, DOCA mode only\n"
         "  --allow-physical-ports       opt in to using already isolated test interfaces\n"
         "Physical EAL allow/block options are prohibited; the app controls probing.\n"
         "Software mode uses only net_pcap virtual ports and never probes physical NICs.");
}

static int parse_mac(const char *text, struct l3_macs *macs)
{
    if (strlen(text) != 19 || (text[0] != '0' && text[0] != '1') || text[1] != ',') return -1;
    for (unsigned i = 0; i < 6; ++i) {
        size_t offset = 2 + i*3;
        if (!isxdigit((unsigned char)text[offset]) || !isxdigit((unsigned char)text[offset+1]) ||
            (i < 5 && text[offset+2] != ':')) return -1;
    }
    unsigned p, b[6]; int end = 0;
    if (sscanf(text, "%u,%2x:%2x:%2x:%2x:%2x:%2x%n", &p,
               &b[0], &b[1], &b[2], &b[3], &b[4], &b[5], &end) != 7 ||
        text[end] || p >= L3_PORTS) return -1;
    for (unsigned i = 0; i < 6; ++i) macs->dst[p][i] = (uint8_t)b[i];
    return 0;
}

static int configure_port(uint16_t port, struct rte_mempool *pool, bool hardware,
                           struct l3_macs *macs)
{
    struct rte_eth_dev_info info;
    if (rte_eth_dev_info_get(port, &info)) return -1;
    if (!info.driver_name || strcmp(info.driver_name, hardware ? "mlx5_pci" : "net_pcap")) {
        /* mlx5 reports either name depending on the packaged PMD. */
        if (!hardware || !info.driver_name || !strstr(info.driver_name, "mlx5")) {
            fputs("Unexpected port driver for selected backend\n", stderr); return -1;
        }
    }
    struct rte_eth_conf configuration = {0};
    uint16_t mtu;
    if (rte_eth_dev_get_mtu(port, &mtu)) return -1;
    if (mtu > RTE_ETHER_MTU) {
        fputs("Jumbo MTU is outside this milestone; reserve test ports with MTU <= 1500\n", stderr);
        return -1;
    }
    configuration.rxmode.mtu = mtu; /* Preserve the configured kernel MTU. */
    if (rte_eth_dev_configure(port, 1, 1, &configuration)) return -1;
    int socket = rte_eth_dev_socket_id(port);
    if (socket < 0) socket = 0;
    if (rte_eth_rx_queue_setup(port, 0, 512, socket, NULL, pool) ||
        rte_eth_tx_queue_setup(port, 0, 512, socket, NULL)) return -1;
    struct rte_ether_addr address;
    if (rte_eth_macaddr_get(port, &address)) return -1;
    memcpy(macs->src[port], address.addr_bytes, 6);
    return rte_eth_dev_start(port);
}

int main(int argc, char **argv)
{
    const char *backend = NULL, *route_file = NULL, *pci[2] = {NULL, NULL};
    unsigned devices_count = 0;
    bool check = false, physical_opt_in = false;
    double duration = 0;
    struct l3_macs macs = {0};
    for (unsigned p = 0; p < L3_PORTS; ++p) { macs.dst[p][0] = 2; macs.dst[p][5] = p; }
    int separator = 0;
    for (int i = 1; i < argc; ++i) if (!strcmp(argv[i], "--")) { separator = i; break; }
    int first = separator ? separator+1 : 1;
    for (int i = first; i < argc; ++i) {
        const char *key = argv[i];
        if (!strcmp(key, "--help") || !strcmp(key, "-h")) { usage(); return 0; }
        if (!strcmp(key, "--check-config")) { check = true; continue; }
        if (!strcmp(key, "--allow-physical-ports")) { physical_opt_in = true; continue; }
        if (++i == argc) { fprintf(stderr, "Missing value for %s\n", key); return 2; }
        const char *value = argv[i];
        if (!strcmp(key, "--backend")) backend = value;
        else if (!strcmp(key, "--routes")) route_file = value;
        else if (!strcmp(key, "--device")) {
            if (devices_count == 2 || !l3_pci_valid(value)) { fputs("Invalid PCI device\n", stderr); return 2; }
            pci[devices_count++] = value;
        } else if (!strcmp(key, "--eth-dest")) {
            if (parse_mac(value, &macs)) { fputs("Invalid --eth-dest\n", stderr); return 2; }
        } else if (!strcmp(key, "--duration")) {
            char *end; errno = 0; duration = strtod(value, &end);
            if (errno || end == value || *end || !isfinite(duration) || duration < 0) {
                fputs("Invalid --duration\n", stderr); return 2;
            }
        } else { fprintf(stderr, "Unknown option: %s\n", key); return 2; }
    }
    if (!backend || (strcmp(backend, "software") && strcmp(backend, "doca")) || !route_file) {
        fputs("Specify --backend software|doca and --routes FILE\n", stderr); return 2;
    }
    bool hardware = !strcmp(backend, "doca");
    if (hardware && (devices_count != 2 || !strcmp(pci[0], pci[1]) || strncmp(pci[0], pci[1], 10))) {
        fputs("DOCA requires two distinct PCI functions on one isolated adapter\n", stderr); return 2;
    }
    if (!hardware && devices_count) { fputs("--device requires the doca backend\n", stderr); return 2; }
    if (hardware && !check && !physical_opt_in) {
        fputs("DOCA requires --allow-physical-ports after reserving isolated test ports\n", stderr); return 2;
    }
    if (l3_eal_validate(separator, (const char *const *)argv, hardware)) {
        fputs("Unsupported EAL option: application owns device probing; software mode requires PCAP files\n", stderr);
        return 2;
    }
    struct l3_routes routes = {0}; char error[256];
    FILE *input = fopen(route_file, "r");
    if (!input) { perror("routes"); return 2; }
    int loaded = l3_routes_read(input, &routes, error, sizeof(error));
    fclose(input);
    if (loaded) { fprintf(stderr, "Invalid routes: %s\n", error); return 2; }
    if (check) { printf("{\"backend\":\"%s\",\"routes\":%zu,\"device_access\":false}\n", backend, routes.count); return 0; }
#ifndef L3_HAVE_DOCA
    if (hardware) { fputs("DOCA backend not built; configure with -Ddoca=enabled\n", stderr); return 2; }
#endif
    if (!separator) { fputs("Separate EAL options from application options with --\n", stderr); return 2; }
    if (hardware && (l3_device_safe(pci[0]) || l3_device_safe(pci[1]))) return 2;

    char **eal = calloc((size_t)separator+6, sizeof(char *));
    if (!eal) return 1;
    int eal_argc = 0;
    for (int i = 0; i < separator; ++i)
        if (strcmp(argv[i], "--no-pci")) eal[eal_argc++] = argv[i];
    if (hardware) {
        /* Same deferred-probe allowlists as the installed DOCA samples. */
        eal[eal_argc++] = "-a"; eal[eal_argc++] = "pci:00:00.0";
        eal[eal_argc++] = "-a"; eal[eal_argc++] = "auxiliary:";
    } else eal[eal_argc++] = "--no-pci";
    int initialized = rte_eal_init(eal_argc, eal);
    free(eal);
    if (initialized < 0) return 1;
    int result = 1;
    struct doca_dev *devices[2] = {0};
    struct l3_flow *flow = NULL;
    struct rte_mempool *pool = NULL;
    bool started[2] = {false, false};
    if (hardware && l3_devices_open(pci, devices)) goto cleanup;
    if (rte_eth_dev_count_avail() != L3_PORTS || !rte_eth_dev_is_valid_port(0) || !rte_eth_dev_is_valid_port(1)) {
        fputs("Exactly two ports with logical IDs 0 and 1 are required\n", stderr); goto cleanup;
    }
    pool = rte_pktmbuf_pool_create("l3fwd_pool", 16383, 128, 0,
                                  RTE_MBUF_DEFAULT_BUF_SIZE, rte_socket_id());
    if (!pool) { fputs("Cannot allocate mbuf pool\n", stderr); goto cleanup; }
    for (uint16_t p = 0; p < L3_PORTS; ++p) {
        if (configure_port(p, pool, hardware, &macs)) { fputs("Port configuration failed\n", stderr); goto cleanup; }
        started[p] = true;
    }
    if (hardware && l3_flow_start(&flow, &routes, &macs, devices)) goto cleanup;
    signal(SIGINT, stop_handler); signal(SIGTERM, stop_handler);
    uint64_t received[2] = {0}, transmitted[2] = {0}, dropped = 0, tx_dropped = 0;
    printf("{\"event\":\"ready\",\"backend\":\"%s\",\"routes\":%zu,\"dpdk\":\"%s\"}\n", backend, routes.count, rte_version());
    fflush(stdout);
    double begin = seconds();
    while (!stop_requested && (!duration || seconds()-begin < duration)) {
        for (uint16_t p = 0; p < L3_PORTS; ++p) {
            struct rte_mbuf *packets[32], *tx[2][32];
            uint16_t pending[2] = {0};
            uint16_t count = rte_eth_rx_burst(p, 0, packets, 32);
            received[p] += count;
            for (uint16_t i = 0; i < count; ++i) {
                uint16_t egress;
                if (rte_pktmbuf_linearize(packets[i]) ||
                    l3_forward(rte_pktmbuf_mtod(packets[i], uint8_t *),
                               rte_pktmbuf_pkt_len(packets[i]), p, &routes, &macs, &egress) != L3_FORWARDED) {
                    rte_pktmbuf_free(packets[i]); ++dropped; continue;
                }
                tx[egress][pending[egress]++] = packets[i];
            }
            for (uint16_t out = 0; out < L3_PORTS; ++out) {
                uint16_t sent = pending[out] ? rte_eth_tx_burst(out, 0, tx[out], pending[out]) : 0;
                transmitted[out] += sent;
                for (uint16_t i = sent; i < pending[out]; ++i) { rte_pktmbuf_free(tx[out][i]); ++tx_dropped; }
            }
        }
    }
    uint64_t hardware_forwarded[2] = {0};
    if (hardware && l3_flow_counters(flow, hardware_forwarded)) goto cleanup;
    printf("{\"event\":\"stats\",\"software_rx\":[%" PRIu64 ",%" PRIu64 "],"
           "\"software_tx\":[%" PRIu64 ",%" PRIu64 "],\"software_dropped\":%" PRIu64 ","
           "\"tx_dropped\":%" PRIu64 ",\"hardware_forwarded\":[%" PRIu64 ",%" PRIu64 "]}\n",
           received[0], received[1], transmitted[0], transmitted[1], dropped, tx_dropped,
           hardware_forwarded[0], hardware_forwarded[1]);
    result = 0;
cleanup:
    if (l3_flow_stop(flow)) result = 1;
    for (uint16_t p = 0; p < L3_PORTS; ++p) {
        if (!rte_eth_dev_is_valid_port(p)) continue;
        if (started[p] && rte_eth_dev_stop(p)) result = 1;
        if (rte_eth_dev_close(p)) result = 1;
    }
    if (pool) rte_mempool_free(pool);
    if (rte_eal_cleanup()) result = 1;
    if (l3_devices_close(devices)) result = 1;
    return result;
}
