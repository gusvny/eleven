#!/bin/sh
# stage_console.sh —— dsh 升级人工测试台（stage 控制台）一键启停（t260916-25）。
#
# 【用途】在独立端口 + 独立 DSH_HOME 上起一个「目标版本 dsh + 真实 sandbar 插件 +
#   真实旧会话数据」的控制台，供人工对 UI 兼容面做升级走查。人工清单随
#   checklist 子命令打印（integration/t260916-25/ui_manual_checklist.md）。
#
# 【舞台纪律边界（review R6）】本壳只服务人工测试/一次性检查，不入场景供给链；
#   自动化场景的舞台仍归 integration/stage_docker.py 单点搭台（t260904-19 定稿）。
#   不得用本壳跑场景——两轨并存、端口档错开、互不管理，防止复活 pre-t260904-19
#   的互相踩踏（lib_stage_console.mjs 头注记载的 t260906-01 六小时错树事故）。
#
# 【照此固化的已验证形态】（integration 手工实测 0.1.5-rc.2 的化石 /tmp/dsh-stage）：
#   <home>/profiles/sandbar-stage  = server/profile 逐文件拷贝，唯一差异是
#                                    cordis.patch.yml webserver 端口 3099→--port；
#   .../sandbar-stage/node_modules/{sandbar-*} 五条软链 → 本仓
#                                    server/plugins/{ui,knowledge,providers,
#                                    temporal-tools,workbench}（仓根自推导，
#                                    修正化石的绝对路径硬编码）；
#   <home>/profiles/node_modules/  = 逐包软链 → <dsh-root>/node_modules（依赖树
#                                    复用目标 dsh 安装，不重装——化石即此形态，
#                                    修正化石指向一次性探针安装的漂移）；
#   启动 = DSH_HOME=<home> <dsh 入口> --profile sandbar-stage
#                                    （票面实测：`dsh web` 子命令不接受 --profile，
#                                    只能用 --profile 形式；入口两级解析：
#                                    <dsh-root>/bin/dsh 优先，npm 包布局回退
#                                    <dsh-root>/lib/bin.js——0.1.5-rc.2 实弹实证）。
#
# 【幂等分档（review R2，KI-016 同族）】.credentials.yaml / settings.yaml /
#   .anonymous-user-id / .agent-presets / storages 每次 prepare **强制重拷**
#   （真源=--src-home，杜绝老凭据假活被误读成「升级 break」）；仅 sessions/
#   允许 skip-if-exists（人工测试要数据稳定，不因重跑换数据）。
#
# 【参照取舍清单（review R4）】
#   a) 依赖树软链目标 = <dsh-root>/node_modules：与该 dsh 安装共享同一物理目录，
#      stage 侧对此树**只读不写**；--dsh-root 指向全局生产安装时同样成立（npm
#      管理的只读面），运行时打一行提示不阻断。
#   b) 凭据（chmod 600）与配置拷入 <home>（默认 /tmp/dsh-stage，重启即清）；
#      **stop 不删 home**（幂等复用 + 会话数据稳定）；要彻底清理直接
#      rm -rf <home>（内含生产凭据副本，不留用的机器应随手清）。
#   c) token URL 提取锚 = 「dsh web: http」字面行（KI-051 同族：上游改文案即
#      脱钩）：提取失败 = 响亮红 + 打印 log 尾 20 行 + 收掉自起台（gen17：
#      URL 静默按「台没起成」收，不留监听态无头台），绝不静默无 URL 收场；
#      profile 端口补丁的「    port: 3099」字面锚同理，补丁未生效即红。
#
# 【红线】3099（生产控制台）/ 7233、8233（生产 Temporal）永不占用、启停、请求；
#   --src-home（默认 ~/.dsh）全程只读（只 cp，不删不改源）；--home 解析为生产
#   home（~/.dsh）或等于 --src-home 时硬拒；stop 只处置本台 pidfile 且杀前必经
#   归属核对，其它进程（docker 测试台/手工台/生产面）只点名绝不杀。
#
# 【杀前归属核对（gen16 仲裁打回项：pidfile 盲信曾实弹误杀无辜 detached 进程）】
#   pidfile 可能陈旧/被篡改/复用——pid 活着不等于是我们起的。判据三处同源
#   （start 幂等分支、stop 主链、孤儿补杀）：ps -axEo pid=,command= 全表一次
#   拉取，行内含「DSH_HOME=<home>」（值后随空格/行尾——防 /tmp/dsh-stage 前缀
#   串扰误命中 /tmp/dsh-stage-2）或行内含「<home>/」路径锚（--version 隔离
#   安装形态下 dsh 命令行自带 <home>/runtime/…，环境显示失灵时的兜底）才算
#   本台；非本台 = 点名 + 清 pidfile + 正常收场（绝不杀）；ps 盲 = fail-closed
#   拒杀点名。
#
# 【进程生命周期（review R3，KI-077 同族）】spawn 经 python3 os.setsid 让 dsh
#   自成进程组（pid=pgid）；start 的「台没起成」终态（等端口超时 / URL 静默
#   宽限耗尽 / URL 端口漂移）一律 = 杀自起进程组 + 清 pidfile + 响亮红 + log 尾
#   （不留悬空进程占 home 抢口）；stop = 杀前锚核对 → TERM → KILL 升级组杀 +
#   孤儿检测（ps 环境锚 DSH_HOME=<home> 精确匹配才补杀，其余响亮点名）。
#
# 【工程纪律】壳内变量展开一律 ${VAR} 花括号形式——裸 $VAR 紧跟全角字符时
#   macOS bash 会把全角字符首字节并入变量名（set -u 下报 unbound variable，
#   t260913-02 同族，本票实弹踩中 20 处一次性根治）；UT 静态用例把守
#   （integration/tests/test_stage_console.py ShellStaticGuardTest）。
#
# 【只读警示（票面④，review R7）】本台连的是**生产 Temporal 与项目注册表**，
#   UI 上的写操作（建票/改配置/发会话）会直接打到生产。警示横幅出现在四处：
#   start 输出、url 输出、selfcheck 输出尾、清单文件顶部。mock 不可行（stage
#   的目的就是真数据人工测试）；UI 内 banner 需改 plugins/ui（超本票写集），
#   列后续票。
#
# 【用法】
#   stage_console.sh start --version 0.1.5-rc.2 [--port 3199] [--home /tmp/dsh-stage]
#                          [--src-home ~/.dsh] [--sessions 10] [--no-open]
#   stage_console.sh start --dsh-root /path/to/@deepseek-ai/dsh [...]（直指现成安装）
#   stage_console.sh prepare [同 start 参数]        # 只组装 home 不起台
#   stage_console.sh stop    [--port N] [--home H]  # 杀前锚核对+组杀+孤儿检测
#   stage_console.sh status  [--port N] [--home H]
#   stage_console.sh url     [--port N] [--home H]  # 恢复打印带 token URL+警示
#   stage_console.sh selfcheck [--token XXX] [...]  # 跑 UI 面自动断言
#   stage_console.sh checklist                      # 打印人工测试清单
# 退出码：0=绿；1=红（操作失败/断言红）；2=用法红/环境红（参数错、护栏拒绝）。

