#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docker 测试舞台单点入口（t260904-19）：全仓唯一搭台方式。

工单背景：自搭进程舞台（随机端口临时控制台 / bench.py 槽位 temporalite / capture-lane
自搭 boot）与 docker 测试台双轨并存——本文件收拢为单轨：一切需要舞台的场景经本模块
搭台（同一 compose 文件 server/docker-compose.test.yml），每台独立 compose 工程
名 + 独立端口档 + 独立容器名/卷前缀，并行互不撞。

子命令：
  up --project <名> [--services temporal|dsh|full] [--namespace <ns>]
     [--fixtures-dir <宿主目录>] [--profile-dir <宿主目录>] [--repo-dir <宿主目录>]
     [--timeout <sec>]        起台；stdout 回 JSON {project,console,temporal,...}
     [--nm-repo-dir <dir>]    插件依赖树（profile/node_modules 装齐者；缺省=泳道缺
                              依赖时回落主树）。与 --repo-dir（被测树）解耦。
  ensure --project <名> [--keep] [...同 up 旗标]   幂等确保：健康台复用；半残拆重起；
                              --keep=在跑台不拆不换（供给台语义，撞车时复测健康再试）
  down --project <名>       拆台（down -v + 零残留核验）；幂等，不存在亦 0
  selftest                  白盒自测（不碰 docker）：禁区排除/档位锁/畸形输入拒收

退出码（三态契约，integration/README.md）：
  0=ok；2=ENV_FAIL（docker 缺席/镜像缺席/起台不健康/端口段耗尽——文案点名缺什么）；
  3=环境冲突（显式指定端口被占，不对抗）；64=用法/畸形输入（场景代码 bug 级）。

## 故障模式取舍清单（review C1：对照 bench.py 槽位制 / capture-lane 自搭台逐项声明）

| 旧舞台故障模式 | 本模块处置 | 取舍 |
| --- | --- | --- |
| 端口撞车（钉死端口） | 档位 flock 原子预留 + 禁区排除 + bind 探测 | 锁贯穿「探测→compose up→健康」窗口，释放前端口已被 daemon 真绑定=闭 TOCTOU |
| 并发串台 | -p 工程名 + 独立容器名 + 独立卷前缀 + 档位锁 | 隔离粒度升到容器级 |
| 持有者崩溃锁不释 | 锁 fd 只在本进程，进程死=内核收 fd=锁自释；若死前容器已绑端口，后来者 bind 探测见忙即滑档 | 不沿用 pass_fds 移交（docker 化后无长命子进程可托管），语义等价 |
| teardown 重入崩溃 | down 幂等：工程不存在/容器已清均 0 退出，可三连 | 沿用 |
| detached 进程泄漏 | 不带：容器由 docker daemon 持有、无宿主孙进程树，down 即全灭；本模块自身不留后台进程 | docker 化根除该故障面（声明非遗漏） |
| 起服务超时无诊断 | 超时带 `docker compose logs` 尾部（2000 字节口径）+ 就地 down -v 清场再退 | 沿用 bench.py 口径 |
| 误连生产 fail-closed | 禁区硬排除 {3099,3199,7233,8233,17233,18233} + 起台后 JSON 端口 ∉ 生产端口自检；python 审计钩子不带（容器内出网由 compose 网络拓扑约束，宿主 socket 钩子无观测面——场景侧 bench.assert_not_production 沿用） | 钩子搬进本模块=假覆盖，如实不带 |
| preset 不合拒跑 | 不带：留在 capture-lane（台与证据语义分层） | 拒跑门不搬 |
| capture-lane 五路径终态回收 | 本模块 CLI 侧：正常/报错/超时/SIGINT/SIGTERM 全走 down -v 清场 | boot 进程组 kill 半边随自搭台退役（无 boot 子进程） |

状态与锁：
  锁/状态根 = $SANDBAR_STAGE_LOCK_DIR > ~/.sandbar/test-stages > 平台临时区回落
  （回落打印 stderr 一行，不静默——沿 bench_root 纪律）。band-<n>.lock 为档位锁；
  project-<名>.json 为在跑台状态（ensure 复用凭据）。
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import pathlib
import re
import signal
import tempfile
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO / "server" / "docker-compose.test.yml"
TEMPORAL_IMAGE = "test-temporal:cli-1.8.3"
TEMPORAL_BUILD_SCRIPT = "server/build-test-temporal.sh"
DSH_IMAGE = "test-dsh:dsh-0.1.1-rc.2"          # 260908：dsh 烤进镜像，起台免每台联网 npm
DSH_BUILD_SCRIPT = "server/build-test-dsh.sh"

# 禁区：生产三口（3099/7233/8233）+ 缺省测试台三口（3199/17233/18233）。
# 档位分配永不返回禁区端口；显式 env 指定禁区端口=拒收。
FORBIDDEN_PORTS = {3099, 3199, 7233, 8233, 17233, 18233}
PROD_PORTS = {3099, 7233, 8233}          # 生产面（bench.PROD_PORTS 同口径 + 3099 console）
DEFAULT_CONSOLE_PORT, DEFAULT_TEMPORAL_PORT, DEFAULT_TEMPORAL_UI_PORT = 3199, 17233, 18233

# 端口档位：21000 起每档 10 宽（console=+0 / temporal=+1 / ui=+2）。
# 档位基址在常见内核临时端口区间（Linux 32768+ / macOS 49152+）之下，结构性安全；
# 运行时再读 ip_local_port_range 剔除重叠（读不到=跳过该纵深防御，不单点依赖）。
BAND_BASE, BAND_STEP, BAND_COUNT = 21000, 10, 400
SLOT_OFFSET = {"console": 0, "temporal": 1, "ui": 2}

PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
DEFAULT_TIMEOUT = 600          # 健康等待上限（盖过 dsh 容器首装 npm i + apt 的实测预算）
_STOP_TIMEOUT = 120            # compose down 上限

EXIT_OK, EXIT_ENV, EXIT_CONFLICT, EXIT_FAIL, EXIT_USAGE = 0, 2, 3, 1, 64


class StageError(Exception):
    """带退出码语义的舞台错误：kind ∈ env/conflict/usage。"""

    def __init__(self, message, kind="env"):
        super().__init__(message)
        self.kind = kind
        self.exit_code = {"env": EXIT_ENV, "conflict": EXIT_CONFLICT, "usage": EXIT_USAGE}[kind]


# ---------------------------------------------------------------- 基础探测

def bind_free(port, host="127.0.0.1") -> bool:
    """端口空闲=能独占 bind（比 connect 探测强：半开/TIME_WAIT 也算不可用）。"""
    s = socket.socket()
    try:
        s.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_open(port, host="127.0.0.1", timeout=1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, int(port))) == 0
    finally:
        s.close()


def http_ok(url, timeout=2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500  # 控制台 4xx（如未就绪重定向）也算 HTTP 活着
    except Exception:
        return False


def ephemeral_range():
    """内核临时端口区间（best-effort，review N2：非 Linux 读不到=返回 None，不崩）。"""
    try:
        text = pathlib.Path("/proc/sys/net/ipv4/ip_local_port_range").read_text()
        lo, hi = (int(x) for x in text.split()[:2])
        return (lo, hi)
    except (OSError, ValueError):
        return None


def band_ports(band_index):
    base = BAND_BASE + band_index * BAND_STEP
    return {name: base + off for name, off in SLOT_OFFSET.items()}


def band_ports_ok(ports, ephemeral=None):
    """档位三端口全部可用（禁区/临时区间构造性排除 + bind 探测）。"""
    for p in ports.values():
        if p in FORBIDDEN_PORTS:
            return False
        if ephemeral and ephemeral[0] <= p <= ephemeral[1]:
            return False
        if not bind_free(p):
            return False
    return True


# ---------------------------------------------------------------- 锁与状态根

_LOCK_ROOT_CACHE = None


def lock_root() -> pathlib.Path:
    global _LOCK_ROOT_CACHE
    if _LOCK_ROOT_CACHE is not None:
        return _LOCK_ROOT_CACHE
    import tempfile
    env_val = os.environ.get("SANDBAR_STAGE_LOCK_DIR")
    candidates = []
    if env_val:
        candidates.append(("env", pathlib.Path(env_val)))
    candidates.append(("home", pathlib.Path.home() / ".sandbar" / "test-stages"))
    for source, root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            # 探针名带 pid+时钟：并发双起两进程互删同名探针会假报「不可写」（L1 并发用例实锤）
            probe = root / (".probe-%d-%d" % (os.getpid(), time.time_ns()))
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            _LOCK_ROOT_CACHE = root
            return root
        except OSError:
            if source == "env":
                raise StageError(
                    "SANDBAR_STAGE_LOCK_DIR=%s 不可写——env 指路的锁根必须可写" % env_val,
                    kind="usage")
            continue
    root = pathlib.Path(tempfile.gettempdir()) / "sandbar-test-stages"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise StageError("锁/状态根不可用：~/.sandbar 与临时区均不可写（%s）" % e, kind="env")
    print("[stage_docker] ~/.sandbar 不可写——锁根降级至 %s（明示降级，可用 "
          "SANDBAR_STAGE_LOCK_DIR 指定）" % root, file=sys.stderr)
    _LOCK_ROOT_CACHE = root
    return root


def _lock_band(band_index):
    """flock 独占档位（非阻塞）。成功返回 fd（调用方负责关闭=释放）。"""
    path = lock_root() / ("band-%d.lock" % band_index)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        raise StageError("档位锁文件不可建（%s: %s；锁根 %s）" % (type(e).__name__, e, lock_root()),
                         kind="env")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        os.close(fd)
        if e.errno in (errno.EACCES, errno.EAGAIN):
            return None
        raise
    return fd


def state_busy_ports():
    """在跑台（state 文件在 + 容器在）占用的端口面——choose_band 的第二道 busy 判据。
    bind 探测探不到「daemon 绑了但 holder 恰死」的窗口；state+容器双在=台活着，端口
    即便瞬时空也别碰。容器不在=陈旧 state（起台进程崩溃未 down）→ 就地清理不阻塞档位。"""
    busy = set()
    for f in lock_root().glob("project-*.json"):
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
            project = st.get("project")
            if not project:
                continue
            if residue_containers(str(project)):
                busy.update(int(p) for p in (st.get("ports") or {}).values())
            else:
                f.unlink()   # 陈旧 state：容器已灭，档位让出（崩溃残留自愈）
        except (OSError, ValueError):
            continue
    return busy


def choose_band(ephemeral=None):
    """原子预留一个端口档：flock 占位 → bind 探测 + 在跑台 state 面，全过才占用。
    返回 (band_index, ports, fd)。锁只护「探测→daemon 真绑定」窗口，up 完成即释放
    （此后由 daemon 绑定 + state 面接管避让——崩溃自释无死锁）。全档耗尽=StageError(env)。"""
    busy_state = state_busy_ports()
    for i in range(BAND_COUNT):
        ports = band_ports(i)
        if not band_ports_ok(ports, ephemeral):
            continue
        if set(ports.values()) & busy_state:
            continue
        fd = _lock_band(i)
        if fd is None:
            continue          # 档被并发者占走 → 滑下一档（非阻塞不排队，见头注取舍）
        # 锁内复核（以锁为界再探一次：并发者可能 probe 后才上锁/起台）
        if not band_ports_ok(ports, ephemeral) or (set(ports.values()) & state_busy_ports()):
            os.close(fd)
            continue
        return i, ports, fd
    raise StageError(
        "端口段耗尽：%d 档（%d~%d）全忙或被锁——查残留舞台（docker ps）与 "
        "SANDBAR_STAGE_LOCK_DIR=%s 下的锁锚" % (BAND_COUNT, BAND_BASE,
                                                BAND_BASE + BAND_COUNT * BAND_STEP, lock_root()),
        kind="env")


def state_path(project) -> pathlib.Path:
    return lock_root() / ("project-%s.json" % project)


def read_state(project):
    try:
        return json.loads(state_path(project).read_text(encoding="utf-8"))
    except Exception:
        return None


def write_state(project, data):
    state_path(project).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def clear_state(project):
    try:
        state_path(project).unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- docker 门槛

def _run(cmd, timeout, env=None, check=True):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=env if env is not None else dict(os.environ), cwd=str(REPO),
                          check=check)


