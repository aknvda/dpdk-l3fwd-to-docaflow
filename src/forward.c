/* SPDX-License-Identifier: BSD-3-Clause */
#include "forward.h"
#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static int number(const char *s, unsigned limit, unsigned *value)
{
    char *end;
    if (!isdigit((unsigned char)*s)) return -1;
    errno = 0;
    unsigned long n = strtoul(s, &end, 10);
    if (errno || *end || n > limit) return -1;
    *value = (unsigned)n;
    return 0;
}

int l3_routes_read(FILE *input, struct l3_routes *routes, char *error, size_t size)
{
    struct l3_routes parsed = {0};
    char line[256];
    unsigned lineno = 0;
    const char *reason = "invalid route (expected Raddress/prefix port, prefix 1..32, port 0..1)";
    while (fgets(line, sizeof(line), input)) {
        ++lineno;
        if (!strchr(line, '\n') && !feof(input)) {
            reason = "route line too long";
            goto invalid;
        }
        char *p = line;
        while (isspace((unsigned char)*p)) ++p;
        if (!*p || *p == '#') continue;
        if (*p++ != 'R') goto invalid;
        char address[64], port_text[32], extra;
        if (sscanf(p, "%63s %31s %c", address, port_text, &extra) != 2) goto invalid;
        char *slash = strchr(address, '/');
        if (!slash) goto invalid;
        *slash++ = '\0';
        unsigned depth, port;
        struct in_addr ip;
        if (number(slash, 32, &depth) || depth == 0 ||
            number(port_text, L3_PORTS-1, &port) || inet_pton(AF_INET, address, &ip) != 1)
            goto invalid;
        uint32_t network = ntohl(ip.s_addr) & (UINT32_MAX << (32-depth));
        size_t i;
        for (i = 0; i < parsed.count; ++i)
            if (parsed.entries[i].network == network && parsed.entries[i].depth == depth) break;
        if (i == parsed.count) {
            if (parsed.count == L3_MAX_ROUTES) { reason = "too many routes"; goto invalid; }
            ++parsed.count;
        }
        parsed.entries[i] = (struct l3_route){network, (uint8_t)depth, (uint16_t)port};
    }
    if (ferror(input)) { reason = "route file read error"; goto invalid; }
    if (!parsed.count) { reason = "route file is empty"; goto invalid; }
    *routes = parsed;
    return 0;
invalid:
    if (size) snprintf(error, size, "line %u: %s", lineno, reason);
    return -1;
}

uint16_t l3_lookup(const struct l3_routes *routes, uint32_t ip, uint16_t ingress)
{
    unsigned best = 0;
    uint16_t port = ingress;
    for (size_t i = 0; i < routes->count; ++i) {
        const struct l3_route *r = &routes->entries[i];
        if (r->depth > best && (ip & (UINT32_MAX << (32-r->depth))) == r->network) {
            best = r->depth;
            port = r->port;
        }
    }
    return port;
}

static enum l3_result validate_frame(const uint8_t *frame, size_t length)
{
    if (length < 14) return L3_MALFORMED;
    if (frame[12] != 8 || frame[13] != 0) return L3_UNSUPPORTED;
    if (length < 34) return L3_MALFORMED;
    const uint8_t *ip = frame + 14;
    size_t ihl = (ip[0] & 15u) * 4u;
    size_t total = ((size_t)ip[2] << 8) | ip[3];
    if ((ip[0] >> 4) != 4 || ihl < 20 || length-14 < ihl ||
        total < ihl || total > length-14) return L3_MALFORMED;
    return L3_FORWARDED;
}

int l3_route_metadata_decode(uint32_t metadata)
{
    return (metadata & ~UINT32_C(1)) == L3_ROUTE_META ? (int)(metadata & 1) : -1;
}

enum l3_result l3_forward_selected(uint8_t *frame, size_t length, uint16_t egress,
                                   const struct l3_macs *macs)
{
    if (egress >= L3_PORTS) return L3_MALFORMED;
    enum l3_result valid = validate_frame(frame, length);
    if (valid != L3_FORWARDED) return valid;
    uint8_t *ip = frame + 14;
    --ip[8];
    /* Preserve the pinned upstream sample's native-endian increment, including
     * its edge cases. This is not a general RFC router checksum implementation. */
    uint16_t raw_checksum;
    memcpy(&raw_checksum, ip+10, sizeof(raw_checksum));
    ++raw_checksum;
    memcpy(ip+10, &raw_checksum, sizeof(raw_checksum));
    memcpy(frame, macs->dst[egress], 6);
    memcpy(frame+6, macs->src[egress], 6);
    return L3_FORWARDED;
}

enum l3_result l3_forward(uint8_t *frame, size_t length, uint16_t ingress,
                          const struct l3_routes *routes, const struct l3_macs *macs,
                          uint16_t *egress)
{
    if (ingress >= L3_PORTS) return L3_MALFORMED;
    enum l3_result valid = validate_frame(frame, length);
    if (valid != L3_FORWARDED) return valid;
    uint32_t destination;
    memcpy(&destination, frame+30, sizeof(destination));
    *egress = l3_lookup(routes, ntohl(destination), ingress);
    return l3_forward_selected(frame, length, *egress, macs);
}
