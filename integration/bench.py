#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离测试台共享库（t260904-02，engine-hardening ①）：temporalite 槽位制 + console
boot 骨架 python 侧 + 「不连生产」审计钩子。

契约对齐真源=integration/t260904-02/lib_gate.py 头注（design_integration_tests
段交付；本文件实现其声明的成员面：PROD_PORTS / ProductionGuardError /
assert_not_production / BenchBusy / acquire_slot / Slot(index…stopped,
start_temporalite/stop) / poc_python / audit_hook_env / write_registry）。

迁回来源=suyou/integration/t260903-06 boot-and-run-parallel-dom.mjs 的 boot 骨架
（临时 DSH_HOME / 临时 profile / port-0 内核分配 / 凭据只拷 credentials / teardown
幂等），收成本库供引擎行为场景复用。console profile 构建复用真源
server/dsh/ui-check/capture-lane.mjs（integration/bench_console.mjs 薄壳，不复制
逻辑防双份漂移）；本文件承载 python 侧骨架与 temporalite 槽位制。

## 骨架故障模式对照（review C6 要求落文，防迁移丢半边）

| suyou t260903-06 骨架故障模式 | 本库对应 | 差异与理由 |
| --- | --- | --- |
| 端口撞车（钉死端口必撞） | temporalite=槽位端口（基址+槽号，1910N/1920N/1930N）；console=port-0 内核分配 | 槽端口起前探活，被外来者占=BenchEnvConflict（exit3 语义）不对抗（t260903-11 纪律） |
| 用户 settings.yaml 钉死 3099 | TempDSHHome 只拷 .credentials.yaml，不拷 settings | 同骨架 |
| teardown 漏进程（detached 泄漏） | start_new_session=True + killpg TERM→KILL 兜底 + 端口释放核验 | 同骨架（加强：核验） |
| teardown 重入崩溃 | stop()/release() 各自幂等，teardown 全清可三连调用零异常 | 同骨架 |
| 信号路径泄漏（SIGINT/SIGTERM/exit 三钩子） | 场景侧注册（atexit + signal），本库提供幂等原语 | 宿主职责不变 |
| 起服务超时无诊断 | start_temporalite 就绪等待超时带日志尾 2000 字节 | 同骨架 |
| preset 不合=exit2 拒跑 | bench_console --selfcheck 的 buildTempProfile 腿改显式 SKIP 继续跑其余 | selfcheck 是自检非场景门；SKIP 原因必须打印，不静默 |
| （新增）并发串台 | flock 槽独占 + 槽专属 db + 槽专属 namespace + 端口组隔离 | epic 验收 4 |
| （新增）误连生产 | assert_not_production（7233/8233 fail-closed）+ python 审计钩子（socket.connect 先记后抛=阻断） | epic 验收 5；Go 面（temporal CLI）靠显式端口参数断言补面 |
| （新增）持槽者崩溃锁不释 | flock fd 移交 temporalite 进程（pass_fds），起跑后本进程即放手 | temporalite 活=锁活；kill -9/崩溃=内核收 fd=锁自释（场景①崩溃腿） |

红线：绝不碰 3099（console 属用户操作面）；绝不碰 7233/8233（生产 temporal 的
frontend/UI；--ui-port 缺省=--port+1000 是暗雷，故三端口全显式）；SUYOU_TARGET_HOST
指向生产=构造即拒（fail-closed）。

环境缝（泳道缺资产时的回退，KI-020③ 邻接绷带）：
  SUYOU_TEMPORAL_BIN   temporal 二进制（缺省：<repo>/server/dsh/temporal-poc/bin/temporal，
                        泳道缺失时读 .git gitfile 回退主树同位）
  SUYOU_POC_PYTHON     带 temporalio 的解释器（缺省：<repo>/…/.venv/bin/python，同样回退主树）
  SANDBAR_TEST_BENCH_DIR    槽位根（缺省 ~/.sandbar/test-benches）
  SANDBAR_TEST_BENCH_SLOTS  槽数（缺省 4）

