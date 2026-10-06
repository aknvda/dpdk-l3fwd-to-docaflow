/* SPDX-License-Identifier: BSD-3-Clause */
#include "options.h"
#include <string.h>

static int pcap_file_device(const char *value)
{
    /* The PCAP PMD can also access live NICs. Only its file-only form is allowed. */
    const char *comma = strchr(value, ',');
    if (!comma || comma != value+9 || strncmp(value, "net_pcap", 8) ||
        (value[8] != '0' && value[8] != '1')) return -1;
    unsigned rx = 0, tx = 0;
    for (const char *p = comma+1; *p;) {
        const char *end = strchr(p, ',');
        size_t n = end ? (size_t)(end-p) : strlen(p);
        if (n <= 8) return -1;
        if (!strncmp(p, "rx_pcap=", 8)) ++rx;
        else if (!strncmp(p, "tx_pcap=", 8)) ++tx;
        else return -1;
        if (end && !end[1]) return -1;
        p = end ? end+1 : p+n;
    }
    return rx == 1 && tx == 1 ? 0 : -1;
}

int l3_eal_validate(int argc, const char *const argv[], int hardware)
{
    const char *flags[] = {"--no-pci", "--no-huge", "--no-telemetry", "--in-memory",
        "--legacy-mem", "--single-file-segments"};
    const char *values[] = {"--lcores", "-l", "-c", "-m", "--main-lcore", "--socket-mem",
        "--socket-limit", "--file-prefix", "--huge-dir", "--iova-mode", "--log-level", "--vdev"};
    for (int i = 1; i < argc; ++i) {
        if (hardware && !strcmp(argv[i], "--no-pci")) return -1;
        int known = 0;
        for (unsigned j = 0; j < sizeof(flags)/sizeof(flags[0]); ++j)
            if (!strcmp(argv[i], flags[j])) known = 1;
        if (known) continue;
        for (unsigned j = 0; j < sizeof(values)/sizeof(values[0]); ++j) {
            size_t n = strlen(values[j]);
            if (strncmp(argv[i], values[j], n) || (argv[i][n] && argv[i][n] != '=')) continue;
            const char *value;
            if (argv[i][n] == '=') value = argv[i]+n+1;
            else if (++i < argc) value = argv[i];
            else return -1;
            if (!*value || *value == '-') return -1;
            if (!strcmp(values[j], "--vdev") && (hardware || pcap_file_device(value))) return -1;
            known = 1;
            break;
        }
        if (!known) return -1;
    }
    return 0;
}
