/* SPDX-License-Identifier: BSD-3-Clause */
#include "flow.h"
#include <stdio.h>
int l3_flow_start(struct l3_flow **f, const struct l3_routes *r,
                  const struct l3_macs *m, struct doca_dev *d[2],
                  const volatile sig_atomic_t *cancelled, bool internal_loopback)
{ (void)f; (void)r; (void)m; (void)d; (void)cancelled; (void)internal_loopback;
  fputs("DOCA backend not built\n", stderr); return -1; }
int l3_flow_counters(struct l3_flow *f, uint64_t c[2])
{ (void)f; c[0] = c[1] = 0; return 0; }
int l3_flow_stop(struct l3_flow *f) { (void)f; return 0; }
