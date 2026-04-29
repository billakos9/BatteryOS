#!/bin/bash
# Start BatteryOS backend + frontend with one command
# Usage: ./start.sh [--no-browser]
set -e

cd "$(dirname "$0")"

echo "============================================"
echo "BatteryOS Development Starter"
echo "============================================"
echo "Backend : http://127.0.0.1:8000/"
echo "Frontend: http://127.0.0.1:5173/"
echo "============================================"
echo ""

python3 start_dev.py "$@"
