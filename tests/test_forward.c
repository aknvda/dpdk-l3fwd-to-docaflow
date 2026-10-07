/* SPDX-License-Identifier: BSD-3-Clause */
#include "forward.h"
#include <assert.h>
#include <string.h>
#include <stdlib.h>

static int load(const char *text, struct l3_routes *routes)
{
    char error[128];
    FILE *f = tmpfile();
    assert(f != NULL);
    assert(fwrite(text, 1, strlen(text), f) == strlen(text));
    rewind(f);
    int result = l3_routes_read(f, routes, error, sizeof(error));
    fclose(f);
    return result;
}

static uint16_t checksum(const uint8_t *p, size_t n)
{
    uint32_t sum = 0;
    for (size_t i = 0; i < n; i += 2) sum += ((uint32_t)p[i] << 8) | p[i+1];
    while (sum >> 16) sum = (sum & 65535) + (sum >> 16);
    return (uint16_t)~sum;
}

int main(void)
{
    struct l3_routes routes = {0};
    assert(load("# routes\nR10.0.0.0/8 0\nR10.1.0.0/16 1\n"
                "R10.1.2.0/24 0\nR10.1.2.3/32 1\n", &routes) == 0);
    assert(routes.count == 4);
    assert(l3_lookup(&routes, 0x0a090001, 1) == 0);
    assert(l3_lookup(&routes, 0x0a010001, 0) == 1);
    assert(l3_lookup(&routes, 0x0a010204, 1) == 0);
    assert(l3_lookup(&routes, 0x0a010203, 0) == 1);
    assert(l3_lookup(&routes, 0xcb007101, 0) == 0);
    assert(l3_lookup(&routes, 0xcb007101, 1) == 1);
    struct l3_routes duplicate = {0};
    assert(load(" R10.1.2.99/24 0\nR10.1.2.0/24 1\n", &duplicate) == 0);
    assert(duplicate.count == 1 && l3_lookup(&duplicate, 0x0a010203, 0) == 1);
    const char *invalid[] = {"", "R10.0.0.0/0 0\n", "R10.0.0.0/33 0\n",
        "R10.0.0.0/-1 0\n", "R10.0.0.0/8 2\n", "R10.0.0.0/8 -1\n",
        "R10.0.0.0/8 0 extra\n", "R999.0.0.0/8 0\n", "R10.0.0.0/8x 0\n"};
    for (size_t i = 0; i < sizeof(invalid)/sizeof(invalid[0]); ++i) {
        struct l3_routes unchanged = routes;
        assert(load(invalid[i], &unchanged) != 0);
        assert(memcmp(&unchanged, &routes, sizeof(routes)) == 0);
    }
    FILE *many = tmpfile();
    assert(many != NULL);
    for (unsigned i = 0; i <= L3_MAX_ROUTES; ++i)
        fprintf(many, "R10.%u.%u.0/24 0\n", i/256, i%256);
    rewind(many);
    char error[128];
    assert(l3_routes_read(many, &duplicate, error, sizeof(error)) != 0);
    fclose(many);

    uint8_t frame[60] = {0};
    frame[12] = 8; frame[14] = 0x45; frame[17] = 46;
    frame[22] = 64; frame[23] = 17;
    frame[26] = 198; frame[27] = 51; frame[28] = 100; frame[29] = 1;
    frame[30] = 10; frame[31] = 1; frame[32] = 2; frame[33] = 3;
    uint16_t ck = checksum(frame+14, 20);
    frame[24] = (uint8_t)(ck >> 8); frame[25] = (uint8_t)ck;
    struct l3_macs macs = {{{2,0,0,0,0,1}, {2,0,0,0,0,2}},
                          {{2,0,0,0,1,1}, {2,0,0,0,1,2}}};
    uint8_t original[60]; memcpy(original, frame, sizeof(frame));
    uint16_t egress = 99;
    assert(l3_forward(frame, sizeof(frame), 0, &routes, &macs, &egress) == L3_FORWARDED);
    assert(egress == 1 && frame[22] == 63 && checksum(frame+14, 20) == 0);
    assert(memcmp(frame, macs.dst[1], 6) == 0 && memcmp(frame+6, macs.src[1], 6) == 0);
    assert(memcmp(frame+26, original+26, sizeof(frame)-26) == 0);
    for (size_t length = 0; length < sizeof(frame); ++length) {
        memcpy(frame, original, sizeof(frame));
        assert(l3_forward(frame, length, 0, &routes, &macs, &egress) != L3_FORWARDED);
    }
    memcpy(frame, original, sizeof(frame)); frame[14] = 0x4f;
    assert(l3_forward(frame, sizeof(frame), 0, &routes, &macs, &egress) == L3_MALFORMED);
    memcpy(frame, original, sizeof(frame)); frame[12] = 0x86; frame[13] = 0xdd;
    assert(l3_forward(frame, sizeof(frame), 0, &routes, &macs, &egress) == L3_UNSUPPORTED);
    for (unsigned ttl = 0; ttl < 2; ++ttl) {
        memcpy(frame, original, sizeof(frame)); frame[22] = (uint8_t)ttl;
        assert(l3_forward(frame, sizeof(frame), 0, &routes, &macs, &egress) == L3_FORWARDED);
        assert(frame[22] == (uint8_t)(ttl-1));
    }
    puts("C forwarding tests: PASS");
    assert(l3_route_metadata_decode(L3_ROUTE_META) == 0);
    assert(l3_route_metadata_decode(L3_ROUTE_META | 1) == 1);
    assert(l3_route_metadata_decode(0) == -1);
    assert(l3_route_metadata_decode(L3_ROUTE_META | 2) == -1);
    const unsigned ttls[] = {0, 1, 2, 64, 255};
    const unsigned checksums[] = {0, 0xfeff, 0xff00, 0xffff};
    for (unsigned p = 0; p < L3_PORTS; ++p) {
        for (unsigned t = 0; t < sizeof(ttls)/sizeof(ttls[0]); ++t) {
            for (unsigned c = 0; c < sizeof(checksums)/sizeof(checksums[0]); ++c) {
                memcpy(frame, original, sizeof(frame)); frame[22] = (uint8_t)ttls[t];
                frame[24] = checksums[c] >> 8; frame[25] = checksums[c];
                uint8_t expected[60]; memcpy(expected, frame, sizeof(frame));
                struct l3_routes selected = {.count = 1, .entries = {{0x0a000000, 8, p}}};
                assert(l3_forward(expected, sizeof(expected), 0, &selected, &macs, &egress) == L3_FORWARDED);
                assert(l3_forward_selected(frame, sizeof(frame), p, &macs) == L3_FORWARDED);
                assert(memcmp(frame, expected, sizeof(frame)) == 0);
            }
        }
    }
    memcpy(frame, original, sizeof(frame));
    assert(l3_forward_selected(frame, sizeof(frame), 2, &macs) == L3_MALFORMED);
    assert(memcmp(frame, original, sizeof(frame)) == 0);
    for (size_t length = 0; length < sizeof(frame); ++length) {
        assert(l3_forward_selected(frame, length, 0, &macs) != L3_FORWARDED);
        assert(memcmp(frame, original, sizeof(frame)) == 0);
    }
    puts("Selected hardware route rewrite tests: PASS");
    return 0;
}