def docker_present():
    try:
        _run(["docker", "info"], timeout=15)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def temporal_image_present():
    try:
        _run(["docker", "image", "inspect", TEMPORAL_IMAGE], timeout=15)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def dsh_image_present():
    try:
        _run(["docker", "image", "inspect", DSH_IMAGE], timeout=15)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def compose_env(project, services, ports, opts):
    """compose 渲染 env（docker-compose.test.yml 的 SANDBAR_TEST_* 旋钮）。"""
    env = dict(os.environ)
    env["SANDBAR_TEST_TEMPORAL_NAME"] = "%s-temporal" % project
    env["SANDBAR_TEST_DSH_NAME"] = "%s-dsh" % project
    env["SANDBAR_TEST_NAMESPACE"] = opts.get("namespace") or "suyou-test"  # naming-compat
    env["SANDBAR_TEST_TEMPORAL_PORT"] = str(ports["temporal"])
    env["SANDBAR_TEST_TEMPORAL_UI_PORT"] = str(ports["ui"])
    env["SANDBAR_TEST_CONSOLE_PORT"] = str(ports["console"])
    if opts.get("repo_dir"):
        env["SANDBAR_TEST_REPO_DIR"] = str(opts["repo_dir"])
    # 插件依赖树与被测树解耦（gen2 模型）：/repo=被测 workbench 树，
    # /repo-nm=profile/node_modules 装齐的树（缺省经 default_repo_dir 回落主树）。
    env["SANDBAR_TEST_NM_REPO_DIR"] = str(opts.get("nm_repo_dir") or default_repo_dir())
    # admin.log 遮蔽文件预创建（compose 单文件 bind 的宿主端必须存在，否则 docker
    # 会建出目录）：每台独立 tmp 副本，主树/泳道真 admin.log 不被测试触碰。
    admin_log = pathlib.Path(tempfile.gettempdir()) / ("sandbar-admin-log-%s.log" % project)
    if not admin_log.exists():
        admin_log.touch()
    env["SANDBAR_TEST_ADMIN_LOG"] = str(admin_log)
    # 容器端挂载点预创建（t260905-08 泳道实锤）：compose 对 /repo 与 /repo-nm 两处单文件
    # bind admin.log，而 /repo 挂 :ro——被挂树若无 server/admin.log，docker 建挂载点
    # =EROFS 起台炸（主树常在跑有此文件故 /repo-nm 侧从未露，泳道 worktree 作 /repo 即现形）。
    # *.log 是 gitignored 运行时物，touch 空文件不触交付面。
    for tree in (opts.get("repo_dir") or str(REPO), opts.get("nm_repo_dir") or default_repo_dir()):
        server_dir = pathlib.Path(tree) / "server"
        if server_dir.is_dir():
            shadow = server_dir / "admin.log"
            if not shadow.exists():
                shadow.touch()
    # 凭据物化（gen4）：容器台缺凭据=壳层准入遮罩全屏拦截指针（自搭台对照实锤）。
    # 源：env SANDBAR_TEST_CREDENTIALS > ~/.sandbar/projects/suyou > <repo>/.dsh > 主树 .dsh。
    cred_env = os.environ.get("SANDBAR_TEST_CREDENTIALS")
    cred_src = None
    for cand in ([cred_env] if cred_env else []) + [
            os.path.expanduser("~/.sandbar/projects/suyou/credentials.yaml"),
            str(REPO / ".dsh" / ".credentials.yaml"),
            "/Users/user/Documents/sandbar/.dsh/.credentials.yaml"]:
        if cand and os.path.isfile(cand):
            cred_src = cand
            break
    cred_dst = pathlib.Path(tempfile.gettempdir()) / ("sandbar-credentials-%s.yaml" % project)
    if cred_src:
        shutil.copyfile(cred_src, cred_dst)
        os.chmod(cred_dst, 0o600)  # dsh credentials-local fail-closed：644=拒启（gen4 实锤）
        env["SANDBAR_TEST_CREDENTIALS"] = str(cred_dst)
    # agent preset 物化（gen6：会话创建依赖 sandbar-integration preset；源=宿主  # naming-compat
    # ~/.dsh/.agent-presets/<项目> 或仓内 .dsh 同位）。缺失=空目录（preset 缺失
    # 诚实呈现），不阻塞起台。
    presets_dir = pathlib.Path(tempfile.gettempdir()) / ("sandbar-agent-presets-%s" % project)
    presets_dir.mkdir(parents=True, exist_ok=True)
    preset_name = "sandbar-integration"  # naming-compat
    for base in filter(None, [os.path.expanduser("~/.dsh/.agent-presets"),
                              str(REPO / ".dsh" / ".agent-presets"),
                              "/Users/user/Documents/sandbar/.dsh/.agent-presets"]):
        cand = pathlib.Path(base) / preset_name
        if cand.is_dir():
            dst = presets_dir / preset_name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(cand, dst)
            break
    env["SANDBAR_TEST_AGENT_PRESETS"] = str(presets_dir)
    if cred_src:
        print("注：容器台凭据物化自 %s（壳层准入面）" % cred_src)
    else:
        print("警告：未找到宿主凭据源——容器台可能弹壳层准入遮罩（弹层输入不可用面）")
    if opts.get("fixtures_dir"):
        env["SANDBAR_TEST_FIXTURES_DIR"] = str(opts["fixtures_dir"])
    if opts.get("profile_dir"):
        env["SANDBAR_TEST_PROFILE_DIR"] = str(opts["profile_dir"])
        env["SANDBAR_TEST_PROFILE"] = opts.get("profile_name") or "suyou"
        env["SANDBAR_TEST_PROFILE_SRC"] = "/profile"
    if opts.get("projects_dir"):
        env["SANDBAR_TEST_PROJECTS_DIR"] = str(opts["projects_dir"])
    if "temporal" not in services:
        # dsh-only 舞台：容器内引擎地址钉死不可达回环口（场景的「Temporal 不可达」
        # 断言面；127.0.0.1:1 在容器内恒拒绝）。绝不落生产 7233。
        env["SANDBAR_TEST_TARGET_HOST"] = "127.0.0.1:1"
    return env


