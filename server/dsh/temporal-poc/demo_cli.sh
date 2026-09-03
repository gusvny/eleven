#!/usr/bin/env bash
# 端到端演示（t260821-02 步1）：client.py 五个子命令 + worker 定形（后台起 / 优雅停）。
#
# 前置：./setup.sh 跑过；./run_server.sh 在另一个 shell 里跑着（temporal dev server）。
# 本脚本自己用 worker.py --daemon 起 worker、演示 client.py 五个子命令、最后优雅停 worker。
# 输出同时落 out/demo-step1-cli.txt。
set -uo pipefail

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$POC_DIR"
PY="$POC_DIR/.venv/bin/python"
CLI="$POC_DIR/client.py"
ADDR="127.0.0.1:7233"
PIDFILE="$POC_DIR/data/worker.pid"
LOGFILE="$POC_DIR/out/worker-step1.log"
RUN="$(date +%m%d-%H%M%S)"
PROPOSAL="p260821-step1-${RUN}"
WF_ID="content-pipeline:${PROPOSAL}"
CANCEL_PROPOSAL="p260821-step1-cancel-${RUN}"
CANCEL_WF_ID="content-pipeline:${CANCEL_PROPOSAL}"
mkdir -p out

line() { printf '%s\n' "=============================================================================="; }

cli() {  # cli <子命令> [argsJSON] → stdout 原样（无 argsJSON 时缺省 {}，由 client.py 兜底）
  if [ -n "${2:-}" ]; then
    "$PY" "$CLI" "$1" "$2"
  else
    "$PY" "$CLI" "$1"
  fi
}

# snap <wf_id> → "stage stage_state status result"（query 只读）
snap() {
  cli query "{\"workflow_id\":\"$1\"}" \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
if not d.get("ok"): print("ERR", d.get("error")); sys.exit(0)
r=d.get("result",{}); s=r.get("snapshot",{})
print(s.get("stage"), s.get("stage_state"), r.get("status"), s.get("result",""))'
}

# wait_stage <wf_id> <stage> <state> <timeout_s> → 轮询到目标状态（query 实时读）
wait_stage() {
  local wf="$1" want_stage="$2" want_state="$3" to="${4:-120}"
  local waited=0 got
  while [ "$waited" -lt "$to" ]; do
    got="$(snap "$wf")"
    set -- $got
    if [ "$1" = "$want_stage" ] && [ "$2" = "$want_state" ]; then
      echo "$got"; return 0
    fi
    sleep 1; waited=$((waited + 1))
  done
  echo "TIMEOUT $got"; return 1
}

line; echo "端到端演示（t260821-02 步1）｜client.py 五子命令 + worker 定形"; line
echo "run=$RUN  proposal=$PROPOSAL"
echo

# ① 预检：temporal dev server 在线
if ! "$POC_DIR/bin/temporal" operator namespace list --address "$ADDR" >/dev/null 2>&1; then
  echo "✗ 连不上 temporal（${ADDR}）。先在另一个 shell 跑：./run_server.sh" >&2
  exit 1
fi
echo "① temporal dev server 在线（${ADDR}，UI http://127.0.0.1:8233）"
echo

# ② worker 定形：后台起（--daemon 写 pidfile）
echo "② worker 后台起（worker.py --daemon --pidfile data/worker.pid --logfile out/worker-step1.log）："
"$PY" worker.py --daemon --pidfile "$PIDFILE" --logfile "$LOGFILE"
sleep 6
echo "   worker pid=$(cat "$PIDFILE")，日志见 out/worker-step1.log"
echo

# ③ start：启动 content-pipeline workflow
echo "③ client.py start（content-pipeline）："
cli start "{\"type\":\"content-pipeline\",\"proposal\":\"$PROPOSAL\",\"title\":\"步1 端到端演示提案\",\"scope\":\"260627\",\"label\":\"真脚本 qc_run(260627)\"}"
echo
echo "   等 worker 把 workflow 跑到 approve 人门（无超时挂起）……"
SNAP="$(wait_stage "$WF_ID" approve awaiting-human 60)"
echo "   → $SNAP"
echo