set -u

REPO=$(cd "$(dirname "$0")/../.." && pwd -P)
LIB="$REPO/integration/lib_stage_ui_surface.mjs"
CHECKLIST="$REPO/integration/t260916-25/ui_manual_checklist.md"
# 保护端口：3099=生产控制台；7233/8233=生产 Temporal（docs/testing-guide.md 端口表）。
PROTECTED_PORTS=" 3099 7233 8233 "

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die_usage() { printf 'usage红: %s\n' "$*" >&2; exit 2; }
die_red()   { printf 'RED: %s\n' "$*" >&2; exit 1; }

banner() {
  cat <<'BANNER'
======================================================================
 ⚠  只读警示：本 stage 控制台连接【生产 Temporal 与项目注册表】。
    UI 上的写操作（建票 / 改配置 / 发会话）会直接打到生产！
    本台仅用于人工走查 UI 兼容面，请勿执行破坏性写操作。
======================================================================
BANNER
}

# ---------- 参数 ----------
CMD="${1:-}"
[ -n "$CMD" ] && shift
PORT=3199
HOME_DIR=/tmp/dsh-stage
SRC_HOME="$HOME/.dsh"
SESSIONS_N=10
SESS_SRC=""
VERSION=""
DSH_ROOT_ARG=""
OPEN_FLAG=""
TOKEN_ARG=""

need2() { [ $# -ge 2 ] || die_usage "$1 缺值"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version)      need2 "$@"; VERSION="$2"; shift 2 ;;
    --dsh-root)     need2 "$@"; DSH_ROOT_ARG="$2"; shift 2 ;;
    --port)         need2 "$@"; PORT="$2"; shift 2 ;;
    --home)         need2 "$@"; HOME_DIR="$2"; shift 2 ;;
    --src-home)     need2 "$@"; SRC_HOME="$2"; shift 2 ;;
    --sessions)     need2 "$@"; SESSIONS_N="$2"; shift 2 ;;
    --sessions-dir) need2 "$@"; SESS_SRC="$2"; shift 2 ;;
    --no-open)      OPEN_FLAG="--no-open"; shift ;;
    --token)        need2 "$@"; TOKEN_ARG="--token $2"; shift 2 ;;
    --help|-h)      sed -n '2,70p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die_usage "未知参数：$1" ;;
  esac
done

# ---------- 护栏 ----------
port_in_protected() {
  case "$PROTECTED_PORTS" in *" $1 "*) return 0 ;; *) return 1 ;; esac
}
port_listener() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null; }
busy_who() { port_listener "$1" | awk 'NR>1{print $1" pid="$2}' | sort -u | tr '\n' ' '; }

