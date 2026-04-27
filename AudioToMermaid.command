#!/bin/bash
cd "$(dirname "$0")"

# Launch Brave with remote debugging if not already running with it
if ! lsof -i :9222 &>/dev/null; then
    echo "Starting Brave with remote debugging..."
    open -a "Brave Browser" --args --remote-debugging-port=9222
    sleep 3
fi

# Activate venv and run
source .venv/bin/activate
python -m src
