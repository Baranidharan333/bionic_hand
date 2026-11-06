"""Pure encode/decode helpers for the Bionic Hand CAN protocol (manual v1.0.0, section 3.3).

No I/O here, so everything can be unit-tested without hardware.

Bus: 1 Mbps, standard 11-bit ID, data frames. Arbitration ID = device CAN ID (default 0x01).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Finger codes (manual 2.4) - same for left and right hand.
FINGERS: Dict[int, str] = {
    1: "little",
    2: "ring",
    3: "middle",
    4: "index",
    5: "thumb",
    6: "thumb_base",  # thumb metacarpal joint
}
FINGER_IDS: Dict[str, int] = {v: k for k, v in FINGERS.items()}

# Read commands (request payload, and the (byte0, byte1) prefix the reply carries).
CMD_QUERY_ANGLES = bytes([0xA1, 0x01])
CMD_QUERY_VERSION = bytes([0xA1, 0x02])
CMD_READ_LIMITS = 0xD1  # + finger id + 6 zero bytes
CMD_READ_STATUS = 0xD3  # + finger id + 6 zero bytes

# Units from manual 3.4 "Parameter Analysis".
VOLTAGE_UNIT_V = 0.1
CURRENT_UNIT_MA = 6.5


def finger_id(finger: "int | str") -> int:
    """Accept 1..6 or a name like 'index' and return the numeric finger code."""
    if isinstance(finger, str):
        key = finger.strip().lower()
        if key.isdigit():
            finger = int(key)
        elif key in FINGER_IDS:
            return FINGER_IDS[key]
        else:
            raise ValueError(f"unknown finger {finger!r}; use 1..6 or one of {list(FINGER_IDS)}")
    if finger not in FINGERS:
        raise ValueError(f"finger id must be 1..6, got {finger}")
    return finger


# --------------------------------------------------------------------------- control commands
# Action modes (byte0 = 0x03).
GESTURES: Dict[str, int] = {
    "open": 0x01,
    "fist": 0x02,
    "index": 0x03,
    "middle": 0x04,
    "ring": 0x05,
    "little": 0x06,
    "ok": 0x07,
}
POWER_ON = bytes([0x03, 0x11])
POWER_OFF = bytes([0x03, 0x00])

# 4-byte settings. Manual layout: "<cmd> <value> 00" (whole hand) / "<cmd> <id> <value> 00" (one finger).
SETTING_ALL = {"speed": 0x05, "torque": 0x06, "accel": 0x07}
SETTING_ONE = {"accel": 0x08, "speed": 0x09, "torque": 0x10}


def u8(value: int, what: str = "value") -> int:
    value = int(value)
    if not 0 <= value <= 255:
        raise ValueError(f"{what} must be 0..255, got {value}")
    return value


def gesture_request(name: str) -> bytes:
    key = name.strip().lower()
    if key not in GESTURES:
        raise ValueError(f"unknown gesture {name!r}; use one of {list(GESTURES)}")
    return bytes([0x03, GESTURES[key]])


def angle(value: int) -> int:
    value = int(value)
    if not 0 <= value <= ANGLE_MAX:
        raise ValueError(f"angle must be 0..{ANGLE_MAX} degrees, got {value}")
    return value


def finger_position_request(finger: "int | str", value: int) -> bytes:
    """Single-finger position (04 ID Angle 00); value in degrees 0..90, same scale as the angle reply."""
    return bytes([0x04, finger_id(finger), angle(value), 0x00])


def pose_request(values) -> bytes:
    """All-finger position mode (A3 a1..a6 00); degrees 0..90 for fingers 1..6."""
    vals = [angle(v) for v in values]
    if len(vals) != 6:
        raise ValueError("pose needs exactly 6 values (fingers 1..6)")
    return bytes([0xA3, *vals, 0x00])


def setting_request(kind: str, value: int, finger: "int | str | None" = None) -> bytes:
    """speed / torque / accel for the whole hand (finger=None) or one finger."""
    kind = kind.lower()
    if finger is None:
        if kind not in SETTING_ALL:
            raise ValueError(f"setting must be one of {list(SETTING_ALL)}")
        return bytes([SETTING_ALL[kind], u8(value, kind), 0x00, 0x00])
    if kind not in SETTING_ONE:
        raise ValueError(f"setting must be one of {list(SETTING_ONE)}")
    return bytes([SETTING_ONE[kind], finger_id(finger), u8(value, kind), 0x00])


def read_limits_request(fid: int) -> bytes:
    return bytes([CMD_READ_LIMITS, finger_id(fid), 0, 0, 0, 0, 0, 0])


def read_status_request(fid: int) -> bytes:
    return bytes([CMD_READ_STATUS, finger_id(fid), 0, 0, 0, 0, 0, 0])


def _u16(lo_hi: bytes, byteorder: str) -> int:
    return int.from_bytes(lo_hi, byteorder)  # type: ignore[arg-type]


def _s12(raw: int) -> int:
    """Position correction: BIT11 is the sign bit, bits 0..10 the magnitude (manual 3.4)."""
    mag = raw & 0x7FF
    return -mag if raw & 0x800 else mag


# --------------------------------------------------------------------------- results


ANGLE_MAX = 90  # angles are degrees 0..90 (verified on hardware: matches manual's X=(max-raw)*90/(max-min))


@dataclass
class Angles:
    """Reply to A1 01: one byte per finger = angle in degrees 0..90 (0 = servo at its max-step limit)."""

    raw: Dict[int, int]

    @property
    def percent(self) -> Dict[int, float]:
        return {k: round(min(v, ANGLE_MAX) * 100.0 / ANGLE_MAX, 1) for k, v in self.raw.items()}

    def by_name(self) -> Dict[str, int]:
        return {FINGERS[k]: v for k, v in self.raw.items()}

    def as_list(self) -> List[int]:
        return [self.raw[i] for i in range(1, 7)]


@dataclass
class Limits:
    """Reply to D1: servo min / max / correction (2 bytes each)."""

    finger: int
    servo_min: int
    servo_max: int
    correction: int
    raw_bytes: bytes = field(repr=False, default=b"")


@dataclass
class Status:
    """Reply to D3: voltage, temperature, present servo position.

    Verified on hardware: bytes 4-5 ("Current Servo Value" in the manual) are the servo's present
    position in steps - it always lies within that finger's D1 min/max limits. Bytes 6-7 are
    undocumented (seen as 2000, later 1, on the real hand) and kept as `extra`.
    """

    finger: int
    voltage_v: float
    temperature_c: int
    position_steps: int
    extra: int = 0
    raw_bytes: bytes = field(repr=False, default=b"")


# --------------------------------------------------------------------------- decoders


class ProtocolError(ValueError):
    pass


def _check(data: bytes, prefix: bytes, min_len: int = 8) -> None:
    if len(data) < min_len or data[: len(prefix)] != prefix:
        raise ProtocolError(f"unexpected reply {data.hex(' ')} (expected {prefix.hex(' ')} ..)")


def decode_angles(data: bytes) -> Angles:
    _check(data, CMD_QUERY_ANGLES)
    return Angles(raw={i + 1: data[2 + i] for i in range(6)})


def decode_version(data: bytes) -> str:
    """The manual does not document the version reply layout; return the payload as hex."""
    _check(data, CMD_QUERY_VERSION, min_len=2)
    return data[2:].hex(" ") or "(empty)"


def decode_limits(data: bytes, byteorder: str = "little") -> Limits:
    _check(data, bytes([CMD_READ_LIMITS]))
    return Limits(
        finger=data[1],
        servo_min=_u16(data[2:4], byteorder),
        servo_max=_u16(data[4:6], byteorder),
        correction=_s12(_u16(data[6:8], byteorder)),
        raw_bytes=bytes(data),
    )


def decode_status(data: bytes, byteorder: str = "little") -> Status:
    _check(data, bytes([CMD_READ_STATUS]))
    return Status(
        finger=data[1],
        voltage_v=round(data[2] * VOLTAGE_UNIT_V, 1),
        temperature_c=data[3],
        position_steps=_u16(data[4:6], byteorder),
        extra=_u16(data[6:8], byteorder),
        raw_bytes=bytes(data),
    )


def reply_matches(request: bytes, reply: bytes) -> bool:
    """True if `reply` answers `request` (same command byte; same sub-command/finger byte)."""
    if len(reply) < 2 or len(request) < 2:
        return False
    return reply[0] == request[0] and reply[1] == request[1]


# --------------------------------------------------------------------------- error frames

CAN_ERR_TX_TIMEOUT = 0x001
CAN_ERR_LOSTARB = 0x002
CAN_ERR_CRTL = 0x004
CAN_ERR_PROT = 0x008
CAN_ERR_TRX = 0x010
CAN_ERR_ACK = 0x020
CAN_ERR_BUSOFF = 0x040
CAN_ERR_BUSERROR = 0x080
CAN_ERR_RESTARTED = 0x100


def describe_error_frame(arb_id: int, data: bytes) -> str:
    """Human-readable summary of a SocketCAN error frame (linux/can/error.h)."""
    parts = []
    if arb_id & CAN_ERR_ACK:
        parts.append("no ACK (no other node acknowledged our frame)")
    if arb_id & CAN_ERR_BUSOFF:
        parts.append("bus-off")
    if arb_id & CAN_ERR_CRTL and len(data) > 1:
        c = data[1]
        if c & 0x30:
            parts.append("controller error-passive")
        elif c & 0x0C:
            parts.append("controller error-warning")
    if arb_id & CAN_ERR_PROT:
        parts.append("protocol violation")
    if arb_id & CAN_ERR_TRX:
        parts.append("transceiver error")
    if arb_id & CAN_ERR_BUSERROR:
        parts.append("bus error")
    if arb_id & CAN_ERR_RESTARTED:
        parts.append("controller restarted")
    if len(data) >= 8:
        parts.append(f"tx_err={data[6]} rx_err={data[7]}")
    return ", ".join(parts) or f"error frame id=0x{arb_id:03x}"


@dataclass
class BusHealth:
    error_frames: int = 0
    ack_errors: int = 0
    last_error: Optional[str] = None
