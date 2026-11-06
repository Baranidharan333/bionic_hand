"""Simulated hand(s) on a python-can virtual bus - for tests and demo mode (no hardware)."""
from __future__ import annotations

import math
import threading
import time
from typing import Dict, Iterable, List, Optional

import can

from . import protocol as p

OPEN_VALUE = 0     # simulator's guess: 0° = open (the manual does not say)
CLOSED_VALUE = 90
GESTURE_POSES = {  # fingers 1..6 (little, ring, middle, index, thumb, thumb_base)
    0x01: [OPEN_VALUE] * 6,
    0x02: [CLOSED_VALUE] * 6,
    0x03: [90, 90, 90, 0, 90, 90],   # index pointing
    0x04: [90, 90, 0, 90, 90, 90],
    0x05: [90, 0, 90, 90, 90, 90],
    0x06: [0, 90, 90, 90, 90, 90],
    0x07: [0, 0, 0, 70, 70, 45],       # OK
}


class _SimHand:
    def __init__(self, cid: int, angles: List[int]):
        self.cid = cid
        self.current = [float(a) for a in angles]
        self.target = list(angles)
        self.speed = 400.0  # raw units per second
        self.powered = True
        self.controlled = False  # stops the idle animation once commanded


class SimulatedHands(threading.Thread):
    """Answers reads and obeys control commands for each CAN ID in `ids`.

    animate:      fingers drift slowly until the first control command arrives.
    reply_offset: feedback frames are sent on cid + reply_offset (default: same ID).
    """

    def __init__(self, channel: str, ids: Iterable[int] = (0x01,), animate: bool = False,
                 angles: Optional[list] = None, reply_offset: int = 0):
        super().__init__(daemon=True, name="sim-hands")
        self.bus = can.Bus(interface="virtual", channel=channel)
        self.animate = animate
        self.reply_offset = reply_offset
        base = angles or [10, 20, 30, 40, 50, 90]
        self.hands: Dict[int, _SimHand] = {cid: _SimHand(cid, base) for cid in ids}
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._last = time.monotonic()

    def angles_for(self, cid: int) -> list:
        h = self.hands[cid]
        if self.animate and not h.controlled:
            t = time.monotonic() - self._t0
            return [int(127 + 120 * math.sin(t * 0.8 + i * 0.6 + cid)) for i in range(6)]
        return [int(round(v)) for v in h.current]

    def _step(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        for h in self.hands.values():
            if not h.powered:
                continue
            for i in range(6):
                d = h.target[i] - h.current[i]
                step = h.speed * dt
                h.current[i] = h.target[i] if abs(d) <= step else h.current[i] + math.copysign(step, d)

    def handle(self, cid: int, d: bytes) -> Optional[bytes]:
        h = self.hands[cid]
        # ---- reads
        if d[:2] == b"\xA1\x01":
            return bytes([0xA1, 0x01] + self.angles_for(cid))
        if d[:2] == b"\xA1\x02":
            return bytes([0xA1, 0x02, 0x01, 0x00, cid])
        if d[0] == 0xD1:
            return (bytes([0xD1, d[1]]) + (100).to_bytes(2, "little") + (3995).to_bytes(2, "little")
                    + (0x800 | 5).to_bytes(2, "little"))
        if d[0] == 0xD3 and d[1] in p.FINGERS:
            # like the real hand: 6.4 V, temp, present position in steps (0° = max step 3995), then 2000
            ang = self.angles_for(cid)[d[1] - 1]
            steps = int(3995 - ang * (3995 - 100) / 90)
            return (bytes([0xD3, d[1], 64, 30 + d[1]]) + steps.to_bytes(2, "little")
                    + (2000).to_bytes(2, "little"))
        # ---- control (no reply)
        if d[0] == 0x03 and len(d) >= 2:
            if d[1] == 0x00:
                h.powered = False
            elif d[1] == 0x11:
                h.powered = True
            elif d[1] in GESTURE_POSES:
                self._take_control(h)
                h.target = list(GESTURE_POSES[d[1]])
        elif d[0] == 0x04 and len(d) >= 3 and d[1] in p.FINGERS:
            self._take_control(h)
            h.target[d[1] - 1] = d[2]
        elif d[0] == 0xA3 and len(d) >= 7:
            self._take_control(h)
            h.target = list(d[1:7])
        elif d[0] == 0x05 and len(d) >= 2:
            h.speed = max(20.0, d[1] * 4.0)
        return None

    def _take_control(self, h: _SimHand) -> None:
        if not h.controlled:
            h.current = [float(a) for a in self.angles_for(h.cid)]
            h.controlled = True

    def run(self) -> None:
        while not self._stop.is_set():
            m = self.bus.recv(0.02)
            self._step()
            if m is None or m.is_error_frame or m.arbitration_id not in self.hands:
                continue
            out = self.handle(m.arbitration_id, bytes(m.data))
            if out:
                self.bus.send(can.Message(arbitration_id=m.arbitration_id + self.reply_offset,
                                          data=out, is_extended_id=False))

    def close(self) -> None:
        self._stop.set()
        self.join(1)
        self.bus.shutdown()
