/* SPDX-License-Identifier: BSD-3-Clause */
#include "flow.h"
#include <arpa/inet.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <doca_flow.h>
#include <doca_log.h>

struct completion { unsigned submitted, completed; bool failed; };
struct l3_flow {
    bool initialized;
    const volatile sig_atomic_t *cancelled;
    uint16_t queue;
    struct doca_flow_port *ports[L3_PORTS];
    struct doca_flow_pipe *exceptions[L3_PORTS];
    struct doca_flow_pipe_entry *rewrite[L3_PORTS];
    struct completion completion[L3_PORTS];
};

/* Contexts live until ports and the flow library have been destroyed. */
static void entry_completed(struct doca_flow_pipe_entry *entry, uint16_t queue,
                            enum doca_flow_entry_status status,
                            enum doca_flow_entry_op operation, void *context)
{
    (void)entry; (void)queue;
    if (operation != DOCA_FLOW_ENTRY_OP_ADD || !context) return;
    struct completion *c = context;
    ++c->completed;
    if (status != DOCA_FLOW_ENTRY_STATUS_SUCCESS) c->failed = true;
}

static double seconds(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

/* Drain each submission: bounded queue use and no READY on submission alone. */
static doca_error_t finish_entry(struct l3_flow *flow, unsigned p, doca_error_t added)
{
    if (added != DOCA_SUCCESS) return added;
    struct completion *c = &flow->completion[p];
    ++c->submitted;
    double deadline = seconds() + 2.0;
    while (c->completed < c->submitted && !c->failed) {
        if (flow->cancelled && *flow->cancelled) return DOCA_ERROR_BAD_STATE;
        if (seconds() >= deadline) return DOCA_ERROR_TIME_OUT;
        doca_error_t err = doca_flow_entries_process(flow->ports[p], 0, 10000, 1);
        if (err != DOCA_SUCCESS) return err;
    }
    return c->failed || c->completed != c->submitted ? DOCA_ERROR_BAD_STATE : DOCA_SUCCESS;
}

#define TRY(expression) do { \
    err = (flow->cancelled && *flow->cancelled) ? DOCA_ERROR_BAD_STATE : (expression); \
    if (err != DOCA_SUCCESS) { \
        fprintf(stderr, "%s: %s failed: %s (%d)\n", __func__, #expression, \
                doca_error_get_descr(err), (int)err); \
        goto out; \
    } \
} while (0)

static doca_error_t initialize(struct l3_flow *flow)
{
    struct doca_flow_cfg *cfg = NULL;
    struct doca_log_backend *sdk_log;
    doca_error_t err;
    TRY(doca_log_backend_create_with_file_sdk(stderr, &sdk_log));
    TRY(doca_log_backend_set_sdk_level(sdk_log, DOCA_LOG_LEVEL_WARNING));
    TRY(doca_flow_cfg_create(&cfg));
    TRY(doca_flow_cfg_set_pipe_queues(cfg, 1));
    TRY(doca_flow_cfg_set_mode_args(cfg, "vnf,hws"));
    TRY(doca_flow_cfg_set_resource_mode(cfg, DOCA_FLOW_RESOURCE_MODE_PORT));
    TRY(doca_flow_cfg_set_cb_entry_process(cfg, entry_completed));
    TRY(doca_flow_init(cfg));
    flow->initialized = true;
out:
    if (cfg) doca_flow_cfg_destroy(cfg);
    return err;
}

static doca_error_t start_port(struct l3_flow *flow, unsigned p,
                              struct doca_dev *device, size_t routes)
{
    struct doca_flow_port_cfg *cfg = NULL;
    doca_error_t err;
    uint32_t action_bytes = 64;
    while (action_bytes < (routes + 256) * DOCA_FLOW_MAX_ENTRY_ACTIONS_MEM_SIZE)
        action_bytes *= 2;
    TRY(doca_flow_port_cfg_create(&cfg));
    TRY(doca_flow_port_cfg_set_port_id(cfg, p));
    TRY(doca_flow_port_cfg_set_dev(cfg, device));
    TRY(doca_flow_port_cfg_set_actions_mem_size(cfg, action_bytes));
    TRY(doca_flow_port_cfg_set_nr_resources(cfg, DOCA_FLOW_RESOURCE_COUNTER, 1));
    TRY(doca_flow_port_cfg_set_nr_resources(cfg, DOCA_FLOW_RESOURCE_RSS, 1));
    TRY(doca_flow_port_start(cfg, &flow->ports[p]));
out:
    if (cfg) doca_flow_port_cfg_destroy(cfg);
    return err;
}

