#!/usr/bin/env bash
# sandbar 控制台停止脚本（2026-09-03 随 start-console.sh 移植，宿主令 A 案）
#
# 用法：
#   ./stop-console.sh           # 停 sandbar profile 的 dsh web 控制台（3099）
#   ./stop-console.sh --all     # 连 temporal dev server + worker 一起停
#
# 只认 'dsh --profile sandbar' 精确行——未来的 sandbar-headless 无人值守任务不受影响
# （ERE 里 sandbar 后只许空格或行尾，'sandbar-headless' 的 '-' 不匹配）。
# temporal server/worker 是共享基建（巡检 schedule 挂在上面），默认不动。
set -euo pipefail

PAT='dsh --profile sandbar( |$)'
PIDS=$(pgrep -f "$PAT" || true)

if [ -z "$PIDS" ]; then
  echo "○ 控制台本就没在跑"
else
  echo "▶ 停控制台：$PIDS"
  kill $PIDS
  for i in $(seq 1 10); do
    pgrep -f "$PAT" >/dev/null || break
    sleep 1
  done
  if pgrep -f "$PAT" >/dev/null; then
    echo "⚠ 10 秒没退，补 SIGKILL"
    pgrep -f "$PAT" | xargs kill -9
  fi
  echo "✓ 控制台已停"
fi

if [ "${1:-}" = "--all" ]; then
  # t260907-10：双分支收尸——迁移窗口内旧路径在跑 worker 也要停得住；摘除票删旧分支
  TPIDS=$(pgrep -f 'temporal server start-dev|engine/worker.py|temporal-poc/worker.py' || true)
  if [ -n "$TPIDS" ]; then
    echo "▶ 停 temporal server/worker：$TPIDS"
    kill $TPIDS 2>/dev/null || true
    echo "✓ temporal 已停（巡检 schedule 随之停摆，重起控制台会自动拉起）"
  else
    echo "○ temporal 本就没在跑"
  fi
else
  LEFT=$(pgrep -fl 'temporal server start-dev|engine/worker.py|temporal-poc/worker.py' || true)
  [ -n "$LEFT" ] && echo "○ temporal 仍在跑（不动它；要一起停：./stop-console.sh --all）"
fi
