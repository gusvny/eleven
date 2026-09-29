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
#   ./start-console.sh --bits-check     # 只做「安装 bits 指纹对账」并退出（不起服务、不占端口）
#   ./start-console.sh -- 其他 dsh web 参数
#
# 说明：
#   - profile 经 ~/.dsh/profiles/sandbar 软链 → server/profile（插件软链解析，跨 dsh 安装）
#   - 插件：sandbar-tools（admin 工具）/ sandbar-admin-ui / sandbar-workbench（工单台）
#     / sandbar-knowledge / sandbar-temporal-tools / sandbar-providers
#   - headless（无人值守重活）用：dsh run --profile sandbar-headless "任务"（软链待建则先用 suyou-headless）
set -euo pipefail

# ── dsh 安装 bits 指纹对账（260923 事故后加）────────────────────────────────
# 事故：版本号一模一样、却谁都起不来。
#   同一天 npm 装出的 @deepseek-ai/dsh@0.1.5-rc.2（09-23 10:13）与 09-21 验证过的
#   那份 tarball 解包（~/.sandbar/dsh-015）**不是同一套 bits**：dsh 的依赖写的是
#   semver 区间，09-23 解析到的 cordis 族比 09-21 各高一档，其中
#   cordis-plugin-hmr 1.0.18 **删掉了 registerConfig**；而 launcher
#   （dsh-app-boot watchUserPatches）在 profile patchReload=live（自定义 profile 的
#   缺省值）下必调 hmr.registerConfig → 该安装自不相容，profile 侧改不动它。
#   ⇒ 只校「version 字段 == 目标版本」不足以判定可用（那一步两套都过）。
#   故此处对已验证的解析集做指纹对账，不符就换一套或响亮报错——不要裸跑踩雷。
DSH_BITS_FINGERPRINT_CORDIS="4.0.2"
DSH_BITS_FINGERPRINT_LOADER="1.0.3"
DSH_BITS_FINGERPRINT_HMR="1.0.17"

# 末级软链解析（macOS 无 readlink -f）：bin 可能是 /opt/homebrew/bin/dsh → …/lib/bin.js
resolve_final_link() {
  _t="$1"
  while [ -L "$_t" ]; do
    _d=$(cd -P "$(dirname "$_t")" && pwd)
    _t=$(readlink "$_t")
    case "$_t" in /*) ;; *) _t="$_d/$_t" ;; esac
  done
  printf '%s' "$_t"
}

# 从 bin 路径定位 dsh 包根（…/node_modules/@deepseek-ai/dsh）
dsh_pkg_root_of() {
  printf '%s' "$1" | sed -n 's#\(.*/node_modules/@deepseek-ai/dsh\)\(/.*\)\{0,1\}$#\1#p'
}

# 读嵌套/并列两种布局下的包版本；找不到回空
pkg_version_of() {
  _root="$1"; _name="$2"
  for _cand in "$_root/node_modules/@deepseek-ai/$_name" "$(dirname "$_root")/$_name"; do
    [ -f "$_cand/package.json" ] || continue
    sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$_cand/package.json" | head -1
    return 0
  done
  return 1
}

# 对账一套 bin：0=过；1=不过（原因写入 DSH_BITS_REASON）
bits_check() {
  _bin="$1"
  DSH_BITS_REASON=""
  _resolved=$(resolve_final_link "$_bin")
  _root=$(dsh_pkg_root_of "$_resolved")
  if [ -z "$_root" ]; then
    DSH_BITS_REASON="无法从 bin 定位安装根（bin=$_bin → ${_resolved}）——指纹未对账"
    return 2
  fi
  _c=$(pkg_version_of "$_root" cordis || true)
  _l=$(pkg_version_of "$_root" cordis-plugin-loader || true)
  _h=$(pkg_version_of "$_root" cordis-plugin-hmr || true)
  DSH_BITS_SEEN="cordis=${_c:-缺} loader=${_l:-缺} hmr=${_h:-缺}"
  if [ "$_c" != "$DSH_BITS_FINGERPRINT_CORDIS" ] || \
     [ "$_l" != "$DSH_BITS_FINGERPRINT_LOADER" ] || \
     [ "$_h" != "$DSH_BITS_FINGERPRINT_HMR" ]; then
    DSH_BITS_REASON="cordis 族版本与已验证集不符（期望 cordis=$DSH_BITS_FINGERPRINT_CORDIS loader=$DSH_BITS_FINGERPRINT_LOADER hmr=${DSH_BITS_FINGERPRINT_HMR}；实得 ${DSH_BITS_SEEN}）"
    return 1
  fi
  _hmrdir=$(dirname "$(resolve_final_link "$_root/node_modules/@deepseek-ai/cordis-plugin-hmr/package.json")")
  if ! grep -rq "registerConfig" "$_hmrdir/lib" 2>/dev/null; then
    DSH_BITS_REASON="cordis-plugin-hmr 里没有 registerConfig（launcher 在 patchReload=live 下必调它 → 起不来）"
    return 1
  fi
  return 0
}

