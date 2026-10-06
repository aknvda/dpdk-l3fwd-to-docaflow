/* SPDX-License-Identifier: BSD-3-Clause */
#ifndef L3_NETSTATE_H
#define L3_NETSTATE_H
#include <net/if.h>
struct l3_net_state { char name[IF_NAMESIZE]; unsigned index; };
/* Call after adapter admission, before any SDK/DPDK probing. */
int l3_net_snapshot_at(const char *pci, const char *sysfs, struct l3_net_state *state);
int l3_net_restore(const struct l3_net_state *state);
#endif
