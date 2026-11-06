#!/usr/bin/env python3
"""
Tkinter GUI for controlling the Intelligent Bionic Robotic Hand over CAN.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, Optional

from can_hand_control import ACTION_MODES, HandCanClient

FINGER_LAYOUT = [
    (1, "Little"),
    (2, "Ring"),
    (3, "Middle"),
    (4, "Index"),
    (5, "Thumb"),
    (6, "Thumb MCP"),
]

ACTION_ORDER = ["open", "fist", "index", "middle", "ring", "little", "ok"]


def parse_int(value: str) -> int:
    return int(value, 0)


class HandGuiApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Bionic Hand CAN Control")
        self.root.geometry("900x560")

        self.client: Optional[HandCanClient] = None

        self.interface_var = tk.StringVar(value="canalystii")
        self.channel_var = tk.StringVar(value="0")
        self.bitrate_var = tk.StringVar(value="1000000")
        self.arb_id_var = tk.StringVar(value="0x01")
        self.timeout_var = tk.StringVar(value="0.5")
        self.status_var = tk.StringVar(value="Disconnected")
        self.action_var = tk.StringVar(value="open")

        self.finger_vars: Dict[int, tk.IntVar] = {}

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="both", expand=True)

        self._build_connection_frame(top)
        self._build_command_frame(top)
        self._build_finger_frame(top)
        self._build_status_frame(top)

    def _build_connection_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Connection", padding=10)
        frame.pack(fill="x")

        ttk.Label(frame, text="Interface").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.interface_var, width=14).grid(row=0, column=1, padx=6, sticky="w")

        ttk.Label(frame, text="Channel").grid(row=0, column=2, sticky="w")
        ttk.Entry(frame, textvariable=self.channel_var, width=10).grid(row=0, column=3, padx=6, sticky="w")

        ttk.Label(frame, text="Bitrate").grid(row=0, column=4, sticky="w")
        ttk.Entry(frame, textvariable=self.bitrate_var, width=12).grid(row=0, column=5, padx=6, sticky="w")

        ttk.Label(frame, text="Arb ID").grid(row=0, column=6, sticky="w")
        ttk.Entry(frame, textvariable=self.arb_id_var, width=10).grid(row=0, column=7, padx=6, sticky="w")

        ttk.Label(frame, text="Timeout(s)").grid(row=0, column=8, sticky="w")
        ttk.Entry(frame, textvariable=self.timeout_var, width=10).grid(row=0, column=9, padx=6, sticky="w")

        self.connect_btn = ttk.Button(frame, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=10, padx=6)

        self.disconnect_btn = ttk.Button(frame, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_btn.grid(row=0, column=11, padx=6)

    def _build_command_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Commands", padding=10)
        frame.pack(fill="x", pady=(10, 0))

        ttk.Button(frame, text="Power ON", command=lambda: self._run(self._cmd_power, True)).pack(side="left", padx=4)
        ttk.Button(frame, text="Power OFF", command=lambda: self._run(self._cmd_power, False)).pack(side="left", padx=4)

        ttk.Separator(frame, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(frame, text="Action").pack(side="left")
        action_box = ttk.Combobox(frame, textvariable=self.action_var, values=ACTION_ORDER, state="readonly", width=10)
        action_box.pack(side="left", padx=6)
        ttk.Button(frame, text="Run Action", command=lambda: self._run(self._cmd_action)).pack(side="left", padx=4)

        ttk.Separator(frame, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(frame, text="Read Angles", command=lambda: self._run(self._cmd_read_angles)).pack(side="left", padx=4)
        ttk.Button(frame, text="Send All", command=lambda: self._run(self._cmd_send_all)).pack(side="left", padx=4)

    def _build_finger_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Finger Position (Raw 0..255)", padding=10)
        frame.pack(fill="both", expand=True, pady=(10, 0))

        for row, (finger_id, label) in enumerate(FINGER_LAYOUT):
            value_var = tk.IntVar(value=0)
            self.finger_vars[finger_id] = value_var

            ttk.Label(frame, text=f"ID{finger_id} {label}", width=12).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)

            scale = tk.Scale(
                frame,
                from_=0,
                to=255,
                orient="horizontal",
                variable=value_var,
                resolution=1,
                showvalue=False,
                length=520,
            )
            scale.grid(row=row, column=1, sticky="ew", pady=6)

            value_label = ttk.Label(frame, textvariable=value_var, width=4)
            value_label.grid(row=row, column=2, padx=8)

            btn = ttk.Button(frame, text="Send", command=lambda fid=finger_id: self._run(self._cmd_send_finger, fid))
            btn.grid(row=row, column=3, padx=(4, 0), pady=6)

        frame.columnconfigure(1, weight=1)

    def _build_status_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=(0, 10, 0, 0))
        frame.pack(fill="x")
        ttk.Label(frame, text="Status:").pack(side="left")
        ttk.Label(frame, textvariable=self.status_var).pack(side="left", padx=8)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _require_client(self) -> HandCanClient:
        if self.client is None:
            raise RuntimeError("Not connected. Click Connect first.")
        return self.client

    def connect(self) -> None:
        if self.client is not None:
            self._set_status("Already connected")
            return
        try:
            interface = self.interface_var.get().strip()
            channel = self.channel_var.get().strip()
            bitrate_text = self.bitrate_var.get().strip()
            bitrate = int(bitrate_text) if bitrate_text else None
            arbitration_id = parse_int(self.arb_id_var.get().strip())
            timeout = float(self.timeout_var.get().strip())

            self.client = HandCanClient(
                channel=channel,
                arbitration_id=arbitration_id,
                bitrate=bitrate,
                interface=interface,
                timeout=timeout,
            )
        except Exception as exc:
            self.client = None
            messagebox.showerror("Connect Failed", str(exc))
            self._set_status("Connect failed")
            return

        self.connect_btn.configure(state="disabled")
        self.disconnect_btn.configure(state="normal")
        self._set_status(f"Connected: {interface} / {channel}")

    def disconnect(self) -> None:
        if self.client is None:
            return
        try:
            self.client.close()
        except Exception:
            pass
        self.client = None
        self.connect_btn.configure(state="normal")
        self.disconnect_btn.configure(state="disabled")
        self._set_status("Disconnected")

    def _cmd_power(self, on: bool) -> None:
        self._require_client().power(on)
        self._set_status(f"Power {'ON' if on else 'OFF'} sent")

    def _cmd_action(self) -> None:
        mode = self.action_var.get().strip().lower()
        code = ACTION_MODES[mode]
        self._require_client().action(code)
        self._set_status(f"Action '{mode}' sent")

    def _cmd_send_finger(self, finger_id: int) -> None:
        value = self.finger_vars[finger_id].get()
        self._require_client().set_single_position(finger_id, value)
        self._set_status(f"ID{finger_id} -> {value}")

    def _cmd_send_all(self) -> None:
        values = [self.finger_vars[fid].get() for fid, _ in FINGER_LAYOUT]
        self._require_client().set_all_positions(values)
        self._set_status(f"Pose sent: {values}")

    def _cmd_read_angles(self) -> None:
        angles = self._require_client().query_angles()
        for finger_id, _ in FINGER_LAYOUT:
            self.finger_vars[finger_id].set(angles[finger_id])
        self._set_status("Angles refreshed")

    def _run(self, func, *args) -> None:
        try:
            func(*args)
        except Exception as exc:
            messagebox.showerror("Command Failed", str(exc))
            self._set_status("Command failed")

    def _on_close(self) -> None:
        self.disconnect()
        self.root.destroy()


def main() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(
            "Tkinter GUI requires a display. Set DISPLAY correctly or run on a desktop session."
        ) from exc
    app = HandGuiApp(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
