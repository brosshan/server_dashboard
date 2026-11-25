#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================================"
echo "  Starting Datacenter Monitor Agent (Linux)..."
echo "============================================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[Error] python3 not found! Please install python3."
    exit 1
fi

# Check if config exists
if [ ! -f "agent_config.json" ]; then
    echo "[Warning] agent_config.json not found!"
    echo "Please copy agent_config.json.template to agent_config.json"
    echo "and fill in your server_url and api_key before running."
    exit 1
fi

# Install required packages (pinned versions, verbose output)
echo "[Checking Dependencies...]"
pip3 install -r requirements.txt

echo ""
echo "[Starting Agent...]"
python3 agent.py