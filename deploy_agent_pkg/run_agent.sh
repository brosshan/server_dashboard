#!/bin/bash
cd "$(dirname "$0")"

echo "============================================================"
echo "  Starting Datacenter Monitor Agent (Linux)..."
echo "============================================================"

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[Error] python3 not found! Please install python3."
    exit 1
fi

# 2. Check virtualenv validity
VENV_OK=1
if [ ! -f ".venv/bin/python" ]; then
    VENV_OK=0
else
    .venv/bin/python -c "import sys" &> /dev/null || VENV_OK=0
fi

if [ "$VENV_OK" -eq 0 ]; then
    echo "[Creating dedicated Virtual Environment...]"
    rm -rf .venv
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "[Error] Failed to create virtualenv. Please install python3-venv."
        exit 1
    fi
    source .venv/bin/activate
    echo "[Installing required packages...]"
    pip install --upgrade pip &> /dev/null
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

echo "[Starting Agent...]"
python agent.py
