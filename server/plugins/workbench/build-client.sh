#!/usr/bin/env bash
# workbench 客户端产物唯一构建入口（t260910-15：构建产物抖动钉死）。
# 口径：同源码 + 同工具版本（lockfile 钉死 tsdown 0.22.2）+ 同参数（全部来自
# tsdown.config.ts）→ 产物逐字节可复现。禁止绕过本脚本手跑 tsdown/npx/pnpm
# 构建（npx 与裸 pnpm install 的传递依赖不受本目录 lockfile 约束，是压缩器
# 漂移入口）。产物仅 lib/client.cjs 与 lib/client.js 两个（config 未开
# sourcemap、无 gzip 步骤；未来若开 sourcemap，map 含绝对路径不入仓）。
# 跨包依赖（t260911-06/KI-073 钉链）：src/client/index.tsx 以 ../../../
# 相对引用兄弟插件包 knowledge/providers（上三级=server/plugins/），二者
# 缺席时构建必然 UNRESOLVED_IMPORT 非零——前置自检显式点名，不留给压缩
# 报错兜圈子。若未来移除该依赖，请同步删除对应自检项。
set -euo pipefail
cd "$(dirname "$0")"

for sibling in ../knowledge/src ../providers/src; do
  if [ ! -d "$sibling" ]; then
    echo "FAIL 构建跨包依赖缺席：$sibling 不在场（本入口按 server/plugins/ 同层布局解析 ../../../knowledge|providers），拒绝在残缺树上构建" >&2
    exit 1
  fi
done

echo "[build-client] node $(node -v) / npm $(npm -v)（版本留痕，便于事后归因）"

# 按 lockfile 精确安装（--ignore-scripts：本包依赖树 hasInstallScript=0，安全）。
# 失败（含离线且缓存不可用）时显式点名环境原因退出非零，不做静默降级。
if ! npm ci --no-audit --ignore-scripts; then
  echo "FAIL npm ci 失败：依赖无法按 package-lock.json 安装（离线环境请先暖 npm 缓存后重试）" >&2
  exit 1
fi

# 失败消法（t260911-06/C6，260911 夜全量回归实证修订）：tsdown 失败时拆掉旧
# 产物再退非零——失败构建呈现「缺件」响亮红（git status deleted 极醒目），机械
# 消解「旧产物冒充现场」。rm 必须只在失败路径：成功路径上先拆后建会给并发读
# lib 的兄弟场景（bundle-sync/bundle-loads/capture 族）制造 ENOENT 缺件窗口
# （全量回归实锤回红）；成功路径由 tsdown 原子性覆盖 + 尾部 cmp 复核兜底。
if ! node_modules/.bin/tsdown -c tsdown.config.ts; then
  rm -f lib/client.cjs lib/client.js
  echo "FAIL tsdown 构建失败：已拆 lib 旧产物（缺件响亮红），拒绝留旧产物冒充现场" >&2
  exit 1
fi

# 复核 onSuccess 复制：cjs 与 js 必须逐字节一致（不一致=半新产物，FAIL 点名）。
if ! cmp -s lib/client.cjs lib/client.js; then
  echo "FAIL lib/client.cjs 与 lib/client.js 逐字节不一致（onSuccess 复制缺失/半新产物），拒绝交付" >&2
  exit 1
fi

echo "[build-client] 产物 sha256："
shasum -a 256 lib/client.cjs lib/client.js
