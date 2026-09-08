#!/usr/bin/env bash
# sandbar 控制台启动脚本（2026-09-03 安装制切换落位，宿主令 A 案：console 安家 sandbar）
# 由 suyou/start-console.sh 移植：profile 名改 sandbar，其余机制同源。
#
# 拓扑（切换后）：
#   - 本仓=引擎开发地+运行地（边开发边用）；supervisor（temporal-tools 插件）
#     按本文件位置推导 repo=sandbar，拉起本仓 engine 的 server/worker，
#     数据卷=本仓 data/temporal.db（2026-09-03 自 suyou 迁入全史 68MB）
#   - suyou=纯项目仓：app/pipeline/docs+策略件（roles/verify/merge-checks/场景），
#     其票在本引擎上跑（registry 定位仓根，泳道开在项目仓）
#
# 用法：
#   ./start-console.sh                  # 默认端口 3099（profile cordis.patch.yml webserver 配置）
#   ./start-console.sh --port 3100      # 覆盖端口（如需并行起第二个实例）
#   ./start-console.sh -- 其他 dsh web 参数
#
# 说明：
#   - profile 经 ~/.dsh/profiles/sandbar 软链 → server/profile（插件软链解析，跨 dsh 安装）
#   - 插件：sandbar-tools（admin 工具）/ sandbar-admin-ui / sandbar-workbench（工单台）
#     / sandbar-knowledge / sandbar-temporal-tools / sandbar-providers
#   - headless（无人值守重活）用：dsh run --profile sandbar-headless "任务"（软链待建则先用 suyou-headless）
set -euo pipefail

DSH_BIN="${DSH_BIN:-$(command -v dsh || true)}"
if [ -z "$DSH_BIN" ]; then
  echo "❌ 找不到 dsh 全局命令。安装：npm i -g @deepseek-ai/dsh@0.1.1-rc.2" >&2
  exit 1
fi

# 端口覆盖：--port N 转成 dsh web 的 --port 参数（透传），默认由 profile 决定（3099）
PORT=3099
ARGS=()
if [ "${1:-}" = "--port" ]; then
  PORT="$2"
  ARGS+=(--port "$2")
  shift 2
fi
ARGS+=("$@")

# 浏览器开页用 localhost 不用 127.0.0.1（260822 定案）：本机 Chrome 的代理链路
# 只放行主机名 localhost、劫持 IP 字面量 127.0.0.1——dsh 自动开的 127.0.0.1 页
# 会卡死成"页面在、数据全断"。故压住 dsh 自开（--no-open），这里自己开 localhost。
NO_OPEN=0
for a in ${ARGS[@]+"${ARGS[@]}"}; do [ "$a" = "--no-open" ] && NO_OPEN=1; done
if [ "$NO_OPEN" -eq 0 ]; then
  ARGS+=(--no-open)
  ( sleep 4; open "http://localhost:$PORT/" ) &
fi

# 工单台插件自动构建：src/client/ 改了就重建 lib/client.js
# 构建器优先用插件本地 node_modules/.bin/tsdown；本地缺失才退 npx（走网络现装，慢）。
# （2026-09-03 注：本仓 workbench 尚未装 devDep，src 变更后首次构建会走 npx；
#   引擎开发常态化后建议 cd server/plugins/workbench && pnpm install 装本地构建器。）
WORKBENCH_DIR="$(cd "$(dirname "$0")/server/plugins/workbench" && pwd)"
if [ -f "$WORKBENCH_DIR/src/client/index.tsx" ] && \
   [ "$WORKBENCH_DIR/src/client/index.tsx" -nt "$WORKBENCH_DIR/lib/client.js" ]; then
  echo "🔧 工单台插件源码有更新，自动重建 lib/client.js …"
  if [ -x "$WORKBENCH_DIR/node_modules/.bin/tsdown" ]; then
    (cd "$WORKBENCH_DIR" && ./node_modules/.bin/tsdown -c tsdown.config.ts) || \
      echo "⚠️  tsdown 构建失败（lib/client.js 保持旧版本，src 改动未生效）" 2>&1
  elif command -v npx >/dev/null 2>&1; then
    (cd "$WORKBENCH_DIR" && npx -y tsdown@0.22.2 -c tsdown.config.ts) || \
      echo "⚠️  tsdown 构建失败（lib/client.js 保持旧版本，src 改动未生效）" 2>&1
  else
    echo "⚠️  未找到 tsdown（跳过自动构建；lib/client.js 保持旧版本，src 改动未生效）" 2>&1
  fi
fi

echo "▶ 启动 sandbar 控制台：$(basename "$DSH_BIN") --profile sandbar ${ARGS[*]:-（默认端口 3099）}"
# profile 即 app 容器——sandbar profile 组合 dsh-base+dsh-web-app+本仓补丁，直接 boot 出 web UI。
# bash 3.2 空数组 + set -u：${ARGS[@]} 需 + 守卫，否则 unbound
exec "$DSH_BIN" --profile sandbar ${ARGS[@]+"${ARGS[@]}"}