锁文件口径（epic 验收 4 已注明）：lock=槽目录内文件，stop() 清 db/日志后保留
空 lock 文件=槽锚（unlink 后旧 flock inode 与新建文件不再互斥=假独占风险）。
"""

from __future__ import annotations

import errno
import fcntl
import os
import pathlib
import signal
import socket
import subprocess
import time

REPO = pathlib.Path(__file__).resolve().parent.parent

# 生产端口面（frontend/UI）：本库一切出网路径的 fail-closed 黑名单。
# metrics 端口生产侧未固定公开，不列入（隔离台自身 metrics 全显式即可）。
PROD_PORTS = {7233, 8233}

# 槽位端口基址：frontend 19100+ / UI 19200+ / metrics 19300+ 槽号。
# 结构性避开 7233/8233/3099；--ui-port 缺省=--port+1000（CLI 实测），必须显式。
SLOT_FE_BASE = 19100
SLOT_UI_BASE = 19200
SLOT_MET_BASE = 19300

_START_TIMEOUT = 60          # temporalite 就绪上限（秒）
_STOP_TERM_TIMEOUT = 10      # 优雅停等待（秒）


class ProductionGuardError(RuntimeError):
    """目标是生产 temporal（7233/8233）——fail-closed 拒跑。"""


class BenchBusy(RuntimeError):
    """槽满排队超 deadline（真超时，非断言假红；文案可辨）。"""


class BenchEnvConflict(RuntimeError):
    """槽端口被外来者占用——环境冲突不对抗（exit3 语义）。"""


class MissingAsset(RuntimeError):
    """temporal 二进制/venv 解释器不可得（exit2 语义，文案指路）。"""


def assert_not_production(host_port: str) -> str:
    """fail-closed：host:port 指向生产（7233/8233）即抛 ProductionGuardError。
    返回原串（合法时）供链式使用。"""
    s = str(host_port or "")
    port = None
    if ":" in s:
        port = s.rsplit(":", 1)[1].strip()
    elif s.isdigit():
        port = s
    if port is not None:
        try:
            n = int(port)
        except ValueError:
            n = None
        if n in PROD_PORTS:
            raise ProductionGuardError(
                "拒跑（fail-closed）：目标是生产 temporal 端口 %d（%r）——隔离台绝不碰 7233/8233"
                % (n, s))
    if not s:
        raise ProductionGuardError("拒跑（fail-closed）：空目标地址")
    return s


def port_open(port, host="127.0.0.1", timeout=1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, int(port))) == 0
    finally:
        s.close()


def pick_free_port() -> int:
    """port-0 内核分配（骨架口径：bind(0) 取内核给的端口后释放）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    n = s.getsockname()[1]
    s.close()
    return n


