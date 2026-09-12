#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 场景共享夹具（integration 岗 design_integration_tests 段）。

六条场景共用：三态框架 / 隔离锁根 CLI / 残台注入与心跳保持 / docker 公开观测面
（ps/network/volume 的 compose label / IPAM 子网 / 端口 TCP）/ 受管网段表推导 /
清扫 CLI 调用与并行拆台 / 坏 docker 桩。前置与基础步骤允许共享（岗位用例设计
纪律），六场景各自 intent 不同面不互替。

灰盒纪律：断言只锚公开面——CLI 进程级行为（退出码 / stdout JSON / stderr
STAGE_ 行）、docker 公开观测面（compose label 过滤的容器/网络/卷、IPAM 配置、
端口可连性）、进程表公开观测面（pgrep -f 匹配 CLI 子命令行）。实现内部函数与
私有命名不进断言。

注入面声明：残台形态注入 = **租约状态面手术**（工单验收 C 明令「手工改租约制造
形态」——租约就是本票被测的状态面，注入它不是绑定实现细节）。字段名与
stage_docker 头注声明的租约形状一致（state/heartbeat_ts/ttl_sec/holder.pid/
repo_dir/owner_root），集中在 craft_lease/edit_lease 两处。
"""
import hashlib
import ipaddress
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CLI = os.path.join(REPO, "integration", "stage_docker.py")
COMPOSE = os.path.join(REPO, "server", "docker-compose.test.yml")

# 与 stage_docker 头注声明的缺省一致（场景不设该 env，即测缺省路径）。
NET_BASE_DEFAULT = "10.213.0.0/16"

# 生产面（CLAUDE.md 硬规则 1：3099 控制台 / 7233 生产 Temporal 全程不可触碰）
PROD_PORTS = {3099, 7233, 8233}
# 缺省台与保留面（stage_docker FORBIDDEN_PORTS 同集）
FORBIDDEN_PORTS = {3099, 3199, 7233, 8233, 17233, 18233}

# 保险丝红行点名标记（stage_docker 头注与 capacity 红文案的公开措辞）
FUSE_MARK = "保险丝"
# daemon 资源类失败特征（环境归因，不诬产品——t260905-06/t260904-12 口径）
DAEMON_ENV_PAT = None  # 延迟编译（见 env_guard）


def _daemon_env_pat():
    global DAEMON_ENV_PAT
    if DAEMON_ENV_PAT is None:
        import re
        DAEMON_ENV_PAT = re.compile(
            r"address pools have been fully subnetted"
            r"|no space left on device"
            r"|Cannot connect to the Docker daemon", re.I)
    return DAEMON_ENV_PAT


def stage_tag(base):
    """场景台项目名唯一化：后缀=本 worktree 路径 hash。同 worktree 内稳定
    （重跑幂等），跨 worktree 不同（并行泳道互拆根治——t260910-12 gen2 纪律）。
    场景内所有 compose 工程名一律经本 helper 派生。"""
    return "%s-%s" % (base, hashlib.md5(REPO.encode("utf-8")).hexdigest()[:8])


def iso_root(slug):
    """场景专属隔离锁根：租约/锁面只在此根内，生产共享根
    （/tmp/sandbar-test-stages）的在飞台绝不被本票场景触碰——清扫/保险丝计数
    的被测面=注入面本身，跨泳道竞争不属于任何一条 intent。"""
    root = "/tmp/sandbar-t26091202-%s-%s" % (slug, hashlib.md5(REPO.encode("utf-8")).hexdigest()[:8])
    os.makedirs(root, exist_ok=True)
    return root


# ---- 三态框架（环境缺件=ENV_FAIL exit 2；na 仅限系统状态条件腿；无第四态状态值）----

_passed = _failed = _env_failed = _na = 0


def check(cond, label):
    global _passed, _failed
    print(("ok    " if cond else "FAIL  ") + label, flush=True)
    if cond:
        _passed += 1
    else:
        _failed += 1
    return bool(cond)


def envfail(label):
    global _env_failed
    _env_failed += 1
    print("ENV_FAIL %s（环境缺件，没验成——原因归环境，exit 2）" % label, flush=True)


def na(label):
    """系统状态条件腿没验成（观测工具缺席等）：计 na 不计 fail——全腿 na=场景红。"""
    global _na
    _na += 1
    print("NA    %s（系统状态条件腿：观测工具缺席，非产品非环境）" % label, flush=True)


def finish():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (_passed, _failed, _env_failed, _na), flush=True)
    if _failed:
        sys.exit(1)
    if _env_failed:
        sys.exit(2)
    if _na >= _passed and _passed == 0:
        sys.exit(1)   # 全腿 na=没验成任何东西，按场景红处理
    sys.exit(0)


def env_guard(err, leg="腿"):
    """stderr 命中 daemon 资源类失败 → ENV_FAIL exit 2（点名特征），不吞产品红。"""
    if err and _daemon_env_pat().search(err):
        envfail("docker daemon 资源类失败（%s…）：%s 没验成"
                % (" ".join(err.strip().split())[:150], leg))
        finish()
    return False


# ---- CLI 调用（锁根必填：绝不意外触碰生产共享根）----

def cli(root, *args, **kw):
    """stage_docker CLI 子进程调用。root=隔离锁根（必填）。"""
    cwd = kw.get("cwd", REPO)
    timeout = kw.get("timeout", 900)
    env_extra = kw.get("env_extra") or {}
    env = dict(os.environ)
    env["SANDBAR_STAGE_LOCK_DIR"] = root
    env.update(env_extra)
    return subprocess.run([sys.executable, CLI] + [str(a) for a in args],
                          capture_output=True, text=True, timeout=timeout,
                          cwd=cwd, env=env)


def cli_async(root, *args, **kw):
    """发车不等待（并发起台/失控样本用）。返回 Popen。"""
    timeout = kw.get("timeout", 900)
    env_extra = kw.get("env_extra") or {}
    env = dict(os.environ)
    env["SANDBAR_STAGE_LOCK_DIR"] = root
    env.update(env_extra)
    return subprocess.Popen([sys.executable, CLI] + [str(a) for a in args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=kw.get("cwd", REPO), env=env)


def last_json(proc):
    try:
        return json.loads((proc.stdout or "").strip().split("\n")[-1])
    except (ValueError, IndexError):
        return None


def extract_json(text):
    """宽容 JSON 抽取：末行 → 首个 { 到末个 }。解析失败返回 None（断言面判）。"""
    if not text:
        return None
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    for ln in reversed(lines):
        ln = ln.strip()
        if ln.startswith("{") or ln.startswith("["):
            try:
                return json.loads(ln)
            except ValueError:
                break
    i, j = text.find("{"), text.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(text[i:j + 1])
        except ValueError:
            return None
    return None


def json_string_values(obj):
    """JSON 树内全部字符串值（点名断言用：报告格式变化不破断言）。"""
    out = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= json_string_values(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= json_string_values(v)
    elif isinstance(obj, str):
        out.add(obj)
    return out


# ---- docker 公开观测面 ----

def docker_present():
    try:
        return subprocess.run(["docker", "info"], capture_output=True,
                              timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _docker(args, timeout=30):
    return subprocess.run(["docker"] + args, capture_output=True, text=True,
                          timeout=timeout)


def compose_containers(project):
    p = _docker(["ps", "-a", "--filter",
                 "label=com.docker.compose.project=%s" % project,
                 "--format", "{{.ID}}"])
    return [x for x in (p.stdout or "").split() if x]


def compose_networks(project):
    p = _docker(["network", "ls", "--filter",
                 "label=com.docker.compose.project=%s" % project,
                 "--format", "{{.Name}}"])
    return [x for x in (p.stdout or "").split() if x]


def compose_volumes(project):
    p = _docker(["volume", "ls", "--filter",
                 "label=com.docker.compose.project=%s" % project,
                 "--format", "{{.Name}}"])
    return [x for x in (p.stdout or "").split() if x]


def network_subnets(names):
    """逐网络 inspect IPAM 子网（B 验收腿：网段必须落在受管表内）。"""
    out = {}
    for n in names:
        p = _docker(["network", "inspect", n, "--format",
                     "{{json .IPAM.Config}}"])
        subs = []
        try:
            cfg = json.loads((p.stdout or "[]").strip() or "[]")
            for c in cfg if isinstance(cfg, list) else []:
                s = c.get("Subnet")
                if s:
                    subs.append(str(s))
        except (ValueError, AttributeError):
            pass
        out[n] = subs
    return out


def global_counts():
    """全机容器数 / 网络数（G 腿：跑前跑后回落基线）。"""
    pc = _docker(["ps", "-aq"], timeout=30)
    pn = _docker(["network", "ls", "-q"], timeout=30)
    return (len([x for x in (pc.stdout or "").split() if x.strip()]),
            len([x for x in (pn.stdout or "").split() if x.strip()]))


def listen_pid(port):
    """生产端口 LISTEN 进程 pid（全程未触碰的观测面）。工具缺席返回 None。"""
    try:
        p = subprocess.run(["lsof", "-nP", "-iTCP:%d" % int(port),
                            "-sTCP:LISTEN", "-t"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    for ln in (p.stdout or "").split():
        if ln.strip().isdigit():
            return int(ln.strip())
    return None


def tcp_open(port, timeout=2.0):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def hold_pids(project):
    try:
        p = subprocess.run(["pgrep", "-f",
                            "stage_docker.py hold --project %s" % project],
                           capture_output=True, text=True, timeout=15)
        return [int(x) for x in (p.stdout or "").split() if x.strip().isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def hold_pids_prefix(tag_prefix):
    """前缀匹配（失控样本的孤儿持有腿清点——损害有界断言面）。"""
    try:
        p = subprocess.run(["pgrep", "-f",
                            "stage_docker.py hold --project %s" % tag_prefix],
                           capture_output=True, text=True, timeout=15)
        return [int(x) for x in (p.stdout or "").split() if x.strip().isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


# ---- 受管网段表（B 腿断言基准；场景不设 NET_BASE env = 测缺省路径）----

def net_table():
    """base /16 切出的全部 /24 槽（含保留尾槽——保留槽的「不被分配」由
    「≠手工缺省网段」腿覆盖，此处不复制实现的保留逻辑）。"""
    try:
        base = ipaddress.ip_network(
            os.environ.get("SANDBAR_STAGE_NET_BASE", NET_BASE_DEFAULT).strip())
    except ValueError:
        return []
    if base.prefixlen > 24:
        return []
    return [str(s) for s in base.subnets(new_prefix=24)]


def manual_default_subnet():
    """compose 文件在无 SANDBAR_TEST_SUBNET 时的渲染 ipam 子网（=手工直跑
    compose 落的网段；分配器绝不发出的保留槽）。渲染失败/无 ipam → None。"""
    env = dict(os.environ)
    env.pop("SANDBAR_TEST_SUBNET", None)
    try:
        p = subprocess.run(["docker", "compose", "-f", COMPOSE,
                            "config", "--format", "json"],
                           capture_output=True, text=True, timeout=60,
                           cwd=REPO, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    try:
        cfg = json.loads(p.stdout or "{}")
        net = (cfg.get("networks") or {}).get("default") or {}
        ipam = (net.get("ipam") or {}).get("config") or []
        for c in ipam:
            if c.get("subnet"):
                return str(c["subnet"])
    except (ValueError, AttributeError):
        return None
    return None


# ---- 租约状态面注入（工单验收 C 明令的注入口；字段=stage_docker 头注声明的形状）----

def lease_file(root, project):
    return os.path.join(root, "project-%s.json" % project)


def read_lease_file(root, project):
    try:
        with open(lease_file(root, project), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_lease_file(root, project, lease):
    """原子写（tmp + os.replace）：并发读者不见半文件（与实现同口径）。"""
    dst = lease_file(root, project)
    tmp = "%s.tmp-%d-%d" % (dst, os.getpid(), time.time_ns())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(lease, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, dst)


def craft_lease(root, project, *, state="up", holder_pid, heartbeat_ts=None,
                ttl_sec=90.0, owner_root=None, repo_dir=None, keep=False,
                services=("temporal",), ports=None):
    """手写一条形态完整的租约（字段集=stage_docker 头注声明的租约形状）。
    heartbeat_ts=None → 现在（新鲜）。owner_root=None → 不写该键（legacy 形态）。"""
    now = time.time()
    lease = {
        "lease_id": "%s-%d-%s" % (project, int(now * 1000), os.urandom(4).hex()),
        "project": project,
        "holder": {"ticket": "t260912-02", "pid": int(holder_pid)},
        "anchor_pid": None,
        "state": state,
        "services": list(services),
        "ports": dict(ports or {}),
        "subnet": None,
        "ts": now,
        "heartbeat_ts": float(heartbeat_ts if heartbeat_ts is not None else now),
        "ttl_sec": float(ttl_sec),
        "repo_dir": repo_dir,
        "container_ids": [],
    }
    if owner_root is not None:
        lease["owner_root"] = str(owner_root)
    if keep:
        lease["keep"] = True
    write_lease_file(root, project, lease)
    return lease


def edit_lease(root, project, mutate):
    """对在册租约做状态面手术（验收 C 注入口）。mutate(dict)->dict。"""
    lease = read_lease_file(root, project)
    if not isinstance(lease, dict):
        return None
    new = mutate(dict(lease))
    if isinstance(new, dict):
        write_lease_file(root, project, new)
    return new


def drop_owner(root, project):
    """剥掉 owner_root 键 = legacy 旧格式形态（260912 存量残台的租约形状）。"""
    return edit_lease(root, project, lambda d: {k: v for k, v in d.items()
                                                if k != "owner_root"})


class BeatKeeper(object):
    """场景侧心跳保持：被手术的租约由场景进程续心跳（hold 已被杀，真实
    残台形态=「心跳进程尚活、租约永新鲜」的镜像面）。stop() 后停写。"""

    def __init__(self, root, projects, gap=2.0):
        self.root = root
        self.projects = list(projects)
        self.gap = gap
        self._stop = threading.Event()
        self._thread = None

    def _loop(self):
        while not self._stop.is_set():
            for p in self.projects:
                if self._stop.is_set():
                    return
                edit_lease(self.root, p, lambda d: (
                    d.update({"heartbeat_ts": time.time()}) or d))
            self._stop.wait(self.gap)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)


def sleep_holder(seconds=3600):
    """活的持有者进程（辅证面：保险丝计数/心跳新鲜都只认租约，不认 pid——
    本进程只为「活 pid」形态提供真实 pid）。返回 Popen（.pid 供租约注入；
    收尾用 kill_holder 回收——kill_pid 对自家子进程会等僵尸到超时）。"""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%d)" % seconds],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def kill_holder(proc, timeout=5):
    """SIGKILL 场景自建的持有者 Popen 并 wait 回收（僵尸不回收会让存活性探针假阳）。"""
    if proc is None:
        return
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=timeout)
    except Exception:
        pass


def kill_pid(pid, timeout=10):
    try:
        os.kill(int(pid), signal.SIGKILL)
    except (ProcessLookupError, ValueError, OSError):
        return
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return
        time.sleep(0.1)


def kill_holds(project, timeout=10):
    """杀掉某工程的持有腿（真实残台手术前置：hold 活着会以内存副本回写租约，
    冲掉场景手术——先杀再改，形态才立得住）。"""
    pids = hold_pids(project)
    for pid in pids:
        kill_pid(pid, timeout=timeout)
    return pids


# ---- 清扫 CLI 与并行拆台 ----

def sweep(root, *args, **kw):
    """sweep 子进程调用。返回 (proc, report_json_or_None)。"""
    timeout = kw.get("timeout", 180)
    env_extra = kw.get("env_extra") or {}
    proc = cli(root, "sweep", *args, timeout=timeout, env_extra=env_extra)
    return proc, extract_json(proc.stdout or "")


def guarded_down(projects, root, workers=8, timeout=300):
    """finally 兜底拆台（并行）：起过的工程不残留（崩溃路径零残留半边）。
    返回 {(project, rc)}。"""

    def _one(proj):
        try:
            return (proj, cli(root, "down", "--project", proj,
                              timeout=timeout).returncode)
        except (OSError, subprocess.SubprocessError):
            return (proj, -1)

    if not projects:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return dict(ex.map(_one, projects))


def up_stage(root, project, services="temporal", timeout=600, **kw):
    """起一台真台并归因 daemon 环境红。返回 (proc, state_json)。"""
    proc = cli(root, "up", "--project", project, "--services", services,
               timeout=timeout, **kw)
    env_guard(proc.stderr, "起台腿 %s" % project)
    return proc, last_json(proc)


# ---- 坏 docker 桩（D 验收腿：清理失败必须响亮上抛）----

def docker_shim_dir():
    """返回一个置前 PATH 后 docker 必失败的临时目录（只遮蔽 docker，不动 git）。"""
    d = tempfile.mkdtemp(prefix="sandbar-t26091202-shim-")
    shim = os.path.join(d, "docker")
    with open(shim, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n"
                 "echo \"shim: docker unavailable for sweep-failure injection\" >&2\n"
                 "exit 1\n")
    os.chmod(shim, 0o755)
    return d


def rm_rf(path):
    shutil.rmtree(path, ignore_errors=True)


def rand_slot(table, taken):
    """从受管表挑一个未被占用的槽（compose 渲染腿注入用）。"""
    for s in random.sample(table, min(len(table), 32)):
        if s not in taken:
            return s
    return None


def wait_until(fn, budget, gap=0.5):
    t0 = time.time()
    while time.time() - t0 < budget:
        if fn():
            return True
        time.sleep(gap)
    return False
