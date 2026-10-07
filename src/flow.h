/* SPDX-License-Identifier: BSD-3-Clause */
#ifndef L3_FLOW_H
#define L3_FLOW_H
#include "forward.h"
#include "device.h"
#include <signal.h>
#include <stdbool.h>
struct l3_flow;
int l3_flow_start(struct l3_flow **flow, const struct l3_routes *routes,
                  const struct l3_macs *macs, struct doca_dev *devices[2],
                  const volatile sig_atomic_t *cancelled, bool internal_loopback, bool strict_checksum);
int l3_flow_counters(struct l3_flow *flow, uint64_t forwarded[2], uint64_t lookups[2]);
int l3_flow_stop(struct l3_flow *flow);
#endif
