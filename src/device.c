/* SPDX-License-Identifier: BSD-3-Clause */
#include "device.h"
#include <dirent.h>
#include <ctype.h>
#include <errno.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

int l3_pci_valid(const char *pci)
{
    if (!pci || strlen(pci) != 12) return 0;
    for (unsigned i = 0; i < 12; ++i)
        if (i != 4 && i != 7 && i != 10 && !isxdigit((unsigned char)pci[i])) return 0;
    unsigned domain, bus, slot, function;
    int end = 0;
    return strlen(pci) == 12 && pci[4] == ':' && pci[7] == ':' && pci[10] == '.' &&
        sscanf(pci, "%4x:%2x:%2x.%1x%n", &domain, &bus, &slot, &function, &end) == 4 &&
        end == 12 && domain <= 65535 && bus <= 255 && slot <= 31 && function <= 7;
}

int l3_device_safe_at(const char *pci, const char *sysfs, const struct ifaddrs *addresses)
{
    /* Reject addressed/enslaved interfaces on every PCI function of the adapter,
     * not only the selected function. Never reconfigure or unbind an interface. */
    if (!l3_pci_valid(pci)) return -1;
    int result = -1, selected_exists = 0;
    for (unsigned function = 0; function < 8; ++function) {
        char path[1024];
        int n = snprintf(path, sizeof(path), "%s/bus/pci/devices/%.11s%u/sriov_numvfs", sysfs, pci, function);
        if (n < 0 || (size_t)n >= sizeof(path)) goto done;
        FILE *vfs = fopen(path, "r");
        if (vfs) {
            unsigned count;
            int read = fscanf(vfs, "%u", &count);
            fclose(vfs);
            if (read != 1 || count) { fputs("Refusing adapter with active or unreadable VFs\n", stderr); goto done; }
        } else if (errno != ENOENT) goto done;
        n = snprintf(path, sizeof(path), "%s/bus/pci/devices/%.11s%u/net", sysfs, pci, function);
        if (n < 0 || (size_t)n >= sizeof(path)) goto done;
        DIR *net = opendir(path);
        if (!net) { if (errno == ENOENT) continue; goto done; }
        struct dirent *entry;
        while ((entry = readdir(net))) {
            if (entry->d_name[0] == '.') continue;
            if (function == (unsigned)(pci[11]-'0')) selected_exists = 1;
            char netpath[1536];
            n = snprintf(netpath, sizeof(netpath), "%s/class/net/%s", sysfs, entry->d_name);
            if (n < 0 || (size_t)n >= sizeof(netpath)) { closedir(net); goto done; }
            DIR *links = opendir(netpath);
            if (!links) { closedir(net); goto done; }
            struct dirent *link;
            int attached = 0;
            while ((link = readdir(links)))
                if (!strcmp(link->d_name, "master") || !strncmp(link->d_name, "upper_", 6)) attached = 1;
            closedir(links);
            if (attached) {
                fputs("Refusing adapter with upper/enslaved interfaces; use isolated test ports.\n", stderr);
                closedir(net); goto done;
            }
            int found = 0;
            for (const struct ifaddrs *a = addresses; a; a = a->ifa_next) {
                if (strcmp(a->ifa_name, entry->d_name)) continue;
                found = 1;
                if ((a->ifa_flags & IFF_UP) || (a->ifa_addr &&
                    (a->ifa_addr->sa_family == AF_INET || a->ifa_addr->sa_family == AF_INET6))) {
                    fputs("Refusing adapter with an UP or IP-configured interface; preserve management access.\n", stderr);
                    closedir(net); goto done;
                }
            }
            if (!found) { closedir(net); goto done; }
        }
        closedir(net);
    }
    if (!selected_exists) fprintf(stderr, "Selected PCI function has no accessible network interface.\n");
    else result = 0;
done:
    return result;
}

int l3_device_safe(const char *pci)
{
    struct ifaddrs *addresses = NULL;
    if (getifaddrs(&addresses) != 0) { perror("getifaddrs"); return -1; }
    int result = l3_device_safe_at(pci, "/sys", addresses);
    freeifaddrs(addresses);
    return result;
}

#ifdef L3_HAVE_DOCA
#include <doca_dev.h>
#include <doca_dpdk.h>
#include <doca_error.h>

int l3_devices_open(const char *pci[2], struct doca_dev *devices[2])
{
    struct doca_devinfo **infos = NULL;
    uint32_t count = 0;
    doca_error_t err = doca_devinfo_create_list(&infos, &count);
    if (err != DOCA_SUCCESS) goto fail;
    for (unsigned p = 0; p < 2; ++p) {
        for (uint32_t i = 0; i < count; ++i) {
            uint8_t equal = 0;
            err = doca_devinfo_is_equal_pci_addr(infos[i], pci[p], &equal);
            if (err != DOCA_SUCCESS || !equal) continue;
            err = doca_dev_open(infos[i], &devices[p]);
            if (err != DOCA_SUCCESS) goto fail;
            break;
        }
        if (!devices[p]) { err = DOCA_ERROR_NOT_FOUND; goto fail; }
        err = doca_dpdk_port_probe(devices[p], "dv_flow_en=2");
        if (err != DOCA_SUCCESS) goto fail;
        uint16_t port;
        err = doca_dpdk_get_first_port_id(devices[p], &port);
        if (err != DOCA_SUCCESS || port != p) { err = DOCA_ERROR_BAD_STATE; goto fail; }
    }
    doca_devinfo_destroy_list(infos);
    return 0;
fail:
    fprintf(stderr, "DOCA device setup failed: %s\n", doca_error_get_descr(err));
    if (infos) doca_devinfo_destroy_list(infos);
    /* Caller closes any DPDK ports before closing partially opened devices. */
    return -1;
}

int l3_devices_close(struct doca_dev *devices[2])
{
    int failed = 0;
    for (unsigned p = 0; p < 2; ++p) {
        if (devices[p] && doca_dev_close(devices[p]) != DOCA_SUCCESS) failed = -1;
        devices[p] = NULL;
    }
    return failed;
}
#else
int l3_devices_open(const char *pci[2], struct doca_dev *devices[2])
{ (void)pci; (void)devices; return -1; }
int l3_devices_close(struct doca_dev *devices[2])
{ (void)devices; return 0; }
#endif
