/* SPDX-License-Identifier: BSD-3-Clause */
/* Model paired-port references at the SDK boundary. No hardware is opened. */
#include "../src/flow.c"
#include <assert.h>

static char handles[L3_PORTS];
static char pipe_handles[L3_PORTS][6];
static bool pipe_live[L3_PORTS][6];
/* exception, rewrite, LPM, root: outgoing edges within each pipeline. */
static const unsigned edges[6] = {0, 1, 3, 5, 0, 24};
static bool live[L3_PORTS], references[L3_PORTS], destroyed;
static int fail_stop = -1;

static unsigned port_index(struct doca_flow_port *port)
{
    for (unsigned p = 0; p < L3_PORTS; ++p)
        if (port == (struct doca_flow_port *)&handles[p]) return p;
    abort(); /* Never pass a missing/unknown port to the SDK. */
}

void __wrap_doca_flow_pipe_destroy(struct doca_flow_pipe *pipe)
{
    for (unsigned p = 0; p < L3_PORTS; ++p) {
        for (unsigned node = 0; node < 6; ++node) {
            if (pipe != (struct doca_flow_pipe *)&pipe_handles[p][node]) continue;
            assert(pipe_live[p][node]);
            for (unsigned source = 0; source < 6; ++source)
                assert(!pipe_live[p][source] || !(edges[source] & (1u << node)));
            pipe_live[p][node] = false;
            return;
        }
    }
    abort();
}

void __wrap_doca_flow_port_pipes_flush(struct doca_flow_port *port)
{
    unsigned p = port_index(port);
    assert(live[p]);
    /* A generic flush need not know the application's dependency order. */
    for (unsigned node = 0; node < 6; ++node)
        if (pipe_live[p][node])
            __wrap_doca_flow_pipe_destroy((struct doca_flow_pipe *)&pipe_handles[p][node]);
    references[p] = false;
}

doca_error_t __wrap_doca_flow_port_stop(struct doca_flow_port *port)
{
    unsigned p = port_index(port);
    assert(live[p]);
    /* Paired-port forwarding rules may retain the other port's resources. */
    if (references[p ^ 1]) return DOCA_ERROR_IN_USE;
    live[p] = false;
    references[p] = false;
    return (int)p == fail_stop ? DOCA_ERROR_DRIVER : DOCA_SUCCESS;
}

void __wrap_doca_flow_destroy(void)
{
    assert(!live[0] && !live[1]);
    assert(!destroyed);
    destroyed = true;
}

static void cleanup_case(unsigned ports, unsigned pipes, bool initialized, int failure)
{
    struct l3_flow *flow = calloc(1, sizeof(*flow));
    assert(flow);
    memset(live, 0, sizeof(live));
    memset(references, 0, sizeof(references));
    memset(pipe_live, 0, sizeof(pipe_live));
    destroyed = false;
    fail_stop = failure;
    flow->initialized = initialized;
    for (unsigned p = 0; p < ports; ++p) {
        flow->ports[p] = (struct doca_flow_port *)&handles[p];
        live[p] = references[p] = true;
        struct doca_flow_pipe **slots[] = {&flow->exceptions[p], &flow->rewrites[p],
                                          &flow->lpm[p], &flow->roots[p], &flow->capture_sinks[p], &flow->captures[p]};
        for (unsigned node = 0; node < 6 && 6*p+node < pipes; ++node) {
            *slots[node] = (struct doca_flow_pipe *)&pipe_handles[p][node];
            pipe_live[p][node] = true;
        }
    }
    assert(l3_flow_stop(flow) == (failure < 0 ? 0 : -1));
    assert(!live[0] && !live[1]);
    for (unsigned p = 0; p < L3_PORTS; ++p)
        for (unsigned node = 0; node < 6; ++node) assert(!pipe_live[p][node]);
    assert(destroyed == initialized);
}

int main(void)
{
    cleanup_case(2, 12, true, -1);
    for (unsigned pipes = 0; pipes < 12; ++pipes) cleanup_case(2, pipes, true, -1);
    cleanup_case(2, 12, true, 1); /* Continue cleanup after a failed port stop. */
    cleanup_case(2, 12, true, 0);
    cleanup_case(1, 0, true, -1); /* Startup failed before the second port opened. */
    cleanup_case(0, 0, true, -1);
    cleanup_case(0, 0, false, -1);
    assert(l3_flow_stop(NULL) == 0);
    puts("DOCA paired-port cleanup tests: PASS (no hardware access)");
}
