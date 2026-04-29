#!/bin/bash

echo "╔══════════════════════════════════════════╗"
echo "║        NEXUS PANEL - INSTALLER           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Update system
echo "[1/5] Updating package lists..."
apt-get update -qq 2>/dev/null || yum update -y -q 2>/dev/null

# Install Python3 and pip if not present
echo "[2/5] Checking Python3..."
if ! command -v python3 &>/dev/null; then
    apt-get install -y python3 python3-pip 2>/dev/null || yum install -y python3 python3-pip 2>/dev/null
fi

if ! command -v pip3 &>/dev/null; then
    apt-get install -y python3-pip 2>/dev/null || yum install -y python3-pip 2>/dev/null
fi

# Install required Python packages
echo "[3/5] Installing Python dependencies..."
pip3 install --quiet \
    flask \
    flask-socketio \
    flask-login \
    psutil \
    eventlet \
    simple-websocket \
    gevent \
    gevent-websocket

echo "[4/5] Setting up permissions..."
chmod +x panel.py 2>/dev/null

echo "[5/5] Done!"
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Installation complete!                  ║"
echo "║  Run: python3 panel.py                   ║"
echo "║  Then open: http://YOUR_IP:5555          ║"
echo "║  Login: admin / admin                    ║"
echo "╚══════════════════════════════════════════╝"
