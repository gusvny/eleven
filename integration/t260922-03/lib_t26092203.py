#!/usr/bin/env python3
"""t260922-03 共享夹具：npm/dsh 双桩（PATH 缝）+ 探针 live 档离线驱动。

两场景（sc_t260922_03_probe_live_green / sc_t260922_03_probe_live_cred_env）
共享本夹具。缝的选择（灰盒纪律：只用公开面）：

- **PATH 缝**：探针用 `npm install --prefix <p> @deepseek-ai/dsh@<ver>` 隔离安装，
  npm 取自 PATH——场景把自己的 shim 目录前置到 PATH，npm 桩对该调用形状落假前缀
  （package.json 钉同版本过 verify_install + .bin/dsh 桩），探针其余流程原样走。
  不依赖宿主真 npm/真网，也不依赖 --reuse-install（该旗标现况结构性失灵：探针每次
  mkdtemp 新 tmp，prefix 恒在自己的空目录里——已作缺陷上报，场景不锚它）。
- **dsh 桩**只演用户可感知面：退出码 / MISSING_CREDENTIAL 自报形状 / 会话产物落盘 /
  会话续写语义（create-or-resume：首次会话带 id 照样落产物，已有会话档则零新文件——
  与引擎「每次 spawn 都注入 DSH_HEADLESS_SESSION + resume patch」的生产形状同形）。
- 判据只落探针公开契约（CLI 旗标 / 退出码 / 台账行字面 / SANDBAR_PROBE_EXPECTED_ROUTE
  旋钮），不锚探针内部实现（守望轮询周期、字面量提取方式、文案措辞均可变）。

红线与边界：零真 npm 安装、零真网、不碰宿主全局 dsh、不碰 console 3099；全部写面
在 /tmp（$HOME 前提自供给的隔离 home 是唯一例外，见下）。会话超时旋钮压到 60s
（KI-078 教训：场景自己绝不留无界等待；探针看门狗正常时远用不到它）。

$HOME 前提自供给（镜 integration/t260922-07/sc_t260922_07_escape_out_of_roots.py
同款先例，其文件头「HOME 前提自供给」段即本段出处）：探针 live 档的越界写目标根
（$HOME/.sandbar-probe-escape，probe_dsh_seam.build_escape_main_repo）必须落在
「三根」（lane ∪ /tmp ∪ tmpdir）之外才有鉴别力；宿主 agent 沙箱（workspace-write）
不含 $HOME 时该建位必 OSError → 探针诚实自判 ENV 红、两条场景整场红——**归测试资产
供给面而非产品面**：修法是自建前提，不是放宽断言（断言面与 $HOME 形态完全无关，
探针照跑同一套判据）。真实 $HOME 可写→原样用（零副作用）；不可写→仓根 .sandbar/
下建隔离 home（.dsh 软链真源零拷贝：require_probe_env 与探针隔离 DSH_HOME 组装都
经它读到宿主配置；仓根在三根之外→越界位审计语义不变）；两形态皆不可写→ENV 红
exit 2 点名（透传不冒充，绝不静默降级成产品红）。
"""
from __future__ import annotations

import atexit
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

LIB_DIR = pathlib.Path(__file__).resolve().parent           # integration/t260922-03/
REPO_ROOT = LIB_DIR.parents[1]                              # 仓根（场景 cwd=仓根执行）
sys.path.insert(0, str(REPO_ROOT / "integration"))
from lib_env import env_fail  # noqa: E402  三态纪律：环境缺席=exit 2 点名，绝不静默

PROBE = REPO_ROOT / "integration" / "t260916-24" / "probe_dsh_seam.py"
STUB_VERSION = "9.9.9-probe-stub"        # --version 显式钉（探针 verify_install 对照面）
STUB_ROUTE = "stub-route-alpha"          # 桩自报的 provider 路由（ENV 点名判据）
STUB_VAR = "STUB_API_KEY"                # 桩自报的补救变量（ENV 补救路径判据）
STUB_PROVIDER, STUB_MODEL = "stub-provider", "stub-model"
ROUTE_ENV = "SANDBAR_PROBE_EXPECTED_ROUTE"   # 探针文档化旋钮：期望路由显式钉
MODE_ENV = "T26092203_STUB_MODE"             # 场景→桩选档旋钮（经探针 env 透传到达桩；
                                             #   该透传本身是票面验收③补救路径
                                             #   「export DEEPSEEK_API_KEY 重跑」的前提面）