def compose_cmd(project, args, env, timeout):
    try:
        return _run(["docker", "compose", "-f", str(COMPOSE_FILE), "-p", project] + args,
                    timeout=timeout, env=env, check=False)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise StageError("docker compose %s 失败：%s" % (" ".join(args), e), kind="env")


def compose_logs_tail(project, env, limit=2000):
    try:
        p = compose_cmd(project, ["logs", "--tail", "80"], env, timeout=30)
        return ((p.stdout or "") + (p.stderr or ""))[-limit:]
    except Exception:
        return ""


def residue_containers(project):
    """该工程名下的残留容器清单（零残留核验面）。"""
    try:
        p = _run(["docker", "ps", "-a", "--filter",
                  "label=com.docker.compose.project=%s" % project,
                  "--format", "{{.Names}}"], timeout=15)
        return [x for x in (p.stdout or "").splitlines() if x.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        return ["<docker ps 不可用>"]


# ---------------------------------------------------------------- 校验

def validate_project(project):
    if not PROJECT_RE.match(str(project or "")):
        raise StageError(
            "--project 不合法：%r（白名单 ^[a-z][a-z0-9-]{1,40}$：小写字母/数字/中划线）"
            % project, kind="usage")


def validate_service_set(services):
    if services not in ("temporal", "dsh", "full"):
        raise StageError("--services 不合法：%r（可选 temporal|dsh|full）" % services, kind="usage")
    return {"temporal": ["temporal"], "dsh": ["dsh"], "full": ["temporal", "dsh"]}[services]


def validate_dir(label, value, required=False):
    if not value:
        if required:
            raise StageError("%s 缺失（必填）" % label, kind="usage")
        return None
    p = pathlib.Path(value)
    if not p.is_dir():
        raise StageError("%s 不存在或不是目录：%s（检查项=%s）" % (label, value, label), kind="usage")
    return str(p.resolve())


def validate_port_env(name, value):
    """显式端口旋钮校验：数字/范围/禁区/被占——每条失败都点名检查项。"""
    if value is None:
        return None
    v = str(value).strip()
    if not v.isdigit():
        raise StageError("env %s 不合法：%r（必须是十进制端口数字）" % (name, value), kind="usage")
    n = int(v)
    if not (1 <= n <= 65535):
        raise StageError("env %s 越界：%d（1~65535）" % (name, n), kind="usage")
    if n in FORBIDDEN_PORTS:
        raise StageError("env %s=%d 落在禁区端口面（生产 3099/7233/8233 或缺省测试台 "
                         "3199/17233/18233）——舞台端口绝不占用禁区" % (name, n), kind="usage")
    if not bind_free(n):
        raise StageError("env %s=%d 已被占用（bind 探测失败）——环境冲突不对抗，换端口或清占用者"
                         % (name, n), kind="conflict")
    return n


def explicit_ports(services):
    """env 显式指定端口路径（全有或全无，杜绝半指定歧义）。"""
    names = {"console": "SANDBAR_TEST_CONSOLE_PORT", "temporal": "SANDBAR_TEST_TEMPORAL_PORT",
             "ui": "SANDBAR_TEST_TEMPORAL_UI_PORT"}
    values = {k: os.environ.get(v) for k, v in names.items()}
    given = {k: v for k, v in values.items() if v is not None}
    if not given:
        return None
    need = set()
    if "temporal" in services:
        need.update(("temporal", "ui"))
    if "dsh" in services:
        need.add("console")
    missing = need - set(given)
    if missing:
        raise StageError("端口旋钮半指定：给了 %s 但缺 %s（%s）——要么全给要么全不给"
                         % (sorted(set(given) & need), sorted(missing),
                            {v: k for k, v in names.items()}), kind="usage")
    return {k: validate_port_env(names[k], v) for k, v in given.items()}


# ---------------------------------------------------------------- 健康探针

def wait_temporal(port, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if port_open(port, timeout=1.0):
            return
        time.sleep(0.5)
    raise StageError("temporal %ds 内未就绪（127.0.0.1:%d）" % (timeout, port), kind="env")


def wait_console(port, timeout):
    t0 = time.time()
    url = "http://127.0.0.1:%d/" % port
    while time.time() - t0 < timeout:
        if http_ok(url):
            return
        time.sleep(1.0)
    raise StageError("console %ds 内未就绪（%s）" % (timeout, url), kind="env")


def stage_healthy(state):
    """ensure 复用判定：容器在跑 + 端口活着。"""
    if not state:
        return False
    if not residue_containers(state["project"]):
        return False
    for p in state["ports"].values():
        if not port_open(p, timeout=1.0):
            return False
    return True


# ---------------------------------------------------------------- namespace/SA

def resolve_temporal_cli():
    """temporal CLI 解析（沿 bench._resolve_asset 口径：env > 泳道位 > 主树回退）。"""
    # MissingAsset（env 钉指路不存在/泳道主树均缺）=明确不可得，不吞——env 钉是
    # L1「CLI 不可得」分支的依赖面（gen2 实锤：supply 自愈在泳道建 bin 软链后，
    # 吞异常回退泳道位会让 L1 假设漂移）。
    try:
        import bench  # noqa: PLC0415 同目录共享库
        return str(bench.resolve_temporal_bin())
    except bench.MissingAsset:
        return None
    except Exception:
        cand = REPO / "server" / "engine" / "bin" / "temporal"
        return str(cand) if cand.exists() else None


def register_namespace(ns, addr, timeout=30):
    """namespace + ProjectKey/EpicCode SA + 保留期（幂等；tolerate already exist）。
    返回 (ok, 说明)。temporal CLI 缺失/失败不阻塞起台——返回 False 由 JSON 如实呈现，
    依赖 SA 的场景（ticket-start 带 project）会在客户端大声报错（不静默）。"""
    cli = resolve_temporal_cli()
    if not cli or not pathlib.Path(cli).exists():
        return False, "temporal CLI 不可得（%s 缺失，env SANDBAR_TEMPORAL_BIN 可指路）——SA/保留期未注册" % cli
    last_err = ""

    def cli_ok(args, tolerate):
        # gen6 实锤：namespace 服务在 TCP 就绪后仍有短暂未就绪窗——失败短重试
        # （3 次×2s）；失败时附 CLI stderr 尾（原实现吞 stderr=「create 失败」
        # 无从归因，违反报错精确性纪律）。
        nonlocal last_err
        for attempt in range(3):
            try:
                p = subprocess.run([cli] + args, capture_output=True, text=True, timeout=timeout)
            except (subprocess.SubprocessError, OSError) as e:
                last_err = str(e)
                return False
            if p.returncode == 0:
                return True
            low = ((p.stdout or "") + (p.stderr or "")).lower()
            if any(t in low for t in tolerate):
                return True
            last_err = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()[-1][:160] if ((p.stderr or "") + (p.stdout or "")).strip() else "rc=%s 无输出" % p.returncode
            if attempt < 2:
                time.sleep(2)
        return False
    ok = cli_ok(["operator", "namespace", "create", ns, "--address", addr],
                ("already exist", "already created"))
    if not ok:
        return False, "namespace create 失败（ns=%s）：%s" % (ns, last_err)
    for name in ("ProjectKey", "EpicCode"):
        if not cli_ok(["operator", "search-attribute", "create", "--namespace", ns,
                       "--name", name, "--type", "Keyword", "--address", addr],
                      ("already exist", "already defined", "already registered")):
            return False, "SA %s 注册失败（ns=%s）：%s" % (name, ns, last_err)
    cli_ok(["operator", "namespace", "update", "--retention", "876000h",
            "--namespace", ns, "--address", addr], ())  # 保留期尽力而为，失败仅缺保留
    return True, "namespace+SA 就绪"


# ---------------------------------------------------------------- up / down / ensure

def _bootstrap_lane_nm():
    """泳道侧自举 profile 农场链（t260907-10 供给面自愈；gen4 补 headless 变体）。

    目录重构后农场链=五条相对软链（sandbar-* → ../../plugins/<目录>），纯运行期
    工件（gitignored），任何新泳道/新克隆都天然缺——供给必须自愈而非依赖手工预制。
    两变体同链（profile 与 profile-headless 的 node_modules 同款五链，cordis.patch.yml
    注释钦点「两份保持一致」）——只建 web 漏 headless 是 t260907-05 农场场景钉过的
    对抗面。幂等：链在即跳过；目标插件目录缺席（实现未落地态）不硬造，交由调用方
    报环境红。
    """
    farm = [("sandbar-admin-ui", "ui"), ("sandbar-workbench", "workbench"),
            ("sandbar-knowledge", "knowledge"), ("sandbar-providers", "providers"),
            ("sandbar-temporal-tools", "temporal-tools")]
    missing = [d for _, d in farm
               if not (REPO / "server" / "plugins" / d).is_dir()]
    if missing:
        print("注：泳道 plugins 缺 %s——农场链自举跳过（实现未落地态）" % missing)
        return False
    made = 0
    for prof in ("profile", "profile-headless"):
        nm = REPO / "server" / prof / "node_modules"
        nm.mkdir(parents=True, exist_ok=True)
        for pkg, d in farm:
            link = nm / pkg
            if not link.is_symlink():
                link.symlink_to("../../plugins/%s" % d)
                made += 1
    if made:
        print("注：泳道 profile*/node_modules 农场链自举 %d 条（两变体同款五链，"
              "sandbar-* → ../../plugins/*，运行期工件不入库）" % made)
    return True


def default_repo_dir():
    """REPO 挂载默认值（gen2 真容器实锤③）：容器内 dsh 是 npm 全局装的控制台，
    /repo 只供 profile+插件——泳道 worktree 恒缺 gitignored 的 profile/node_modules，
    挂泳道=插件解析失败（ERR_MODULE_NOT_FOUND）。故：泳道 profile 带插件依赖→挂
    泳道（缺则先自举农场链，t260907-10）；否则回落主树（git common dir 的父级，主树
    已装齐）。capture/bench 场景被测 workbench 不受影响（经 profile 软链显式指
    /repo/server/plugins/workbench，而该路径只在被测树作为 repo_dir 显式传入时才有
    意义——lib_fix15/bench-shot 均显式传）。"""
    nm_complete = all(
        (REPO / "server" / prof / "node_modules" / pkg).is_symlink()
        for prof in ("profile", "profile-headless")
        for pkg in ("sandbar-admin-ui", "sandbar-workbench", "sandbar-knowledge",
                    "sandbar-providers", "sandbar-temporal-tools"))
    # 完备性判据=两变体十链齐（gen4：单 profile 在而 headless 缺的半成品态曾短路
    # 跳过自举——t260907-05 农场场景 profile-headless 五链红即此因）
    if nm_complete or _bootstrap_lane_nm():
        return str(REPO)
    try:
        p = _run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                 timeout=15, check=False)
        main = os.path.abspath(os.path.join((p.stdout or "").strip(), ".."))
        if os.path.isdir(os.path.join(main, "server", "profile", "node_modules")):
            print("注：泳道缺 profile/node_modules——/repo 回落挂主树（插件依赖面）：%s"
                  % main)
            return main
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    raise StageError("泳道与主树均无 server/profile/node_modules——测试台插件依赖面"
                     "缺失；先在主树 server/profile 装依赖（npm install）", kind="env")


def _wait_diag(project, env):
    """wait 失败诊断附件：容器状态行+日志尾（gen2 伴随①：报错必须精确——
    「console 600s 未就绪」曾把 EROFS crash loop 误导向「慢」）。"""
    parts = []
    try:
        p = _run(["docker", "ps", "-a", "--filter",
                  "label=com.docker.compose.project=%s" % project,
                  "--format", "{{.Names}}: {{.Status}}"], timeout=15)
        parts.append("容器状态：" + (p.stdout.strip() or "（无容器）"))
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    tail = compose_logs_tail(project, env, limit=800)
    if tail:
        parts.append("日志尾：\n" + tail)
    return "\n".join(parts)


def do_up(project, services_list, opts, timeout, lock_fd=None):
    """起台本体（锁由调用方持有；失败路径就地 down -v 清场再抛）。"""
    ports = opts["ports"]
    env = compose_env(project, services_list, ports, opts)
    # 总时限预算（gen2 伴随②：--timeout 罩住 up+wait 全程——此前 up 与 wait 各自
    # 独立吃满 timeout，900s 参数实测可拖 20+ 分钟不自退）。清理面（down/logs）
    # 另有自身短超时，不计入预算。
    t0 = time.time()

    def _remaining(minimum=30):
        return max(minimum, int(timeout - (time.time() - t0)))

    def _wait(name, fn, port):
        try:
            fn(port, _remaining())
        except StageError as e:
            raise StageError("%s\n——诊断附件：\n%s" % (e, _wait_diag(project, env)),
                             kind="env") from None
    try:
        p = compose_cmd(project, ["up", "-d", "--quiet-pull"] + list(services_list),
                        env, timeout=timeout)
        if p.returncode != 0:
            tail = ((p.stdout or "") + (p.stderr or ""))[-2000:]
            raise StageError("docker compose up 失败（rc=%s）：\n%s" % (p.returncode, tail),
                             kind="env")
        if "temporal" in services_list:
            _wait("temporal", wait_temporal, ports["temporal"])
        if "dsh" in services_list:
            _wait("console", wait_console, ports["console"])
    except StageError:
        _do_down(project, env, quiet=True)
        raise
    except BaseException:
        _do_down(project, env, quiet=True)
        raise
    sa_registered, sa_note = (False, "本台无 temporal 服务，未注册 namespace/SA")
    if "temporal" in services_list:
        sa_registered, sa_note = register_namespace(env["SANDBAR_TEST_NAMESPACE"],
                                                    "127.0.0.1:%d" % ports["temporal"])
    # 红线自检：起台端口绝不含生产面
    for name, p in ports.items():
        if p in PROD_PORTS:
            _do_down(project, env, quiet=True)
            raise StageError("起台端口 %s=%d 落在生产端口面——红线自检失败，已就地清场"
                             % (name, p), kind="env")
    used = [k for k in ("temporal", "ui", "console") if k in ports
            and ("temporal" in services_list if k in ("temporal", "ui") else "dsh" in services_list)]
    state = {"project": project, "services": services_list, "namespace": env["SANDBAR_TEST_NAMESPACE"],
             "ports": {k: ports[k] for k in used}, "repo_dir": opts.get("repo_dir"),
             "ts": int(time.time()), "sa_registered": sa_registered, "sa_note": sa_note}
    write_state(project, state)
    return state


def _do_down(project, env=None, quiet=False):
    """down -v + 容器清单核验（内部版本：不清状态文件由 do_down 统一管）。"""
    env = env if env is not None else dict(os.environ)
    try:
        compose_cmd(project, ["down", "-v", "--remove-orphans", "--timeout", "30"],
                    env, timeout=_STOP_TIMEOUT)
    except StageError:
        if not quiet:
            raise


def do_down(project):
    """拆台：down -v + 零残留核验 + 清状态文件。幂等（工程不存在亦成功）。"""
    validate_project(project)
    if not docker_present():
        raise StageError("docker 不可用（docker info 失败）——拆台需要 docker", kind="env")
    env = dict(os.environ)
    env.setdefault("SANDBAR_TEST_TEMPORAL_NAME", "%s-temporal" % project)
    env.setdefault("SANDBAR_TEST_DSH_NAME", "%s-dsh" % project)
    compose_cmd(project, ["down", "-v", "--remove-orphans", "--timeout", "30"],
                env, timeout=_STOP_TIMEOUT)
    clear_state(project)
    residue = residue_containers(project)
    return {"project": project, "down": True, "residue": residue}


def do_ensure(project, services_list, opts, timeout, keep=False):
    """幂等确保：健康台复用；半残拆重起；--keep=不拆在跑台（N3：撞车先复测健康）。"""
    validate_project(project)
    state = read_state(project)
    if state and stage_healthy(state):
        state = dict(state)
        state["reused"] = True
        return state
    if state and keep and residue_containers(project):
        # --keep：在跑但不健康——不拆（可能他泳道同窗在用），如实报环境红（N3 兜底）
        raise StageError("供给台 %s 在跑但不健康（ports=%s）；--keep 语义不拆在跑台——"
                         "人工核查或去旗重跑" % (project, state.get("ports")), kind="env")
    if state:
        do_down(project)
    return do_up_public(project, services_list, opts, timeout)


def do_up_public(project, services_list, opts, timeout):
    """up 完整流程：校验 → docker/镜像门槛 → 端口（显式 env 或档位分配）→ 起台。"""
    validate_project(project)
    if not docker_present():
        raise StageError("ENV_FAIL: docker 不可用（docker info 失败）——本票测试台一律走 "
                         "docker；启动 Docker/OrbStack 后重试", kind="env")
    if "temporal" in services_list and not temporal_image_present():
        raise StageError(
            "ENV_FAIL: 测试镜像缺席：%s（本机自建镜像、无 registry 拉取）——"
            "先跑 sh %s 重建，再重试" % (TEMPORAL_IMAGE, TEMPORAL_BUILD_SCRIPT), kind="env")
    if "dsh" in services_list and not dsh_image_present():
        raise StageError(
            "ENV_FAIL: 测试镜像缺席：%s（本机自建镜像、无 registry 拉取；此前每台容器内"
            "联网 npm 装 dsh ~2 分钟，260908 起烤进镜像）——先跑 sh %s 重建，再重试"
            % (DSH_IMAGE, DSH_BUILD_SCRIPT), kind="env")
    ports = explicit_ports(services_list)
    lock_fd = None
    try:
        if ports is None:
            _, ports, lock_fd = choose_band(ephemeral_range())
        opts = dict(opts)
        opts["ports"] = ports
        return do_up(project, services_list, opts, timeout, lock_fd=lock_fd)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)   # daemon 已真绑定端口，释放后无冲突窗口（头注取舍）


