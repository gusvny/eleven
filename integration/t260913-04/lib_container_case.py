#!/usr/bin/env python3
"""t260913-04 共享夹具：agent 执行面容器化的驱动面与断言面（灰盒 L2/L3 公共面）。

本文件不带 sc_ 前缀 = 共享夹具（登记铁律：非 sc_ 文件视为共享代码，不进场景清单）。

绑定面（全部是方案 gen1 的**声明契约**，不是实现细节——实现改名=这些常量改一处）：
  - 旋钮   SANDBAR_AGENT_RUNTIME=docker|host（缺省 host）；SANDBAR_DOCKER_BIN（docker
           CLI 可注入缝，方案 D6/D3）；SANDBAR_AGENT_CMD / SANDBAR_AGENT_RESUME（引擎
           既有公开旋钮）。
  - 容器   名 sandbar-agent-<ticket_id>；label sandbar.agent.ticket / .lane / .project。
  - supervisor 容器内 CLI：/usr/local/bin/sandbar-exec <pgid文件> <cmd...>（方案 D3），
            收割协议 = docker exec … kill -TERM -- -<pgid> → 超时 kill（KI-009 语义）。
  - pin    泳道 artifacts 下 sandbox_pin*.yml：字面量 `mode: 'danger-full-access'`（宿主 260914 A 案：容器内全权、隔离靠挂载面）+
            `bash-sandbox.timeoutMs/maxTimeoutMs=900000`（方案 D5/D8）。
  - 镜像   仓名 sandbar-agent（tag 随版）；构建入口 server/build_agent_image.sh。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（integration/lib_env.py 契约，无第四态）。
实现段落地前红属预期（TDD 验收棒）；arbitrate/merge 期必须绿。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                # integration/ （lib_env）
sys.path.insert(0, str(HERE))                        # 本票目录

import lib_env  # noqa: E402

EXIT_PASS, EXIT_FAIL, EXIT_ENV_FAIL = lib_env.EXIT_PASS, lib_env.EXIT_FAIL, lib_env.EXIT_ENV_FAIL

# ---- 声明契约常量（实现必须兑现；改名=契约变更须过 review）----
RUNTIME_ENV = "SANDBAR_AGENT_RUNTIME"
DOCKER_BIN_ENV = "SANDBAR_DOCKER_BIN"
IMAGE_REPO = "sandbar-agent"
BUILD_SCRIPT = "server/engine/build_agent_image.sh"
DOCKERFILE = "server/engine/Dockerfile.agent"
RUNTIME_MODULE = "server/engine/agent_runtime.py"
WORKER_SH = "server/engine/run_worker.sh"
CONTAINER_FMT = "sandbar-agent-%s"
LABEL_TICKET = "sandbar.agent.ticket"
LABEL_LANE = "sandbar.agent.lane"
LABEL_PROJECT = "sandbar.agent.project"
PIN_GLOB = "sandbox_pin*.yml"
FORBIDDEN_ENV_KEYS = ("DSH_PERMISSION_MODE", "DSH_SANDBOX_MODE", "DSH_SANDBOX_DISABLED")
DOCKER_SOCK = "/var/run/docker.sock"


class Checker:
    """子用例级三态记账：pass/fail/env_fail/na + SUMMARY 行 + 退出码优先级（fail>env>pass；
    全部子用例 N/A=产品红 exit 1）。词表只认 pass/fail/env_fail/na 三态四值（无第四态）。"""

    def __init__(self, title):
        self.title = title
        self.c = {"pass": 0, "fail": 0, "env_fail": 0, "na": 0}

    def check(self, cond, label, detail=""):
        self.c["pass" if cond else "fail"] += 1
        print(("  ok    " if cond else "  FAIL  ") + label + ("" if cond else
              ("  | %s" % detail if detail else "")), flush=True)
        return bool(cond)

    def env(self, reason):
        self.c["env_fail"] += 1
        print("  ENV_FAIL  %s" % reason, flush=True)

    def na(self, reason):
        self.c["na"] += 1
        print("  N/A  %s" % reason, flush=True)

    def finish(self):
        total = sum(self.c.values())
        print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (
            self.c["pass"], self.c["fail"], self.c["env_fail"], self.c["na"]))
        if self.c["fail"] > 0:
            sys.exit(EXIT_FAIL)
        if total > 0 and self.c["na"] >= total:
            print("FAIL: 全部子用例 N/A——场景无可验对象（设计/覆盖问题）")
            sys.exit(EXIT_FAIL)
        if self.c["env_fail"] > 0:
            sys.exit(EXIT_ENV_FAIL)
        sys.exit(EXIT_PASS)


def uniq(tag):
    """夹具票/容器名的进程内唯一后缀（并发安全）：同一条场景可能同时被多个泳道的
    强制全跑执行（engine 池在例外面回册），固定名会互相拆容器/撞名——夹具名必须唯一。"""
    return "%s-%d-%d" % (tag, os.getpid(), int(time.time() * 1000) % 1000000)


# ---------------------------------------------------------------- 基础探针
def sh(*cmd, cwd=None, timeout=120, env=None):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None, timeout=timeout, env=env)


def require_docker(C):
    if shutil.which("docker") is None:
        C.env("docker 不可用（无 docker 命令）——本票容器面场景一律走 docker，"
              "启动 Docker/OrbStack 后重试")
        C.finish()
    p = sh("docker", "info", timeout=30)
    if p.returncode != 0:
        C.env("docker daemon 不可用（docker info 失败）：%s" % (p.stderr or "").strip()[:160])
        C.finish()


def agent_image_tag(C):
    """缺省镜像 tag（版本同步位=build_agent_image.sh）；缺席按实现状态分派：
    Dockerfile.agent 在场=可构建而未建（ENV_FAIL 点名构建命令）；不在场=契约未落地
    （FAIL 验收棒，环境没病）。"""
    p = sh("docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}", IMAGE_REPO)
    tags = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    if tags:
        return sorted(tags)[0]
    if (REPO / DOCKERFILE).exists():
        C.env("镜像 %s 缺席（本机自建无 registry）——先跑 sh %s" % (IMAGE_REPO, BUILD_SCRIPT))
        C.finish()
    C.check(False, "镜像与构建声明均未落地：%s / %s 不存在（方案 §3 改动清单）"
            % (DOCKERFILE, BUILD_SCRIPT))
    C.finish()


def venv_python():
    p = REPO / "server/engine/.venv/bin/python"
    return str(p) if p.exists() else sys.executable


def load_engine(C):
    """直调引擎单点的既有姿势（t260911-03 先例）：temporalio 可导入才进，缺=环境红。
    导入前先把 Temporal 目标黑洞化（场景直调绝不许碰 7233 生产——_fetch_ticket_project
    的软降级路径吃一个 connection refused 即回落 legacy，语义不变）。
    直调不在 Temporal activity 上下文里 → 给 activity 心跳/取消探测打进程内桩
    （只影响本进程；断言面不涉 Temporal 心跳语义）。
    注意：DSH_CMD 是 import 时捕获的模块常量——每条 slice 换 env 后必须
    importlib.reload(agent_activities)（见各场景 run_slice），否则 SANDBAR_AGENT_CMD
    等旋钮在导入期就焊死。"""
    try:
        import temporalio  # noqa: F401
    except Exception:
        C.env("temporalio 不可导入——用 %s 跑（缺环境点名，环境红非产品红）" % venv_python())
        C.finish()
    os.environ.setdefault("SANDBAR_TARGET_HOST", "127.0.0.1:1")
    os.environ.setdefault("SANDBAR_NAMESPACE", "sandbar-itest-blackhole")
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import agent_activities  # noqa: F401
    aa = sys.modules["agent_activities"]
    import temporalio.activity as _ta
    _ta.heartbeat = lambda *a, **k: None          # 上下文外心跳=no-op
    _ta.cancelled = lambda *a, **k: False         # 上下文外取消探测=未取消
    return aa


# ---------------------------------------------------------------- 夹具搭建
def mk_repo(path, files=None, branch="main"):
    """带本地身份的最小 git 仓（真 git，无网络）。"""
    path.mkdir(parents=True, exist_ok=True)
    for rel, content in (files or {"README.md": "# fixture\n"}).items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    sh("git", "init", "-q", "-b", branch, cwd=path)
    sh("git", "config", "user.email", "t@t", cwd=path)
    sh("git", "config", "user.name", "t", cwd=path)
    sh("git", "add", "-A", cwd=path)
    sh("git", "commit", "-qm", "init", cwd=path)
    return path


def mk_repo_lane(tmp, ticket, files=None):
    """tmp 主仓 + 真注册泳道 worktree → (main, lane)。泳道形态与引擎 prepare_workspace
    一致（worktree 的 .git=gitfile 指主仓——D2 降级契约的事实底座）。"""
    main = mk_repo(tmp / ("main-" + ticket), files=files)
    lane = tmp / ("lane-" + ticket)
    r = sh("git", "-C", main, "worktree", "add", "-q", "-b", "lane/" + ticket, lane)
    if r.returncode != 0:
        raise RuntimeError("worktree add 失败: %s" % r.stderr)
    return main, lane


def write_stub(lane, mode, spy_path, result_file=None):
    """agent 桩（挂在泳道内=同路径挂载后容器内同路径可见）：
    - 记录面：argv / env / cwd / id / uname 追加进 spy 文件（宿主与容器同路径可读）；
    - instant：写结果 JSON（优先 result_file 直写位；argv 里 */.sandbar/stage_*.json
      也认）后退出（段正常交付）；
    - latewrite：先写结果再长眠（KI-009 迟写排水面：结果交付后进程树仍活着，
      引擎 reap 必须按组收割）。"""
    stub = lane / ".sandbar" / "agent_stub.sh"
    stub.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "#!/bin/sh\n"
        "{\n"
        "  echo '--- argv'\n"
        "  printf '%s\\n' \"$@\"\n"
        "  echo '--- cwd'\n"
        "  pwd\n"
        "  echo '--- id'\n"
        "  id -u\n"
        "  id -g\n"
        "  echo '--- uname'\n"
        "  uname -a\n"
        "  echo '--- env'\n"
        "  env\n"
        "} >> '@@SPY@@' 2>/dev/null\n"
    ).replace("@@SPY@@", str(spy_path))
    if mode in ("instant", "latewrite"):
        body += (
            "RESULT_JSON='{\"status\":\"ok\",\"summary\":\"[stub] %s\","
            "\"report\":\"stub\",\"deliverables\":[],\"files_changed\":[],"
            "\"evidence\":\"stub\"}'\n"
            "write_result() { printf '%%s\\n' \"$RESULT_JSON\" > \"$1\"; }\n"
            % ("迟写面" if mode == "latewrite" else "容器面交付")
        )
        body += "RF=''\n"
        if result_file:
            body += "RF='%s'\n" % result_file
        body += (
            "[ -z \"$RF\" ] && for a in \"$@\"; do case \"$a\" in "
            "*/.sandbar/stage_*.json) RF=\"$a\";; esac; done\n"
            "[ -n \"$RF\" ] && write_result \"$RF\"\n"
        )
        if mode == "latewrite":
            body += "sleep 180\n"
        body += "exit 0\n"
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)
    return stub


def make_fake_docker(dirpath):
    """SANDBAR_DOCKER_BIN 注入桩：把每次调用原样记进日志（JSON 行），一律 exit 0、
    空 stdout——断言面=引擎传给 docker 的 argv（挂载面/env 面/user 面/名字/label/
    pin patch），不依赖引擎对输出的解析。"""
    log = Path(dirpath) / "fake-docker.log"
    fake = Path(dirpath) / "fake-docker"
    fake.write_text(
        "#!/bin/sh\n"
        "printf '%%s\\n' \"$*\" >> '%s'\n"
        "exit 0\n" % log, encoding="utf-8")
    fake.chmod(0o755)
    return fake, log


def read_log(log):
    if not Path(log).exists():
        return []
    return [ln for ln in Path(log).read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------- 断言面
def env_assignments(argv):
    """docker 风格 argv 里的 env 赋值候选（-e/--env 后随或整 token 形如 KEY=VALUE）。"""
    out = []
    for i, t in enumerate(argv):
        if t in ("-e", "--env") and i + 1 < len(argv) and "=" in argv[i + 1]:
            out.append(argv[i + 1])
        elif "=" in t and t == t.strip() and " " not in t:
            k = t.split("=", 1)[0]
            if k.replace("_", "").isalnum() and k.upper() == k and len(k) > 2:
                out.append(t)
    return out


def bind_sources(argv):
    """argv 里的 bind 挂载源候选（host路径:容器路径 或 --mount source=… 形态）。"""
    out = []
    for t in argv:
        if t.startswith("--mount") or "type=bind" in t:
            if "source=" in t:
                out.append(t.split("source=", 1)[1].split(",")[0])
        elif t.count(":") >= 1 and not t.startswith("-"):
            src = t.split(":")[0]
            if src.startswith("/") and Path(src).exists():
                out.append(src)
    return out


def containers_by_label(label_key, label_val=None):
    args = ["docker", "ps", "-a", "--format", "{{.ID}} {{.Names}}", "--filter",
            "label=%s" % label_key]
    if label_val is not None:
        args[-1] = "label=%s=%s" % (label_key, label_val)
    p = sh(*args)
    return [ln for ln in (p.stdout or "").splitlines() if ln.strip()]


def exec_in(container, *cmd, timeout=60):
    return sh("docker", "exec", container, *cmd, timeout=timeout)


def net_vol_snapshot():
    n = sh("docker", "network", "ls", "--format", "{{.Name}}").stdout.split()
    v = sh("docker", "volume", "ls", "--format", "{{.Name}}").stdout.split()
    return set(n), set(v)