PROBE_TIMEOUT_SEC = 120                      # 场景侧看门狗：探针卡死场景也不许挂死
ISO_HOME_PREFIX = "sc3-iso-home-"            # 隔离 home 前缀（与兄弟场景同前缀=同族可识别）


# 0.1.5 实测报错形状（票面原文的路由/变量位换成桩值，引号与分号结构保持——
# 探针归因锚的正是这个形状；实现换提取方式也不破判据：两个桩字面量必须在台账出现）
MISSING_CRED_LINE = (
    'dsh: MISSING_CREDENTIAL: llm-stub: no API key for provider route "%s"; '
    "store %s through the credentials service (dsh credentials set %s), "
    "or export %s and rerun." % (STUB_ROUTE, STUB_VAR, STUB_VAR, STUB_VAR)
)

# 桩落盘的 vN 会话产物（session.v3.jsonl，未压缩——探针两代口径的 vN 半边）：
# request/context 主 + request/header 备（主备合一面）+ assistant/message usage
# 全键含整型 cacheReadTokens（可选键在场且整型=PASS 半边）。
_SESSION_LINES = (
    '{"type":"request/context","data":{"provider":"%s","model":"%s"}}'
    % (STUB_PROVIDER, STUB_MODEL),
    '{"type":"request/header","data":{"header":{"config":'
    '{"provider":"%s","model":"%s"}}}}' % (STUB_PROVIDER, STUB_MODEL),
    '{"type":"assistant/message","data":{"usage":'
    '{"inputTokens":3,"outputTokens":5,"cacheReadTokens":0}}}',
)

# dsh 桩（sh，零依赖）三档：green=健康会话（落产物+泳道内写+越界不写+resume 零新
# 文件）；hang=自报 MISSING_CREDENTIAL 后挂住（票面「静默等到超时」的挂死形状）；
# fail=普通失败退出码 3（日志无凭据字面——产品红保全面）。
_STUB_TEMPLATE = """#!/bin/sh
# t260922-03 dsh 桩（$MODE_ENV 选档）——只演用户可感知面，见 lib_t26092203.py 头注
echo "stub-up mode=$T26092203_STUB_MODE session=${DSH_HEADLESS_SESSION:-none}"
case "$T26092203_STUB_MODE" in
  green)
    # 首次/续跑的判据=**本会话档是否已存在**（create-or-resume 真语义），不是「有无
    # DSH_HEADLESS_SESSION」——引擎每次 spawn 都注入该 env + resume patch（
    # agent_activities.py:2656-2675 无条件），首次会话同样带 id；拿「有无 id」当
    # 首次判据=把生产形状误判成续跑（t260922-03 场景 260923 假红根因）。
    if [ ! -f "$DSH_HOME/sessions/session.v3.jsonl" ]; then
      mkdir -p "$DSH_HOME/sessions" || exit 4
      printf '%s\\n' \\
        '_L1_' '_L2_' '_L3_' > "$DSH_HOME/sessions/session.v3.jsonl" || exit 4
      printf 'ok\\n' > ./probe_write_here.txt || exit 4
    fi
    exit 0 ;;
  hang)
    printf '%s\\n' '_MISSING_'
    sleep 300
    exit 0 ;;
  fail)
    printf '%s\\n' 'stub diagnostic: session failed (no credential literal on this face)'
    exit 3 ;;
  *)
    printf '%s\\n' "stub: unknown T26092203_STUB_MODE=$T26092203_STUB_MODE"
    exit 9 ;;
esac
"""

