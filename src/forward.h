/* SPDX-License-Identifier: BSD-3-Clause */
#ifndef L3_FORWARD_H
#define L3_FORWARD_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define L3_MAX_ROUTES 1024
#define L3_PORTS 2
struct l3_route { uint32_t network; uint8_t depth; uint16_t port; };
struct l3_routes { size_t count; struct l3_route entries[L3_MAX_ROUTES]; };
struct l3_macs { uint8_t src[L3_PORTS][6]; uint8_t dst[L3_PORTS][6]; };
enum l3_result { L3_FORWARDED, L3_UNSUPPORTED, L3_MALFORMED };
int l3_routes_read(FILE *input, struct l3_routes *routes, char *error, size_t size);
uint16_t l3_lookup(const struct l3_routes *routes, uint32_t ip, uint16_t ingress);
enum l3_result l3_forward(uint8_t *frame, size_t length, uint16_t ingress,
                          const struct l3_routes *routes, const struct l3_macs *macs,
                          uint16_t *egress);
#endif
