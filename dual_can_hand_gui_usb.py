#!/usr/bin/env python3
"""
Tkinter GUI for controlling left and right CAN hands over USB-CAN adapters.

Default mapping:
  - Left:  CANalyst-II / channel 0 / arb-id 0x01
  - Right: CANalyst-II / channel 1 / arb-id 0x01

Run:
  python3 dual_can_hand_gui_usb.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
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


class HandPanel:
    def __init__(
        self,
        parent: ttk.Frame,
        title: str,
        channel: int,
        arbitration_id: int = 0x01,
        bitrate: int = 1000000,
        timeout: float = 0.5,
    ) -> None:
        self.frame = ttk.LabelFrame(parent, text=title, padding=10)
        self.client: Optional[HandCanClient] = None

        self.interface = "canalystii"
        self.channel = str(channel)
        self.bitrate = int(bitrate)
        self.arbitration_id = int(arbitration_id)
        self.timeout = float(timeout)

        self.action_var = tk.StringVar(value="open")
        self.status_var = tk.StringVar(value="Disconnected")

        self.finger_vars: Dict[int, tk.IntVar] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        conn = ttk.Frame(self.frame)
        conn.pack(fill="x")
        info = (
            f"Fixed transport: CANalyst-II  |  Channel: {self.channel}  |  "
            f"Bitrate: {self.bitrate}  |  Arb ID: {hex(self.arbitration_id)}  |  Timeout: {self.timeout:.1f}s"
        )
        ttk.Label(conn, text=info).pack(anchor="w")

        cmd = ttk.Frame(self.frame)
        cmd.pack(fill="x", pady=(10, 6))

        ttk.Button(cmd, text="Power ON", command=lambda: self._run(self._cmd_power, True)).pack(side="left", padx=3)
        ttk.Button(cmd, text="Power OFF", command=lambda: self._run(self._cmd_power, False)).pack(side="left", padx=3)

        ttk.Separator(cmd, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(cmd, text="Action").pack(side="left")
        action_box = ttk.Combobox(cmd, textvariable=self.action_var, values=ACTION_ORDER, state="readonly", width=10)
        action_box.pack(side="left", padx=4)
        ttk.Button(cmd, text="Run Action", command=lambda: self._run(self._cmd_action)).pack(side="left", padx=3)

        ttk.Separator(cmd, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(cmd, text="Read Angles", command=lambda: self._run(self._cmd_read_angles)).pack(side="left", padx=3)
        ttk.Button(cmd, text="Read Version", command=lambda: self._run(self._cmd_read_version)).pack(side="left", padx=3)
        ttk.Button(cmd, text="Send All", command=lambda: self._run(self._cmd_send_all)).pack(side="left", padx=3)

        fingers = ttk.Frame(self.frame)
        fingers.pack(fill="both", expand=True)

        for row, (finger_id, label) in enumerate(FINGER_LAYOUT):
            value_var = tk.IntVar(value=0)
            self.finger_vars[finger_id] = value_var

            ttk.Label(fingers, text=f"{label}", width=10).grid(row=row, column=0, sticky="w")
            scale = tk.Scale(
                fingers,
                from_=0,
                to=90,
                orient="horizontal",
                variable=value_var,
                resolution=1,
                showvalue=False,
                length=280,
            )
            scale.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
            ttk.Label(fingers, textvariable=value_var, width=4).grid(row=row, column=2)
            ttk.Button(
                fingers,
                text="Send",
                command=lambda fid=finger_id: self._run(self._cmd_send_finger, fid),
            ).grid(row=row, column=3, padx=4)

        fingers.columnconfigure(1, weight=1)
        ttk.Label(self.frame, textvariable=self.status_var).pack(anchor="w", pady=(8, 0))

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _require_client(self) -> HandCanClient:
        if self.client is None:
            raise RuntimeError("Not connected")
        return self.client

    def connect(self) -> None:
        if self.client is not None:
            self._set_status("Already connected")
            return

        self.client = HandCanClient(
            channel=self.channel,
            arbitration_id=self.arbitration_id,
            bitrate=self.bitrate,
            interface=self.interface,
            timeout=self.timeout,
        )
        self._set_status(f"Connected: CANalyst-II/ch{self.channel} id={hex(self.arbitration_id)}")

    def disconnect(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self._set_status("Disconnected")

    def close(self) -> None:
        self.disconnect()

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

    def _cmd_read_version(self) -> None:
        data = self._require_client().query_version()
        hex_text = " ".join(f"{b:02X}" for b in data)
        self._set_status(f"Version raw: {hex_text}")

    def _run(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:
            messagebox.showerror("Command Failed", str(exc))
            self._set_status("Command failed")


class DualUsbCanHandGuiApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Dual CAN Hand Control (CANalyst-II ch0 + ch1)")
        self.root.geometry("1480x760")

        self.left_panel: Optional[HandPanel] = None
        self.right_panel: Optional[HandPanel] = None
        self.status_var = tk.StringVar(value="Idle")
        self.camera_process: Optional[subprocess.Popen] = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Auto mode: Left hand -> CANalyst-II ch0, Right hand -> CANalyst-II ch1",
        ).pack(anchor="w", pady=(0, 8))

        top_controls = ttk.Frame(outer)
        top_controls.pack(fill="x", pady=(0, 8))
        ttk.Button(
            top_controls,
            text="Reconnect Both",
            command=lambda: self._run(self._reconnect_both),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            top_controls,
            text="Disconnect Both",
            command=self._disconnect_both,
        ).pack(side="left", padx=6)
        ttk.Separator(top_controls, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(
            top_controls,
            text="Start Camera Gesture",
            command=lambda: self._run(self._start_camera_gesture),
        ).pack(side="left", padx=6)
        ttk.Button(
            top_controls,
            text="Stop Camera Gesture",
            command=self._stop_camera_gesture,
        ).pack(side="left", padx=6)

        hands = ttk.Frame(outer)
        hands.pack(fill="both", expand=True)

        left_wrap = ttk.Frame(hands)
        left_wrap.pack(side="left", fill="both", expand=True, padx=(0, 5))
        right_wrap = ttk.Frame(hands)
        right_wrap.pack(side="left", fill="both", expand=True, padx=(5, 0))

        self.left_panel = HandPanel(left_wrap, "Left", channel=0, arbitration_id=0x01)
        self.right_panel = HandPanel(right_wrap, "Right", channel=1, arbitration_id=0x01)

        self.left_panel.frame.pack(fill="both", expand=True)
        self.right_panel.frame.pack(fill="both", expand=True)

        bottom = ttk.Frame(outer, padding=(0, 8, 0, 0))
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Status:").pack(side="left")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left", padx=6)

        # Best-effort auto connect on launch.
        self.root.after(150, lambda: self._run(self._connect_both, show_dialog=False))

    def _run(self, fn, *args, show_dialog: bool = True) -> None:
        try:
            fn(*args)
        except Exception as exc:
            if show_dialog:
                messagebox.showerror("Dual Hand Operation Failed", str(exc))
            self.status_var.set(f"Failed: {exc}")

    def _connect_panel(self, panel: HandPanel, side_label: str) -> None:
        if panel.client is not None:
            return
        try:
            panel.connect()
        except Exception as exc:
            raise RuntimeError(f"{side_label} connect failed: {exc}") from exc

    def _connect_both(self) -> None:
        if self.left_panel is None or self.right_panel is None:
            raise RuntimeError("Panels are not initialized")

        connected = []
        try:
            self._connect_panel(self.left_panel, "Left")
            connected.append(self.left_panel)
            self._connect_panel(self.right_panel, "Right")
            connected.append(self.right_panel)
        except Exception:
            for panel in connected:
                panel.disconnect()
            raise

        self.status_var.set("Connected both hands (CANalyst-II ch0 + ch1)")

    def _reconnect_both(self) -> None:
        self._disconnect_both()
        self._connect_both()

    def _disconnect_both(self) -> None:
        if self.left_panel is not None:
            self.left_panel.disconnect()
        if self.right_panel is not None:
            self.right_panel.disconnect()
        self.status_var.set("Disconnected both hands")

    def _camera_script_path(self) -> Path:
        return Path(__file__).resolve().parent / "camera_bimanual_finger_control.py"

    @staticmethod
    def _camera_venv_python() -> str:
        """Return the camera venv Python that has mediapipe installed."""
        venv_python = Path(__file__).resolve().parent / "camera" / "bin" / "python3"
        if venv_python.exists():
            return str(venv_python)
        return sys.executable

    @staticmethod
    def _camera_env() -> Dict[str, str]:
        env = os.environ.copy()
        if "QT_QPA_FONTDIR" not in env:
            for font_dir in (
                "/usr/share/fonts/truetype/dejavu",
                "/usr/share/fonts/dejavu",
                "/usr/share/fonts/truetype/freefont",
            ):
                if Path(font_dir).is_dir():
                    env["QT_QPA_FONTDIR"] = font_dir
                    break
        return env

    def _is_camera_running(self) -> bool:
        return self.camera_process is not None and self.camera_process.poll() is None

    def _poll_camera_process(self) -> None:
        if self.camera_process is None:
            return
        code = self.camera_process.poll()
        if code is None:
            self.root.after(800, self._poll_camera_process)
            return
        self.camera_process = None
        self.status_var.set(f"Camera gesture stopped (exit code {code})")

    def _start_camera_gesture(self) -> None:
        if self._is_camera_running():
            self.status_var.set("Camera gesture is already running")
            return

        script_path = self._camera_script_path()
        if not script_path.exists():
            raise RuntimeError(f"Camera gesture script not found: {script_path}")

        # Free the CAN channels for the camera gesture process.
        self._disconnect_both()

        cmd = [
            self._camera_venv_python(),
            str(script_path),
            "--interface",
            "canalystii",
            "--left-channel",
            "0",
            "--right-channel",
            "1",
            "--left-arb-id",
            "0x01",
            "--right-arb-id",
            "0x01",
            "--angle-min",
            "0",
            "--angle-max",
            "90",
            "--power-on",
            "--flip-view",
        ]
        self.camera_process = subprocess.Popen(cmd, cwd=str(script_path.parent), env=self._camera_env())
        self.status_var.set("Camera gesture running (press q in camera window to quit)")
        self.root.after(800, self._poll_camera_process)

    def _stop_camera_gesture(self, update_status: bool = True) -> None:
        if self.camera_process is None:
            if update_status:
                self.status_var.set("Camera gesture is not running")
            return

        proc = self.camera_process
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
        self.camera_process = None
        if update_status:
            self.status_var.set("Camera gesture stopped")

    def _on_close(self) -> None:
        self._stop_camera_gesture(update_status=False)
        self._disconnect_both()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = DualUsbCanHandGuiApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        try:
            app._on_close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
