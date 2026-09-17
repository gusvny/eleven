#!/usr/bin/env bash
# 起 python worker（需先 ./setup.sh 与 ./run_server.sh）。
#
# SANDBAR_AGENT_RUNTIME=docker（t260913-04，方案 D6）：本机 macOS 无可用沙箱后端
# （Seatbelt fail-closed，KI-083），headless agent 的命令面必须走「每票一容器」执行面。
# 代码缺省仍是 host（存量语义冻结）——生产 worker 由本脚本显式声明 docker，一处接线、
# 审计可见。docker/镜像缺席时引擎 fail-closed 点名（不静默回落 host）。
#
# dsh 版本面四旋钮（t260916-24，缺省=现行为；worker 启动即记录进 meta 并在首票
# spawn 落票面 dsh_pin_<tag>.json，升级切流只动引擎侧旋钮，console(3099) 用的全局
# dsh 不受影响——红线 #1 自动满足）：
#   SANDBAR_AGENT_CMD            host 形态整命令（shlex），显式钉二进制路径，例：
#                                SANDBAR_AGENT_CMD="/opt/dsh-versions/0.1.5-rc.2/bin/dsh --profile sandbar-headless"
#   SANDBAR_AGENT_IMAGE          docker 形态镜像 tag（agent_runtime 消费），例：
#                                SANDBAR_AGENT_IMAGE=sandbar-agent:dsh-0.1.5-rc.2-s1
#   SANDBAR_DSH_EXPECTED_VERSION 期望版本；与实际不符=每次 spawn 响亮告警（票面留痕）
#   SANDBAR_DSH_STRICT=1         版本不符升格硬闸：worker 拒绝上线（缺省只告警）
set -euo pipefail
POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$POC_DIR"
export SANDBAR_AGENT_RUNTIME=docker
exec "$POC_DIR/.venv/bin/python" worker.py
