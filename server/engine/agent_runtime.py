# -*- coding: utf-8 -*-
"""agent 执行面传输层（t260913-04 容器化）：host=现状直跑 / docker=每票一容器。

单点职责（方案 gen1 D1–D9，review C1–C6 条款落点在注释里带 (C#)/(R#) 标记）：
  - spawn_agent：三分叉点（通用段/仲裁/验收走查）唯一的 agent 进程启动口；
  - ensure_container：每票一容器（确定性名 sandbar-agent-<ticket>，幂等自愈），
    挂载面白名单等值=【恰好泳道一项】（红线 2；C4）；
  - exec_agent：docker exec -w <泳道> + env 白名单（DSH_PERMISSION_MODE 等沙箱旋钮
    结构性禁入——红线 C 第一层）+ 容器内 supervisor（sandbar-exec，pgid 协议）；
  - AgentProc.reap：host=组粒度 killpg（复用 agent_activities._reap_agent_proc）；
    docker=容器内按组 TERM→KILL（KI-009 语义 1:1）；reap 绝不外抛（C6/R8）；
  - remove_container / gc_stale_containers：收口即拆 + 每票首活动扫孤儿（验收 G）；
  - sandbox_pin_yaml：容器执行面一次性钉死 patch 的【内容单点】（引擎 spawn 与
    场景/单测同源，防漂移）。容器内口径=宿主 260914 A 案：mode=danger-full-access
    （容器内全权），隔离由 docker 挂载面承担（容器只见本票泳道）；pin 钉死的是
    「模式字面量不被 env/profile 篡改」这件事本身。三重对抗已真探针实证（260913，见 D5）：
      env 面 DSH_PERMISSION_MODE=其他值 → 字面量压制；
      profile 层注入 disabled:true → 入口级 disabled:false 压制（config 内写无效）；
      settings 面注入 → 合成链整段无视。

本模块 stdlib-only（无 temporalio / 无仓内依赖）：integration 场景以系统 python3 直
import（t260907-06 lib 三态口径同款）。禁 import shared/agent_activities（前者体量大、
后者带 temporalio；host reap 走函数内迟 import 避免环）。
"""
from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ---- 旋钮（环境变量名/缺省值是契约面，改名=破兼容） ----
RUNTIME_ENV = "SANDBAR_AGENT_RUNTIME"
RUNTIMES = ("host", "docker")
DEFAULT_RUNTIME = "host"          # D6：存量语义冻结；生产接线=run_worker.sh 显式 docker
DOCKER_BIN_ENV = "SANDBAR_DOCKER_BIN"   # 单测注入 fake docker 的缝
DEFAULT_DOCKER_BIN = "docker"
IMAGE_ENV = "SANDBAR_AGENT_IMAGE"
# t260921-14 镜像同升（Q3=同升）：三处缺省同翻 0.1.5-rc.2-s1（本处+Dockerfile ARG+
# build_agent_image.sh，test_镜像版本三处同步机械防漂移）；回退=env 指回旧 tag
# （SANDBAR_AGENT_IMAGE=sandbar-agent:dsh-0.1.1-rc.2-s1，无需重建）或本行回改。
DEFAULT_AGENT_IMAGE = "sandbar-agent:dsh-0.1.5-rc.2-s1"
BASH_TIMEOUT_MS_ENV = "SANDBAR_AGENT_BASH_TIMEOUT_MS"
BASH_TIMEOUT_MS_DEFAULT = 900000  # D8：对齐引擎 SANDBAR_INTEG_CMD_TIMEOUT_SEC 缺省 900s（有界有源）

# docker CLI 调用超时（t260921-05 常量化：缺省=历史字面量逐字节不变，生产语义零变化；
# 提为常量只为单测悬挂子用例可 monkeypatch 收紧快测，不必真等 30s）
DOCKER_INFO_TIMEOUT_SEC = 15
DOCKER_RM_TIMEOUT_SEC = 30
DOCKER_PS_TIMEOUT_SEC = 30