static struct doca_flow_fwd software_fwd(struct l3_flow *flow)
{
    struct doca_flow_fwd rss = {0};
    rss.type = DOCA_FLOW_FWD_RSS;
    rss.rss_type = DOCA_FLOW_RESOURCE_TYPE_NON_SHARED;
    rss.rss.outer_flags = DOCA_FLOW_RSS_IPV4;
    rss.rss.queues_array = &flow->queue;
    rss.rss.nr_queues = 1;
    return rss;
}

static struct doca_flow_fwd exception_fwd(struct l3_flow *flow, unsigned p)
{
    struct doca_flow_fwd fwd = {.type = DOCA_FLOW_FWD_PIPE, .next_pipe = flow->exceptions[p]};
    return fwd;
}

static doca_error_t exception_pipe(struct l3_flow *flow, unsigned p)
{
    /* RSS is supported on a match, not directly as a pipe's miss destination. */
    struct doca_flow_pipe_cfg *cfg = NULL;
    struct doca_flow_match match = {0};
    struct doca_flow_fwd rss = software_fwd(flow);
    struct doca_flow_pipe_entry *entry;
    doca_error_t err;
    TRY(doca_flow_pipe_cfg_create(&cfg, flow->ports[p]));
    TRY(doca_flow_pipe_cfg_set_name(cfg, "SOFTWARE_EXCEPTIONS"));
    TRY(doca_flow_pipe_cfg_set_type(cfg, DOCA_FLOW_PIPE_BASIC));
    TRY(doca_flow_pipe_cfg_set_is_root(cfg, false));
    TRY(doca_flow_pipe_cfg_set_nr_entries(cfg, 1));
    TRY(doca_flow_pipe_cfg_set_match(cfg, &match, NULL));
    TRY(doca_flow_pipe_create(cfg, &rss, NULL, &flow->exceptions[p]));
    TRY(finish_entry(flow, p, doca_flow_pipe_basic_add_entry(0, flow->exceptions[p], &match,
        0, NULL, NULL, NULL, DOCA_FLOW_ENTRY_FLAGS_NO_WAIT, &flow->completion[p], &entry)));
out:
    if (cfg) doca_flow_pipe_cfg_destroy(cfg);
    return err;
}

static doca_error_t rewrite_pipe(struct l3_flow *flow, unsigned p,
                                const struct l3_macs *macs, struct doca_flow_pipe **pipe)
{
    struct doca_flow_pipe_cfg *cfg = NULL;
    struct doca_flow_match match = {0};
    struct doca_flow_actions actions = {0}, *actions_array[] = {&actions};
    struct doca_flow_monitor monitor = {0};
    struct doca_flow_fwd fwd = {.type = DOCA_FLOW_FWD_PORT, .port_id = p ^ 1};
    struct doca_flow_fwd miss = exception_fwd(flow, p);
    struct doca_flow_action_desc desc = {0};
    struct doca_flow_action_descs descs = {.nb_action_desc = 1, .desc_array = &desc};
    struct doca_flow_action_descs *descs_array[] = {&descs};
    doca_error_t err;
    match.parser_meta.outer_l3_type = DOCA_FLOW_L3_META_IPV4;
    memcpy(actions.outer.eth.src_mac, macs->src[p ^ 1], 6);
    memcpy(actions.outer.eth.dst_mac, macs->dst[p ^ 1], 6);
    actions.outer.l3_type = DOCA_FLOW_L3_TYPE_IP4;
    actions.outer.ip4.ttl = UINT8_MAX; /* ADD 255 is an 8-bit decrement. */
    desc.type = DOCA_FLOW_ACTION_ADD;
    desc.field_op.dst.field_string = "outer.ipv4.ttl";
    desc.field_op.width = 8;
    monitor.counter_type = DOCA_FLOW_RESOURCE_TYPE_NON_SHARED;
    TRY(doca_flow_pipe_cfg_create(&cfg, flow->ports[p]));
    TRY(doca_flow_pipe_cfg_set_name(cfg, "EGRESS_REWRITE"));
    TRY(doca_flow_pipe_cfg_set_type(cfg, DOCA_FLOW_PIPE_BASIC));
    TRY(doca_flow_pipe_cfg_set_is_root(cfg, false));
    TRY(doca_flow_pipe_cfg_set_nr_entries(cfg, 1));
    TRY(doca_flow_pipe_cfg_set_match(cfg, &match, NULL));
    TRY(doca_flow_pipe_cfg_set_actions(cfg, actions_array, NULL, descs_array, 1));
    TRY(doca_flow_pipe_cfg_set_monitor(cfg, &monitor));
    TRY(doca_flow_pipe_create(cfg, &fwd, &miss, pipe));
    memset(&match, 0, sizeof(match));
    /* Supply the TTL operand explicitly: 0xff in a template is changeable. */
    TRY(finish_entry(flow, p, doca_flow_pipe_basic_add_entry(0, *pipe, &match, 0,
        &actions, NULL, NULL, DOCA_FLOW_ENTRY_FLAGS_NO_WAIT,
        &flow->completion[p], &flow->rewrite[p])));
out:
    if (cfg) doca_flow_pipe_cfg_destroy(cfg);
    return err;
}

