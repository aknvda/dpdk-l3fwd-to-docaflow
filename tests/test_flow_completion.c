/* SPDX-License-Identifier: BSD-3-Clause */
/* Exercise the production completion gate with a fault-injected SDK call.
 * This does not create a DOCA port or emulate hardware forwarding. */
#include "../src/flow.c"
#include <assert.h>

static struct l3_flow fixture;
static unsigned calls;
enum fault { COMPLETE, CALLBACK_ERROR, PROCESS_ERROR, NO_CALLBACK, EXTRA_CALLBACK };
static enum fault injected;

doca_error_t __wrap_doca_flow_entries_process(struct doca_flow_port *port, uint16_t queue,
                                              uint64_t timeout, uint32_t count)
{
    (void)port; (void)queue; (void)timeout;
    assert(count == 1);
    ++calls;
    if (injected == PROCESS_ERROR) return DOCA_ERROR_DRIVER;
    if (injected == NO_CALLBACK) {
        struct timespec wait = {.tv_nsec = 1000000};
        nanosleep(&wait, NULL);
        return DOCA_SUCCESS;
    }
    entry_completed(NULL, 0, injected == CALLBACK_ERROR ? DOCA_FLOW_ENTRY_STATUS_ERROR :
                    DOCA_FLOW_ENTRY_STATUS_SUCCESS, DOCA_FLOW_ENTRY_OP_ADD, &fixture.completion[0]);
    if (injected == EXTRA_CALLBACK)
        entry_completed(NULL, 0, DOCA_FLOW_ENTRY_STATUS_SUCCESS, DOCA_FLOW_ENTRY_OP_ADD,
                        &fixture.completion[0]);
    return DOCA_SUCCESS;
}

int main(void)
{
    assert(finish_entry(&fixture, 0, DOCA_ERROR_NO_MEMORY) == DOCA_ERROR_NO_MEMORY);
    assert(calls == 0 && fixture.completion[0].submitted == 0);
    for (unsigned i = 0; i < 100; ++i) assert(finish_entry(&fixture, 0, DOCA_SUCCESS) == DOCA_SUCCESS);
    assert(fixture.completion[0].submitted == 100 && fixture.completion[0].completed == 100);
    entry_completed(NULL, 0, DOCA_FLOW_ENTRY_STATUS_SUCCESS, DOCA_FLOW_ENTRY_OP_DEL,
                    &fixture.completion[0]);
    assert(fixture.completion[0].completed == 100);
    injected = CALLBACK_ERROR;
    assert(finish_entry(&fixture, 0, DOCA_SUCCESS) == DOCA_ERROR_BAD_STATE);
    assert(fixture.completion[0].failed);
    injected = COMPLETE;
    assert(finish_entry(&fixture, 0, DOCA_SUCCESS) != DOCA_SUCCESS); /* Failure is sticky. */
    memset(&fixture, 0, sizeof(fixture));
    injected = PROCESS_ERROR;
    assert(finish_entry(&fixture, 0, DOCA_SUCCESS) == DOCA_ERROR_DRIVER);
    memset(&fixture, 0, sizeof(fixture));
    injected = EXTRA_CALLBACK;
    assert(finish_entry(&fixture, 0, DOCA_SUCCESS) == DOCA_ERROR_BAD_STATE);
    memset(&fixture, 0, sizeof(fixture));
    injected = NO_CALLBACK;
    assert(finish_entry(&fixture, 0, DOCA_SUCCESS) == DOCA_ERROR_TIME_OUT);
    assert(fixture.completion[0].completed == 0);
    puts("DOCA completion fault-injection tests: PASS (no hardware access)");
}