# npm 桩（sh，PATH 缝）：只实现探针的调用形状「install --prefix <p>
# @deepseek-ai/dsh@<ver> …」——落假前缀（package.json 钉版本 + .bin/dsh 桩）后
# exit 0；其余形状 fail-closed 报错退出 1（绝不静默假装装好）。
_NPM_SHIM = """#!/bin/sh
# t260922-03 npm 桩（PATH 缝）——见 lib_t26092203.py 头注
prefix=""; ver=""
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) prefix="$2"; shift ;;
    @deepseek-ai/dsh@*) ver="${1#@deepseek-ai/dsh@}" ;;
  esac
  shift
done
if [ -z "$prefix" ] || [ -z "$ver" ]; then
  echo "npm-shim: 只支持 install --prefix <p> @deepseek-ai/dsh@<ver> 形状（收到: $*）" >&2
  exit 1
fi
mkdir -p "$prefix/node_modules/@deepseek-ai/dsh" "$prefix/node_modules/.bin" || exit 1
printf '{"name": "@deepseek-ai/dsh", "version": "%s"}\\n' "$ver" \\
  > "$prefix/node_modules/@deepseek-ai/dsh/package.json" || exit 1
cp "$(dirname "$0")/dsh-stub" "$prefix/node_modules/.bin/dsh" || exit 1
chmod 755 "$prefix/node_modules/.bin/dsh"
echo "npm-shim: stub install @deepseek-ai/dsh@$ver (mode=$T26092203_STUB_MODE)"
"""


def _home_writable(home):
    """$HOME 可写性原子探针：mkdtemp 建删零残留；OSError=不可写（兄弟场景同款判据）。"""
    try:
        d = tempfile.mkdtemp(prefix=".t26092203-home-probe-", dir=str(home))
    except OSError:
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


_ISO_HOME = {"dir": None, "prev": None}


def _iso_home_cleanup():
    """隔离 home 回收（全终态：正常/报错/提前 sys.exit 都经 atexit 走到；父目录空则移除，
    非空=兄弟场景在用，留着不吞别人的目录）。"""
    d = _ISO_HOME.get("dir")
    if not d:
        return
    _ISO_HOME["dir"] = None
    shutil.rmtree(str(d), ignore_errors=True)
    try:
        pathlib.Path(d).parent.rmdir()
    except OSError:
        pass
    prev = _ISO_HOME.get("prev")
    if prev is None:
        os.environ.pop("HOME", None)
    else:
        os.environ["HOME"] = prev


def ensure_probe_home():
    """探针 $HOME 前提自供给（见模块头注；归测试资产供给面，断言面零改动）。

    返回 (home, isolated)：isolated=True=本次自建隔离 home（已置 os.environ['HOME']）；
    两形态皆不可写→(None, False)，调用方按环境红收口（不吞不冒充）。幂等：已可写则零副作用。"""
    real = pathlib.Path.home()
    if _home_writable(real):
        return real, False
    try:
        base = REPO_ROOT / ".sandbar"          # 仓根 .sandbar（gitignored；兄弟场景同落位）
        base.mkdir(parents=True, exist_ok=True)
        iso = pathlib.Path(tempfile.mkdtemp(prefix=ISO_HOME_PREFIX, dir=str(base)))
    except OSError:
        return None, False
    try:
        if (real / ".dsh").exists():
            os.symlink(str(real / ".dsh"), str(iso / ".dsh"))
    except OSError:
        shutil.rmtree(str(iso), ignore_errors=True)
        return None, False
    _ISO_HOME["dir"] = str(iso)
    _ISO_HOME["prev"] = os.environ.get("HOME")
    os.environ["HOME"] = str(iso)
    atexit.register(_iso_home_cleanup)
    # 前缀非 '[' 起首（t260921-06 词面前缀纪律：'[' 起首行会被规范行解析器当候选）
    print("T26092203_ISO_HOME: 真实 $HOME 不可写（宿主沙箱 workspace-write 等）——"
          "场景自建仓根隔离 HOME 跑同判据：%s（.dsh 软链真源；三根之外，断言面无关）"
          % iso, flush=True)
    return iso, True


