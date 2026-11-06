"""Flask web app: scan the CAN bus for Bionic Hands, label them Left/Right, read and control them.

Run (from hand_sdk/):
    python3 webapp/app.py                 # real hardware on can0
    python3 webapp/app.py --sim           # two simulated hands (IDs 0x01, 0x02), no hardware
    python3 webapp/app.py --read-only     # monitoring only: control endpoints refuse to move hands
    python3 webapp/app.py --channel can1 --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from typing import Dict, Optional

from flask import Flask, jsonify, render_template, request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import can  # noqa: E402

from bionic_hand import BionicHand, HandError  # noqa: E402
from bionic_hand import protocol as p  # noqa: E402
from bionic_hand.linkinfo import link_info  # noqa: E402
from bionic_hand.sim import SimulatedHands  # noqa: E402

LABELS_FILE = os.path.join(HERE, "hands.json")


class HandService:
    """Owns the single CAN connection shared by all web requests."""

    def __init__(self, channel: str, interface: str, sim: bool, timeout: float, read_only: bool = False):
        self.read_only = read_only
        self.channel = channel
        self.interface = interface
        self.sim = sim
        self.timeout = timeout
        self.hand: Optional[BionicHand] = None
        self.open_error: Optional[str] = None
        self._sim: Optional[SimulatedHands] = None
        self._sim_bus = None
        self._lock = threading.Lock()
        self.labels: Dict[int, str] = self._load_labels()

    # -------------------------------------------------------------- connection

    def open(self, channel: Optional[str] = None, interface: Optional[str] = None) -> None:
        with self._lock:
            self._close_locked()
            if channel:
                self.channel = channel
            if interface:
                self.interface = interface
            try:
                if self.sim:
                    self._sim = SimulatedHands("webapp-sim", ids=(0x01, 0x02), animate=True)
                    self._sim.start()
                    self._sim_bus = can.Bus(interface="virtual", channel="webapp-sim")
                    self.hand = BionicHand(bus=self._sim_bus, timeout=self.timeout)
                else:
                    self.hand = BionicHand(self.channel, interface=self.interface, timeout=self.timeout)
                self.open_error = None
            except Exception as exc:
                self.hand = None
                self.open_error = f"cannot open {self.interface}:{self.channel}: {exc}"

    def _close_locked(self) -> None:
        if self.hand:
            self.hand.close()
            self.hand = None
        if self._sim_bus:
            self._sim_bus.shutdown()
            self._sim_bus = None
        if self._sim:
            self._sim.close()
            self._sim = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def require(self) -> BionicHand:
        if self.hand is None:
            raise HandError(self.open_error or "not connected")
        return self.hand

    # -------------------------------------------------------------- labels

    def _load_labels(self) -> Dict[int, str]:
        try:
            with open(LABELS_FILE) as fh:
                return {int(k): v for k, v in json.load(fh).items()}
        except (OSError, ValueError):
            return {}

    def set_label(self, cid: int, label: str) -> None:
        if label:
            # one ID per label: assigning "Left" to a hand removes it from any other hand
            for k in [k for k, v in self.labels.items() if v == label and k != cid]:
                del self.labels[k]
            self.labels[cid] = label
        else:
            self.labels.pop(cid, None)
        with open(LABELS_FILE, "w") as fh:
            json.dump({str(k): v for k, v in sorted(self.labels.items())}, fh, indent=2)

    # -------------------------------------------------------------- views

    def state(self) -> dict:
        h = self.hand
        health = h.health if h else p.BusHealth()
        return {
            "connected": h is not None,
            "sim": self.sim,
            "read_only": self.read_only,
            "channel": self.channel,
            "interface": self.interface,
            "open_error": self.open_error,
            "link": {"available": False, "error": "simulated bus"} if self.sim else link_info(self.channel),
            "health": {"error_frames": health.error_frames, "ack_errors": health.ack_errors,
                       "last_error": health.last_error},
            "diagnosis": h.diagnose() if h and health.error_frames else None,
            "labels": {str(k): v for k, v in self.labels.items()},
        }


def angles_json(a: p.Angles) -> list:
    return [{"id": fid, "name": p.FINGERS[fid], "raw": a.raw[fid], "percent": a.percent[fid]}
            for fid in sorted(a.raw)]


def create_app(service: HandService) -> Flask:
    app = Flask(__name__)

    @app.errorhandler(HandError)
    def _hand_error(exc):
        return jsonify(error=str(exc)), 503

    @app.errorhandler(ValueError)
    def _value_error(exc):
        return jsonify(error=str(exc)), 400

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def api_state():
        return jsonify(service.state())

    @app.post("/api/connect")
    def api_connect():
        body = request.get_json(silent=True) or {}
        service.open(body.get("channel"), body.get("interface"))
        return jsonify(service.state())

    @app.post("/api/scan")
    def api_scan():
        body = request.get_json(silent=True) or {}
        lo = int(body.get("lo", 1))
        hi = int(body.get("hi", 16))
        if not (0 <= lo <= hi <= 0x7FF):
            raise ValueError("ID range must satisfy 0 <= lo <= hi <= 0x7FF")
        hand = service.require()
        err_before = hand.health.error_frames
        error = None
        found = {}
        try:
            found = hand.scan(lo, hi, timeout=float(body.get("timeout", 0.08)))
        except HandError as exc:  # TX blocked: report what we have plus the reason
            error = str(exc)
        return jsonify(
            range=[lo, hi],
            found=[{"id": cid, "hex": f"0x{cid:02X}", "label": service.labels.get(cid, ""),
                    "reply_id": hand.reply_ids.get(cid), "angles": angles_json(a)}
                   for cid, a in sorted(found.items())],
            error=error,
            new_error_frames=hand.health.error_frames - err_before,
            diagnosis=hand.diagnose() if not found else None,
            state=service.state(),
        )

    @app.post("/api/labels")
    def api_labels():
        body = request.get_json(force=True)
        label = (body.get("label") or "").strip()
        if label not in ("", "Left", "Right"):
            raise ValueError("label must be Left, Right or empty")
        service.set_label(int(body["id"]), label)
        return jsonify(labels={str(k): v for k, v in service.labels.items()})

    @app.get("/api/hand/<int:cid>")
    def api_hand(cid: int):
        hand = service.require()
        snap = hand.snapshot(with_status=request.args.get("status") == "1", device_id=cid)
        return jsonify(
            id=cid,
            reply_id=hand.reply_ids.get(cid),
            online=snap.angles is not None,
            timestamp=snap.timestamp,
            angles=angles_json(snap.angles) if snap.angles else None,
            status=[{"id": fid, "name": p.FINGERS[fid], "voltage_v": s.voltage_v,
                     "temperature_c": s.temperature_c, "position_steps": s.position_steps}
                    for fid, s in sorted(snap.status.items())],
            errors=snap.errors,
        )

    @app.get("/api/hand/<int:cid>/details")
    def api_details(cid: int):
        hand = service.require()
        limits = hand.read_all_limits(device_id=cid)
        try:
            version = hand.query_version(device_id=cid)
        except HandError as exc:
            version = f"unavailable ({exc})"
        return jsonify(
            id=cid,
            version=version,
            limits=[{"id": fid, "name": p.FINGERS[fid], "min": l.servo_min, "max": l.servo_max,
                     "correction": l.correction, "raw": l.raw_bytes.hex(" ")}
                    for fid, l in sorted(limits.items())],
        )

    # ------------------------------------------------------------------ control (moves the hand)

    def control_hand() -> BionicHand:
        if service.read_only:
            raise HandError("control is disabled (server started with --read-only)")
        return service.require()

    @app.post("/api/hand/<int:cid>/gesture")
    def api_gesture(cid: int):
        name = (request.get_json(force=True).get("name") or "").lower()
        control_hand().gesture(name, device_id=cid)
        return jsonify(ok=True, sent=name)

    @app.post("/api/hand/<int:cid>/power")
    def api_power(cid: int):
        on = bool(request.get_json(force=True).get("on"))
        control_hand().power(on, device_id=cid)
        return jsonify(ok=True, power=on)

    @app.post("/api/hand/<int:cid>/finger")
    def api_finger(cid: int):
        body = request.get_json(force=True)
        control_hand().set_finger(body["finger"], int(body["value"]), device_id=cid)
        return jsonify(ok=True)

    @app.post("/api/hand/<int:cid>/pose")
    def api_pose(cid: int):
        values = [int(v) for v in request.get_json(force=True)["values"]]
        control_hand().set_pose(values, device_id=cid)
        return jsonify(ok=True, values=values)

    @app.post("/api/hand/<int:cid>/setting")
    def api_setting(cid: int):
        body = request.get_json(force=True)
        finger = body.get("finger") or None
        control_hand().set_setting(body["kind"], int(body["value"]), finger, device_id=cid)
        return jsonify(ok=True)

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Bionic Hand CAN web app")
    ap.add_argument("--channel", default="can0")
    ap.add_argument("--interface", default="socketcan")
    ap.add_argument("--sim", action="store_true", help="use two simulated hands instead of hardware")
    ap.add_argument("--timeout", type=float, default=0.3, help="per-request reply timeout (s)")
    ap.add_argument("--read-only", action="store_true", help="disable all commands that move the hands")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other machines")
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()

    service = HandService(args.channel, args.interface, args.sim, args.timeout, args.read_only)
    service.open()
    app = create_app(service)
    mode = "SIMULATED hands" if args.sim else f"{args.interface}:{args.channel}"
    print(f"Bionic Hand web app ({mode}) -> http://{args.host}:{args.port}")
    try:
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally:
        service.close()


if __name__ == "__main__":
    main()