# 候选顺序：显式 DSH_BIN > 机器级钉（~/.sandbar/dsh-015，与 project.yaml paths.dsh_bin 同源）> PATH 上的 dsh
DSH_BIN_EXPLICIT="${DSH_BIN:-}"
CANDIDATES=()
[ -n "$DSH_BIN_EXPLICIT" ] && CANDIDATES+=("$DSH_BIN_EXPLICIT")
[ -x "$HOME/.sandbar/dsh-015/bin/dsh" ] && CANDIDATES+=("$HOME/.sandbar/dsh-015/bin/dsh")
_p=$(command -v dsh || true); [ -n "$_p" ] && CANDIDATES+=("$_p")

# 对账不过时的统一出路提示（避免每次改文案两处不同步）
bits_fail_hint() {
  {
    echo "     期望：cordis=$DSH_BITS_FINGERPRINT_CORDIS loader=$DSH_BITS_FINGERPRINT_LOADER hmr=$DSH_BITS_FINGERPRINT_HMR"
    echo "     出路：① DSH_BIN=<某套已验证安装>/bin/dsh ./start-console.sh"
    echo "           ② 修那套安装：钉住 cordis 族重装（npm --before / overrides）"
    echo "           ③ 明知 bits 不对仍要起（如升级预演）：SANDBAR_SKIP_DSH_BITS_CHECK=1 ./start-console.sh"
  } >&2
}

if [ "${1:-}" = "--bits-check" ]; then
  if [ "${#CANDIDATES[@]}" -eq 0 ]; then echo "❌ 找不到任何 dsh（DSH_BIN 未设、机器钉不在位、PATH 上也没有）" >&2; exit 1; fi
  _any=0
  for c in "${CANDIDATES[@]}"; do
    if bits_check "$c"; then echo "✅ bits 指纹对账通过：${c}（${DSH_BITS_SEEN}）"; _any=1
    else echo "❌ $c —— $DSH_BITS_REASON"; fi
  done
  [ "$_any" = 1 ] || exit 1
  exit 0
fi

if [ "${#CANDIDATES[@]}" -eq 0 ]; then
  echo "❌ 找不到 dsh。装一套可用 bits，或用 DSH_BIN=<路径> 指定（注意：版本号对不代表 bits 对）" >&2
  exit 1
fi

DSH_BIN=""
DSH_BITS_NOTE=""
if [ -n "$DSH_BIN_EXPLICIT" ]; then
  # 显式指定＝听用户的（升级预演要能拿候选 bits 起），但 bits 不对必须响亮拦下，
  # 不许静默换成另一套——否则「我明明指了新版，起来的却是旧的」这种事会骗人。
  if bits_check "$DSH_BIN_EXPLICIT"; then
    DSH_BIN="$DSH_BIN_EXPLICIT"; DSH_BITS_NOTE="$DSH_BITS_SEEN"
  elif [ "${SANDBAR_SKIP_DSH_BITS_CHECK:-0}" = "1" ]; then
    DSH_BIN="$DSH_BIN_EXPLICIT"
    echo "⚠️  SANDBAR_SKIP_DSH_BITS_CHECK=1：无视指纹对账，强行用 ${DSH_BIN}（${DSH_BITS_REASON}）" >&2
  else
    echo "❌ 显式指定的 DSH_BIN=$DSH_BIN_EXPLICIT 未通过 bits 指纹对账：$DSH_BITS_REASON" >&2
    bits_fail_hint
    exit 1
  fi
else
  # 未指定＝自动挑一套能用的：坏的那套跳过（点名原因），好的那套用上。
  for c in "${CANDIDATES[@]}"; do
    if bits_check "$c"; then DSH_BIN="$c"; DSH_BITS_NOTE="$DSH_BITS_SEEN"; break; fi
    echo "⚠️  跳过 ${c}：$DSH_BITS_REASON" >&2
  done
fi

if [ -z "$DSH_BIN" ]; then
  echo "❌ 没有一套 dsh 安装通过 bits 指纹对账——控制台起不来，且原因不在 profile 侧：" >&2
  bits_fail_hint
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
#
# 260929 补记：打印 URL 里的 127.0.0.1 是 dsh-web-app 的 lib 常量（LOOPBACK_HOST，
# localWebUrl 硬编码），profile 的 webserver.config.host 只管绑定管不了打印——无旋钮。
# 且登录 cookie 按 host:port 分账，localhost 与 127.0.0.1 是两份独立 cookie，混用主机名
# 会莫名 401。故启动时把 dsh 输出过 sed，把 127.0.0.1:$PORT 改写成 localhost:$PORT 再
# 回显——照抄打印 URL 即落在有直连保障的主机名上，两个坑一起绕开。
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

echo "▶ 启动 sandbar 控制台：$DSH_BIN --profile sandbar ${ARGS[*]:-（默认端口 3099）}"
[ -n "$DSH_BITS_NOTE" ] && echo "  bits 指纹对账通过（${DSH_BITS_NOTE}）"
# profile 即 app 容器——sandbar profile 组合 dsh-base+dsh-web-app+本仓补丁，直接 boot 出 web UI。
# bash 3.2 空数组 + set -u：${ARGS[@]} 需 + 守卫，否则 unbound
# 输出过 sed 改写打印 URL（260929 补记）：URL 可能落在任一输出流故 2>&1 合流；
# sed -l 行缓冲保证日志即产即显；set -o pipefail 保住 dsh 的退出码与 Ctrl+C 语义。
exec "$DSH_BIN" --profile sandbar ${ARGS[@]+"${ARGS[@]}"} 2>&1 |
  sed -l "s#127\.0\.0\.1:$PORT#localhost:$PORT#g"
