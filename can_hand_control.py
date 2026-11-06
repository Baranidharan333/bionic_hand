#!/usr/bin/env python3
"""
Control script for the Intelligent Bionic Robotic Hand over CAN.

Manual reference: "Robot Hand User Manual-En.pdf", section 3.3 (CAN protocol).
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from textwrap import dedent
from typing import Dict, Iterable, List, Optional, Sequence

try:
    import can  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'python-can'. Install it with: pip install python-can"
    ) from exc

if not hasattr(can, "rc"):  # pragma: no cover
    raise SystemExit(
        "Detected incompatible 'can' package at "
        f"{getattr(can, '__file__', '<unknown>')}. "
        "Uninstall 'can' and install 'python-can' (pip uninstall can; pip install python-can)."
    )

try:
    CANBus = can.Bus
except AttributeError:  # pragma: no cover
    from can.interface import Bus as CANBus  # type: ignore

try:
    CANMessage = can.Message
except AttributeError:  # pragma: no cover
    from can.message import Message as CANMessage  # type: ignore


FINGER_IDS: Dict[str, int] = {
    "little": 1,
    "ring": 2,
    "middle": 3,
    "index": 4,
    "thumb": 5,
    "thumb_metacarpal": 6,
}

ACTION_MODES: Dict[str, int] = {
    "open": 0x01,
    "fist": 0x02,
    "index": 0x03,
    "middle": 0x04,
    "ring": 0x05,
    "little": 0x06,
    "ok": 0x07,
}


def u8(value: int, field: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{field} must be in [0, 255], got {value}")
    return value


def u16_to_bytes(value: int, field: str) -> List[int]:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{field} must be in [0, 65535], got {value}")
    return [(value >> 8) & 0xFF, value & 0xFF]


def parse_int(text: str) -> int:
    return int(text, 0)


def parse_finger(value: str) -> int:
    low = value.strip().lower()
    if low in FINGER_IDS:
        return FINGER_IDS[low]
    parsed = parse_int(value)
    if 1 <= parsed <= 6:
        return parsed
    raise argparse.ArgumentTypeError(
        "finger must be one of: little|ring|middle|index|thumb|thumb_metacarpal or 1..6"
    )


@dataclass
class HandCanClient:
    channel: str
    arbitration_id: int
    bitrate: Optional[int]
    interface: str
    timeout: float

    def __post_init__(self) -> None:
        try:
            if self.interface == "socketcan":
                self.bus = CANBus(channel=self.channel, interface=self.interface)
            elif self.interface == "canalystii":
                self.bus = self._open_canalystii_bus()
            else:
                kwargs = {"channel": self.channel, "interface": self.interface}
                if self.bitrate is not None:
                    kwargs["bitrate"] = self.bitrate
                self.bus = CANBus(**kwargs)
        except OSError as exc:
            if self.interface == "socketcan" and exc.errno == 19:
                raise RuntimeError(socketcan_missing_device_help(self.channel)) from exc
            raise RuntimeError(
                f"Failed to open CAN bus (interface={self.interface}, channel={self.channel}): {exc}"
            ) from exc
        except TypeError as exc:
            raise RuntimeError(
                f"Failed to open CAN bus (interface={self.interface}, channel={self.channel}): {exc}"
            ) from exc

    def _open_canalystii_bus(self):
        # python-can changed CANalyst-II arg name from `baud` (old) to `bitrate` (new).
        # Support both to work across distro/system versions.
        ch: object = self.channel
        if isinstance(ch, str):
            raw = ch.strip()
            if raw.isdigit():
                ch = int(raw)
            else:
                ch = raw

        kwargs = {"channel": ch, "interface": "canalystii"}
        if self.bitrate is not None:
            kwargs["bitrate"] = self.bitrate
        try:
            return CANBus(**kwargs)
        except TypeError as exc:
            if self.bitrate is not None and "bitrate" in str(exc):
                kwargs.pop("bitrate", None)
                kwargs["baud"] = self.bitrate
                try:
                    return CANBus(**kwargs)
                except AttributeError as inner_exc:
                    if "VCI_OpenDevice" in str(inner_exc):
                        raise RuntimeError(canalystii_driver_missing_help()) from inner_exc
                    raise
            raise
        except AttributeError as exc:
            if "VCI_OpenDevice" in str(exc):
                raise RuntimeError(canalystii_driver_missing_help()) from exc
            raise
        except Exception as exc:
            msg = str(exc).lower()
            if (
                "access denied" in msg
                or "insufficient permissions" in msg
                or "permission denied" in msg
            ):
                raise RuntimeError(canalystii_permission_help()) from exc
            raise

    def close(self) -> None:
        self.bus.shutdown()

    def _send(self, data: Sequence[int]) -> None:
        msg = CANMessage(
            arbitration_id=self.arbitration_id,
            is_extended_id=False,
            data=list(data),
        )
        self.bus.send(msg)

    def _send_recv(self, data: Sequence[int], timeout: Optional[float] = None) -> can.Message:
        self._send(data)
        t = self.timeout if timeout is None else timeout
        while True:
            msg = self.bus.recv(timeout=t)
            if msg is None:
                raise TimeoutError("Timed out waiting for CAN response")
            if msg.is_extended_id:
                continue
            if msg.arbitration_id == self.arbitration_id:
                return msg

    def query_angles(self) -> Dict[int, int]:
        msg = self._send_recv([0xA1, 0x01])
        data = list(msg.data)
        if len(data) < 8 or data[0] != 0xA1 or data[1] != 0x01:
            raise RuntimeError(f"Unexpected response: {[hex(b) for b in data]}")
        return {i + 1: data[i + 2] for i in range(6)}

    def query_version(self) -> List[int]:
        msg = self._send_recv([0xA1, 0x02])
        return list(msg.data)

    def save_flash(self) -> None:
        self._send([0xA1, 0x0E])

    def action(self, mode: int) -> None:
        self._send([0x03, u8(mode, "mode")])

    def power(self, on: bool) -> None:
        self._send([0x03, 0x11 if on else 0x00])

    def modify_can_id(self, new_id: int) -> None:
        self._send([0x2E, u8(new_id, "new_id")])

    def set_single_position(self, finger_id: int, angle: int) -> None:
        self._send([0x04, u8(finger_id, "finger_id"), u8(angle, "angle"), 0x00])

    def set_single_acceleration(self, finger_id: int, acceleration: int) -> None:
        self._send([0x08, u8(finger_id, "finger_id"), u8(acceleration, "acceleration"), 0x00])

    def set_single_speed(self, finger_id: int, speed: int) -> None:
        self._send([0x09, u8(finger_id, "finger_id"), u8(speed, "speed"), 0x00])

    def set_single_torque(self, finger_id: int, torque: int) -> None:
        self._send([0x10, u8(finger_id, "finger_id"), u8(torque, "torque"), 0x00])

    def set_global_speed(self, speed: int) -> None:
        self._send([0x05, 0x00, u8(speed, "speed"), 0x00])

    def set_global_torque(self, torque: int) -> None:
        self._send([0x06, 0x00, u8(torque, "torque"), 0x00])

    def set_global_acceleration(self, acceleration: int) -> None:
        self._send([0x07, 0x00, u8(acceleration, "acceleration"), 0x00])

    def set_baud_setting(self, baud_value: int) -> None:
        self._send([0x3F, 0x00, u8(baud_value, "baud_value"), 0x00])

    def set_all_positions(self, angles: Iterable[int]) -> None:
        vals = [u8(v, "angle") for v in angles]
        if len(vals) != 6:
            raise ValueError("Exactly 6 angles are required")
        self._send([0xA3, *vals, 0x00])

    def read_limits(self, finger_id: int) -> Dict[str, int]:
        msg = self._send_recv([0xD1, u8(finger_id, "finger_id"), 0, 0, 0, 0, 0, 0])
        data = list(msg.data)
        if len(data) < 8 or data[0] != 0xD1:
            raise RuntimeError(f"Unexpected response: {[hex(b) for b in data]}")
        return {
            "finger_id": data[1],
            "servo_min": (data[2] << 8) | data[3],
            "servo_max": (data[4] << 8) | data[5],
            "servo_correction": (data[6] << 8) | data[7],
        }

    def write_limits(self, finger_id: int, servo_min: int, servo_max: int, servo_corr: int) -> None:
        mn = u16_to_bytes(servo_min, "servo_min")
        mx = u16_to_bytes(servo_max, "servo_max")
        cr = u16_to_bytes(servo_corr, "servo_corr")
        self._send([0xD2, u8(finger_id, "finger_id"), mn[0], mn[1], mx[0], mx[1], cr[0], cr[1]])

    def read_status(self, finger_id: int) -> Dict[str, int]:
        msg = self._send_recv([0xD3, u8(finger_id, "finger_id"), 0, 0, 0, 0, 0, 0])
        data = list(msg.data)
        if len(data) < 8 or data[0] != 0xD3:
            raise RuntimeError(f"Unexpected response: {[hex(b) for b in data]}")
        return {
            "finger_id": data[1],
            "voltage_raw": data[2],
            "temperature_c": data[3],
            "current_servo_value": (data[4] << 8) | data[5],
        }


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--channel", default="can0", help="CAN channel/device, e.g. can0 or COM3")
    parser.add_argument(
        "--interface",
        default="socketcan",
        help="python-can bus type, e.g. socketcan, slcan, pcan, kvaser",
    )
    parser.add_argument(
        "--arb-id",
        type=parse_int,
        default=0x01,
        help="CAN arbitration ID of the hand (default: 0x01)",
    )
    parser.add_argument(
        "--bitrate",
        type=int,
        default=None,
        help="Bus bitrate for interfaces that require it (manual says 1000000)",
    )
    parser.add_argument("--timeout", type=float, default=0.5, help="Receive timeout in seconds")


def socketcan_missing_device_help(channel: str) -> str:
    user_hint = "" if os.geteuid() == 0 else "Prefix setup commands with sudo.\n"
    return dedent(
        f"""\
        CAN interface '{channel}' does not exist.
        {user_hint}For SocketCAN at 1 Mbps (manual default), create/bring up the device:
          ip link set {channel} down 2>/dev/null || true
          ip link set {channel} type can bitrate 1000000
          ip link set {channel} up
          ip -details link show {channel}

        If you use a USB-CAN adapter:
          1) It may expose a SocketCAN device (still use --interface socketcan --channel can0).
          2) If it exposes a serial tty, use slcan first, then create can0:
             slcand -o -c -s8 /dev/ttyUSB0 can0
             ip link set can0 up
             python3 can_hand_control.py --interface socketcan --channel can0 query-angles

        Quick check:
          ip link show
        """
    )


def canalystii_driver_missing_help() -> str:
    return dedent(
        """\
        CANalyst-II backend is present, but native driver library is missing.
        The installed distro backend expects `libcontrolcan.so` (Linux) or `ControlCAN.dll` (Windows).

        Recommended fix:
          python3 -m pip install --upgrade "python-can[canalystii]"
          python3 -c "import can; print(can.__version__, can.__file__)"

        Alternative fix for old distro backend:
          - Get `libcontrolcan.so` from the adapter vendor SDK.
          - Place it in current directory (same folder as this script), or install it under
            /usr/local/lib and run: sudo ldconfig

        Retry command:
          python3 can_hand_control.py --interface canalystii --channel 0 --bitrate 1000000 query-angles
        """
    )


def canalystii_permission_help() -> str:
    return dedent(
        """\
        USB access denied for CANalyst-II (insufficient permissions).

        Quick test:
          sudo python3 can_hand_control.py --interface canalystii --channel 0 --bitrate 1000000 query-angles

        Permanent fix (udev rule):
          sudo tee /etc/udev/rules.d/99-canalystii.rules >/dev/null <<'EOF'
          SUBSYSTEM=="usb", ATTR{idVendor}=="04d8", ATTR{idProduct}=="0053", MODE="0666", GROUP="plugdev"
          EOF
          sudo udevadm control --reload-rules
          sudo udevadm trigger
          # unplug and replug the adapter

        Verify:
          lsusb -d 04d8:0053
        """
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Intelligent Bionic Hand over CAN")
    add_common_args(parser)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("query-angles")
    sub.add_parser("query-version")
    sub.add_parser("save-flash")

    p_power = sub.add_parser("power")
    p_power.add_argument("state", choices=["on", "off"])

    p_action = sub.add_parser("action")
    p_action.add_argument("mode", choices=sorted(ACTION_MODES.keys()))

    p_id = sub.add_parser("set-can-id")
    p_id.add_argument("new_id", type=parse_int)

    p_sfp = sub.add_parser("set-finger-pos")
    p_sfp.add_argument("finger", type=parse_finger)
    p_sfp.add_argument("value", type=parse_int, help="Raw position byte [0..255]")

    p_sfs = sub.add_parser("set-finger-speed")
    p_sfs.add_argument("finger", type=parse_finger)
    p_sfs.add_argument("value", type=parse_int)

    p_sfa = sub.add_parser("set-finger-accel")
    p_sfa.add_argument("finger", type=parse_finger)
    p_sfa.add_argument("value", type=parse_int)

    p_sft = sub.add_parser("set-finger-torque")
    p_sft.add_argument("finger", type=parse_finger)
    p_sft.add_argument("value", type=parse_int)

    p_gs = sub.add_parser("set-speed")
    p_gs.add_argument("value", type=parse_int)
    p_gt = sub.add_parser("set-torque")
    p_gt.add_argument("value", type=parse_int)
    p_ga = sub.add_parser("set-accel")
    p_ga.add_argument("value", type=parse_int)

    p_baud = sub.add_parser("set-baud-param")
    p_baud.add_argument("value", type=parse_int, help="Raw baud parameter byte")

    p_pose = sub.add_parser("set-pose")
    p_pose.add_argument(
        "angles",
        type=parse_int,
        nargs=6,
        metavar=("ID1", "ID2", "ID3", "ID4", "ID5", "ID6"),
    )

    p_rl = sub.add_parser("read-limits")
    p_rl.add_argument("finger", type=parse_finger)

    p_wl = sub.add_parser("write-limits")
    p_wl.add_argument("finger", type=parse_finger)
    p_wl.add_argument("servo_min", type=parse_int)
    p_wl.add_argument("servo_max", type=parse_int)
    p_wl.add_argument("servo_corr", type=parse_int)

    p_rs = sub.add_parser("read-status")
    p_rs.add_argument("finger", type=parse_finger)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        client = HandCanClient(
            channel=args.channel,
            arbitration_id=args.arb_id,
            bitrate=args.bitrate,
            interface=args.interface,
            timeout=args.timeout,
        )
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        if args.cmd == "query-angles":
            angles = client.query_angles()
            for finger_id in range(1, 7):
                print(f"ID{finger_id}: {angles[finger_id]}")
        elif args.cmd == "query-version":
            raw = client.query_version()
            print("Version response bytes:", " ".join(f"0x{b:02X}" for b in raw))
        elif args.cmd == "save-flash":
            client.save_flash()
            print("Flash save command sent.")
        elif args.cmd == "power":
            client.power(args.state == "on")
            print(f"Power {args.state} command sent.")
        elif args.cmd == "action":
            client.action(ACTION_MODES[args.mode])
            print(f"Action '{args.mode}' command sent.")
        elif args.cmd == "set-can-id":
            client.modify_can_id(args.new_id)
            print(f"Set CAN ID command sent: {args.new_id:#x}")
        elif args.cmd == "set-finger-pos":
            client.set_single_position(args.finger, args.value)
            print(f"Finger {args.finger} position command sent: {args.value}")
        elif args.cmd == "set-finger-speed":
            client.set_single_speed(args.finger, args.value)
            print(f"Finger {args.finger} speed command sent: {args.value}")
        elif args.cmd == "set-finger-accel":
            client.set_single_acceleration(args.finger, args.value)
            print(f"Finger {args.finger} acceleration command sent: {args.value}")
        elif args.cmd == "set-finger-torque":
            client.set_single_torque(args.finger, args.value)
            print(f"Finger {args.finger} torque command sent: {args.value}")
        elif args.cmd == "set-speed":
            client.set_global_speed(args.value)
            print(f"Global speed command sent: {args.value}")
        elif args.cmd == "set-torque":
            client.set_global_torque(args.value)
            print(f"Global torque command sent: {args.value}")
        elif args.cmd == "set-accel":
            client.set_global_acceleration(args.value)
            print(f"Global acceleration command sent: {args.value}")
        elif args.cmd == "set-baud-param":
            client.set_baud_setting(args.value)
            print(f"Baud parameter command sent: {args.value}")
        elif args.cmd == "set-pose":
            client.set_all_positions(args.angles)
            print("Pose command sent:", list(args.angles))
        elif args.cmd == "read-limits":
            out = client.read_limits(args.finger)
            print(out)
        elif args.cmd == "write-limits":
            client.write_limits(args.finger, args.servo_min, args.servo_max, args.servo_corr)
            print("Write limits command sent.")
        elif args.cmd == "read-status":
            out = client.read_status(args.finger)
            print(out)
        else:  # pragma: no cover
            parser.error(f"Unknown command: {args.cmd}")
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