# ---------------------------------------------------------------- selftest（白盒，不碰 docker）

def selftest():
    fails = []

    def ok(cond, label):
        print(("ok    " if cond else "FAIL  ") + label)
        if not cond:
            fails.append(label)

    # ① 禁区/临时区间构造性排除：全部档位端口永不落禁区与临时区间
    eph = ephemeral_range()
    all_ports = [p for i in range(BAND_COUNT) for p in band_ports(i).values()]
    ok(not (set(all_ports) & FORBIDDEN_PORTS),
       "全部 %d 个档位端口 ∩ 禁区端口 = ∅" % len(all_ports))
    if eph:
        overlap = [p for p in all_ports if eph[0] <= p <= eph[1]]
        ok(not overlap, "档位端口与内核临时区间 %s 零重叠（重叠 %d 个）" % (eph, len(overlap)))
    else:
        ok(True, "临时区间读取不可得（非 Linux）——纵深防御缺席不算红（N2）")
    ok(all(21000 <= p < BAND_BASE + BAND_COUNT * BAND_STEP for p in all_ports),
       "档位端口全部落在 %d~%d 预留窗内" % (BAND_BASE, BAND_BASE + BAND_COUNT * BAND_STEP))
    ok(len({tuple(sorted(band_ports(i).items())) for i in range(BAND_COUNT)}) == BAND_COUNT,
       "档位端口两两不重叠")

    # ② 档位锁互斥：同进程第二 OFD flock 必败（内核语义）
    fd = _lock_band(0)
    ok(fd is not None, "band-0 首次上锁成功")
    if fd is not None:
        ok(_lock_band(0) is None, "band-0 二次上锁非阻塞失败（互斥成立）")
        os.close(fd)
        fd2 = _lock_band(0)
        ok(fd2 is not None, "释放后 band-0 立即可复抢（崩溃自释语义）")
        if fd2 is not None:
            os.close(fd2)

    # ③ 畸形输入拒收（每条点名检查项，零副作用）
    for project in ("Bad_Name", "", "-x", "a" * 50, "大写"):
        try:
            validate_project(project)
            ok(False, "--project %r 应拒收" % project)
        except StageError as e:
            ok(e.kind == "usage" and "project" in str(e), "--project %r 拒收专名点 project" % project)
    for bad, why in (({"console": "abc"}, "非数字"), ({"console": "0"}, "越界"),
                     ({"console": "3099"}, "禁区"), ({"console": "70000"}, "超范围")):
        try:
            validate_port_env("SANDBAR_TEST_CONSOLE_PORT", list(bad.values())[0])
            ok(False, "端口 %r 应拒收（%s）" % (bad, why))
        except StageError as e:
            ok(True, "端口 %r 拒收（%s，kind=%s）" % (bad, why, e.kind))
    try:
        validate_dir("fixtures-dir", "/nonexistent-stage-dir-xyz")
        ok(False, "fixtures-dir 不存在应拒收")
    except StageError as e:
        ok(e.kind == "usage" and "fixtures-dir" in str(e), "fixtures-dir 拒收点名检查项")
    try:
        os.environ["SANDBAR_TEST_CONSOLE_PORT"] = "21001"  # 只给 console=半指定
        explicit_ports(("temporal",))
        ok(False, "端口半指定应拒收")
    except StageError as e:
        ok("半指定" in str(e), "端口半指定拒收文案可辨")
    finally:
        os.environ.pop("SANDBAR_TEST_CONSOLE_PORT", None)

    # ④ 服务集校验
    for bad in ("", "all", "temporal,dsh"):
        try:
            validate_service_set(bad)
            ok(False, "--services %r 应拒收" % bad)
        except StageError:
            ok(True, "--services %r 拒收" % bad)

    print(("SELFTEST 全绿" if not fails else "SELFTEST %d 项红" % len(fails)))
    return EXIT_FAIL if fails else EXIT_OK


