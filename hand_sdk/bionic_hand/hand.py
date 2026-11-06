"""BionicHand: read data from the hand over SocketCAN (or any python-can bus)."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional

import can

from . import protocol as p


class HandError(RuntimeError):
    pass


class HandNotResponding(HandError):
    pass


@dataclass
class Snapshot:
    """Everything readable from the hand at one moment."""

    timestamp: float
    angles: Optional[p.Angles]
    status: Dict[int, p.Status] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class BionicHand:
    """Client for the Intelligent Bionic Robotic Hand (CAN protocol): read data and send commands.

    Example:
        with BionicHand("can0") as hand:
            print(hand.query_angles().raw)
            print(hand.read_status("index"))
    """

    def __init__(
        self,
        channel: str = "can0",
        interface: str = "socketcan",
        device_id: int = 0x01,
        timeout: float = 0.3,
        byteorder: str = "little",
        bus: Optional[can.BusABC] = None,
        **bus_kwargs,
    ) -> None:
        """
        device_id: CAN ID of the hand (factory default 0x01).
        byteorder: byte order of the 2-byte fields in D1/D3 replies. The manual does not
                   state it for CAN; the RS485 example (raw "3B 09" = 2363) is little-endian,
                   so that is the default. Use "big" if values look wrong.
        bus:       pass an existing python-can bus (e.g. a virtual bus for tests).
        """
        self.device_id = device_id
        self.timeout = timeout
        self.byteorder = byteorder
        self.health = p.BusHealth()
        self.reply_ids: Dict[int, int] = {}  # command CAN ID -> CAN ID the reply arrived on
        self._own_bus = bus is None
        self.bus = bus or can.Bus(interface=interface, channel=channel, **bus_kwargs)
        self._rx: "queue.Queue[can.Message]" = queue.Queue(maxsize=1024)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._listeners: List[Callable[[can.Message], None]] = []
        self._reader = threading.Thread(target=self._read_loop, name="bionic-hand-rx", daemon=True)
        self._reader.start()

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        self._stop.set()
        self._reader.join(timeout=1.0)
        if self._own_bus:
            self.bus.shutdown()

    def __enter__(self) -> "BionicHand":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def add_listener(self, fn: Callable[[can.Message], None]) -> None:
        """Call `fn(msg)` for every non-error frame received (raw sniffing)."""
        self._listeners.append(fn)

    # ------------------------------------------------------------------ transport

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self.bus.recv(timeout=0.1)
            except can.CanError as exc:  # e.g. "Network is down": fails instantly, so back off
                self.health.last_error = str(exc)
                self._stop.wait(0.5)
                continue
            if msg is None:
                continue
            if msg.is_error_frame:
                self.health.error_frames += 1
                if msg.arbitration_id & p.CAN_ERR_ACK:
                    self.health.ack_errors += 1
                self.health.last_error = p.describe_error_frame(msg.arbitration_id, bytes(msg.data))
                continue
            for fn in self._listeners:
                try:
                    fn(msg)
                except Exception:  # never let a listener kill the reader
                    pass
            try:
                self._rx.put_nowait(msg)
            except queue.Full:
                try:
                    self._rx.get_nowait()
                except queue.Empty:
                    pass
                self._rx.put_nowait(msg)

    def _drain(self) -> None:
        while True:
            try:
                self._rx.get_nowait()
            except queue.Empty:
                return

    def request(self, payload: bytes, timeout: Optional[float] = None, device_id: Optional[int] = None) -> bytes:
        """Send `payload` to the hand and return the data of the matching reply.

        device_id overrides self.device_id for this call (useful with several hands on one bus).
        """
        timeout = self.timeout if timeout is None else timeout
        cid = self.device_id if device_id is None else device_id
        with self._lock:
            self._drain()
            ack_before = self.health.ack_errors
            msg = can.Message(arbitration_id=cid, data=payload, is_extended_id=False)
            try:
                self.bus.send(msg, timeout=timeout)
            except can.CanError as exc:
                raise HandError(f"send failed: {exc}. {self.diagnose()}") from exc
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    reply = self._rx.get(timeout=remaining)
                except queue.Empty:
                    break
                data = bytes(reply.data)
                if p.reply_matches(payload, data):
                    # the manual does not document the feedback ID; record what the hand really uses
                    self.reply_ids[cid] = reply.arbitration_id
                    return data
            hint = self.diagnose() if self.health.ack_errors > ack_before else ""
            raise HandNotResponding(f"no reply to {payload.hex(' ')} within {timeout:.2f}s. {hint}".strip())

    def diagnose(self) -> str:
        h = self.health
        if h.ack_errors:
            return (
                f"Bus reports {h.ack_errors} no-ACK errors (last: {h.last_error}). Nothing on the bus is "
                "acknowledging frames: check the hand has 12V power, CAN_H/CAN_L are not swapped, "
                "there is 120-ohm termination, and the bitrate is 1 Mbps."
            )
        if h.error_frames:
            return f"{h.error_frames} error frames seen (last: {h.last_error})."
        if h.last_error and "network is down" in h.last_error.lower():
            return "The CAN interface is down. Run ./can_up.sh (sets 1 Mbps and brings can0 up)."
        if h.last_error:
            return f"Last bus error: {h.last_error}."
        return "No bus errors seen; check device_id (default 0x01)."

    # ------------------------------------------------------------------ reads

    def query_angles(self, device_id: Optional[int] = None) -> p.Angles:
        """Current position of all 6 fingers (degrees 0..90 each)."""
        return p.decode_angles(self.request(p.CMD_QUERY_ANGLES, device_id=device_id))

    def query_version(self, device_id: Optional[int] = None) -> str:
        return p.decode_version(self.request(p.CMD_QUERY_VERSION, device_id=device_id))

    def read_limits(self, finger: "int | str", device_id: Optional[int] = None) -> p.Limits:
        """Servo min / max / correction for one finger (debug command D1)."""
        data = self.request(p.read_limits_request(p.finger_id(finger)), device_id=device_id)
        return p.decode_limits(data, self.byteorder)

    def read_status(self, finger: "int | str", device_id: Optional[int] = None) -> p.Status:
        """Voltage / temperature / current for one finger (debug command D3)."""
        data = self.request(p.read_status_request(p.finger_id(finger)), device_id=device_id)
        return p.decode_status(data, self.byteorder)

    def read_all_status(self, device_id: Optional[int] = None) -> Dict[int, p.Status]:
        return {fid: self.read_status(fid, device_id) for fid in p.FINGERS}

    def read_all_limits(self, device_id: Optional[int] = None) -> Dict[int, p.Limits]:
        return {fid: self.read_limits(fid, device_id) for fid in p.FINGERS}

    def ping(self, device_id: Optional[int] = None) -> bool:
        try:
            self.query_angles(device_id)
            return True
        except HandError:
            return False

    def scan(self, lo: int = 0x01, hi: int = 0x7F, timeout: float = 0.1) -> Dict[int, p.Angles]:
        """Probe CAN IDs lo..hi with the read-only angle query; return {id: angles} for responders.

        Stops early (raising HandError) if the bus refuses to transmit.
        """
        found: Dict[int, p.Angles] = {}
        for cid in range(lo, hi + 1):
            try:
                found[cid] = p.decode_angles(self.request(p.CMD_QUERY_ANGLES, timeout=timeout, device_id=cid))
            except HandNotResponding:
                continue
        return found

    # ------------------------------------------------------------------ control (moves the hand!)

    def send(self, payload: bytes, device_id: Optional[int] = None) -> None:
        """Send a command that expects no reply."""
        cid = self.device_id if device_id is None else device_id
        with self._lock:
            try:
                self.bus.send(can.Message(arbitration_id=cid, data=payload, is_extended_id=False),
                              timeout=self.timeout)
            except can.CanError as exc:
                raise HandError(f"send failed: {exc}. {self.diagnose()}") from exc

    def gesture(self, name: str, device_id: Optional[int] = None) -> None:
        """open, fist, index, middle, ring, little, ok."""
        self.send(p.gesture_request(name), device_id)

    def open_hand(self, device_id: Optional[int] = None) -> None:
        self.gesture("open", device_id)

    def close_hand(self, device_id: Optional[int] = None) -> None:
        self.gesture("fist", device_id)

    def power(self, on: bool, device_id: Optional[int] = None) -> None:
        self.send(p.POWER_ON if on else p.POWER_OFF, device_id)

    def set_finger(self, finger: "int | str", value: int, device_id: Optional[int] = None) -> None:
        """Move one finger to an angle in degrees 0..90."""
        self.send(p.finger_position_request(finger, value), device_id)

    def set_pose(self, values, device_id: Optional[int] = None) -> None:
        """Move all 6 fingers at once (degrees 0..90 each, fingers 1..6)."""
        self.send(p.pose_request(values), device_id)

    def set_setting(self, kind: str, value: int, finger: "int | str | None" = None,
                    device_id: Optional[int] = None) -> None:
        """kind = speed | torque | accel; whole hand if finger is None."""
        self.send(p.setting_request(kind, value, finger), device_id)

    def snapshot(self, with_status: bool = True, device_id: Optional[int] = None) -> Snapshot:
        """Angles + per-finger status. Individual failures are recorded, not raised."""
        snap = Snapshot(timestamp=time.time(), angles=None)
        try:
            snap.angles = self.query_angles(device_id)
        except (HandError, p.ProtocolError) as exc:
            snap.errors.append(f"angles: {exc}")
        if with_status and snap.angles is not None:  # skip 6 slow timeouts if the hand is offline
            for fid in p.FINGERS:
                try:
                    snap.status[fid] = self.read_status(fid, device_id)
                except (HandError, p.ProtocolError) as exc:
                    snap.errors.append(f"status {p.FINGERS[fid]}: {exc}")
        return snap

    def stream(self, rate_hz: float = 10.0, with_status: bool = False) -> Iterator[Snapshot]:
        """Yield snapshots at roughly `rate_hz` until the caller stops iterating."""
        period = 1.0 / rate_hz
        nxt = time.monotonic()
        while True:
            yield self.snapshot(with_status=with_status)
            nxt += period
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.monotonic()