def require_probe_env():
    """场景前置在位性（缺=ENV 红 exit 2 点名，绝不静默降级）。
    npm 不在此列：由 PATH 缝的 npm 桩供给，判据面不依赖宿主 npm。
    首步=$HOME 前提自供给（探针越界写目标根建于 $HOME 之下；两形态皆不可写=ENV 红点名）。"""
    home, isolated = ensure_probe_home()
    if home is None:
        env_fail("无可用 $HOME 建探针越界写目标根（%s）：真实 $HOME 与仓根 .sandbar/ "
                 "隔离位均不可写——环境态（探针越界子用例无目标位），非产品红"
                 % (pathlib.Path.home() / ".sandbar-probe-escape"))
    if not PROBE.is_file():
        env_fail("缺被测探针 %s" % PROBE)
    if not shutil.which("zstd"):
        env_fail("缺 zstd（探针 which_or_env_fail 同名面；缺了探针必出 ENV 行）")
    dsh_home = pathlib.Path.home() / ".dsh"      # 隔离态下经软链读同一真源
    for rel, is_dir in (("profiles/sandbar-headless", True), ("settings.yaml", False),
                        (".credentials.yaml", False)):
        p = dsh_home / rel
        if not (p.is_dir() if is_dir else p.is_file()):
            env_fail("缺 ~/.dsh/%s（探针隔离 home 组装前置；宿主 dsh 环境未配）" % rel)


def _stub_body():
    return (_STUB_TEMPLATE
            .replace("$MODE_ENV", MODE_ENV)
            .replace("_L1_", _SESSION_LINES[0])
            .replace("_L2_", _SESSION_LINES[1])
            .replace("_L3_", _SESSION_LINES[2])
            .replace("_MISSING_", MISSING_CRED_LINE))


def run_probe(mode, timeout=PROBE_TIMEOUT_SEC):
    """探针 live 档直跑（CLI 公开面：--version 显式钉；npm 经 PATH 缝桩供给）。
    返回 (rc, stdout, stderr, 墙钟秒, 场景临时目录)；rc=None=场景看门狗收割（挂死形状）。"""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26092203-scene-"))
    shim_bin = tmp / "shim-bin"
    shim_bin.mkdir()
    stub = shim_bin / "dsh-stub"
    stub.write_text(_stub_body(), "utf-8")
    stub.chmod(0o755)
    shim = shim_bin / "npm"
    shim.write_text(_NPM_SHIM, "utf-8")
    shim.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(shim_bin) + os.pathsep + env.get("PATH", "")
    env[MODE_ENV] = mode
    env[ROUTE_ENV] = "%s/%s" % (STUB_PROVIDER, STUB_MODEL)
    env["SANDBAR_PROBE_SESSION_TIMEOUT_SEC"] = "60"   # 上界封顶：守望坏掉也不空等 900s
    cmd = [sys.executable, str(PROBE), "--version", STUB_VERSION]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True,
                           text=True, timeout=timeout)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return None, "", ("探针 %ds 未返回（场景看门狗收割）——凭据缺失挂死形状仍在" % timeout), \
               time.monotonic() - t0, tmp
    return rc, out, err, time.monotonic() - t0, tmp


def probe_tmp_of(out):
    """从探针 stdout 提取其工作目录（资源回收检查的精确锚；格式漂移=None→检查降级）。"""
    m = re.search(r"工作目录：(\S+?)（", out)
    return m.group(1) if m else None


def stub_orphans(out, grace_sec=1.5):
    """探针退出后是否残留桩进程（按探针自报的临时目录路径精确匹配，零误伤并行面）。
    返回 (pids, note)；note 非 None=检查未执行（降级说明，不作 FAIL 依据）。"""
    tmp_path = probe_tmp_of(out)
    if not tmp_path:
        return [], "探针 stdout 无工作目录行（输出格式漂移？）——孤儿检查降级跳过"
    if not shutil.which("pgrep"):
        return [], "pgrep 缺席——孤儿检查降级跳过"
    time.sleep(grace_sec)
    p = subprocess.run(["pgrep", "-f", tmp_path], capture_output=True, text=True)
    return [x for x in p.stdout.split() if x.strip()], None


def reap_orphans(pids):
    """孤儿清理（SIGTERM，先于报告；不用 pkill 字面，进程面只碰精确匹配的桩 pid）。"""
    import signal as _signal
    for pid in pids:
        try:
            os.kill(int(pid), _signal.SIGTERM)
        except (ValueError, OSError):
            pass


def cleanup(tmp: pathlib.Path):
    shutil.rmtree(str(tmp), ignore_errors=True)