CONTAINER_PREFIX = "sandbar-agent-"
LBL_TICKET = "sandbar.agent.ticket"
LBL_LANE = "sandbar.agent.lane"
LBL_PROJECT = "sandbar.agent.project"
EXEC_DIR_REL = ".sandbar/exec"    # pgid 档目录（宿主预建；SETTLE_PATHSPEC/path 闸已放行 .sandbar，review C4 已核）
HOME_IN_CONTAINER = "/tmp/agent-home"  # C4：运行期可写目录优先容器本地（/tmp 在沙箱写授予面内）
TMPDIR_IN_CONTAINER = "/tmp"
SANDBAR_EXEC_IN_CONTAINER = "/usr/local/bin/sandbar-exec"

# env 白名单（红线 C 第一层）：宿主 env 一律【不整包透传】；沙箱旋钮（DSH_PERMISSION_MODE、
# DSH_SANDBOX_* 等）永不入列——容器内有效模式由 sandbox_pin patch 字面量钉死（第二层）。
# t260925-08：调用方身份注入两键入列（字面量就地复制：本模块禁 import shared，等值由
# 单测 test_t260925_08 锁定 shared.CALLER_PROJECT_ENV / CALLER_SURFACE_ENV）——
#   SANDBAR_CALLER_PROJECT=项目 key（KI-119：泳道 agent 写操作身份机制注入）；
#   SANDBAR_CALLER_SURFACE="lane-agent"（注入面标签，identity_receipt 消费）。
ENV_ALLOWLIST = ("DSH_HOME", "DSH_HEADLESS_SESSION",
                 "SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_SURFACE")

REAP_TERM_TIMEOUT_SEC = 15.0      # 与 agent_activities.AGENT_REAP_TERM_TIMEOUT_SEC 同值同源语义
REAP_KILL_TIMEOUT_SEC = 5.0


class AgentRuntimeError(RuntimeError):
    """容器执行面 fail-closed 错误（点名根因与修复路径，绝不静默回落 host）。"""


def runtime_mode() -> str:
    """读 SANDBAR_AGENT_RUNTIME（缺省 host）。非法值=点名报错（不静默回落——拼写错误
    静默变 host = 沙箱面静默丢失，违反 fail-closed）。"""
    raw = (os.environ.get(RUNTIME_ENV) or "").strip().lower()
    if not raw:
        return DEFAULT_RUNTIME
    if raw not in RUNTIMES:
        raise AgentRuntimeError(
            "%s=%r 非法（合法值：%s）" % (RUNTIME_ENV, raw, "|".join(RUNTIMES)))
    return raw


def docker_bin() -> str:
    return os.environ.get(DOCKER_BIN_ENV) or DEFAULT_DOCKER_BIN


def agent_image() -> str:
    return os.environ.get(IMAGE_ENV) or DEFAULT_AGENT_IMAGE


def bash_timeout_ms() -> int:
    raw = os.environ.get(BASH_TIMEOUT_MS_ENV) or ""
    try:
        v = int(raw) if raw else BASH_TIMEOUT_MS_DEFAULT
    except ValueError:
        v = BASH_TIMEOUT_MS_DEFAULT
    return max(1000, v)


# ---- 容器内 dsh 版本实测（t260921-14 交付③：三面自检的容器实证面） ----
# 版本样 token（与 dsh_pin._VERSION_RE 同语义：semver 带预发布段；本模块禁仓内依赖
# 故就地复制——漂移由 tri_face 的 tag-derived vs 实测对账兜住，两处表达同一契约）。
_VERSION_LIKE_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
DSH_PROBE_CONTAINER_PREFIX = "sandbar-dsh-probe-"
DSH_PROBE_TIMEOUT_SEC = 60.0