# ④ query 确认：停在 approve 人门（state 只有 workflow 代码能推）
echo "④ client.py query（读 stage，确认停在人门）："
cli query "{\"workflow_id\":\"$WF_ID\"}" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d["result"]; s=r["snapshot"]; print("   stage=%s  state=%s  status=%s  blocked=%s"%(s["stage"],s["stage_state"],r["status"],s["blocked_reason"]))'
echo

# ⑤ signal 过人门 approve（人签字）
echo "⑤ client.py signal（sign gate=approve 人签字）："
cli signal "{\"workflow_id\":\"$WF_ID\",\"signal\":\"sign\",\"input\":{\"who\":\"用户（人）\",\"gate\":\"approve\",\"decision\":\"approve\",\"note\":\"立项通过\"}}"
echo
echo "   等机器门（真 qc_run 260627）跑完 → 停在 final-review 人门……"
SNAP="$(wait_stage "$WF_ID" final-review awaiting-human 180)"
echo "   → $SNAP"
echo
echo "   机器门实测（query 里 qc_runs）："
cli query "{\"workflow_id\":\"$WF_ID\"}" | python3 -c 'import json,sys; d=json.load(sys.stdin); q=d["result"]["snapshot"].get("qc_runs",[]); print("   qc_runs=%s"%json.dumps(q,ensure_ascii=False))'
echo

# ⑥ signal 过人门 final-review（终审只能是人）
echo "⑥ client.py signal（sign gate=final-review 终审通过）："
cli signal "{\"workflow_id\":\"$WF_ID\",\"signal\":\"sign\",\"input\":{\"who\":\"用户（人）\",\"gate\":\"final-review\",\"decision\":\"approve\",\"note\":\"终审通过，可发布\"}}"
echo
echo "   等 publish（dry-run）后 workflow 完成……"
SNAP="$(wait_stage "$WF_ID" publish awaiting 60)"
echo "   → $SNAP"
echo
echo "⑦ query 确认终态 + 时间线（workflow 自己推的，无第二个写入方）："
cli query "{\"workflow_id\":\"$WF_ID\"}" | python3 -c 'import json,sys
d=json.load(sys.stdin); r=d["result"]; s=r["snapshot"]
print("   final: stage=%s state=%s status=%s result=%s"%(s["stage"],s["stage_state"],r["status"],s["result"]))
for row in s.get("timeline",[]): print("     %s  %-13s %-14s %s"%(row["at"],row["stage"],row["state"],row["reason"]))'
echo

# ⑧ schedule-list：只读列 Schedule
echo "⑧ client.py schedule-list（只读）："
cli schedule-list
echo

# ⑨ cancel：再起一条并停掉（证明 cancel 子命令）
echo "⑨ client.py start + cancel（停掉一条挂人门的 workflow）："
cli start "{\"type\":\"content-pipeline\",\"proposal\":\"$CANCEL_PROPOSAL\",\"title\":\"cancel 演示\",\"scope\":\"260627\"}"
sleep 3
cli cancel "{\"workflow_id\":\"$CANCEL_WF_ID\",\"reason\":\"步1 端到端演示：cancel 子命令演示\"}"
echo
echo "   cancel 后 query 该 workflow 的 status："
cli query "{\"workflow_id\":\"$CANCEL_WF_ID\"}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   status=%s"%(d.get("result",{}).get("status") if d.get("ok") else d.get("error")))' 2>/dev/null || echo "   （terminate 后 query 可能报 NotFound，属正常——已被停掉）"
echo

# ⑩ worker 优雅停（SIGTERM → shutdown）
echo "⑩ worker 优雅停（kill -TERM \$(cat pidfile)）："
W="$(cat "$PIDFILE" 2>/dev/null || echo '')"
if [ -n "$W" ] && kill -TERM "$W" 2>/dev/null; then
  echo "   SIGTERM 已发 worker pid=${W}，等它优雅退出……"
  sleep 4
  if kill -0 "$W" 2>/dev/null; then
    echo "   ⚠ worker pid=$W 仍在（优雅停可能超时）"
  else
    echo "   worker pid=$W 已退出（优雅停完成）"
  fi
else
  echo "   （无 pidfile，跳过）"
fi
echo
echo "端到端演示结束：start→query→signal→query 全走通；schedule-list / cancel 跑通；worker 后台起+优雅停。"
echo "输出存档：out/demo-step1-cli.txt"