kill_group() { # $1=pid(=pgid，spawn 用 setsid 保证)  $2=信号名
  kill "-$2" "-$1" 2>/dev/null || true
}

# ---------- 归属核对（头注「杀前归属核对」节；gen16 仲裁打回项根治） ----------
# ps 全表一次拉取，同一命令内主链核对与孤儿补杀共享；ps 盲（被拒/非零/空表）
# 一律按「不可观测」上报，由调用方 fail-closed，绝不带着盲表杀伐。
PS_TABLE=""

ps_refresh() { # → 0=表在位；1=ps 盲（本机不可观测）
  PS_TABLE=$(ps -axEo pid=,command= 2>/dev/null)
  if [ "$?" -ne 0 ] || [ -z "$PS_TABLE" ]; then
    PS_TABLE=""
    return 1
  fi
  return 0
}

pid_class() { # $1=pid → 0=本台锚命中 / 1=在表但非本台 / 3=不在表（已退/残像）
  # stdout=该 pid 的 ps 行（截 160 字符，红文案点名用，不刷屏）。
  printf '%s\n' "$PS_TABLE" | awk -v p="$1" \
    -v anchor="DSH_HOME=${HOME_DIR}" -v ap="${HOME_DIR}/" '
    BEGIN { alen = length(anchor) }
    function anchored(line,   i, c) {
      i = index(line, anchor)
      if (i > 0) {
        c = substr(line, i + alen, 1)
        if (c == "" || c == " ") return 1
      }
      if (index(line, ap) > 0) return 1
      return 0
    }
    $1 == p {
      seen = 1
      print substr($0, 1, 160)
      if (anchored($0)) exit 0
      exit 1
    }
    END { if (! seen) exit 3 }
  '
}

our_pids() { # stdout=表内锚命中本 home 的全部 pid（孤儿补杀候选，含组内成员）
  printf '%s\n' "$PS_TABLE" | awk -v anchor="DSH_HOME=${HOME_DIR}" -v ap="${HOME_DIR}/" '
    BEGIN { alen = length(anchor) }
    {
      i = index($0, anchor)
      hit = 0
      if (i > 0) {
        c = substr($0, i + alen, 1)
        if (c == "" || c == " ") hit = 1
      }
      if (! hit && index($0, ap) > 0) hit = 1
      if (hit) print $1
    }
  '
}

# 起台类命令（start/prepare）的完整护栏。
guards_start() {
  case "$PORT" in ''|*[!0-9]*) die_usage "--port 必须是数字端口，得 '$PORT'" ;; esac
  [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die_usage "--port 越界：$PORT"
  if port_in_protected "$PORT"; then
    die_usage "端口 $PORT 属保护面（3099=生产控制台；7233/8233=生产 Temporal）——永不占用"
  fi
  case "$SESSIONS_N" in ''|*[!0-9]*) die_usage "--sessions 必须是非负整数，得 '$SESSIONS_N'" ;; esac
  local L
  L=$(port_listener "$PORT")
  [ -z "$L" ] || die_usage "端口 $PORT 已被占用（$(busy_who "$PORT")）——绝不抢占，请换 --port"
  mkdir -p "$HOME_DIR" 2>/dev/null || die_usage "--home 不可创建：$HOME_DIR"
  HOME_DIR=$(cd "$HOME_DIR" && pwd -P)
  SRC_HOME=$(cd "$SRC_HOME" 2>/dev/null && pwd -P) || die_usage "--src-home 不存在：$SRC_HOME"
  [ "$HOME_DIR" != "/" ] || die_usage "--home 不能是根目录"
  [ "$HOME_DIR" != "$SRC_HOME" ] || die_usage "--home 不得等于 --src-home（等于把生产 home 当 stage home 用）"
  if [ "$HOME_DIR" = "$HOME/.dsh" ] || [ "$HOME_DIR" = "$(cd "$HOME/.dsh" 2>/dev/null && pwd -P)" ]; then
    die_usage "--home 不得是 ~/.dsh（生产 home）"
  fi
}

# stop/status 的弱护栏（home 可能尚未创建，不 mkdir）。
guards_stop() {
  [ -d "$HOME_DIR" ] && HOME_DIR=$(cd "$HOME_DIR" && pwd -P)
}

