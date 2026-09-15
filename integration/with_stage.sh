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

# 泳道唯一化（t260910-12 arbitrate gen2）：compose 项目名是 docker daemon
# **全局**可见面，硬编码常量会让并行泳道跑同一场景时互相 down 掉对方的台
# （docker events 铁证：t260910-14 泳道 down t26090704-sched 拆掉本泳道
# 同名台）。后缀=本 worktree 路径 hash——同 worktree 稳定（幂等复用不受
# 影响），跨 worktree 不同（互拆根治）。ensure/down/注入同值，台生命周期
# 语义不变。
STAGE_PROJECT="${PROJECT}-$(printf %s "$PWD" | md5 -q | cut -c1-8)"

stage_ensure() {
  python3 integration/stage_docker.py ensure --project "$STAGE_PROJECT" \
    --services temporal 2>&1
}

# 生命周期锚（t260910-12 回归修复）：ensure 必须作为**本壳的前台子进程**跑、
# 输出落临时文件——绝不能放 `INFO=$(...)` 命令替换里：子壳在 ensure 返回瞬息
# 退出=hold 腿的锚死，台会在场景命令运行中被 ③回收拆掉（main 无 hold 腿故
# 旧日无此形态；回归复现实锤 hold 日志「锚进程已亡——回收孤儿台」而场景命令
# 还在跑）。锚=本 with_stage 壳：活到 "$@" 跑完 + down 收割；本壳意外死亡
# 仍由 hold ③兜底回收（场景台语义不漏，零启发式）。
INFO_FILE=$(mktemp "${TMPDIR:-/tmp}/with-stage-info.XXXXXX")
trap 'rm -f "$INFO_FILE"' EXIT
stage_ensure > "$INFO_FILE"
RC=$?
if [ $RC -ne 0 ]; then
  # 瞬态重试（t260910-12 目标④）：三类已知瞬态（502/拒连/起台面繁忙）命中
  # 白名单自动重试一次——分类判定走 lib_transient_retry.py 单源（本脚本不
  # 复制白名单）；重试仍红才按环境红收口，文案原样上报不吞不改。
  if python3 integration/lib_transient_retry.py is-transient < "$INFO_FILE" >/dev/null 2>&1; then
    echo "with_stage: ensure 红命中瞬态白名单，2s 后自动重试一次" >&2
    sleep 2
    stage_ensure > "$INFO_FILE"
    RC=$?
  fi
fi
if [ $RC -ne 0 ]; then
  # ${RC} 必须带花括号：紧跟其后的全角右括号是多字节字符，裸写法（美元符号+RC+全角
  # 右括号）会被部分 shell 解析成变量名的一部分 → set -u 下报 unbound variable，**把这条错误
  # 路径自己打崩**（调用方只见 UnicodeDecodeError，真因「台没起来」被吞）。
  # t260913-02 arbitrate 实测：t02-t260902-02-archive-legacy-e2e ENV_FAIL 的尾巴
  # 即为该形态。写集内全 shell 家族复扫仅此一处。
  echo "with_stage: 台没起来（ensure exit=${RC}）：" >&2
  tail -5 "$INFO_FILE" >&2
  exit 2
fi

LAST=$(tail -1 "$INFO_FILE")
PORT=$(printf '%s' "$LAST" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ports"]["temporal"])' 2>/dev/null)
NS=$(printf '%s' "$LAST" | python3 -c 'import json,sys; print(json.load(sys.stdin)["namespace"])' 2>/dev/null)
if [ -z "${PORT:-}" ] || [ -z "${NS:-}" ]; then
  echo "with_stage: ensure 回报缺 ports.temporal/namespace：$LAST" >&2
  python3 integration/stage_docker.py down --project "$STAGE_PROJECT" >/dev/null 2>&1 || true
  exit 2
fi

export SANDBAR_TARGET_HOST="127.0.0.1:$PORT"
export SANDBAR_NAMESPACE="$NS"

"$@"
RC=$?

python3 integration/stage_docker.py down --project "$STAGE_PROJECT" >/dev/null 2>&1 || true
exit $RC
