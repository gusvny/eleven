#!/usr/bin/env bash
# 起 python worker（需先 ./setup.sh 与 ./run_server.sh）。
#
# SANDBAR_AGENT_RUNTIME=docker（t260913-04，方案 D6）：本机 macOS 无可用沙箱后端
# （Seatbelt fail-closed，KI-083），headless agent 的命令面必须走「每票一容器」执行面。
# 代码缺省仍是 host（存量语义冻结）——生产 worker 由本脚本显式声明 docker，一处接线、
# 审计可见。docker/镜像缺席时引擎 fail-closed 点名（不静默回落 host）。
set -euo pipefail
POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$POC_DIR"
export SANDBAR_AGENT_RUNTIME=docker
exec "$POC_DIR/.venv/bin/python" worker.py
