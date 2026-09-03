#!/usr/bin/env bash
# 一键跑全部 demo（A 全流程 / B 红灯卡住 / C 调度+单例 / D 持久性）。
#
# 前置：./setup.sh 跑过；./run_server.sh 在另一个 shell 里跑着。
# 本脚本自己起/停 worker（A、B、C 用一个；D 自己管自己的），输出同时落 out/。
set -uo pipefail
POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$POC_DIR"
CLI="./bin/temporal"
PY="$POC_DIR/.venv/bin/python"
ADDR="127.0.0.1:7233"
mkdir -p out

if ! $CLI operator namespace list --address "$ADDR" >/dev/null 2>&1; then
  echo "✗ 连不上 temporal（${ADDR}）。先在另一个 shell 跑：./run_server.sh" >&2
  exit 1
fi
echo "✓ dev server 在线（${ADDR}，UI http://127.0.0.1:8233）"

echo "→ 起 worker"
"$PY" worker.py > out/worker-demo.log 2>&1 &
WPID=$!
cleanup() { kill -TERM "${WPID}" 2>/dev/null || true; }
trap cleanup EXIT
sleep 8

"$PY" demo_happy.py    2>&1 | tee out/demo-A-happy.txt
echo; echo
"$PY" demo_fail.py     2>&1 | tee out/demo-B-red-blocked.txt
echo; echo
"$PY" demo_schedule.py 2>&1 | tee out/demo-C-schedule-dedup.txt
echo; echo

echo "→ 停 worker（Demo D 要独占 worker 生命周期）"
kill -TERM "${WPID}" 2>/dev/null || true
sleep 3
./demo_durability.sh   2>&1 | tee out/demo-D-durability.txt

echo
echo "全部 demo 跑完。输出存档在 out/：demo-A-happy.txt / demo-B-red-blocked.txt /"
echo "demo-C-schedule-dedup.txt / demo-D-durability.txt"
echo "残留：content-pipeline:p260821-red 故意留在 running（挂在机器门红灯上），去 UI 看得见。"
