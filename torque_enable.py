import can
import time

if not hasattr(can, "rc"):
    raise SystemExit(
        "Detected incompatible 'can' package at "
        f"{getattr(can, '__file__', '<unknown>')}. "
        "Uninstall 'can' and install 'python-can' (pip uninstall can; pip install python-can)."
    )

try:
    CANBus = can.Bus
except AttributeError:
    from can.interface import Bus as CANBus  # type: ignore

try:
    CANMessage = can.Message
except AttributeError:
    from can.message import Message as CANMessage  # type: ignore

def main() -> None:
    try:
        bus = CANBus(interface='canalystii', channel=0, bitrate=1000000)
    except Exception as exc:
        msg = str(exc).lower()
        if "permission denied" in msg:
            raise SystemExit(
                "Failed to access CANalyst-II (permission denied). "
                "Run with proper USB permissions/udev rules, or run once with sudo for testing."
            ) from exc
        raise SystemExit(f"Failed to open CAN bus: {exc}") from exc

    try:
        # Power ON
        bus.send(CANMessage(arbitration_id=0x01,
                            data=[0x03, 0x11],
                            is_extended_id=False))

        time.sleep(0.1)

        # Enable Torque
        bus.send(CANMessage(arbitration_id=0x01,
                            data=[0x10, 0x01, 0x00, 0x00],
                            is_extended_id=False))
    except Exception as exc:
        raise SystemExit(f"Failed to send CAN frame: {exc}") from exc
    finally:
        bus.shutdown()

    print("Hand Powered + Torque Enabled ✅")


if __name__ == "__main__":
    main()