static doca_error_t route_pipe(struct l3_flow *flow, unsigned p,
                              const struct l3_routes *routes, struct doca_flow_pipe *rewrite,
                              struct doca_flow_pipe **pipe)
{
    struct doca_flow_pipe_cfg *cfg = NULL;
    struct doca_flow_match match = {0};
    struct doca_flow_actions actions = {0}, *actions_array[] = {&actions};
    struct doca_flow_fwd changeable = {.type = DOCA_FLOW_FWD_CHANGEABLE};
    struct doca_flow_fwd miss = exception_fwd(flow, p);
    doca_error_t err;
    match.outer.l3_type = DOCA_FLOW_L3_TYPE_IP4;
    match.outer.ip4.dst_ip = UINT32_MAX;
    TRY(doca_flow_pipe_cfg_create(&cfg, flow->ports[p]));
    TRY(doca_flow_pipe_cfg_set_name(cfg, "IPV4_LPM"));
    TRY(doca_flow_pipe_cfg_set_type(cfg, DOCA_FLOW_PIPE_LPM));
    TRY(doca_flow_pipe_cfg_set_is_root(cfg, false));
    TRY(doca_flow_pipe_cfg_set_nr_entries(cfg, routes->count));
    TRY(doca_flow_pipe_cfg_set_match(cfg, &match, NULL));
    TRY(doca_flow_pipe_cfg_set_actions(cfg, actions_array, NULL, NULL, 1));
    TRY(doca_flow_pipe_create(cfg, &changeable, &miss, pipe));
    for (size_t i = 0; i < routes->count; ++i) {
        const struct l3_route *r = &routes->entries[i];
        struct doca_flow_match entry = {0}, mask = {0};
        struct doca_flow_pipe_entry *handle;
        struct doca_flow_fwd fwd = miss;
        entry.outer.ip4.dst_ip = htonl(r->network);
        mask.outer.ip4.dst_ip = htonl(UINT32_MAX << (32 - r->depth));
        if (r->port != p) { fwd.type = DOCA_FLOW_FWD_PIPE; fwd.next_pipe = rewrite; }
        /* Same-port hits and misses take the original, unmodified packet to software. */
        TRY(finish_entry(flow, p, doca_flow_pipe_lpm_add_entry(0, *pipe, &entry, &mask,
            0, NULL, NULL, &fwd, DOCA_FLOW_ENTRY_FLAGS_NO_WAIT, &flow->completion[p], &handle)));
    }
out:
    if (cfg) doca_flow_pipe_cfg_destroy(cfg);
    return err;
}

