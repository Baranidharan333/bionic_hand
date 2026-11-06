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

def disable_torque():
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
        msg = CANMessage(
            arbitration_id=0x01,   # your hand CAN ID
            data=[0x03, 0x00],     # example command
            is_extended_id=False
        )

        bus.send(msg)
        print("Message Sent ✅")

        time.sleep(0.1)

    except Exception as exc:
        raise SystemExit(f"Failed to send CAN frame: {exc}") from exc
    finally:
        bus.shutdown()   # VERY IMPORTANT
        print("CAN Bus Closed Cleanly")

if __name__ == "__main__":
    disable_torque()
