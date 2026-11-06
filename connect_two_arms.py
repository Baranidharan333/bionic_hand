#!/usr/bin/env python3
"""
Connect to two bionic hands over CAN and run a quick connectivity check.

Default mapping:
  - Left arm:  CANalyst-II channel 0, arbitration id 0x01
  - Right arm: CANalyst-II channel 1, arbitration id 0x01
"""

from __future__ import annotations

import argparse
from typing import Optional

from can_hand_control import HandCanClient, parse_int


def _new_client(
    interface: str,
    channel: str,
    arbitration_id: int,
    bitrate: Optional[int],
    timeout: float,
) -> HandCanClient:
    return HandCanClient(
        channel=channel,
        arbitration_id=arbitration_id,
        bitrate=bitrate,
        interface=interface,
        timeout=timeout,
    )


def _connect_and_check(label: str, client: HandCanClient, power_on: bool, read_angles: bool) -> None:
    if power_on:
        client.power(True)
        print(f"[{label}] power on command sent")

    version = client.query_version()
    print(f"[{label}] version response: {' '.join(f'{b:02X}' for b in version)}")

    if read_angles:
        angles = client.query_angles()
        print(f"[{label}] angles: {angles}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Connect to two bionic hand arms and verify communication.")
    p.add_argument("--interface", default="canalystii", help="CAN interface name (default: canalystii)")
    p.add_argument("--bitrate", type=int, default=1_000_000, help="Bitrate in bps (default: 1000000)")
    p.add_argument("--timeout", type=float, default=0.6, help="Read timeout in seconds (default: 0.6)")

    p.add_argument("--left-channel", default="0", help="Left arm CAN channel (default: 0)")
    p.add_argument("--right-channel", default="1", help="Right arm CAN channel (default: 1)")
    p.add_argument("--left-arb-id", type=parse_int, default=0x01, help="Left arm arbitration id (default: 0x01)")
    p.add_argument("--right-arb-id", type=parse_int, default=0x01, help="Right arm arbitration id (default: 0x01)")

    p.add_argument("--power-on", action="store_true", help="Send power-on command after connect")
    p.add_argument("--skip-angles", action="store_true", help="Skip angle query")
    return p


def main() -> None:
    args = build_parser().parse_args()
    left: Optional[HandCanClient] = None
    right: Optional[HandCanClient] = None

    try:
        try:
            left = _new_client(
                interface=args.interface,
                channel=args.left_channel,
                arbitration_id=args.left_arb_id,
                bitrate=args.bitrate,
                timeout=args.timeout,
            )
            print(
                f"Connected LEFT  interface={args.interface} channel={args.left_channel} "
                f"arb_id={hex(args.left_arb_id)}"
            )

            right = _new_client(
                interface=args.interface,
                channel=args.right_channel,
                arbitration_id=args.right_arb_id,
                bitrate=args.bitrate,
                timeout=args.timeout,
            )
            print(
                f"Connected RIGHT interface={args.interface} channel={args.right_channel} "
                f"arb_id={hex(args.right_arb_id)}"
            )

            _connect_and_check("LEFT", left, args.power_on, not args.skip_angles)
            _connect_and_check("RIGHT", right, args.power_on, not args.skip_angles)
            print("Both arms connected and checked successfully.")
        except Exception as exc:
            raise SystemExit(f"Dual-arm connect failed: {exc}") from exc
    finally:
        if left is not None:
            try:
                left.close()
            except Exception:
                pass
        if right is not None:
            try:
                right.close()
            except Exception:
                pass
        print("CAN buses closed.")


if __name__ == "__main__":
    main()
