#!/bin/bash
# Configure can0 at 1 Mbps and bring it up.
# No restart-ms: this gs_usb adapter does not support it.

set -e

CAN_INTERFACE="${1:-can0}"
BITRATE=1000000

echo "================================"
echo "       CAN INTERFACE SETUP"
echo "================================"

# Check CAN interface
if ! ip link show "$CAN_INTERFACE" >/dev/null 2>&1; then
    echo "ERROR: $CAN_INTERFACE not found!"
    echo "Check USB-to-CAN adapter connection."
    exit 1
fi

# Bring interface down
echo "[1/3] Bringing $CAN_INTERFACE down..."
sudo ip link set "$CAN_INTERFACE" down || true

# Configure bitrate
echo "[2/3] Configuring bitrate: $BITRATE"
sudo ip link set "$CAN_INTERFACE" type can bitrate "$BITRATE"

# Bring interface up
echo "[3/3] Bringing $CAN_INTERFACE up..."
sudo ip link set "$CAN_INTERFACE" up

echo ""
echo "CAN interface status:"
ip -details -statistics link show "$CAN_INTERFACE"

echo ""
echo "CAN setup completed."
