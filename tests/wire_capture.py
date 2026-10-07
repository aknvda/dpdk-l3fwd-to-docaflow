"""Paced finite replay with concurrent capture and a full post-send window."""
import itertools
import math
import select
import socket
import time


def capture_replay(sockets, inputs, pps, settle, alive, actual=None):
    if len(sockets) != 2 or not math.isfinite(pps) or not 1 <= pps <= 1000:
        raise ValueError('Require two sockets and 1..1000 aggregate packets/s')
    if not math.isfinite(settle) or settle <= 0:
        raise ValueError('Require a positive post-send observation interval')
    pending = [(p, frame) for pair in itertools.zip_longest(inputs[0], inputs[1])
               for p, frame in enumerate(pair) if frame is not None]
    if not pending: raise ValueError('Empty replay is not a test')
    if actual is None: actual = {0: [], 1: []}
    for sock in sockets: sock.setblocking(False)
    sent, received = 0, 0
    next_send = time.monotonic()
    end = None
    while end is None or time.monotonic() < end:
        if not alive(): raise RuntimeError('DUT exited during packet replay/capture')
        now = time.monotonic()
        if sent < len(pending) and now >= next_send:
            port, frame = pending[sent]
            if sockets[port].send(frame) != len(frame):
                raise RuntimeError('Partial packet transmission')
            sent += 1
            next_send = time.monotonic()+1/pps
            if sent == len(pending): end = time.monotonic()+settle
        until = min(.02, max(0, (end if end is not None else next_send)-time.monotonic()))
        ready, _, _ = select.select(sockets, [], [], until)
        for sock in ready:
            port = sockets.index(sock)
            for _ in range(32):
                try:
                    frame, _, flags, address = sock.recvmsg(65536)
                except BlockingIOError:
                    break
                if isinstance(address, tuple) and len(address) > 2 and address[2] == 4:  # PACKET_OUTGOING
                    continue
                if flags & socket.MSG_TRUNC:
                    raise RuntimeError('Truncated packet capture')
                actual[port].append(frame)
                received += 1
                if received > 2*len(pending)+128:
                    raise RuntimeError('Unexpected traffic exceeds bounded capture capacity')
    return actual
