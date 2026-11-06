"""Read SocketCAN link state from `ip -details -statistics -json link show <ch>` (Linux only)."""
from __future__ import annotations

import json
import subprocess
from typing import Any, Dict


def link_info(channel: str) -> Dict[str, Any]:
    try:
        out = subprocess.run(
            ["ip", "-details", "-statistics", "-json", "link", "show", channel],
            capture_output=True, text=True, timeout=2,
        )
        info = json.loads(out.stdout)[0]
    except Exception as exc:  # ip missing, not linux, unknown channel, virtual bus...
        return {"available": False, "error": str(exc) or "interface not found"}
    ld = info.get("linkinfo", {}).get("info_data", {})
    berr = ld.get("berr_counter") or {}
    return {
        "available": True,
        "operstate": info.get("operstate"),
        "can_state": ld.get("state"),
        "bitrate": ld.get("bittiming", {}).get("bitrate"),
        "restart_ms": ld.get("restart_ms"),
        "tx_err": berr.get("tx"),
        "rx_err": berr.get("rx"),
    }


def format_link_info(d: Dict[str, Any]) -> str:
    if not d.get("available"):
        return f"  (could not read link info: {d.get('error')})"
    lines = [
        f"  operstate : {d['operstate']}",
        f"  can state : {d['can_state']}",
        f"  bitrate   : {d['bitrate']}",
        f"  restart-ms: {d['restart_ms']}",
    ]
    if d.get("tx_err") is not None:
        lines.append(f"  tx/rx err : {d['tx_err']}/{d['rx_err']}")
    return "\n".join(lines)