static doca_error_t root_pipe(struct l3_flow *flow, unsigned p, struct doca_flow_pipe *lpm)
{
    struct doca_flow_pipe_cfg *cfg = NULL;
    struct doca_flow_pipe *pipe;
    struct doca_flow_match match = {0}, mask = {0};
    struct doca_flow_fwd fwd = {.type = DOCA_FLOW_FWD_PIPE, .next_pipe = lpm};
    struct doca_flow_fwd miss = exception_fwd(flow, p);
    doca_error_t err;
    match.parser_meta.outer_l3_type = DOCA_FLOW_L3_META_IPV4;
    mask.parser_meta.outer_l3_type = UINT32_MAX;
    /* Explicit masks are required to match zero-valued no-VLAN/no-fragment flags. */
    mask.parser_meta.outer_l2_type = UINT32_MAX;
    mask.parser_meta.outer_ip_fragmented = 1;
    match.parser_meta.outer_l3_ok = mask.parser_meta.outer_l3_ok = 1;
    match.parser_meta.outer_ip4_checksum_ok = mask.parser_meta.outer_ip4_checksum_ok = 1;
    match.outer.l3_type = DOCA_FLOW_L3_TYPE_IP4;
    match.outer.ip4.version_ihl = 0x45;
    mask.outer.ip4.version_ihl = UINT8_MAX;
    match.outer.ip4.ttl = mask.outer.ip4.ttl = UINT8_MAX;
    TRY(doca_flow_pipe_cfg_create(&cfg, flow->ports[p]));
    TRY(doca_flow_pipe_cfg_set_name(cfg, "IPV4_ADMISSION"));
    TRY(doca_flow_pipe_cfg_set_type(cfg, DOCA_FLOW_PIPE_BASIC));
    TRY(doca_flow_pipe_cfg_set_is_root(cfg, true));
    TRY(doca_flow_pipe_cfg_set_nr_entries(cfg, 254));
    TRY(doca_flow_pipe_cfg_set_match(cfg, &match, &mask));
    TRY(doca_flow_pipe_create(cfg, &fwd, &miss, &pipe));
    for (unsigned ttl = 2; ttl <= 255; ++ttl) {
        struct doca_flow_match entry = {0};
        struct doca_flow_pipe_entry *handle;
        entry.outer.ip4.ttl = ttl;
        TRY(finish_entry(flow, p, doca_flow_pipe_basic_add_entry(0, pipe, &entry, 0,
            NULL, NULL, NULL, DOCA_FLOW_ENTRY_FLAGS_NO_WAIT, &flow->completion[p], &handle)));
    }
out:
    if (cfg) doca_flow_pipe_cfg_destroy(cfg);
    return err;
}

int l3_flow_start(struct l3_flow **output, const struct l3_routes *routes,
                  const struct l3_macs *macs, struct doca_dev *devices[L3_PORTS],
                  const volatile sig_atomic_t *cancelled)
{
    struct l3_flow *flow = calloc(1, sizeof(*flow));
    if (!flow) return -1;
    *output = flow; /* Caller owns cleanup on both success and partial failure. */
    flow->cancelled = cancelled;
    doca_error_t err;
    TRY(initialize(flow));
    for (unsigned p = 0; p < L3_PORTS; ++p) TRY(start_port(flow, p, devices[p], routes->count));
    TRY(doca_flow_port_pair(flow->ports[1], flow->ports[0]));
    TRY(doca_flow_port_pair(flow->ports[0], flow->ports[1]));
    for (unsigned p = 0; p < L3_PORTS; ++p) {
        struct doca_flow_pipe *rewrite, *lpm;
        TRY(exception_pipe(flow, p));
        TRY(rewrite_pipe(flow, p, macs, &rewrite));
        TRY(route_pipe(flow, p, routes, rewrite, &lpm));
        TRY(root_pipe(flow, p, lpm));
    }
    return 0;
out:
    fprintf(stderr, "DOCA pipeline installation failed: %s\n", doca_error_get_descr(err));
    return -1;
}

int l3_flow_counters(struct l3_flow *flow, uint64_t forwarded[L3_PORTS])
{
    for (unsigned p = 0; p < L3_PORTS; ++p) {
        struct doca_flow_resource_query query = {0};
        doca_error_t err = doca_flow_resource_query_entry(flow->rewrite[p], &query);
        if (err != DOCA_SUCCESS) {
            fprintf(stderr, "DOCA counter query failed: %s\n", doca_error_get_descr(err)); return -1;
        }
        forwarded[p] = query.counter.total_pkts;
    }
    return 0;
}

int l3_flow_stop(struct l3_flow *flow)
{
    if (!flow) return 0;
    int result = 0;
    for (unsigned p = L3_PORTS; p-- > 0;)
        if (flow->ports[p] && doca_flow_port_stop(flow->ports[p]) != DOCA_SUCCESS) result = -1;
    if (flow->initialized) doca_flow_destroy();
    free(flow);
    return result;
}
