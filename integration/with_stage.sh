#!/bin/sh
# with_stage.sh <project> <命令...> —— 给需要真 Temporal 台的场景单点搭台再跑。
#
# 用法（run_scenarios.py 的 cmd 走 /bin/sh -c，cwd=仓库根）：
#   sh integration/with_stage.sh t26090202-prune python3 integration/.../sc_xxx.py
#
# 行为：stage_docker ensure 起台 → 从回报 JSON 取端口/namespace 注入
# SANDBAR_TARGET_HOST / SANDBAR_NAMESPACE（场景的「host 未显式设置=环境红」
# 写保原样生效——台没起来就不注入，场景自己按环境红收口）→ 跑命令 →
# 无论成败拆台，退出码透传命令本身（台没起来直接 exit 2）。
set -u

PROJECT=$1
shift

INFO=$(python3 integration/stage_docker.py ensure --project "$PROJECT" \
         --services temporal 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  echo "with_stage: 台没起来（ensure exit=$RC）：" >&2
  printf '%s\n' "$INFO" | tail -5 >&2
  exit 2
fi

LAST=$(printf '%s\n' "$INFO" | tail -1)
PORT=$(printf '%s' "$LAST" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ports"]["temporal"])' 2>/dev/null)
NS=$(printf '%s' "$LAST" | python3 -c 'import json,sys; print(json.load(sys.stdin)["namespace"])' 2>/dev/null)
if [ -z "${PORT:-}" ] || [ -z "${NS:-}" ]; then
  echo "with_stage: ensure 回报缺 ports.temporal/namespace：$LAST" >&2
  python3 integration/stage_docker.py down --project "$PROJECT" >/dev/null 2>&1 || true
  exit 2
fi

export SANDBAR_TARGET_HOST="127.0.0.1:$PORT"
export SANDBAR_NAMESPACE="$NS"

"$@"
RC=$?

python3 integration/stage_docker.py down --project "$PROJECT" >/dev/null 2>&1 || true
exit $RC