# ---------- dsh-root 解析（--dsh-root 直指 / --version 隔离安装，绝不碰全局） ----------
resolve_dsh_root() {
  if [ -n "$DSH_ROOT_ARG" ]; then
    DSH_ROOT=$(cd "$DSH_ROOT_ARG" 2>/dev/null && pwd -P) || die_usage "--dsh-root 不存在：$DSH_ROOT_ARG"
  else
    [ -n "$VERSION" ] || die_usage "start/prepare 需要 --version 或 --dsh-root 其一"
    DSH_ROOT="$HOME_DIR/runtime/$VERSION/node_modules/@deepseek-ai/dsh"
    if [ ! -x "$DSH_ROOT/bin/dsh" ] && [ ! -f "$DSH_ROOT/lib/bin.js" ]; then
      say "== 隔离安装 @deepseek-ai/dsh@$VERSION → $HOME_DIR/runtime/${VERSION}（绝不写全局安装）=="
      mkdir -p "$HOME_DIR/runtime/$VERSION" || die_red "runtime 目录创建失败：$HOME_DIR/runtime/$VERSION"
      # npm cache 也落 stage home 内——不复用 ~/.npm（机器级缓存面，stage 自洽）。
      npm install --prefix "$HOME_DIR/runtime/$VERSION" --cache "$HOME_DIR/.npm-cache" \
        --no-fund --no-audit "@deepseek-ai/dsh@$VERSION" \
        || die_red "npm 隔离安装失败（registry 不可达？）——可改用 --dsh-root 直指现成安装"
    fi
  fi
  # 入口两级解析：bin/dsh（票面手工形态）→ lib/bin.js（npm 包实际布局，
  # files=['lib/*.js'] 无 bin/ 目录，npm 全局软链同指 lib/bin.js——本票实弹实证）。
  if [ -x "$DSH_ROOT/bin/dsh" ]; then
    DSH_BIN="$DSH_ROOT/bin/dsh"
  elif [ -f "$DSH_ROOT/lib/bin.js" ]; then
    DSH_BIN="$DSH_ROOT/lib/bin.js"
  else
    die_red "dsh 入口不存在（bin/dsh 与 lib/bin.js 皆缺）：$DSH_ROOT"
  fi
  local VER
  VER=$("$DSH_BIN" --version 2>/dev/null | head -n 1)
  say "== dsh-root=${DSH_ROOT}（版本 ${VER:-未知}）=="
  # 依赖树定位（两种 npm 布局，取条目多者—— fossil 即 189 项那棵）：
  #   prefix 布局：依赖平铺在 <runtime-prefix>/node_modules（=包根上三级，
  #                0.1.5-rc.2 实测 189 项，包内 node_modules 为 0）；
  #   全局布局：依赖烤在包内 <DSH_ROOT>/node_modules（0.1.1-rc.2 全局实测 186 项）。
  local NM_PKG="$DSH_ROOT/node_modules" NM_PREFIX="$DSH_ROOT/../../../node_modules"
  local na=0 nb=0
  [ -d "$NM_PKG" ] && na=$(ls "$NM_PKG" 2>/dev/null | wc -l | tr -d ' ')
  [ -d "$NM_PREFIX" ] && nb=$(ls "$NM_PREFIX" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$nb" -gt "$na" ]; then DEP_TREE="$NM_PREFIX"; else DEP_TREE="$NM_PKG"; fi
  [ "$((na + nb))" -gt 0 ] || die_red "dsh 依赖树定位失败（$NM_PKG 与 $NM_PREFIX 均空/缺）——安装不完整？"
  say "== 依赖树源=${DEP_TREE}（$([ "$nb" -gt "$na" ] && echo "$nb" || echo "$na") 项）=="
  case "$DSH_ROOT" in
    /opt/homebrew/lib/node_modules/*|/usr/local/lib/node_modules/*)
      warn "依赖树软链目标=全局安装（与生产控制台运行体共享目录）——stage 对其只读不写（取舍清单 a）" ;;
  esac
}

link_plugin() { # $1=包名 $2=插件目录名
  ln -sfn "$REPO/server/plugins/$2" "$PROF/node_modules/$1" \
    || die_red "插件软链失败：$1 → $REPO/server/plugins/$2"
}

# ---------- prepare ----------
cmd_prepare() {
  guards_start
  resolve_dsh_root
  local PROF_SRC="$REPO/server/profile"
  [ -d "$PROF_SRC" ] || die_red "仓库 profile 不存在：$PROF_SRC"
  PROF="$HOME_DIR/profiles/sandbar-stage"
  mkdir -p "$HOME_DIR/profiles" || die_red "profiles 目录创建失败"

  # profile 整目录重拷（与仓内 server/profile 保持同步），唯一差异=端口。
  # 3099 字样全局替换（含注释行——staged 产物红线口径=3099 字样清零，
  # 残留注释 3099 会让「产物无 3099」类回归闸误红；注释语义随替换更准：
  # stage 台确实挪到了所选口）。
  rm -rf "$PROF"
  cp -R "$PROF_SRC" "$PROF" || die_red "profile 拷贝失败：$PROF_SRC → $PROF"
  local PATCH="$PROF/cordis.patch.yml"
  sed "s/3099/$PORT/g" "$PATCH" > "$PATCH.tmp" && mv "$PATCH.tmp" "$PATCH"
  grep -q "^    port: $PORT\$" "$PATCH" \
    || die_red "端口补丁未生效——字面锚「    port: 3099」未命中（上游 profile 格式变了？请人工核对 ${PATCH}）"
  grep -q "3099" "$PATCH" && { die_red "staged profile 仍残留 3099 字样（上游 profile 出现了非端口位的 3099？请人工核对 ${PATCH}）"; return 2; }
  true

  # 五插件软链（真源 cordis.patch.yml 挂载名 ↔ server/plugins 目录）。
  mkdir -p "$PROF/node_modules"
  link_plugin sandbar-admin-ui        ui
  link_plugin sandbar-knowledge       knowledge
  link_plugin sandbar-providers       providers
  link_plugin sandbar-temporal-tools  temporal-tools
  link_plugin sandbar-workbench       workbench

  # 依赖树逐包软链（化石同构：scoped 目录实体化、包逐条软链；源=resolve_dsh_root 定位）。
  local NM="$HOME_DIR/profiles/node_modules"
  rm -rf "$NM"
  mkdir -p "$NM"
  local n=0 entry base sub
  for entry in "$DEP_TREE"/*; do
    base=$(basename "$entry")
    case "$base" in
      @*) mkdir -p "$NM/$base"
          for sub in "$entry"/*; do
            ln -sfn "$sub" "$NM/$base/$(basename "$sub")" && n=$((n + 1))
          done ;;
      *)  ln -sfn "$entry" "$NM/$base" && n=$((n + 1)) ;;
    esac
  done
  say "== 依赖树软链 $n 包 → $DSH_ROOT/node_modules（只读复用）=="

  # 凭据/配置/preset/工作区态：强制重拷（R2——绝不 skip-if-exists）。
  local f d
  for f in .credentials.yaml settings.yaml .anonymous-user-id; do
    if [ -f "$SRC_HOME/$f" ]; then
      cp -f "$SRC_HOME/$f" "$HOME_DIR/$f" || die_red "凭据/配置重拷失败：$f"
    fi
  done
  chmod 600 "$HOME_DIR/.credentials.yaml" 2>/dev/null
  chmod 600 "$HOME_DIR/settings.yaml" 2>/dev/null
  for d in .agent-presets storages; do
    if [ -d "$SRC_HOME/$d" ]; then
      rm -rf "$HOME_DIR/$d"
      cp -R "$SRC_HOME/$d" "$HOME_DIR/$d" || die_red "目录重拷失败：$d"
    fi
  done
  say "== 凭据/配置/preset/工作区态已从 $SRC_HOME 强制重拷（fresh，R2）=="

  # sessions：skip-if-exists（R2 允许——人工测试数据稳定优先）。
  local SESS_DIR="${SESS_SRC:-$SRC_HOME/sessions}" name
  mkdir -p "$HOME_DIR/sessions"
  if [ -d "$SESS_DIR" ]; then
    ls -t "$SESS_DIR" | head -n "$SESSIONS_N" | while IFS= read -r name; do
      [ -n "$name" ] || continue
      if [ ! -e "$HOME_DIR/sessions/$name" ]; then
        cp -R "$SESS_DIR/$name" "$HOME_DIR/sessions/$name" && say "   + 会话 $name"
      else
        say "   = 会话 ${name}（已存在，跳过）"
      fi
    done
  else
    warn "会话源不存在：${SESS_DIR}（stage 将无旧会话数据，selfcheck 的 sessions 面会红）"
  fi
  say "== prepare 完成：$HOME_DIR =="
}

# ---------- URL 提取（R4c：失败响亮） ----------
extract_url() { # $1=log 文件 $2=起始行号（只看本台启动段）
  tail -n +"${2:-1}" "$1" 2>/dev/null \
    | sed -n 's/^dsh web: \(http[^ ]*\).*$/\1/p' | tail -n 1
}

cmd_url_internal() { # 打印 URL+横幅；失败由调用方决定是否致命
  local URL LOG="$HOME_DIR/console.log"
  URL=$(extract_url "$LOG" 1)
  if [ -n "$URL" ]; then
    say "   $URL"
  else
    warn "console.log 里没提取到 dsh web: URL（字面锚脱钩？log 尾：）"
    tail -n 5 "$LOG" 2>/dev/null | sed 's/^/      /' >&2
  fi
}

# ---------- start ----------
cmd_start() {
  # 幂等检查先行（必须先于 guards_start：台在跑时端口正是被本台占着，
  # 先跑端口护栏会把幂等重入误拒成「端口被占」——实弹抓到后前置）。
  [ -d "$HOME_DIR" ] && HOME_DIR=$(cd "$HOME_DIR" && pwd -P)
  if [ -f "$HOME_DIR/stage.pid" ]; then
    local PID0 ROW0 CLS0
    PID0=$(cat "$HOME_DIR/stage.pid" 2>/dev/null || true)
    if [ -n "${PID0:-}" ] && kill -0 "$PID0" 2>/dev/null; then
      # 幂等重入同样核对本台锚（同 stop 杀前核对）：pid 活着≠本台——盲信会把
      # 无关进程误报成「已在跑」，URL 也跟着给错。
      if ! ps_refresh; then
        die_red "进程表不可读（ps 盲），在跑 pid=${PID0} 归属核对不了——fail-closed 不起台。请人工核对 ${HOME_DIR}/stage.pid 与端口 ${PORT}"
      fi
      ROW0=$(pid_class "$PID0")
      CLS0=$?
      if [ "$CLS0" -eq 0 ]; then
        say "== stage 已在跑（pid=${PID0}，锚命中），不重复启动 =="
        cmd_url_internal
        banner
        exit 0
      fi
      if [ "$CLS0" -eq 1 ]; then
        warn "pidfile 记 pid=${PID0} 无本台锚——非本台进程，按陈旧 pidfile 清理后正常起台。进程行：${ROW0}"
      fi
      rm -f "$HOME_DIR/stage.pid"   # 非本台 / 已不在表（kill -0 残像）：按陈旧清理
    else
      rm -f "$HOME_DIR/stage.pid"   # 陈旧 pidfile
    fi
  fi
  guards_start
  local L
  L=$(port_listener "$PORT")
  [ -z "$L" ] || die_usage "端口 $PORT 被占（$(busy_who "$PORT")）且无本台 pidfile——不抢占；换 --port 或人工辨认"

  # 缺件自动 prepare（profile/依赖树/软链任一缺失）。
  if [ ! -d "$HOME_DIR/profiles/sandbar-stage/node_modules/sandbar-workbench" ] \
     || [ ! -d "$HOME_DIR/profiles/node_modules" ]; then
    say "== 关键件缺失，先 prepare =="
    cmd_prepare
  fi
  # 既有 profile 端口与 --port 漂移自动同步（实弹踩坑：上次 prepare 用了默认
  # 口、本次 start 换口 → dsh 起在 prepare 口、start 在 --port 上等成误判）。
  # profile = server/profile + 端口补丁的派生物，刷新派生物无信息丢失；
  # log 一行防静默。
  local PF="$HOME_DIR/profiles/sandbar-stage/cordis.patch.yml"
  if [ -f "$PF" ] && ! grep -q "^    port: $PORT\$" "$PF"; then
    local OLD_PORT
    OLD_PORT=$(sed -n 's/^    port: \([0-9]*\)$/\1/p' "$PF" | tail -n 1)
    sed "s/^    port: ${OLD_PORT}$/    port: $PORT/" "$PF" > "$PF.tmp" && mv "$PF.tmp" "$PF"
    say "⚠ profile 端口 ${OLD_PORT} ≠ --port ${PORT}：已同步（dsh 将起在 ${PORT}）"
  fi
  resolve_dsh_root

  local CONSOLE_LOG="$HOME_DIR/console.log" MARK PID OPEN="" i URL
  printf '\n==== stage_console start %s (port=%s, dsh=%s) ====\n' \
    "$(date '+%F %T')" "$PORT" "$DSH_ROOT" >> "$CONSOLE_LOG"
  MARK=$(wc -l < "$CONSOLE_LOG" | tr -d ' ')
  [ "$OPEN_FLAG" = "--no-open" ] && OPEN="--no-open"

  # spawn：python3 setsid 让 dsh 自成进程组（pid=pgid），stop 可整组收割（R3）。
  DSH_HOME="$HOME_DIR" nohup python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' \
    "$DSH_BIN" --profile sandbar-stage $OPEN >> "$CONSOLE_LOG" 2>&1 &
  PID=$!
  printf '%s\n' "$PID" > "$HOME_DIR/stage.pid"
  say "== 起台中：pid=${PID}（进程组）→ $CONSOLE_LOG =="

  local CAP="${SANDBAR_STAGE_CONSOLE_UP_CAP_S:-120}"
  i=0
  while [ "$i" -lt "$CAP" ]; do
    [ -n "$(port_listener "$PORT")" ] && break
    if ! kill -0 "$PID" 2>/dev/null; then
      kill_group "$PID" KILL
      rm -f "$HOME_DIR/stage.pid"
      die_red "dsh 进程启动即退出（pid=${PID}）——console.log 尾 20 行：
$(tail -n 20 "$CONSOLE_LOG")"
    fi
    i=$((i + 1))
    sleep 1
  done

  if [ -z "$(port_listener "$PORT")" ]; then
    # R3①：等端口超时 = 杀自起进程组，不留悬空进程（台没起来就是坏的）。
    kill_group "$PID" TERM
    sleep 2
    kill -0 "$PID" 2>/dev/null && kill_group "$PID" KILL
    rm -f "$HOME_DIR/stage.pid"
    die_red "起台失败：${CAP}s 内端口 ${PORT} 未就绪——已停掉自起进程。console.log 尾 20 行：
$(tail -n 20 "$CONSOLE_LOG")"
  fi

  # 端口已就绪：URL 行单独宽限（实测存在「台好了但 dsh web: 行迟到」的瞬态；
  # R4c 不静默：宽限后仍无 URL = 响亮红）。gen17 收口：URL 静默同样是「台没起
  # 成」的终态，与端口未就绪超时路同构收台——杀自起组+清 pidfile，绝不留监听
  # 态无头台（否则调用方重试即撞「端口已被占用」）。慢台误杀由宽限覆盖：GRACE
  # 秒仍无 URL 行即真静默，瞬态迟到早已收敛。
  URL=""
  local G=0
  local GRACE="${SANDBAR_STAGE_CONSOLE_URL_GRACE_S:-20}"
  while [ "$G" -lt "$GRACE" ]; do
    URL=$(extract_url "$CONSOLE_LOG" "$MARK")
    [ -n "$URL" ] && break
    G=$((G + 1))
    sleep 1
  done
  if [ -z "$URL" ]; then
    kill_group "$PID" TERM
    sleep 2
    kill -0 "$PID" 2>/dev/null && kill_group "$PID" KILL
    rm -f "$HOME_DIR/stage.pid"
    die_red "台已在端口 ${PORT} 就绪，但 ${GRACE}s 内 log 未出现「dsh web: http」行（上游文案变化或输出缓冲？R4c 不静默）——已停掉自起进程。console.log 尾 20 行：
$(tail -n 20 "$CONSOLE_LOG")"
  fi

  # URL 端口一致性（防「dsh 起在别的口、start 却绿灯」——实弹踩坑的第二半：
  # URL 字面提取不辨端口，台起在漂移口时误报成功）。不一致 = 杀组+响亮红。
  local URL_PORT
  URL_PORT="${URL#*://}"; URL_PORT="${URL_PORT%%/*}"; URL_PORT="${URL_PORT##*:}"
  if [ "$URL_PORT" != "$PORT" ]; then
    kill_group "$PID" TERM
    sleep 1
    kill -0 "$PID" 2>/dev/null && kill_group "$PID" KILL
    rm -f "$HOME_DIR/stage.pid"
    die_red "dsh 起在端口 ${URL_PORT}，与 --port ${PORT} 不一致——已杀自起进程（profile 端口漂移？请人工核对 ${PF}）"
  fi

  say ""
  say "✅ stage 控制台已就绪（dsh-root=${DSH_ROOT}）"
  say "   $URL"
  say ""
  banner
  say "   人工测试清单：${CHECKLIST}（checklist 子命令打印）"
  say "   自检：$0 selfcheck --home $HOME_DIR --port $PORT $TOKEN_ARG"
  say "   停台：$0 stop --home $HOME_DIR --port $PORT"
  exit 0
}

# ---------- stop ----------
cmd_stop() {
  guards_stop
  local PID="" ORPHANS op ROW CLS
  if [ -f "$HOME_DIR/stage.pid" ]; then
    PID=$(cat "$HOME_DIR/stage.pid" 2>/dev/null || true)
    if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
      # 杀前归属核对（头注「杀前归属核对」节；gen16 仲裁打回项）：pid 活着≠本台，
      # 盲信 pidfile 曾实弹误杀无辜 detached 进程。ps 盲=fail-closed 拒杀；
      # 非本台=点名+清 pidfile+不杀。
      if ! ps_refresh; then
        die_red "pid=${PID} 在跑但进程表不可读（ps 盲）——归属核对不了，fail-closed 拒杀（绝不盲信 pidfile）。请人工核对 ${HOME_DIR}/stage.pid 与端口 ${PORT} 后手动处置"
      fi
      ROW=$(pid_class "$PID")
      CLS=$?
      case "$CLS" in
        0)
          say "== stop：锚命中（pid=${PID} 是本台），TERM 进程组 =="
          kill_group "$PID" TERM
          local i=0
          while [ "$i" -lt 10 ] && kill -0 "$PID" 2>/dev/null; do
            sleep 0.5
            i=$((i + 1))
          done
          if kill -0 "$PID" 2>/dev/null; then
            say "== 5s 未退，KILL 进程组 ${PID} =="
            kill_group "$PID" KILL
            sleep 1
          fi
          if kill -0 "$PID" 2>/dev/null; then
            die_red "进程组 ${PID} 杀不掉——人工介入（勿盲杀）；端口 ${PORT} 状态：$(busy_who "$PORT")"
          fi
          say "== 进程组 ${PID} 已退 =="
          ;;
        1)
          warn "pidfile 记 pid=${PID}，但其进程无本台锚（DSH_HOME=${HOME_DIR} / ${HOME_DIR}/ 均未命中）——非本台进程，绝不杀；仅清 pidfile。进程行：${ROW}"
          ;;
        *)
          say "== pidfile 记 pid=${PID} 已不在进程表（kill -0 残像/恰退），清理 =="
          ;;
      esac
      rm -f "$HOME_DIR/stage.pid"
    else
      say "== pidfile 陈旧（pid=${PID:-?} 已不在），清理 =="
      rm -f "$HOME_DIR/stage.pid"
    fi
  fi

  # 孤儿检测（R3②）：锚精确命中本 home 的才补杀；其余只点名。与主链同一判据
  # （gen16 盲信 pidfile 教训的收口）；ps 盲=跳过补杀只警示，绝不盲杀。
  if ps_refresh; then
    ORPHANS=$(our_pids | awk -v me="${PID:-}" '$1 != me')
    for op in $ORPHANS; do
      warn "发现本台残留进程 pid=${op}（DSH_HOME 锚定 ${HOME_DIR}）——补杀"
      kill -9 "$op" 2>/dev/null || warn "kill -9 ${op} 失败（可能已退出）"
    done
  else
    warn "进程表不可读（ps 盲）——孤儿检测此轮跳过（不杀任何进程）；残留请人工排查 ps aux | grep DSH_HOME"
  fi

  local FIN
  FIN=$(port_listener "$PORT")
  if [ -n "$FIN" ]; then
    warn "端口 $PORT 仍被监听（$(busy_who "$PORT")）——若非本台（docker 测试台/手工台），本壳绝不触碰，请人工辨认"
    exit 1
  fi
  if [ -n "$PID" ]; then
    say "== stop 完成：端口 $PORT 已释放，无残留进程 =="
  else
    say "== 无在跑 pidfile；端口 $PORT 空闲，无残留 =="
  fi
}

# ---------- status / url / selfcheck / checklist ----------
cmd_status() {
  guards_stop
  local PID L NOTE ROW
  PID=$(cat "$HOME_DIR/stage.pid" 2>/dev/null || true)
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    NOTE=""
    if ps_refresh; then
      ROW=$(pid_class "$PID")
      case "$?" in
        0) NOTE="，锚命中" ;;
        1) NOTE="，⚠ 无本台锚（pidfile 疑被篡改/复用）" ;;
        *) NOTE="（kill -0 残像）" ;;
      esac
    fi
    say "stage: 在跑（pid=${PID}，home=${HOME_DIR}${NOTE}）"
  else
    say "stage: 未在跑（home=${HOME_DIR}）"
  fi
  L=$(port_listener "$PORT")
  if [ -n "$L" ]; then
    say "端口 ${PORT}：被监听（$(busy_who "$PORT")）"
  else
    say "端口 ${PORT}：空闲"
  fi
}

cmd_url() {
  guards_stop
  local PID
  PID=$(cat "$HOME_DIR/stage.pid" 2>/dev/null || true)
  if [ -z "${PID:-}" ] || ! kill -0 "$PID" 2>/dev/null; then
    die_red "stage 未在跑（先 start）"
  fi
  local URL
  URL=$(extract_url "$HOME_DIR/console.log" 1)
  if [ -z "$URL" ]; then
    die_red "console.log 未提取到 dsh web: URL（字面锚脱钩？请看 $HOME_DIR/console.log）"
  fi
  say "stage 控制台（home=${HOME_DIR}）："
  say "   $URL"
  banner   # R7：警示到达面之一
}

cmd_selfcheck() {
  guards_stop
  [ -f "$LIB" ] || die_red "断言库缺失：$LIB"
  # 自动认证（0.1.5 实弹：web 需 token 兑换 cookie）——从 console.log 提取
  # 最近一次启动的 token 传给断言库；显式 --token 可覆盖（后者生效）。
  local AUTO_TOKEN=""
  local URL
  URL=$(extract_url "$HOME_DIR/console.log" 1)
  if [ -n "$URL" ] && [ "$URL" != "${URL%%token=*}" ]; then
    AUTO_TOKEN="--token ${URL##*token=}"
  fi
  say "== stage UI 面自检 → http://127.0.0.1:${PORT}/（home=${HOME_DIR}）=="
  local rc=0
  # shellcheck disable=SC2086  # 两个 token 参数故意词切分传给 node
  node "$LIB" --base-url "http://127.0.0.1:$PORT" --home "$HOME_DIR" $AUTO_TOKEN $TOKEN_ARG || rc=$?
  if [ "$rc" -eq 0 ]; then
    say "== 自检全绿 =="
  else
    say "== 自检非绿（rc=${rc}：1=断言红，2=环境红/用法红）==" >&2
  fi
  banner   # R7：警示到达面之一
  exit "$rc"
}

cmd_checklist() {
  [ -f "$CHECKLIST" ] || die_red "清单缺失：$CHECKLIST"
  cat "$CHECKLIST"
  banner   # R7：清单随打印带警示（文件顶部另有同款）
}

print_usage() {
  sed -n '2,75p' "$0" | sed 's/^# \{0,1\}//'
}

# ---------- dispatch ----------
case "$CMD" in
  start)     cmd_start ;;
  prepare)   cmd_prepare ;;
  stop)      cmd_stop ;;
  status)    cmd_status ;;
  url)       cmd_url ;;
  selfcheck) cmd_selfcheck ;;
  checklist) cmd_checklist ;;
  ''|help)   print_usage; exit 2 ;;
  -h|--help) print_usage; exit 0 ;;
  *)         die_usage "未知子命令：$CMD" ;;
esac
