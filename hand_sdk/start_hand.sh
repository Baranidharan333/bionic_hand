#!/bin/bash
# Bring up CAN, free port 5000 (asks first), then start the Bionic Hand web app.

set -e

cd ~/Documents/IHUB/openarm_doc/Bionic_hand/hand_sdk

echo "Starting CAN..."
./can_up.sh

echo "Checking port 5000..."
./kill_port.sh 5000

echo "Starting Bionic Hand Web App..."
python3 webapp/app.py
