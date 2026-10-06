/* SPDX-License-Identifier: BSD-3-Clause */
#include "netstate.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

int l3_net_snapshot_at(const char *pci, const char *sysfs, struct l3_net_state *state)
{
    char path[1024];
    int n = snprintf(path, sizeof(path), "%s/bus/pci/devices/%s/net", sysfs, pci);
    if (n < 0 || (size_t)n >= sizeof(path)) return -1;
    DIR *net = opendir(path);
    if (!net) return -1;
    unsigned count = 0;
    struct dirent *entry;
    struct l3_net_state found = {0};
    while ((entry = readdir(net))) {
        if (entry->d_name[0] == '.') continue;
        if (++count > 1 || strlen(entry->d_name) >= sizeof(found.name)) break;
        memcpy(found.name, entry->d_name, strlen(entry->d_name)+1);
    }
    closedir(net);
    if (count != 1 || !found.name[0]) return -1;
    found.index = if_nametoindex(found.name);
    if (!found.index) return -1;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    struct ifreq req = {0};
    memcpy(req.ifr_name, found.name, sizeof(req.ifr_name));
    int result = ioctl(fd, SIOCGIFFLAGS, &req);
    close(fd);
    if (result || (req.ifr_flags & IFF_UP)) return -1;
    *state = found;
    return 0;
}

int l3_net_restore(const struct l3_net_state *state)
{
    /* Failed mlx5 probes can release their ethdev after setting Linux IFF_UP. */
    if (!state->index || if_nametoindex(state->name) != state->index) return -1;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    struct ifreq req = {0};
    memcpy(req.ifr_name, state->name, sizeof(req.ifr_name));
    int result = ioctl(fd, SIOCGIFFLAGS, &req);
    if (!result && (req.ifr_flags & IFF_UP)) {
        req.ifr_flags &= (short)~IFF_UP;
        result = ioctl(fd, SIOCSIFFLAGS, &req);
    }
    close(fd);
    return result;
}
