#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p "$SCRIPT_DIR"/logs
sudo cp "$SCRIPT_DIR"/deploy/memoryx-hermes.service /etc/systemd/system/memoryx-hermes.service
sudo systemctl daemon-reload
sudo systemctl enable --now memoryx-hermes
