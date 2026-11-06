#!/bin/bash
# Show what is listening on a TCP port (default 5000) and kill it after confirmation.

PORT="${1:-5000}"

echo "================================"
echo "        PORT KILL SCRIPT"
echo "================================"

# Check whether port is in use
if ! sudo lsof -t -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null; then
    echo "Port $PORT is already free."
    exit 0
fi

echo ""
echo "Processes using port $PORT:"
sudo lsof -nP -iTCP:"$PORT" -sTCP:LISTEN

echo ""
read -p "Kill process(es) using port $PORT? (y/n): " CONFIRM

if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
    sudo fuser -k "$PORT/tcp"
    echo "Port $PORT processes terminated."
else
    echo "Operation cancelled."
fi