def main_root_of(repo_root) -> "pathlib.Path | None":
    """worktree 的 .git 是 gitfile（"gitdir: <main>/.git/worktrees/<name>"）→ 主仓根。
    非 worktree（.git 是目录）→ None。只读 .git 文件（不写不改）。"""
    git_path = pathlib.Path(repo_root) / ".git"
    try:
        if not git_path.is_file():
            return None
        first = git_path.read_text(encoding="utf-8").splitlines()[0].strip()
    except OSError:
        return None
    if not first.startswith("gitdir:"):
        return None
    gitdir = pathlib.Path(first[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = pathlib.Path(repo_root) / gitdir
    gitdir = gitdir.resolve()
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return None


def _resolve_asset(env_key, lane_path: pathlib.Path, what: str) -> pathlib.Path:
    """资产解析：env > 泳道位 > 主树回退（gitfile 推导）> MissingAsset。"""
    env_val = os.environ.get(env_key)
    if env_val:
        p = pathlib.Path(env_val)
        if p.exists():
            return p
        raise MissingAsset("%s=%s 不存在（env 指路优先，检查路径）" % (env_key, env_val))
    if lane_path.exists():
        return lane_path
    main = main_root_of(REPO)
    if main is not None:
        rel = lane_path.relative_to(REPO)
        cand = main / rel
        if cand.exists():
            return cand
    raise MissingAsset(
        "%s 不可得：泳道 %s 缺失，主树回退失败（非 worktree 或主树也缺）。"
        "处置：env %s=<路径> 指路，或在主树补齐资产" % (what, lane_path, env_key))


def resolve_temporal_bin() -> pathlib.Path:
    return _resolve_asset("SUYOU_TEMPORAL_BIN",
                          REPO / "server" / "dsh" / "temporal-poc" / "bin" / "temporal",
                          "temporal 二进制")


def resolve_poc_python() -> pathlib.Path:
    return _resolve_asset("SUYOU_POC_PYTHON",
                          REPO / "server" / "dsh" / "temporal-poc" / ".venv" / "bin" / "python",
                          "带 temporalio 的 venv 解释器")


def poc_python() -> str:
    """引擎 venv 解释器（含主树 gitfile 回退）。"""
    return str(resolve_poc_python())


_BENCH_ROOT_CACHE = None


def _root_writable(root: pathlib.Path) -> bool:
    """槽根可用性真探测：mkdir 之外还要真写+删一个探针文件——目录已存在但
    不可写文件时 mkdir(exist_ok=True) 会静默通过（acceptance P1 实锤的假通）。"""
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".probe"
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def bench_root() -> pathlib.Path:
    """槽位根：SANDBAR_TEST_BENCH_DIR > ~/.sandbar/test-benches > 平台临时区回落。

    回落条件=~/.sandbar 不可写（受限沙箱会话）——stderr 一行明示降级路径（不
    静默；真实环境无此行）。进程内缓存保证多槽排队看见同一个根。
    env 指路的根自身不可写=MissingAsset（点名旋钮，不静默换根）。"""
    global _BENCH_ROOT_CACHE
    if _BENCH_ROOT_CACHE is not None:
        return _BENCH_ROOT_CACHE
    import sys as _sys
    import tempfile
    env_val = os.environ.get("SANDBAR_TEST_BENCH_DIR")
    if env_val:
        root = pathlib.Path(env_val)
        if not _root_writable(root):
            raise MissingAsset(
                "SANDBAR_TEST_BENCH_DIR=%s 不可写（mkdir/建文件被拒）——env 指路的槽根"
                "必须可写，请改指可写路径" % env_val)
        _BENCH_ROOT_CACHE = root
        return root
    root = pathlib.Path.home() / ".sandbar" / "test-benches"
    if not _root_writable(root):
        root = pathlib.Path(tempfile.gettempdir()) / "sandbar-test-benches"
        if not _root_writable(root):
            raise MissingAsset(
                "槽根不可用：~/.sandbar 与平台临时区均不可写。处置：env "
                "SANDBAR_TEST_BENCH_DIR=<可写路径> 指路")
        print("[bench] ~/.sandbar 不可写——槽根降级至 %s（明示降级，非静默；"
              "可用 SANDBAR_TEST_BENCH_DIR 旋钮指定）" % root, file=_sys.stderr)
    _BENCH_ROOT_CACHE = root
    return root


def slot_count() -> int:
    try:
        return max(1, int(os.environ.get("SANDBAR_TEST_BENCH_SLOTS") or 4))
    except ValueError:
        return 4


class Slot:
    """一个 temporalite 槽：flock 独占（崩溃自释）+ 槽专属 db/namespace/端口组。

    生命周期：acquire_slot() → start_temporalite() → spawn_env()/跑场景 → stop()。
    - 满槽=排队等锁至 deadline，超时抛 BenchBusy（真超时非假红）；
    - 锁的持有权在 start_temporalite() 成功后移交给 temporalite 进程（fd 随
      pass_fds 继承）：temporalite 活=锁活；kill -9/崩溃=内核收 fd=锁自释——
      场景①崩溃腿断言的「同槽立即可复抢」即此。本进程自身崩溃同理；
    - lock 文件在 stop() 后**保留**（槽锚）：unlink 后 flock 持有的旧 inode 与
      新建文件不再互斥=假独占（epic 验收 4 的「槽位全清」口径=清 db/日志/临时
      产物，空 lock 文件是槽锚保留——已在 epic 落文，review C7）；
    - stop() 幂等（TERM 进程组→KILL 兜底→端口释放核验→清 db/日志）。
    """

    def __init__(self, root, n: int):
        self.root = pathlib.Path(root)
        self.index = int(n)
        self.frontend_port = SLOT_FE_BASE + self.index
        self.ui_port = SLOT_UI_BASE + self.index
        self.metrics_port = SLOT_MET_BASE + self.index
        for p in (self.frontend_port, self.ui_port, self.metrics_port):
            if p in PROD_PORTS:  # 结构上不可达，防御性再闸一道
                raise ProductionGuardError("槽端口 %d 落在生产端口面" % p)
        self.slot_dir = self.root / ("slot-%d" % self.index)
        self.lock_path = self.slot_dir / ("slot-%d.lock" % self.index)   # 槽锚（stop 后保留）
        self.db_path = self.slot_dir / "temporal.db"
        self.log_path = self.slot_dir / "temporalite.log"
        self.namespace = "bench-slot-%d" % self.index
        self.host = "127.0.0.1"
        self.argv = None            # 实际使用的 temporal 起动参数（断言面）
        self.temporalite_pid = None
        self.stopped = False
        self._lock_fd = None

    # ---- 获取/释放 ----

    def try_lock(self) -> bool:
        try:
            self.slot_dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as e:
            # 槽目录/锁文件不可建=环境受限（P1：不裸 traceback，点名旋钮可辨）
            raise MissingAsset(
                "槽 %d 锁文件不可建（%s: %s）——槽根 %s 受限。处置：env "
                "SANDBAR_TEST_BENCH_DIR=<可写路径> 指路"
                % (self.index, type(e).__name__, e, self.root)) from e
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        self._lock_fd = fd
        return True

    def release(self):
        """放锁（未起服务/起服务失败时本进程还持 fd；起跑成功后 fd 已移交，空操作）。"""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

    # ---- 起停 ----

    def _port_free(self, port) -> bool:
        return not port_open(port)

    def start_temporalite(self):
        """起槽 temporalite（幂等：已起且端口活着=复用不重起）。"""
        if self.temporalite_pid is not None and not self.stopped \
                and self._port_free(self.frontend_port) is False:
            return self  # 已在跑
        if self._lock_fd is None:
            raise RuntimeError("槽未上锁先起服务（先 acquire；或锁已随崩溃自释需重新 acquire）")
        for p, label in ((self.frontend_port, "frontend"), (self.ui_port, "ui"),
                         (self.metrics_port, "metrics")):
            if not self._port_free(p):
                raise BenchEnvConflict(
                    "环境冲突：槽 %d 的 %s 端口 %d 已被占用（lsof -ti tcp:%d 查占用者）。"
                    "隔离台不与在位者对抗——重跑或换槽根（SANDBAR_TEST_BENCH_DIR）"
                    % (self.index, label, p, p))
        self.slot_dir.mkdir(parents=True, exist_ok=True)
        bin_path = resolve_temporal_bin()
        # 三端口全显式（--ui-port 缺省=--port+1000 是暗雷；metrics 同理显式）。
        self.argv = [str(bin_path), "server", "start-dev",
                     "--db-filename", str(self.db_path),
                     "--ip", self.host,
                     "--port", str(self.frontend_port),
                     "--ui-port", str(self.ui_port),
                     "--metrics-port", str(self.metrics_port),
                     "--log-level", "warn"]
        logf = open(self.log_path, "ab", buffering=0)
        try:
            # flock fd 随子进程继承（pass_fds）：锁的存活绑定 temporalite 进程。
            self.proc = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL,
                                         stdout=logf, stderr=logf,
                                         cwd=str(self.slot_dir), start_new_session=True,
                                         pass_fds=(self._lock_fd,))
        finally:
            logf.close()
        # 起跑成功：锁移交完成，本进程放手（fd 关闭不影响子进程已继承的锁）。
        self.release()
        self.temporalite_pid = self.proc.pid
        self.stopped = False
        self._wait_ready()
        self._setup_namespace()
        return self

    def _wait_ready(self):
        t0 = time.time()
        while time.time() - t0 < _START_TIMEOUT:
            if self.proc.poll() is not None:
                break
            if port_open(self.frontend_port):
                return
            time.sleep(0.3)
        tail = ""
        try:
            tail = self.log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            pass
        self.stop()
        raise RuntimeError("槽 %d temporalite %.0fs 内未就绪（frontend=%d）。日志尾：\n%s"
                           % (self.index, _START_TIMEOUT, self.frontend_port, tail or "（无日志）"))

    def _cli_ok(self, args, tolerate_contains=()):
        """跑 temporal CLI（对槽地址）；rc!=0 但输出含 tolerate_contains 任一串=幂等容忍。"""
        try:
            proc = subprocess.run([str(resolve_temporal_bin())] + args,
                                  capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return False, "timeout"
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            return True, out
        low = out.lower()
        for token in tolerate_contains:
            if token.lower() in low:
                return True, out
        return False, out

    def _setup_namespace(self):
        """槽专属 namespace + 工单 SA 注册（镜像 run_server.sh；纵深隔离）。"""
        addr = "%s:%d" % (self.host, self.frontend_port)
        ok, out = self._cli_ok(["operator", "namespace", "create", self.namespace,
                                "--address", addr],
                               tolerate_contains=("already exist", "already created"))
        if not ok:
            raise RuntimeError("槽 %d namespace create 失败：%s" % (self.index, out[-300:]))
        for name in ("ProjectKey", "EpicCode"):
            ok, out = self._cli_ok(["operator", "search-attribute", "create",
                                    "--namespace", self.namespace,
                                    "--name", name, "--type", "Keyword",
                                    "--address", addr],
                                   tolerate_contains=("already exist", "already defined",
                                                      "already registered"))
            if not ok:
                raise RuntimeError("槽 %d SA %s 注册失败：%s" % (self.index, name, out[-300:]))

    def stop(self):
        """停 temporalite + 清槽内产物（db/wal/shm/日志）。幂等；lock 文件保留（槽锚）。"""
        proc = getattr(self, "proc", None)
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            t0 = time.time()
            while time.time() - t0 < _STOP_TERM_TIMEOUT and proc.poll() is None:
                time.sleep(0.2)
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        self.proc = None
        self.temporalite_pid = None
        # 端口释放核验（TERM/KILL 后短暂窗口）
        t0 = time.time()
        while time.time() - t0 < 5:
            if self._port_free(self.frontend_port) and self._port_free(self.ui_port) \
                    and self._port_free(self.metrics_port):
                break
            time.sleep(0.2)
        # 清产物：db 本体 + sqlite wal/shm 旁车 + 日志；lock=槽锚保留
        if self.slot_dir.is_dir():
            for f in sorted(self.slot_dir.iterdir()):
                if f == self.lock_path:
                    continue
                try:
                    if f.is_dir():
                        import shutil
                        shutil.rmtree(f, ignore_errors=True)
                    else:
                        f.unlink()
                except OSError:
                    pass
        self.release()
        self.stopped = True

    def teardown(self):
        """全清（stop+release 已含；保留此别名兼容早期调用面）。"""
        self.stop()

    # ---- 场景接口 ----

    def spawn_env(self, **extra) -> dict:
        """被测引擎子进程 env：SUYOU_TARGET_HOST 指槽（过生产守卫）+ 槽 namespace。"""
        env = dict(os.environ)
        env["SUYOU_TARGET_HOST"] = assert_not_production("%s:%d" % (self.host, self.frontend_port))
        env["SUYOU_NAMESPACE"] = self.namespace
        env.update({k: str(v) for k, v in extra.items()})
        return env


def acquire_slot(index=None, deadline_s=None, root=None, poll_s: float = 0.3):
    """抢槽：index 指定=等那一个；None=任一空槽。满槽排队到 deadline（缺省 120s），
    超时抛 BenchBusy（真超时非假红）。"""
    root = pathlib.Path(root) if root else bench_root()
    n_slots = slot_count()
    if deadline_s is None:
        deadline_s = 120.0
    t0 = time.time()
    while True:
        order = [int(index)] if index is not None else list(range(1, n_slots + 1))
        for n in order:
            s = Slot(root, n)
            if s.try_lock():
                return s
            s.release()
        if time.time() - t0 >= deadline_s:
            raise BenchBusy(
                "槽满排队超时：等 %.0fs 无空槽（%s，%d 槽全忙——这是排队超时不是断言失败；"
                "检查是否有崩溃残留场景占槽未释）" % (deadline_s, root, n_slots))
        time.sleep(poll_s)


# ---- 「不连生产」审计钩子（python 面）----
# sitecustomize.py 注入被测子进程 PYTHONPATH：sys.addaudithook 监 socket.connect，
# 目标端口∈PROD_PORTS 先记 jsonl 后 raise——audit 钩子在系统调用前触发，raise 即
# 阻断（自证腿连 127.0.0.1:7233 会被拦，零真连生产）。
# 边界（明示不静默）：只覆盖 python 子进程；Go 面（temporal CLI）由槽位库的
# 显式端口参数 + argv 断言补面。

_AUDIT_SITECUSTOMIZE = '''import json as _json
import os as _os
import sys as _sys

_HITS = _os.environ.get("SANDBAR_AUDIT_HITS", "")
_FORBIDDEN = __FORBIDDEN__


def _bench_audit(event, args):
    if event != "socket.connect":
        return
    addr = args[1] if len(args) > 1 else None
    port = None
    if isinstance(addr, tuple) and len(addr) == 2:
        try:
            port = int(addr[1])
        except (TypeError, ValueError):
            port = None
    elif isinstance(addr, str) and addr.isdigit():
        port = int(addr)
    if port in _FORBIDDEN:
        if _HITS:
            try:
                with open(_HITS, "a") as f:
                    f.write(_json.dumps({"event": event, "addr": list(addr) if isinstance(addr, tuple) else str(addr)}) + "\\n")
            except OSError:
                pass
        raise PermissionError("bench 审计钩子：禁止连接生产端口 %d（隔离台 fail-closed）" % port)


_sys.addaudithook(_bench_audit)
'''


def audit_hook_env(dirpath):
    """装审计钩子。返回 (env 片段, 日志路径)：env 含 PYTHONPATH（前插）+
    SANDBAR_AUDIT_HITS；复装会清旧记录（每腿从零记账）。"""
    d = pathlib.Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    (d / "sitecustomize.py").write_text(
        _AUDIT_SITECUSTOMIZE.replace("__FORBIDDEN__", repr(sorted(PROD_PORTS))),
        encoding="utf-8")
    log_path = d / "hits.jsonl"
    try:
        log_path.unlink()
    except FileNotFoundError:
        pass
    env_add = {"SANDBAR_AUDIT_HITS": str(log_path)}
    existing = os.environ.get("PYTHONPATH", "")
    env_add["PYTHONPATH"] = str(d) + (os.pathsep + existing if existing else "")
    return env_add, str(log_path)


# ---- fixture 注册表 ----

_REGISTRY_KEY_RE = None  # 延迟取 shared 的真源正则（见 write_registry）


def write_registry(dirpath, key, project_dir):
    """造 fixture 项目注册表（形状=server/dsh/temporal-poc shared.load_projects_registry
    的 per-key 目录档）。返回注册表根目录（SANDBAR_PROJECTS_DIR 直用）。"""
    import re
    d = pathlib.Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    if not re.match(r"^[a-z][a-z0-9-]{1,30}$", str(key)):
        raise ValueError("注册表 key 不合法（^[a-z][a-z0-9-]{1,30}$）：%r" % key)
    proj = pathlib.Path(project_dir)
    if not proj.is_absolute():
        raise ValueError("project_dir 必须绝对路径（锚定语义）：%r" % project_dir)
    key_dir = d / str(key)
    key_dir.mkdir(parents=True, exist_ok=True)
    # project_dir 原文落盘（不做 realpath 解引用）：场景断言以传入路径为锚比对，
    # macOS 下 /var→/private/var 符号链接解引用会制造假不匹配。
    (key_dir / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n      - %s\n"
        % (key, key, project_dir),
        encoding="utf-8")
    return str(d)


# ---- console boot 骨架 python 侧（临时家/凭据只拷 credentials/teardown 幂等）----
# profile 构建在 bench_console.mjs（复用 ui-check/capture-lane.mjs 真源）。

class TempDSHHome:
    """临时 DSH_HOME：mkdtemp + 只拷 .credentials.yaml（绝不拷 settings.yaml——
    防用户把端口钉死 3099，骨架原教训）。teardown 幂等 rm。"""

    def __init__(self, base_dir=None):
        import tempfile
        base = pathlib.Path(base_dir) if base_dir else pathlib.Path(tempfile.gettempdir())
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="sandbar-bench-dsh-", dir=str(base)))
        self._gone = False

    def copy_credentials(self) -> bool:
        srcs = []
        if os.environ.get("DSH_HOME"):
            srcs.append(pathlib.Path(os.environ["DSH_HOME"]))
        srcs.append(pathlib.Path.home() / ".dsh")
        for d in srcs:
            cred = d / ".credentials.yaml"
            if cred.is_file():
                (self.home / ".credentials.yaml").write_bytes(cred.read_bytes())
                return True
        return False

    def teardown(self):
        if self._gone:
            return
        self._gone = True
        import shutil
        shutil.rmtree(self.home, ignore_errors=True)