def probe_image_dsh_version(image: str, docker_bin_override: Optional[str] = None,
                            timeout: float = DSH_PROBE_TIMEOUT_SEC) -> Dict[str, Any]:
    """一次性容器内实测 `dsh --version`（t260921-14）：tag-derived 是弱证据，实测防
    「tag 约定漂移无人知」（关 dsh_pin.image_tag_version 的 TODO(T3/Q3)）。

    观测面原语：任何失败都不外抛，返回 {"version": str|None, "state": "ok"|"error",
    "detail": str}——真正起容器失败自有 ensure_container/spawn 路径响亮。全终态回收：
    正常路径 --rm 自净；超时/异常路径 killpg 收割 docker run 客户端 + 按名
    `docker rm -f` 兜底（SIGKILL 客户端后容器可能残留至命令自然退出为止，按名强拆
    保证无孤儿）；容器名带 pid+毫秒唯一段，防并发/复跑撞名。docker_bin_override=
    单测注入缝（生产缺省走 docker_bin() 的 DOCKER_BIN_ENV 旋钮）。
    """
    dbin = docker_bin_override or docker_bin()
    name = "%s%d-%d" % (DSH_PROBE_CONTAINER_PREFIX, os.getpid(), int(time.monotonic() * 1000) % 100000)
    argv = [dbin, "run", "--rm", "--name", name, image, "dsh", "--version"]

    def _force_remove() -> None:
        try:
            subprocess.run([dbin, "rm", "-f", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           timeout=DOCKER_RM_TIMEOUT_SEC, check=False)
        except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass  # 兜底清理失败不外抛（观测面；残留容器由 gc_stale_containers 族按 label 收）

    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        _force_remove()
        return {"version": None, "state": "error",
                "detail": "起不了 docker run（镜像=%s）：%s" % (image, e)}
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL 后不该发生
            pass
        _force_remove()
        return {"version": None, "state": "error",
                "detail": "容器内 dsh --version 超时（>%ss，镜像=%s），进程组已收割+容器按名强拆"
                          % (timeout, image)}
    except BaseException:
        _force_remove()
        raise
    text = (out or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        return {"version": None, "state": "error",
                "detail": "容器内 dsh --version 退出码 %s（镜像=%s），输出=%r"
                          % (proc.returncode, image, text[:200])}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) != 1 or not _VERSION_LIKE_RE.match(lines[0]):
        return {"version": None, "state": "error",
                "detail": "容器内 dsh --version 输出非单行版本样（%d 行，镜像=%s）：%r"
                          % (len(lines), image, text[:200])}
    return {"version": lines[0], "state": "ok",
            "detail": "容器内实测 %s（镜像=%s）" % (lines[0], image)}


def sandbox_pin_yaml() -> str:
    """容器执行面一次性钉死 patch 内容单点（D5+D8；引擎 spawn 与场景/单测同源）。

    口径＝宿主 260914 A 案：**容器内全权（danger-full-access），隔离由挂载面承担**
    （容器只见本票泳道一项；挂载面守卫见 neglock 场景的「宿主边界不可达」子用例）。pin
    的其余防线全部保留：入口级 disabled: false（压 profile 层篡改）、workspaceRoot、
    bash 超时面、exec env 白名单（第二层防线，见 test_agent_runtime 红线 C）。

    必须用【入口级 disabled: false】而非 config.disabled——260913 真探针：profile 层
    注入 `disabled: true` 时 config 内补 false 不生效（入口级才赢），入口级钉 false 后
    被压制。workspaceRoot 一并写（C1：防同 id 整段替换丢授予面）。
    """
    return (
        "# 本文件由 agent activity 每次 spawn 时生成（容器执行面模式钉死+超时覆盖；"
        "真源=agent_runtime.sandbox_pin_yaml，方案 D5/D8，容器内口径=宿主 260914 A 案）。"
        "勿手改：每次 spawn 重写。\n"
        "# 对抗面实证（260913 探针）：env 面 DSH_PERMISSION_MODE 危险值被字面量压制；\n"
        "# profile 层 disabled:true 被入口级 disabled:false 压制；settings 面注入被无视。\n"
        "# 容器内=全权：边界不靠 dsh 沙箱，靠 docker 挂载面（容器只见本票泳道）。\n"
        "- id: sandbox-policy\n"
        "  disabled: false\n"
        "  config:\n"
        "    mode: 'danger-full-access'\n"
        "    workspaceRoot: !!js process.cwd()\n"
        "# permission-presets 的预设表里 danger-full-access 预设=(全权,approval=never)；\n"
        "# 只钉 sandbox 模式时合成缺省=(全权,ask) 不匹配任何预设，dsh boot 直接\n"
        "# 「composed sandbox and approval defaults match no preset」拒启（260914 实测）——\n"
        "# 按其指引显式钉 defaultPreset（条目 id=permission，见 --dump-config）。\n"
        "- id: permission\n"
        "  disabled: false\n"
        "  config:\n"
        "    defaultPreset: 'danger-full-access'\n"
        "- id: bash-sandbox\n"
        "  disabled: false\n"
        "  config:\n"
        "    timeoutMs: %d\n"
        "    maxTimeoutMs: %d\n" % (bash_timeout_ms(), bash_timeout_ms()))


def _docker(args: List[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run([docker_bin()] + args, capture_output=True, text=True,
                          timeout=timeout)


def _docker_present() -> bool:
    try:
        return _docker(["info"], timeout=DOCKER_INFO_TIMEOUT_SEC).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _host_uid_gid() -> str:
    """宿主 worker 的 uid:gid（R4/C4：容器内属主对齐，数字 uid 免 passwd 条目）。"""
    try:
        return "%d:%d" % (os.getuid(), os.getgid())
    except AttributeError as e:  # 非 POSIX：容器面不支持，fail-closed
        raise AgentRuntimeError("容器执行面需要 POSIX uid/gid（%s）" % e)


def container_name_for(ticket_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", ticket_id or "")
    return CONTAINER_PREFIX + (safe or "unknown")


def _container_running(name: str) -> Optional[bool]:
    """权威探测容器是否在跑（C6：不靠 stderr 文案）。None=探测失败（daemon 错误）。"""
    try:
        p = _docker(["inspect", "-f", "{{.State.Running}}", name], timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        if "No such container" in (p.stderr or ""):
            return False   # 权威缺席（inspect rc 语义）；stderr 文案只作兜底注释
        return None        # 其它 daemon 错误：未知态
    return (p.stdout or "").strip() == "true"


def ensure_container(ticket_id: str, lane: Path, project: str = "",
                     log: Optional[Callable[[str], None]] = None) -> str:
    """每票一容器（幂等）：在场 running→复用；在场已停→拆了重建；缺席→建。
    镜像缺席/docker 缺席/泳道不可挂 → fail-closed 点名（不静默回落）。"""
    if not _docker_present():
        raise AgentRuntimeError(
            "docker 不可用——容器执行面无法启动（不静默回落 host）。"
            "修复：启动 Docker/OrbStack，或显式 %s=host" % RUNTIME_ENV)
    image = agent_image()
    try:
        if _docker(["image", "inspect", image], timeout=15).returncode != 0:
            raise AgentRuntimeError(
                "agent 镜像缺席：%s——先跑 sh server/engine/build_agent_image.sh 重建"
                "（不静默回落 host）" % image)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AgentRuntimeError("agent 镜像探测失败：%s" % e)
    lane = Path(lane)
    if not lane.is_dir():
        raise AgentRuntimeError("泳道目录不存在，容器无可挂工作区：%s" % lane)
    name = container_name_for(ticket_id)
    running = _container_running(name)
    if running is False:
        if log:
            log("[agent-runtime] 容器 %s 已停，拆除重建（自愈）" % name)
        _docker(["rm", "-f", name], timeout=30)
    elif running is None:
        # 未知态（daemon 抖动）：交给 run 去撞真实错误，不在探测层猜
        pass
    if running is not True:
        uidgid = _host_uid_gid()
        argv = ["run", "-d", "--name", name, "--user", uidgid, "--init",
                "--label", "%s=%s" % (LBL_TICKET, ticket_id),
                "--label", "%s=%s" % (LBL_LANE, str(lane)),
                "--label", "%s=%s" % (LBL_PROJECT, project or ""),
                # 挂载面白名单等值（C4）：恰好一项=泳道:泳道（rw）。无主树/无 ~/.dsh/
                # 无 docker.sock/无其他票路径；网络缺省 bridge（仅出口，非 host）。
                "-v", "%s:%s" % (lane, lane),
                image, "sleep", "infinity"]
        try:
            p = _docker(argv, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise AgentRuntimeError("起容器失败：%s" % e)
        if p.returncode != 0:
            _docker(["rm", "-f", name], timeout=30)  # 半建状态清扫（幂等）
            raise AgentRuntimeError("起容器失败（rc=%s）：%s"
                                    % (p.returncode, (p.stderr or "").strip()[-400:]))
        if log:
            log("[agent-runtime] 容器就绪：%s（user=%s，挂载=仅泳道 %s）"
                % (name, uidgid, lane))
    return name


def exec_agent(container: str, cwd: Path, cmd: List[str], env_source: Dict[str, str],
               logf, stage_tag: str) -> AgentProc:
    """容器内起 agent 段进程（docker exec + supervisor + pgid 协议）。

    env 只带白名单（+容器本地 HOME/TMPDIR，C4）；pgid 目录由宿主预建（C4①）。
    ensure 与首 exec 的竞争窗口（容器被 gc/收口拆掉）＝exec 客户端非零退出 → 上层
    既有「rc 但无结果文件→raise 点名」诊断面接管（review R2 已核实 ：1278-1284），
    此处不静默重试 ensure。"""
    exec_dir = Path(cwd) / EXEC_DIR_REL
    exec_dir.mkdir(parents=True, exist_ok=True)
    pgid_file = exec_dir / ("%s.pgid" % re.sub(r"[^a-zA-Z0-9_.-]", "_", stage_tag))
    env_args: List[str] = []
    merged: Dict[str, str] = {}
    for k in ENV_ALLOWLIST:
        if k in env_source:
            merged[k] = env_source[k]
    merged["HOME"] = HOME_IN_CONTAINER
    merged["TMPDIR"] = TMPDIR_IN_CONTAINER
    for k, v in merged.items():
        env_args += ["-e", "%s=%s" % (k, v)]
    # supervisor 入口：sh 只做 HOME 预建（docker exec 不替你建目录），随即 exec 换身
    argv = [docker_bin(), "exec", "-w", str(cwd), *env_args, container,
            "/bin/sh", "-c",
            'mkdir -p "$HOME" && exec %s "$@"' % SANDBAR_EXEC_IN_CONTAINER,
            "sandbar-exec", str(pgid_file), *cmd]
    popen = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    return AgentProc(popen, mode="docker", container=container, pgid_file=str(pgid_file))


def spawn_agent(cmd: List[str], cwd: Path, env: Dict[str, str], logf,
                ticket_id: str, stage_tag: str, project: str = "",
                workspace_kind: str = "", lane: Optional[Path] = None,
                log: Optional[Callable[[str], None]] = None,
                force_host: bool = False) -> AgentProc:
    """三分叉点唯一的 agent 进程启动口。host=旧路径逐字节保真；docker=每票一容器。

    force_host（t260916-22 巡检 inspect 段）：显式钉 host 形态——巡检 agent 只读
    （read-only 预设 pin），docker 容器反而让非 suite 期的真仓审查基座不可见（红线 2
    不挂工作区以外宿主路径）；host+read-only pin=最小动面。其它调用点缺省 False=不变。"""
    mode = "host" if force_host else runtime_mode()
    if mode == "host":
        if log:
            log("[agent-runtime] host 形态 spawn（%s，cwd=%s）" % (stage_tag, cwd))
        popen = subprocess.Popen(cmd, cwd=str(cwd), env=env,
                                 stdout=logf, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        return AgentProc(popen, mode="host")
    # ---- docker ----
    if workspace_kind not in ("worktree", "dir") or lane is None:
        raise AgentRuntimeError(
            "main workspace（无泳道目录）容器执行面拒绝——红线 2 禁挂宿主主树；"
            "请用 worktree/dir 泳道，或显式 %s=host（人工决策）" % RUNTIME_ENV)
    t0 = time.monotonic()
    container = ensure_container(ticket_id, Path(lane), project=project, log=log)
    proc = exec_agent(container, Path(cwd), cmd, env, logf, stage_tag)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if log:
        log("[agent-runtime] docker 形态 spawn（%s，容器=%s，ensure+exec %dms，cwd=%s）"
            % (stage_tag, container, elapsed_ms, cwd))
        # D2②：git 读降级注记（预期失败形态进日志，防「树坏了」误读——KI-083 同类教训）
        log("[agent-runtime] 容器执行面 git 读不可用（有意降级：worktree gitfile 指向宿主"
            "主仓元数据，红线 2 不挂载；容器内 git 报 fatal: not a git repository 属正常面，"
            "取证面由宿主 worker 的 merge_check/verify_lane 承担）")
    return proc


def remove_container(ticket_id: str, log: Optional[Callable[[str], None]] = None) -> str:
    """收口即拆（幂等，不外抛——与邻位 git 清理同口径：失败留痕不拦收口）。

    模式闸（t260921-05）：容器拆/扫是 docker 形态专属原语——host 形态 spawn 分支根本
    不起容器，无容器可拆=直接返回空串（零 docker 调用、零开销；这是语义正名，不是
    降级）。运行模式非法值：容忍转 note 留痕不外抛（保「幂等不外抛」契约，同时点名
    不吞配置错误；spawn 侧 fail-closed 点名由 spawn_agent 的 runtime_mode 承担）。
    docker 形态下走 docker_bin()（SANDBAR_DOCKER_BIN 可注入，单测注桩不连真 daemon）。
    """
    try:
        gated = runtime_mode() == "docker"
    except AgentRuntimeError as e:
        note = "运行模式判定异常（容忍留痕）：%s" % e
        if log:
            log("[agent-runtime] %s" % note)
        return note
    if not gated:
        return ""  # host 形态无容器（spawn host 分支不起容器），零 docker 调用
    name = container_name_for(ticket_id)
    try:
        p = _docker(["rm", "-f", name], timeout=DOCKER_RM_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired) as e:
        note = "docker rm 异常（容忍）：%s" % e
        if log:
            log("[agent-runtime] %s" % note)
        return note
    if p.returncode == 0:
        if log:
            log("[agent-runtime] 票收口拆容器：%s" % name)
        return "已拆 %s" % name
    if "No such container" in (p.stderr or ""):
        return ""  # 幂等：本就无容器
    note = "docker rm 失败（留痕不抛）：%s" % (p.stderr or "").strip()[-200:]
    if log:
        log("[agent-runtime] %s" % note)
    return note


def gc_stale_containers(log: Optional[Callable[[str], None]] = None) -> List[str]:
    """孤儿扫尾（D7③）：label 过滤列出 agent 容器，泳道目录已不存在=票已终 → 拆。
    一切异常容忍（返回 note 列表，绝不外抛——挂在 prepare_workspace 首活动，不拦工作流）。

    模式闸（t260921-05）：host 形态无容器面，直接返回空列表（零 docker 调用、零开销；
    语义正名非降级）。运行模式非法值：容忍转 note 进列表（绝不外抛契约不变）。
    docker 形态下走 docker_bin()（SANDBAR_DOCKER_BIN 可注入）。
    """
    notes: List[str] = []
    try:
        gated = runtime_mode() == "docker"
    except AgentRuntimeError as e:
        return ["运行模式判定异常（容忍留痕）：%s" % e]
    if not gated:
        return notes  # host 形态无容器面，零 docker 调用
    if not _docker_present():
        return ["docker 不可用，跳过容器扫尾"]
    fmt = "{{.Names}}\\t{{.Label \"%s\"}}" % LBL_LANE
    try:
        p = _docker(["ps", "-a", "--filter", "label=%s" % LBL_TICKET,
                     "--format", fmt], timeout=DOCKER_PS_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired) as e:
        return ["容器扫尾探测异常（容忍）：%s" % e]
    if p.returncode != 0:
        return ["容器扫尾探测失败（容忍）：%s" % (p.stderr or "").strip()[-200:]]
    for line in (p.stdout or "").splitlines():
        name, _sep, lane = line.partition("\t")
        name = name.strip()
        lane = lane.strip()
        if not name:
            continue
        if lane and Path(lane).is_dir():
            continue  # 活票：保留
        rp = _docker(["rm", "-f", name], timeout=DOCKER_RM_TIMEOUT_SEC)
        if rp.returncode == 0:
            notes.append("gc 拆孤儿容器 %s（泳道已不存在：%s）" % (name, lane or "?"))
        else:
            notes.append("gc 拆 %s 失败（容忍）：%s" % (name, (rp.stderr or "").strip()[-120:]))
    if log:
        for n in notes:
            log("[agent-runtime] %s" % n)
    return notes


class AgentProc:
    """统一 agent 进程句柄：三分叉点的 poll/reap 只认本类。

    host：Popen 直跑，reap=组粒度 killpg（迟 import 复用 agent_activities._reap_agent_proc，
    KI-009 单源语义不复制）。
    docker：Popen=docker exec 客户端；reap=容器内按组 TERM→KILL（pgid 档协议）。
    reap 四终态（正常/报错/超时/取消）全可达且【绝不外抛】（C6/R8）：容器已不在=幂等；
    daemon 无响应=有界超时留痕；pgid 档缺失/坏=跳过组杀留痕；意外 docker 错误=留痕容忍。
    """

    def __init__(self, popen: subprocess.Popen, mode: str, container: str = "",
                 pgid_file: str = ""):
        self._popen = popen
        self.mode = mode
        self.container = container
        self.pgid_file = pgid_file

    # ---- 直通面 ----
    def poll(self) -> Optional[int]:
        return self._popen.poll()

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        return self._popen.wait(timeout)

    @property
    def pid(self) -> int:
        return self._popen.pid

    def kill(self) -> None:
        """客户端硬杀（兜底/测试清理用；组语义回收走 reap）。"""
        self._popen.kill()

    # ---- reap ----
    def reap(self, ticket_id: str = "", stage_id: str = "",
             term_timeout: float = REAP_TERM_TIMEOUT_SEC,
             kill_timeout: float = REAP_KILL_TIMEOUT_SEC) -> str:
        if self.mode == "host":
            from agent_activities import _reap_agent_proc  # 迟 import 防环（KI-009 单源）
            return _reap_agent_proc(self._popen, ticket_id, stage_id,
                                    term_timeout, kill_timeout)
        return self._reap_docker(ticket_id, stage_id, term_timeout, kill_timeout)

    def _read_pgid(self) -> Optional[int]:
        try:
            raw = Path(self.pgid_file).read_text("utf-8").strip()
        except OSError:
            return None
        if not re.fullmatch(r"\d+", raw or ""):
            return None
        return int(raw)

    def _reap_docker(self, ticket_id: str, stage_id: str,
                     term_timeout: float, kill_timeout: float) -> str:
        if self._popen.poll() is not None:
            return ""  # 幂等：客户端已退出（exec 会话终结=容器内 supervisor 已落幕）
        tag = "[%s/%s]" % (ticket_id, stage_id) if ticket_id else "[reap]"
        notes: List[str] = []
        pgid = self._read_pgid()
        if pgid is None:
            # supervisor 启动窗口（reap 紧跟 spawn 的重试/错误路径）：档未落盘≠没有，
            # 短等落盘再判，避免「跳过组杀+客户端悬空」的半收尾。
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                pgid = self._read_pgid()
                if pgid is not None or self._popen.poll() is not None:
                    break  # 档现 / 客户端已退（exec 会话终结→终态收尾）
                time.sleep(0.1)
        if pgid is None:
            notes.append("pgid 档缺失/坏，跳过组杀（容忍）")
        else:
            running = _container_running(self.container)
            if running is False:
                notes.append("容器已不在，幂等 reap")
            else:
                if running is None:
                    notes.append("容器状态探测失败（daemon？容忍续行）")
                try:
                    kp = _docker(["exec", self.container, "kill", "-TERM",
                                  "--", "-%d" % pgid], timeout=max(2.0, term_timeout))
                    if kp.returncode != 0:
                        notes.append("组 TERM 下发失败（容忍）：%s"
                                     % (kp.stderr or "").strip()[-120:])
                    else:
                        notes.append("terminate（容器内进程组 %d）" % pgid)
                except (OSError, subprocess.TimeoutExpired) as e:
                    notes.append("组 TERM 异常（容忍）：%s" % e)
        # 客户端收尾：容器内组灭 → exec 会话终结 → 客户端退出
        try:
            self._popen.wait(term_timeout)
        except subprocess.TimeoutExpired:
            if pgid is not None:
                try:
                    _docker(["exec", self.container, "kill", "-KILL", "--",
                             "-%d" % pgid], timeout=max(2.0, kill_timeout))
                    notes.append("terminate 超时 %ss 升级 KILL（容器内进程组）" % term_timeout)
                except (OSError, subprocess.TimeoutExpired) as e:
                    notes.append("组 KILL 异常（容忍）：%s" % e)
            try:
                self._popen.wait(kill_timeout)
            except subprocess.TimeoutExpired:
                notes.append("kill 后客户端仍未退出（%ss，放弃等待，不阻塞收尾）" % kill_timeout)
        note = "%s reap：%s，rc=%s" % (tag, "→".join(notes) or "无操作", self._popen.poll())
        try:
            from agent_activities import activity  # 迟 import：日志单源
            activity.logger.info(note)
        except Exception:
            pass
        return note