# ---------------------------------------------------------------- CLI

def _parse_opts(argv, i, opts):
    flags = {"--namespace": "namespace", "--fixtures-dir": "fixtures_dir",
             "--profile-dir": "profile_dir", "--profile-name": "profile_name",
             "--repo-dir": "repo_dir", "--nm-repo-dir": "nm_repo_dir",
             "--services": "_services"}
    while i < len(argv):
        a = argv[i]
        if a in flags:
            opts[flags[a]] = argv[i + 1]
            i += 2
        elif a == "--timeout":
            try:
                opts["timeout"] = int(argv[i + 1])
            except (IndexError, ValueError):
                raise StageError("--timeout 需要整数秒", kind="usage")
            i += 2
        elif a == "--keep":
            opts["keep"] = True
            i += 1
        elif a.startswith("--"):
            raise StageError("未知旗标：%s" % a, kind="usage")
        else:
            raise StageError("多余位置参数：%s" % a, kind="usage")
    return opts


def main(argv):
    if not argv:
        print(__doc__)
        return EXIT_USAGE
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "selftest":
            return selftest()
        opts = {}
        i = 0
        if rest and not rest[0].startswith("--"):
            opts["project"] = rest[0]
            i = 1
        elif rest and rest[0] == "--project":
            opts["project"] = rest[1]
            i = 2
        opts = _parse_opts(rest, i, opts)
        project = opts.get("project")
        if cmd in ("up", "ensure"):
            if not project:
                raise StageError("%s 缺 --project <名>" % cmd, kind="usage")
            services = validate_service_set(opts.get("_services") or "temporal")
            timeout = opts.get("timeout") or DEFAULT_TIMEOUT
            clean_opts = {
                "namespace": opts.get("namespace"),
                "fixtures_dir": validate_dir("fixtures-dir", opts.get("fixtures_dir")),
                "profile_dir": validate_dir("profile-dir", opts.get("profile_dir")),
                "profile_name": opts.get("profile_name"),
                "repo_dir": validate_dir("repo-dir", opts.get("repo_dir")) or str(REPO),
                "nm_repo_dir": (validate_dir("nm-repo-dir", opts.get("nm_repo_dir"))
                                or default_repo_dir()),
                "projects_dir": opts.get("projects_dir") or os.environ.get("SANDBAR_TEST_PROJECTS_DIR"),
            }
            if cmd == "up":
                state = do_up_public(project, services, clean_opts, timeout)
            else:
                state = do_ensure(project, services, clean_opts, timeout, keep=opts.get("keep", False))
            print(json.dumps(state, ensure_ascii=False))
            return EXIT_OK
        if cmd == "down":
            if not project:
                raise StageError("down 缺 --project <名>", kind="usage")
            result = do_down(project)
            print(json.dumps(result, ensure_ascii=False))
            return EXIT_OK if not result["residue"] else EXIT_FAIL
        raise StageError("未知子命令：%s（可选 up/ensure/down/selftest）" % cmd, kind="usage")
    except StageError as e:
        print("STAGE_%s: %s" % (e.kind.upper(), e), file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("STAGE_INTERRUPT: 起台被中断（SIGINT）——就地清场", file=sys.stderr)
        return 130


def _signal_teardown(project_holder):
    """SIGTERM 路径：能拿到工程名就清场（四路径回收的信号腿）。"""
    def handler(signum, frame):
        project = project_holder.get("project")
        if project:
            try:
                do_down(project)
            except Exception:
                pass
        sys.exit(130)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handler)


if __name__ == "__main__":
    # 信号腿需要工程名——粗粒度：从 argv 抓 --project 后注册 handler。
    _holder = {}
    if "--project" in sys.argv:
        idx = sys.argv.index("--project")
        if idx + 1 < len(sys.argv):
            _holder["project"] = sys.argv[idx + 1]
            _signal_teardown(_holder)
    sys.exit(main(sys.argv[1:]))
