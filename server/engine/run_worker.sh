#!/usr/bin/env bash
# 起 python worker（需先 ./setup.sh 与 ./run_server.sh）。
set -euo pipefail
POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$POC_DIR"
exec "$POC_DIR/.venv/bin/python" worker.py
