#!/usr/bin/env bash
# Demo D｜持久性：worker 挂掉/重启，流水线状态不丢，停机期间攒下的活自动接着跑。
#
# 前置：①temporal dev server 在跑（./run_server.sh）；②Demo B 已跑过
#       （content-pipeline:p260821-red 仍挂在机器门红灯上）；③**没有别的 worker 在跑**
#       —— 本脚本自己起一个 worker 并持有 PID，好干净地杀掉它（本机沙箱下 ps/pkill 不可用，
#          所以一律按自己记下的 PID 发信号，不做进程枚举）。
set -uo pipefail
POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$POC_DIR"
CLI="./bin/temporal"
PY="$POC_DIR/.venv/bin/python"
ADDR="127.0.0.1:7233"
WF="content-pipeline:p260821-red"
mkdir -p out

line() { printf '%s\n' "=============================================================================="; }
snap() {  # query 快照（要 worker 在线才能应答）
  $CLI workflow query --address "$ADDR" -w "$WF" --type snapshot -o json 2>/dev/null \
    | "$PY" -c 'import json,sys
d=json.load(sys.stdin)
q=d["queryResult"][0] if isinstance(d.get("queryResult"),list) else d
print("   stage=%s/%s  机器门跑过 %d 次  最后 red_count=%s" % (q["stage"],q["stage_state"],len(q["qc_runs"]),q["qc_runs"][-1]["red_count"] if q["qc_runs"] else "-"))'
}
srv() {   # describe 是服务端读，worker 死着也能看
  $CLI workflow describe --address "$ADDR" -w "$WF" -o json 2>/dev/null \
    | "$PY" -c 'import json,sys
d=json.load(sys.stdin)
i=d.get("workflowExecutionInfo",d)
print("   status=%s  historyLength=%s  有待办workflowTask=%s" % (str(i.get("status")).replace("WORKFLOW_EXECUTION_STATUS_",""), i.get("historyLength"), bool(d.get("pendingWorkflowTask"))))'
}

line; echo "Demo D｜worker 重启，状态不丢"; line

echo
echo "① 起一个受本脚本管的 worker（记住 PID）："
"$PY" worker.py > out/worker-demoD.log 2>&1 &
W1=$!
echo "   worker pid=$W1"
sleep 8
echo "② 现状（query 由 worker 应答，证明它在线）："
snap

echo
echo "③ 杀掉 worker（kill -TERM ${W1}）："
kill -TERM "$W1" 2>/dev/null && echo "   TERM 已发" || echo "   发信号失败"
sleep 3
if kill -0 "$W1" 2>/dev/null; then echo "   ⚠ pid $W1 还活着"; else echo "   pid $W1 已退出（无 worker 在线）"; fi

echo
echo "④ worker 死着，服务端里的流水线还在："
srv

echo
echo "⑤ worker 死着时发 signal（retry_qc）——服务端照收，排成待办等 worker 回来："
$CLI workflow signal --address "$ADDR" -w "$WF" --name retry_qc \
  --input '"ops-agent（worker 停机期间）"' >/dev/null 2>&1 \
  && echo "   signal 已投递" || echo "   signal 投递失败"
sleep 3
srv
echo "   （有待办=True 且历史已增长：signal 进了不可变历史，但没人执行）"

echo
echo "⑥ 重启 worker（新进程、新 PID，代码原样）："
"$PY" worker.py > out/worker-demoD-restart.log 2>&1 &
W2=$!
echo "   新 worker pid=$W2"
sleep 10
echo "⑦ 停机期间攒的活自动跑掉了（机器门次数 +1，仍红所以仍卡在同一段）："
snap
srv

echo
echo "⑧ 收尾：把本脚本起的 worker 停掉，环境还原（要继续玩：./run_worker.sh）"
kill -TERM "${W2}" 2>/dev/null && echo "   worker ${W2} 已停" || echo "   worker ${W2} 已不在"
echo
echo "Demo D 结束：worker 是可替换的肌肉，记忆在服务端——「agent 换人/重启不丢状态」的模型基础。"
