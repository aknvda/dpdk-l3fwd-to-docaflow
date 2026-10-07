"""Defer ordinary cancellation until a bounded cleanup phase has finished."""
from contextlib import contextmanager
import signal


@contextmanager
def defer_cancellation():
    # The CLI runs on the main thread. Record signals without raising midway
    # through child reaping or interface restoration; never turn cancellation
    # into a successful run. Nested phases restore the enclosing handlers.
    previous = {}
    cancelled = False

    def record(_signum, _frame):
        nonlocal cancelled
        cancelled = True

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, record)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    if cancelled:
        raise KeyboardInterrupt('Interrupted during cleanup')
