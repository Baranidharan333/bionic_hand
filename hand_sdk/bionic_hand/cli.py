"""Command line reader:  python3 -m bionic_hand <command> [options]

Commands:
  diag      check CAN link state and whether the hand answers
  angles    print current finger positions once
  status    print voltage / temperature / current for each finger
  limits    print servo min / max / correction for each finger
  version   print firmware version bytes
  monitor   stream angles (and optionally status) live, optionally to CSV
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time

from . import protocol as p
from .hand import BionicHand, HandError
from .linkinfo import format_link_info, link_info


def _link_info(channel: str) -> str:
    return format_link_info(link_info(channel))


def cmd_diag(hand: BionicHand, args) -> int:
    print(f"Link {args.channel}:")
    print(_link_info(args.channel))
    print(f"\nQuerying hand at CAN ID 0x{args.id:02X} ...")
    ok = hand.ping()
    time.sleep(0.2)
    h = hand.health
    print(f"  error frames seen: {h.error_frames} (no-ACK: {h.ack_errors})")
    if ok:
        print("  hand responded OK")
        return 0
    print("  NO RESPONSE")
    print("  " + hand.diagnose())
    if h.ack_errors:
        print(
            "\n  To clear a stuck controller after fixing wiring/power:\n"
            f"    ./can_up.sh {args.channel}"
        )
    return 1


def cmd_scan(hand: BionicHand, args) -> int:
    """Listen passively, then probe CAN IDs with the read-only angle query."""
    print(f"Link {args.channel}:")
    print(_link_info(args.channel))
    seen = {}
    hand.add_listener(lambda m: seen.setdefault(m.arbitration_id, bytes(m.data)))
    print(f"\n1) Listening passively for {args.listen:.1f}s ...")
    err0 = hand.health.error_frames
    time.sleep(args.listen)
    print(f"   data frames from IDs: {[hex(i) for i in sorted(seen)] or 'none'}"
          f" | error frames: {hand.health.error_frames - err0}")

    lo, hi = args.range
    print(f"2) Probing IDs 0x{lo:02X}..0x{hi:02X} with A1 01 (query angles) ...")
    found = []
    saved_id = hand.device_id
    for cid in range(lo, hi + 1):
        hand.device_id = cid
        try:
            a = hand.query_angles()
            found.append(cid)
            rid = hand.reply_ids.get(cid, cid)
            print(f"   FOUND hand: command ID 0x{cid:02X}, feedback ID 0x{rid:03X}, angles {a.as_list()}")
        except HandError as exc:
            if "send failed" in str(exc):
                print(f"   send failed at 0x{cid:02X}, TX is blocked - stopping probe")
                break
    hand.device_id = saved_id
    print(f"\nResult: {len(found)} hand(s) detected" + (f" at {[hex(i) for i in found]}" if found else ""))
    if not found:
        print("  " + hand.diagnose())
    return 0 if found else 1


def cmd_angles(hand: BionicHand, args) -> int:
    a = hand.query_angles()
    if args.json:
        print(json.dumps({"degrees": a.by_name(), "percent": {p.FINGERS[k]: v for k, v in a.percent.items()}}))
        return 0
    for fid, deg in a.raw.items():
        print(f"  {fid} {p.FINGERS[fid]:<11} {deg:3d}°  ({a.percent[fid]:5.1f}%)")
    return 0


def cmd_status(hand: BionicHand, args) -> int:
    rows = hand.read_all_status()
    if args.json:
        print(json.dumps({p.FINGERS[k]: {"voltage_v": s.voltage_v, "temperature_c": s.temperature_c,
                                         "position_steps": s.position_steps} for k, s in rows.items()}))
        return 0
    print(f"  {'finger':<13}{'volt':>7}{'temp':>7}{'pos(steps)':>12}   raw")
    for fid, s in rows.items():
        print(f"  {fid} {p.FINGERS[fid]:<11}{s.voltage_v:6.1f}V{s.temperature_c:5d}C{s.position_steps:12d}"
              f"   {s.raw_bytes.hex(' ')}")
    return 0


def cmd_limits(hand: BionicHand, args) -> int:
    rows = hand.read_all_limits()
    print(f"  {'finger':<13}{'min':>6}{'max':>6}{'corr':>6}   raw")
    for fid, l in rows.items():
        print(f"  {fid} {p.FINGERS[fid]:<11}{l.servo_min:6d}{l.servo_max:6d}{l.correction:6d}"
              f"   {l.raw_bytes.hex(' ')}")
    return 0


def cmd_version(hand: BionicHand, args) -> int:
    print("  version:", hand.query_version())
    return 0


def cmd_monitor(hand: BionicHand, args) -> int:
    names = [p.FINGERS[i] for i in range(1, 7)]
    header = ["time"] + names
    if args.status:
        for n in names:
            header += [f"{n}_V", f"{n}_C", f"{n}_steps"]
    writer = None
    fh = None
    if args.csv:
        fh = open(args.csv, "w", newline="")
        writer = csv.writer(fh)
        writer.writerow(header)
    print("  ".join(f"{n[:6]:>6}" for n in names) + "   (Ctrl+C to stop)")
    count = 0
    try:
        for snap in hand.stream(rate_hz=args.rate, with_status=args.status):
            if snap.angles is None:
                print("  ! " + "; ".join(snap.errors))
                continue
            vals = snap.angles.as_list()
            line = "  ".join(f"{v:6d}" for v in vals)
            row = [f"{snap.timestamp:.3f}"] + vals
            if args.status:
                temps = []
                for fid in range(1, 7):
                    s = snap.status.get(fid)
                    row += [s.voltage_v, s.temperature_c, s.position_steps] if s else ["", "", ""]
                    temps.append(f"{s.temperature_c}C" if s else "?")
                line += "   T:" + ",".join(temps)
            print(line)
            if writer:
                writer.writerow(row)
            count += 1
            if args.count and count >= args.count:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if fh:
            fh.close()
            print(f"  saved {count} rows to {args.csv}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bionic_hand", description="Read data from the Bionic Hand over CAN.")
    ap.add_argument("--channel", default="can0")
    ap.add_argument("--interface", default="socketcan")
    ap.add_argument("--id", type=lambda s: int(s, 0), default=0x01, help="hand CAN ID (default 0x01)")
    ap.add_argument("--timeout", type=float, default=0.3)
    ap.add_argument("--byteorder", choices=["little", "big"], default="little",
                    help="byte order of 2-byte fields in status/limits replies")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diag")
    sc = sub.add_parser("scan", help="detect hands on the bus")
    sc.add_argument("--listen", type=float, default=2.0, help="seconds of passive listening")
    sc.add_argument("--range", nargs=2, type=lambda s: int(s, 0), default=[0x01, 0x7F],
                    metavar=("LO", "HI"), help="CAN ID range to probe (default 0x01 0x7F)")
    for name in ("angles", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--json", action="store_true")
    sub.add_parser("limits")
    sub.add_parser("version")
    m = sub.add_parser("monitor")
    m.add_argument("--rate", type=float, default=10.0, help="samples per second")
    m.add_argument("--status", action="store_true", help="also read voltage/temp/current each sample")
    m.add_argument("--csv", help="write samples to this CSV file")
    m.add_argument("--count", type=int, default=0, help="stop after N samples (0 = forever)")
    args = ap.parse_args(argv)

    handlers = {"diag": cmd_diag, "scan": cmd_scan,"angles": cmd_angles, "status": cmd_status, "limits": cmd_limits,
                "version": cmd_version, "monitor": cmd_monitor}
    try:
        hand = BionicHand(args.channel, interface=args.interface, device_id=args.id,
                          timeout=args.timeout, byteorder=args.byteorder)
    except Exception as exc:
        print(f"Cannot open {args.interface}:{args.channel}: {exc}", file=sys.stderr)
        return 2
    try:
        return handlers[args.cmd](hand, args)
    except HandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        hand.close()
