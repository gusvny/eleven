#!/usr/bin/env bash
# workbench 客户端产物唯一构建入口（t260910-15：构建产物抖动钉死）。
# 口径：同源码 + 同工具版本（lockfile 钉死 tsdown 0.22.2）+ 同参数（全部来自
# tsdown.config.ts）→ 产物逐字节可复现。禁止绕过本脚本手跑 tsdown/npx/pnpm
# 构建（npx 与裸 pnpm install 的传递依赖不受本目录 lockfile 约束，是压缩器
# 漂移入口）。产物仅 lib/client.cjs 与 lib/client.js 两个（config 未开
# sourcemap、无 gzip 步骤；未来若开 sourcemap，map 含绝对路径不入仓）。
set -euo pipefail
cd "$(dirname "$0")"

echo "[build-client] node $(node -v) / npm $(npm -v)（版本留痕，便于事后归因）"

# 按 lockfile 精确安装（--ignore-scripts：本包依赖树 hasInstallScript=0，安全）。
# 失败（含离线且缓存不可用）时显式点名环境原因退出非零，不做静默降级。
if ! npm ci --no-audit --ignore-scripts; then
  echo "FAIL npm ci 失败：依赖无法按 package-lock.json 安装（离线环境请先暖 npm 缓存后重试）" >&2
  exit 1
fi

node_modules/.bin/tsdown -c tsdown.config.ts

# 复核 onSuccess 复制：cjs 与 js 必须逐字节一致（不一致=半新产物，FAIL 点名）。
if ! cmp -s lib/client.cjs lib/client.js; then
  echo "FAIL lib/client.cjs 与 lib/client.js 逐字节不一致（onSuccess 复制缺失/半新产物），拒绝交付" >&2
  exit 1
fi

echo "[build-client] 产物 sha256："
shasum -a 256 lib/client.cjs lib/client.js
