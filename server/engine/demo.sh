#!/usr/bin/env bash
# 一键跑全部 demo（持久性 demo D）。
# v1 演示面已随 content-pipeline 模板与 signal 子命令退役删除（t261001-04，
# 历史在 git）——见 README §8.4。留存 demo：demo_durability.sh（自己起/停 worker）。
#
# 前置：./setup.sh 跑过；./run_server.sh 在另一个 shell 里跑着。
set -uo pipefail
POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$POC_DIR"
CLI="./bin/temporal"
ADDR="127.0.0.1:7233"
mkdir -p out

if ! $CLI operator namespace list --address "$ADDR" >/dev/null 2>&1; then
  echo "✗ 连不上 temporal（${ADDR}）。先在另一个 shell 跑：./run_server.sh" >&2
  exit 1
fi
echo "✓ dev server 在线（${ADDR}，UI http://127.0.0.1:8233）"

./demo_durability.sh   2>&1 | tee out/demo-D-durability.txt

echo
echo "demo 跑完。输出存档在 out/demo-D-durability.txt。"
echo "残留：content-pipeline:p260821-red 故意留在 running（挂在机器门红灯上），去 UI 看得见。"
