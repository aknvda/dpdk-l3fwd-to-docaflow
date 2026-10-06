/* SPDX-License-Identifier: BSD-3-Clause */
/* Model kernel calls, not ethdev handles: failed probes may release the latter. */
#define socket fake_socket
#define close fake_close
#define ioctl fake_ioctl
#define if_nametoindex fake_if_nametoindex
#include "../src/netstate.c"
#undef socket
#undef close
#undef ioctl
#undef if_nametoindex
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/stat.h>

static unsigned index_value = 7, writes;
static short flags = (short)(IFF_BROADCAST | IFF_MULTICAST);
static int fail_ioctl;
unsigned fake_if_nametoindex(const char *name) { assert(!strcmp(name, "test0")); return index_value; }
int fake_socket(int domain, int type, int protocol)
{ assert(domain == AF_INET && type == SOCK_DGRAM && protocol == 0); return 42; }
int fake_close(int fd) { assert(fd == 42); return 0; }
int fake_ioctl(int fd, unsigned long request, ...)
{
    assert(fd == 42);
    va_list args; va_start(args, request);
    struct ifreq *req = va_arg(args, struct ifreq *); va_end(args);
    assert(!strcmp(req->ifr_name, "test0"));
    if (fail_ioctl) { errno = EIO; return -1; }
    if (request == SIOCGIFFLAGS) req->ifr_flags = flags;
    else { assert(request == SIOCSIFFLAGS); flags = req->ifr_flags; ++writes; }
    return 0;
}

int main(void)
{
    char root[] = "/tmp/l3-netstate-XXXXXX", path[512];
    assert(mkdtemp(root));
    const char *dirs[] = {"bus", "bus/pci", "bus/pci/devices", "bus/pci/devices/0000:00:01.0",
                         "bus/pci/devices/0000:00:01.0/net", "bus/pci/devices/0000:00:01.0/net/test0"};
    for (unsigned i = 0; i < sizeof(dirs)/sizeof(dirs[0]); ++i) {
        snprintf(path, sizeof(path), "%s/%s", root, dirs[i]); assert(mkdir(path, 0700) == 0);
    }
    struct l3_net_state state = {0};
    assert(l3_net_snapshot_at("0000:00:01.0", root, &state) == 0);
    assert(!strcmp(state.name, "test0") && state.index == 7);
    /* Probe brought the kernel interface UP and failed without an ethdev. */
    flags |= IFF_UP;
    assert(l3_net_restore(&state) == 0);
    assert(flags == (short)(IFF_BROADCAST | IFF_MULTICAST) && writes == 1);
    assert(l3_net_restore(&state) == 0 && writes == 1); /* Already DOWN. */
    index_value = 8; /* Never modify a replacement interface with the same name. */
    assert(l3_net_restore(&state) != 0 && writes == 1);
    index_value = 7; fail_ioctl = 1;
    assert(l3_net_restore(&state) != 0 && writes == 1);
    fail_ioctl = 0; flags |= IFF_UP;
    assert(l3_net_snapshot_at("0000:00:01.0", root, &state) != 0);
    for (unsigned i = sizeof(dirs)/sizeof(dirs[0]); i-- > 0;) {
        snprintf(path, sizeof(path), "%s/%s", root, dirs[i]); assert(rmdir(path) == 0);
    }
    assert(rmdir(root) == 0);
    puts("Kernel port restoration tests: PASS (no network access)");
}
