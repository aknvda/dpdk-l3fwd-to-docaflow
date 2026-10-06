/* SPDX-License-Identifier: BSD-3-Clause */
#include "device.h"
#include <assert.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int main(void)
{
    assert(l3_pci_valid("0000:00:01.0"));
    const char *bad[] = {"+000:00:01.0", "0000:00:ff.0", "0000:00:01.8", "0000:0:01.0", "0000:00:01.0,bad"};
    for (unsigned i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) assert(!l3_pci_valid(bad[i]));
    char root[] = "/tmp/l3-admission-XXXXXX", path[512];
    assert(mkdtemp(root));
    const char *dirs[] = {"bus", "bus/pci", "bus/pci/devices", "bus/pci/devices/0000:00:01.0",
        "bus/pci/devices/0000:00:01.0/net", "bus/pci/devices/0000:00:01.0/net/test0",
        "bus/pci/devices/0000:00:01.1", "bus/pci/devices/0000:00:01.1/net",
        "bus/pci/devices/0000:00:01.1/net/test1", "class", "class/net", "class/net/test0", "class/net/test1"};
    for (unsigned i = 0; i < sizeof(dirs)/sizeof(dirs[0]); ++i) {
        snprintf(path, sizeof(path), "%s/%s", root, dirs[i]); assert(mkdir(path, 0700) == 0);
    }
    struct ifaddrs second = {.ifa_name = "test1"};
    struct ifaddrs first = {.ifa_name = "test0", .ifa_next = &second};
    assert(l3_device_safe_at("0000:00:01.0", root, &first) == 0);
    /* A different function of the same adapter can carry management traffic. */
    struct sockaddr_in address = {.sin_family = AF_INET};
    second.ifa_addr = (struct sockaddr *)&address;
    assert(l3_device_safe_at("0000:00:01.0", root, &first) != 0);
    second.ifa_addr = NULL; second.ifa_flags = IFF_UP;
    assert(l3_device_safe_at("0000:00:01.0", root, &first) != 0);
    second.ifa_flags = 0;
    snprintf(path, sizeof(path), "%s/class/net/test1/upper_vlan", root);
    assert(mkdir(path, 0700) == 0);
    assert(l3_device_safe_at("0000:00:01.0", root, &first) != 0);
    assert(rmdir(path) == 0);
    snprintf(path, sizeof(path), "%s/bus/pci/devices/0000:00:01.1/sriov_numvfs", root);
    FILE *f = fopen(path, "w"); assert(f); fputs("1\n", f); fclose(f);
    assert(l3_device_safe_at("0000:00:01.0", root, &first) != 0);
    assert(unlink(path) == 0);
    assert(l3_device_safe_at("0000:00:01.0", root, NULL) != 0);
    assert(l3_device_safe_at("0000:00:02.0", root, &first) != 0);
    assert(l3_device_safe_at("0000:00:01.0", root, &first) == 0);
    for (unsigned i = sizeof(dirs)/sizeof(dirs[0]); i-- > 0;) {
        snprintf(path, sizeof(path), "%s/%s", root, dirs[i]); assert(rmdir(path) == 0);
    }
    assert(rmdir(root) == 0);
    puts("Device admission tests: PASS");
}
