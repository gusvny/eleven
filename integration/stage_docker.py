#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single entry point for the docker test stage (t260904-19): the only way the
repo brings a stage up.

Hand-built process stages (random-port throwaway consoles, slot-based
temporalite, capture-lane self-built boots) and the docker test bench used to
coexist as two tracks — this file collapses them into one: every scenario that
needs a stage brings it up here (same compose file
server/docker-compose.test.yml), each stage with its own compose project name +
own port band + own container-name/volume prefix, so parallel stages never
collide.

Subcommands:
  up --project <name> [--services temporal|dsh|full] [--namespace <ns>]
     [--fixtures-dir <host dir>] [--profile-dir <host dir>] [--repo-dir <host dir>]
     [--timeout <sec>]        bring a stage up; stdout gets the JSON
                              {project,console,temporal,...}
     [--nm-repo-dir <dir>]    plugin dependency tree (profile/node_modules fully
                              installed; default = fall back to the main tree
                              when the lane lacks them). Decoupled from
                              --repo-dir (the tested tree).
  ensure --project <name> [--keep] [...same flags as up]   idempotent ensure:
                              a live lease (state=up + fresh heartbeat + holder
                              alive) is reused with zero docker queries; a
                              booting lease is waited for, never double-booted;
                              a dead lease (expired AND holder gone) is
                              reclaimed and rebuilt; --keep = never tear down a
                              running face (supply-stage semantics: honest red
                              instead of fighting); --keep boots a RESIDENT
                              lease (keep=true): its hold leg skips the ③
                              anchor-death reclaim — the caller shell is
                              short-lived by design (verify.yaml supply 闸后
                              常驻不拆); the stage lives until explicit down /
                              the MAX_HOLD_S cap / a crash, all folding into
                              the single expiry+holder-dead reclaim criterion
  down --project <name>      tear the stage down (state→downing → hold harvest
                              → down -v → lease release); idempotent, exits 0
                              when absent too
  hold --project <name> --anchor-pid <pid> --lease-id <id>
                             the lease-holding leg (spawned internally by
                             up/ensure; heartbeats the lease for exactly its
                             holding period; seven terminal states — see
                             cmd_hold)
  sweep [--dry-run]          残台清扫（t260912-02）：按主人存在性（compose 工作
                              目录已删 / 泳道不在 git worktree list / 心跳陈旧
                              超阈）判定逐条租约，判拆的全拆（容器+网络+卷）并
                              逐条点名；两条安全阀（booting 新鲜 / 泳道在册）
                              一律不碰；stdout 回 JSON 报告
  inventory                  台面清点（t260915-18，只读）：租约×容器 join 回 JSON——
                              容量面（容器/工程/活租约/孤儿 vs MAX_STAGES 保险丝）
                              + 每台归属（ticket/attempt→project 映射、锚、心跳
                              年龄）；孤儿=本管域容器而无租约文件
  selftest                   white-box self test (never touches docker):
                              forbidden-port exclusion / band locks / lease
                              criteria / malformed input rejection

Exit codes (three-state contract, integration/README.md):
  0=ok; 2=ENV_FAIL (docker absent / image absent / unhealthy boot / port band
  exhausted / 起台保险丝刹停——t260912-02 起不再是排队预算，是
  SANDBAR_STAGE_MAX_STAGES 上限刹停；红行点名保险丝并附活租约清单 =
  失败分类协议要求的 evidence，kind=env 的归属理由见 capacity_acquire 注);
  3=environment conflict (an explicitly requested port is taken; a live lease
  already holds the project — do not fight it); 64=usage/malformed input
  (scenario-code bug class).

## Failure-mode handling (item by item against the old stage's failures, with the verdict)

| old-stage failure | this module's handling |
| --- | --- |
| port collision (pinned ports) | band flock atomic reservation + forbidden-zone exclusion + bind probe. The lock spans the whole "probe -> compose up -> healthy" window; by release time the daemon has really bound the port = TOCTOU closed |
| concurrent cross-talk | own compose project name + own container names + own volume prefix + band lock. Isolation granularity raised to container level |
| holder crash keeps the lock | the lock fd lives only in this process: process death = kernel closes the fd = the lock releases itself. If the container already bound the port before the crash, the next entrant's bind probe sees it busy and slides to the next band |
| teardown re-entry crash | down is idempotent: missing project / already-cleared containers both exit 0, safe to call three times in a row |
| detached process leaks | containers are held by the docker daemon, no host grandchild process tree; the hold leg is the one detached process — it lives exactly one lease and exits via its seven terminal states (release/signal/anchor-death/cap/crash); down harvests it by pid before unlinking the lease |
| service start times out with no diagnosis | the timeout carries a `docker compose logs` tail (2000 bytes) + an in-place down -v cleanup before exiting |
| accidental production connect, fail-closed | hard forbidden set {3099,3199,7233,8233,17233,18233} + a post-boot self-check that the JSON ports are outside the production set |
| preset missing refuses to run | it does not: stay on the capture lane (stage and evidence semantics stay layered) |
| five-path terminal reclamation | CLI side: normal/error/timeout/SIGINT/SIGTERM all run the down -v cleanup |
| 残台白占名额/内存（t260912-02 病灶二：hold 腿活着→租约永新鲜，工作目录删了也判不死）| 主人存在性清扫 sweep：compose 工作目录已删 / 泳道不在 git worktree list / 心跳陈旧超阈 三判据 + booting 新鲜、泳道在册两条安全阀；挂套件前与起台时两处；判拆全拆并逐条点名，清理失败响亮不静默 |
| 爆发建网撞 docker 地址池（t260912-02 病灶三：fully subnetted 纯瞬时头寸）| 受管网段表（10.213.0.0/16 切 /24）：每台 compose 建网显式指定子网（ipam subnet 注入），分配对照在册租约+daemon 现存网段防撞、随机选槽不可猜；建网不再走分配器库存 |

State and locks (t260910-12 lease semantics):
  lock/state root = $SANDBAR_STAGE_LOCK_DIR > ~/.sandbar/test-stages > platform
  temp fallback (the fallback prints one stderr line, never silent).
  band-<n>.lock is the band lock;
  capacity-0.lock is the起台保险丝 global lock (t260912-02：名额排队闸退役——
  只剩保险丝判定；count + placeholder 仍写在同一把 flock 临界区里，
  count-then-claim 原子、并发不超售的性质原样保留);
  ensure-<project>.lock serializes same-project cold boots;
  project-<name>.json is the LEASE record — the single liveness fact:
    {lease_id, holder:{ticket,pid}, anchor_pid, state: booting|up|downing,
     ports, heartbeat_ts, ttl_sec, container_ids, subnet, owner_root, ...}
  Reclaim criterion (the ONLY one): lease expired (now - heartbeat > TTL) AND
  holder process does not exist. No docker ps sampling, no mtime freshness
  grace, no foreign-activity yielding — every "guess whether the other guy is
  dead" heuristic is gone (all three failed in concurrent windows: run
  L/M/O/Q/U/X recorded in the old code comments).
  该判据管的是「复用/判死」语义（ensure 状态机），一字未动（t260912-02）。
  残台清扫是**附加清道夫**，判据按主人存在性（owner_root 目录已删 / 泳道
  不在 git worktree list / 心跳陈旧超阈），只做全拆不参与复用判定——
  260912 实测病灶：hold 腿活着心跳就新鲜，工作目录删了也永判不死，白占
  名额/内存/网络。

  Who keeps the lease alive: the `hold` subcommand — a detached child spawned
  by up/ensure BEFORE booting, living exactly as long as the lease (booting +
  up), heartbeating every LEASE_HEARTBEAT_S. The one-shot CLI process exits
  right after printing its JSON; the hold leg is the process whose pid the
  lease records as holder.pid. Invariant: for the whole holding period there
  is one probeable real process; when it dies (crash/kill -9) the heartbeat
  stops and the lease becomes reclaimable after TTL. This is NOT a daemon:
  one hold per lease, no single point, and a dead hold leaves a
  self-consistent system (expiry + pid-death reclaim).

  Hold's orphan anchor: the CLI passes its own parent pid (--anchor-pid) —
  with_stage.sh's shell / the mjs node process, i.e. the long-lived caller
  that co-exists with the scenario. Anchor death = caller tree gone → hold
  reclaims the orphan stage (down + release). Anchor pid reuse (scenario dead
  + pid recycled) is bounded by SANDBAR_STAGE_MAX_HOLD_S: the hold exits
  honestly past the cap instead of heartbeating forever. When calling the CLI
  straight from an interactive shell, the anchor is that shell — the stage
  then lives up to the cap unless you `down` it (or set a small
  SANDBAR_STAGE_MAX_HOLD_S); the cap-exit stderr line names this.
"""

from __future__ import annotations

import errno
import fcntl
import ipaddress
import json
import os
import pathlib
import random
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
DSH_IMAGE = "test-dsh:dsh-0.1.1-rc.2"          # 260908: dsh baked into the image, no per-stage networked npm at boot
DSH_BUILD_SCRIPT = "server/build-test-dsh.sh"

# Forbidden zone: the three production ports (3099/7233/8233) + the three
# default test-bench ports (3199/17233/18233).
# Band allocation never returns a forbidden port; naming one via env explicitly = rejected.
FORBIDDEN_PORTS = {3099, 3199, 7233, 8233, 17233, 18233}
PROD_PORTS = {3099, 7233, 8233}          # production surface (same set as bench.PROD_PORTS + the 3099 console)
DEFAULT_CONSOLE_PORT, DEFAULT_TEMPORAL_PORT, DEFAULT_TEMPORAL_UI_PORT = 3199, 17233, 18233

# Port bands: 10 wide each, starting at 21000 (console=+0 / temporal=+1 / ui=+2).
# The band base sits below the common kernel ephemeral ranges (Linux 32768+ /
# macOS 49152+) — structurally safe;
# at runtime ip_local_port_range is read as well to strip overlap (unreadable =
# bypass that defense layer, no single point of dependence).
# 带基址可用 SANDBAR_STAGE_BAND_BASE 重指（t260912-02）：多泳道共用一台宿主时，
# 兄弟泳道的真台常驻 21000 窗，L1 电池（要求全净窗的档位竞争面）可重指空闲窗
# 跑；缺省 21000 语义不变，畸形值=usage 红（三态诚实）。
BAND_BASE_DEFAULT = 21000
BAND_STEP, BAND_COUNT = 10, 400
SLOT_OFFSET = {"console": 0, "temporal": 1, "ui": 2}


def band_base():
    """档位带基址：缺省 21000；SANDBAR_STAGE_BAND_BASE 可重指（整数、1024~60000，
    且不与生产面重叠——3099/7233/8233 及缺省台 3199/17233/18233 一律拒绝）。"""
    raw = (os.environ.get("SANDBAR_STAGE_BAND_BASE") or "").strip()
    if not raw:
        return BAND_BASE_DEFAULT
    try:
        val = int(raw)
    except ValueError:
        raise StageError("usage 红：SANDBAR_STAGE_BAND_BASE 必须是整数端口基址"
                         "（得到 %r）" % raw, kind="usage")
    forbidden = PROD_PORTS | {DEFAULT_CONSOLE_PORT, DEFAULT_TEMPORAL_PORT,
                              DEFAULT_TEMPORAL_UI_PORT}
    if any(abs(val - p) < BAND_COUNT * BAND_STEP for p in forbidden):
        raise StageError("usage 红：SANDBAR_STAGE_BAND_BASE=%d 与生产/缺省台端口"
                         "窗重叠（禁区 %s ±%d）" % (val, sorted(forbidden),
                                                   BAND_COUNT * BAND_STEP),
                         kind="usage")
    if not (1024 <= val <= 60000 - BAND_COUNT * BAND_STEP):
        raise StageError("usage 红：SANDBAR_STAGE_BAND_BASE=%d 超出可指窗 "
                         "1024~%d" % (val, 60000 - BAND_COUNT * BAND_STEP),
                         kind="usage")
    return val


def __getattr__(name):  # PEP 562：BAND_BASE 动态解析，读侧零改动
    if name == "BAND_BASE":
        return band_base()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))

# 受管网段表（t260912-02 病灶三）：base /16 切 256 个 /24 槽，每台 compose 建网
# 显式指定子网（compose 文件 ipam subnet 注入），建网不再向 docker 分配器申请
# 库存——「all predefined address pools have been fully subnetted」从根上消失
# （260912 实测：爆发 32 台走池 23/32，指定网段 32/32 1.35s）。尾槽保留给
# 手工直跑 compose 的缺省路径（docker-compose.test.yml 的 env 缺省值），
# 分配器永不发出。与宿主 VPN/局域网撞号时用 SANDBAR_STAGE_NET_BASE 重指。
NET_BASE_DEFAULT = "10.213.0.0/16"
NET_PREFIXLEN = 24                       # base 必须是 /16，槽 = /24
NET_RESERVED_TAIL = 1                    # 尾部保留槽数（手工缺省路径专用）
NET_NAME_FMT = "%s_default"              # compose 默认网络名（确定性，供清理/断言）

# ---- 租约旋钮（env 可调；测试注入小值用，生产缺省见各函数 docstring）----
# 旋钮一律走函数实时读 env：单测同进程改 env 即生效，不必 reload 模块。


def lease_ttl_s():
    """租约 TTL（秒）：过期判据的第一条腿。缺省 90s >> 心跳 5s——心跳线程
    被调度/GC 停顿一两个周期不致误判死。"""
    return float(os.environ.get("SANDBAR_STAGE_LEASE_TTL_S", 90))


def lease_heartbeat_s():
    """hold 心跳周期（秒）。"""
    return float(os.environ.get("SANDBAR_STAGE_HEARTBEAT_S", 5))


def max_hold_s():
    """hold 最大持有期帽（秒）：锚 pid 被复用（场景死+pid 被无关新进程顶替）
    时 hold 会误活——帽把损害上限封死，超帽诚实自退（stderr 留痕），台交给
    判死回收/人工 down。缺省 4h >> 单场景 900s 执行器帽。"""
    return float(os.environ.get("SANDBAR_STAGE_MAX_HOLD_S", 4 * 3600))


def max_stages():
    """起台保险丝（t260912-02 病灶一）：活租约并发上限，缺省 100。它不再是
    名额排队闸——排队闸是全机共用名额，把常驻台/供给台/残台一并计入，正常
    负载也会自挤（260912 实测：上限 12 时 12 台并发 3 台卡满 150s 超时；仅把
    上限改 30 即 12/12 全部 5.3s）。闸的职责只剩防呆：正常负载（≤32 台爆发）
    永不触及，只在「某个测试写错循环一口气起上百台」时刹停点名。env 名不改
    （兼容既有注入脚本），缺省 12→100。"""
    return int(os.environ.get("SANDBAR_STAGE_MAX_STAGES", 100))


def net_base():
    """受管网段表 base（t260912-02 病灶三）。必须是 IPv4 /16——畸形=usage 红
    点名（外部输入三态纪律：畸形拒收，绝不静默回落）。"""
    val = os.environ.get("SANDBAR_STAGE_NET_BASE", NET_BASE_DEFAULT).strip()
    m = re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/16$", val)
    if not m or any(int(g) > 255 for g in m.groups()):
        raise StageError(
            "SANDBAR_STAGE_NET_BASE 不合法：%r（必须是 IPv4 /16 形，如 %s）"
            % (val, NET_BASE_DEFAULT), kind="usage")
    return val


def sweep_stale_s():
    """残台清扫的心跳陈旧阈（秒，t260912-02）。缺省 600 = 6.7×TTL（90s）：
    必须 ≫ TTL，否则 hold 腿一次 GC/调度停顿就可能被误判残台拆掉活台。"""
    return float(os.environ.get("SANDBAR_STAGE_SWEEP_STALE_S", 600))


def stall_grace_s():
    """心跳停更宽限窗（秒，t260913-02 arbitrate gen12）。缺省 20s：租约过期而 holder
    仍活时，先把这段时间用来等心跳恢复（负载压住 hold 腿的一次停顿 ≈ 数秒~数十秒），
    而不是当场把整族场景打成环境红；到期仍不恢复=真僵死，按原语义诚实红点名人工。
    判据（只有 过期 AND holder 亡 才回收）不动，本窗只区分「瞬时停顿」与「真僵死」。"""
    return float(os.environ.get("SANDBAR_STAGE_STALL_GRACE_S", 20))


def sweep_budget_s():
    """单次清扫的时间预算（秒）：超预算的未处理项逐条点名上抛，绝不静默。
    缺省 30s——零残台时实测扫描 ~0.7s，预算只约束「有残台要拆」的长尾。"""
    return float(os.environ.get("SANDBAR_STAGE_SWEEP_BUDGET_S", 30))


def sweep_orphans_enabled(default=True):
    """孤儿容器清扫开关（t260915-18 C10+对抗发现 F1）：SANDBAR_STAGE_SWEEP_ORPHANS
    ∈ {0,off,no} 显式关；∈ {1,on,yes} 显式开；**未设=default**——调用方按自身
    语义给缺省：`sweep` CLI（操作员显式发起）缺省开；up/ensure 挂点钩子缺省
    **关**（260915 实爆 F1：无半径+缺省开的挂点清扫把宿主存量孤儿当一次普通
    up 顺手真拆——真拆须宿主点头，挂点只做租约面，孤儿面必须显式点名启用）。
    畸形值=usage 红点名（不静默归默认）。"""
    raw = str(os.environ.get("SANDBAR_STAGE_SWEEP_ORPHANS", "")).strip().lower()
    if not raw:
        return bool(default)
    if raw in ("0", "off", "no", "false"):
        return False
    if raw in ("1", "on", "yes", "true"):
        return True
    raise StageError("SANDBAR_STAGE_SWEEP_ORPHANS 不合法：%r（须 on/off 族）"
                     % raw, kind="usage")


def orphan_prefix():
    """孤儿清扫半径旋钮（t260915-18 场景② F1 硬契约）：设置后 condemned 仅限
    命中前缀的工程名——孤儿容器是全机全局可见面，无半径的「在管域+超龄即拆」
    会让任一次 sweep 波及他票/宿主存量（宿主点头红线）。空/未设=不限半径。"""
    raw = str(os.environ.get("SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX", "")).strip()
    return raw or None


def orphan_min_age_s():
    """孤儿容器最短年龄阀（秒，t260915-18 C10）：缺省 1800s。容器年龄不足不拆
    ——孤儿判定本就要求「无租约文件」，年龄阀是第二道保守阀（防与 hold ③
    回收窗/极短命场景竞争）。畸形值=usage 红点名（旋钮纪律同 NET_BASE）。"""
    raw = str(os.environ.get("SANDBAR_STAGE_ORPHAN_MIN_AGE_S", "")).strip()
    if not raw:
        return 1800.0
    try:
        v = float(raw)
    except ValueError:
        raise StageError("SANDBAR_STAGE_ORPHAN_MIN_AGE_S 不合法：%r（必须非负秒数）"
                         % raw, kind="usage")
    if v < 0:
        raise StageError("SANDBAR_STAGE_ORPHAN_MIN_AGE_S 不合法：%r（必须非负秒数）"
                         % raw, kind="usage")
    return v


def hold_wait_s():
    """双向有界握手预算（秒）：ensure 等 hold 写就绪 pid 文件 / hold 等租约
    出现，都以此为帽（R1'a：Popen 返回 ≠ 子进程真起来了）。"""
    return float(os.environ.get("SANDBAR_STAGE_HOLD_WAIT_S", 10))


PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
DEFAULT_TIMEOUT = 600          # health-wait ceiling (covers the measured dsh container first-boot npm i + apt budget)
_STOP_TIMEOUT = 120            # compose down ceiling

EXIT_OK, EXIT_ENV, EXIT_CONFLICT, EXIT_FAIL, EXIT_USAGE = 0, 2, 3, 1, 64


class StageError(Exception):
    """Stage error carrying exit-code semantics: kind ∈ env/conflict/usage/fail
    （fail=产品面失败 t260912-02：拆台 compose 真失败要单行诚实红，不走裸异常）。"""

    def __init__(self, message, kind="env"):
        super().__init__(message)
        self.kind = kind
        self.exit_code = {"env": EXIT_ENV, "conflict": EXIT_CONFLICT,
                          "usage": EXIT_USAGE, "fail": EXIT_FAIL}[kind]


# ---------------------------------------------------------------- basic probes

def bind_free(port, host="127.0.0.1") -> bool:
    """A port is free only if we can bind it exclusively (stronger than a
    connect probe: half-open/TIME_WAIT also count as unavailable)."""
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
            return 200 <= r.status < 500  # a console 4xx (e.g. a not-ready redirect) still counts as HTTP alive
    except Exception:
        return False


def ephemeral_range():
    """Kernel ephemeral port range (best-effort; review N2: non-Linux reads
    nothing -> return None, do not crash)."""
    try:
        text = pathlib.Path("/proc/sys/net/ipv4/ip_local_port_range").read_text()
        lo, hi = (int(x) for x in text.split()[:2])
        return (lo, hi)
    except (OSError, ValueError):
        return None


def band_ports(band_index):
    base = band_base() + band_index * BAND_STEP
    return {name: base + off for name, off in SLOT_OFFSET.items()}


def band_ports_ok(ports, ephemeral=None):
    """All three band ports usable (constructive forbidden/ephemeral exclusion
    + bind probe)."""
    for p in ports.values():
        if p in FORBIDDEN_PORTS:
            return False
        if ephemeral and ephemeral[0] <= p <= ephemeral[1]:
            return False
        if not bind_free(p):
            return False
    return True


# ---------------------------------------------------------------- locks and state root

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
            # the probe name carries pid + clock: two concurrent boots deleting each
            # other's same-named probe would falsely report "unwritable" (proven by
            # the L1 concurrency case)
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
    """flock a band exclusively (non-blocking). Returns the fd on success
    (the caller closing it = releasing)."""
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


# ---------------------------------------------------------------- lease primitives (t260910-12)

def pid_alive(pid):
    """Process liveness probe (the lease's second reclaim leg). os.kill(pid,0)
    delivers no signal — it only checks existence: ESRCH = gone (False);
    EPERM = exists but not ours (True — a process we may not signal is still
    alive). Known weakness (KI, reported to the integration owner): a recycled
    pid reads as alive — an expired lease whose pid got reused stays
    "busy" until the满员闸 surfaces it as an honest red; never a teardown of
    someone else's stage. Faults toward NOT reclaiming by design."""
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def process_start_token(pid):
    """进程启动令牌（t260915-18 锚身份）：`ps -p <pid> -o lstart=` 的原文串。
    pid 被重用必然换出不同的启动时间——令牌不匹配=「不是当年那个锚」，治
    pid_alive 的已知弱点（重用读作活）。取不到（ps 缺席/进程已亡/平台差异）
    = None，调用方回落纯 pid 判定（兼容面，不引入新启发式）。"""
    try:
        p = _run(["ps", "-p", str(int(pid)), "-o", "lstart="], timeout=5, check=False)
    except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError):
        return None
    tok = (p.stdout or "").strip()
    return tok or None


def anchor_alive(pid, token):
    """锚身份两段判活（t260915-18）：pid 存在 AND（无令牌=纯 pid 判定；有令牌=
    启动时间逐字匹配）。锚=起台者的长命调用方进程（hold 腿 ③ 的回收判据面）；
    令牌不匹配即判「锚已亡」，宁可交 sweep/人工复核也不续跳误活。令牌探针
    不可得（ps 缺席等）=回落纯 pid 判定——不引入新单点，缺证据时向「不拆」
    fail-closed（crit_iv 靠令牌在才判，此处只影响 hold ③）。"""
    if not pid or not pid_alive(pid):
        return False
    if not token:
        return True
    cur = process_start_token(pid)
    if cur is None:
        return True
    return cur == token


def lease_anchor_alive(lease, anchor_pid):
    """按租约记录判锚活（t260915-18）：新租约带 anchor_token 走两段判活；
    旧格式无令牌回落纯 pid 判定（兼容面，行为一字不改）。畸形租约（非 dict）
    =无锚证据可验=保守判亡（与 anchor_alive「无法验证不续跳」同一口径）。"""
    if not isinstance(lease, dict):
        return False
    return anchor_alive(anchor_pid, lease.get("anchor_token"))


def holder_pid(lease):
    """Extract holder.pid, tolerating missing/malformed holder blocks (→ None
    = un-judgeable, treated as dead downstream)."""
    try:
        pid = (lease or {}).get("holder", {}).get("pid")
        return int(pid) if pid is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def new_lease(project, holder_pid, services, ticket=None, anchor_pid=None, ttl=None,
              lease_id=None, owner_root=None, anchor_token=None):
    """A complete occupancy granted at claim time (ticket spec ①): holder =
    ticket+pid, state=booting, TTL + fresh heartbeat. Written atomically inside
    the caller's flock critical section. lease_id injectable so the hold leg
    can be spawned knowing the id it must find (handshake).
    owner_root（t260912-02）：起台者的模块仓根（=compose 工作目录，_run 的 cwd），
    残台清扫按主人存在性判拆的锚。旧格式租约无此字段，清扫回落 repo_dir（见
    judge_residue）——回落语义是被测树/挂载源，可能有偏差，故活台+目录在时
    crit_ii 一律 fail-closed 不拆（C4b，只留报告行）。
    anchor_token（t260915-18）：锚进程的启动时间令牌（process_start_token），
    治 pid 重用误活——hold ③ 与 sweep crit_iv 据此判「主人已亡 hold 仍续跳」。"""
    now = time.time()
    return {
        "lease_id": lease_id or ("%s-%d-%s" % (project, int(now * 1000), os.urandom(4).hex())),
        "project": project,
        "holder": {"ticket": ticket or os.environ.get("SANDBAR_STAGE_TICKET") or "unknown",
                   "pid": int(holder_pid)},
        "anchor_pid": int(anchor_pid) if anchor_pid else None,
        "anchor_token": anchor_token,
        "state": "booting",
        "services": list(services),
        "ports": {},
        "subnet": None,
        "owner_root": owner_root or str(REPO),
        "ts": now,
        "heartbeat_ts": now,
        "ttl_sec": float(ttl if ttl is not None else lease_ttl_s()),
    }


def validate_holder_pid(pid):
    """holder pid 入口校验（R1'a：绝不把空/0/负数记进租约——记空=租约永可判
    死，回到 R1 的交付即拆）。非法=usage 红点名。"""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise StageError("holder pid 非法：%r（必须正整数——hold 腿 pid 缺失时"
                         "绝不起台）" % (pid,), kind="usage")
    return pid


def lease_path(project) -> pathlib.Path:
    return lock_root() / ("project-%s.json" % project)


def read_lease(project):
    """Read one lease. Malformed (truncated JSON / wrong shape) = None — never
    crash on foreign garbage; None reads as dead downstream."""
    try:
        data = json.loads(lease_path(project).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_lease(project, lease):
    """Atomic lease write: temp file + os.replace — a reader never sees a half
    file (the R5 no-lock polling relies on this). tmp 名带 time_ns：同进程多
    线程并发写不互偷 tmp（UT 实锤：仅 pid 后缀时线程 B 的 replace 会抢走线程
    A 的 tmp → FileNotFoundError）。"""
    p = lease_path(project)
    tmp = p.with_name(".%s.tmp-%d-%d" % (p.name, os.getpid(), time.time_ns()))
    tmp.write_text(json.dumps(lease, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(p))


def release_lease(project):
    """主动释放（正常 down 的最后一步 / 失败路径清理）。幂等。"""
    try:
        lease_path(project).unlink()
    except FileNotFoundError:
        pass


def lease_expired(lease, now=None):
    """过期判据第一条腿：heartbeat 停更超过 TTL。"""
    if not isinstance(lease, dict):
        return True
    try:
        hb = float(lease.get("heartbeat_ts"))
        ttl = float(lease.get("ttl_sec"))
    except (TypeError, ValueError):
        return True
    return (now if now is not None else time.time()) - hb > ttl


def lease_dead(lease, now=None, alive=None):
    """THE reclaim criterion (ticket spec ①): expired AND holder process does
    not exist. Nothing else kills a lease — not docker ps samples, not file
    age, not port reachability. Legacy pre-lease state files (no lease_id, the
    t260904-19 format) and malformed records count as dead: single-host test
    bench, one-shot upgrade window, prefer one false reclaim of an old-format
    stage over a stuck band (review R7). alive() injectable for tests."""
    if not isinstance(lease, dict) or not lease.get("lease_id"):
        return True
    pid = holder_pid(lease)
    if not pid:
        return True
    if not lease_expired(lease, now=now):
        return False
    alive_fn = alive if alive is not None else pid_alive
    return not alive_fn(pid)


def lease_reusable(lease, now=None, alive=None):
    """ensure's reuse test — the R3 primary signal: state=up + heartbeat FRESH
    + holder alive → reuse, ZERO docker queries. Container presence is NOT
    consulted here (docker ps sampling windows must never flip a live lease
    into the teardown path — that was the run L/M/O mutual-teardown family);
    container queries appear only in recovery confirmation and in the
    idempotent-reup evidence (container_ids), never in this decision.
    Expired-but-pid-alive is deliberately NOT reusable: freshness is the
    holder's own claim of liveness — a stale heartbeat with a living pid is
    the pid-reuse/僵死 shape, answered downstream by an honest red instead of
    a silent reuse or a teardown."""
    if not isinstance(lease, dict) or lease.get("state") != "up":
        return False
    if lease_expired(lease, now=now):
        return False
    pid = holder_pid(lease)
    if not pid:
        return False
    alive_fn = alive if alive is not None else pid_alive
    return bool(alive_fn(pid))


def enumerate_leases(now=None, alive=None, reclaim=True):
    """All live leases, keyed by project. Dead leases (expired + holder gone)
    and malformed/legacy records are reclaimed in place (unlink) when
    reclaim=True — reclaim is a local file decision, never a docker call
    (residue containers of a dead lease are cleaned by the next cold boot's
    idempotent do_down, not here: this runs inside choose_band/capacity
    counters where a docker call per record would be a storm amplifier)."""
    live = {}
    root = lock_root()
    for f in sorted(root.glob("project-*.json")):
        project = f.name[len("project-"):-len(".json")]
        lease = read_lease(project)
        if lease is not None and not lease_dead(lease, now=now, alive=alive):
            live[project] = lease
        elif reclaim:
            try:
                f.unlink()
            except OSError:
                pass
    return live


def live_lease_manifest(live):
    """Human-auditable one-line-per-lease manifest (review R2: the满员 red must
    name holder pid + ticket + lease id + claim time so a pid-reuse suspicion
    is checkable at a glance)."""
    lines = []
    for project, lease in sorted(live.items()):
        holder = lease.get("holder") or {}
        lines.append("project=%s holder=%s/pid=%s lease=%s state=%s 起租=%s" % (
            project, holder.get("ticket"), holder.get("pid"),
            str(lease.get("lease_id"))[:16], lease.get("state"),
            time.strftime("%H:%M:%S", time.localtime(lease.get("ts") or 0))))
    return "\n".join(lines)


def capacity_acquire(project, lease, timeout):
    """起台保险丝（t260912-02 病灶一，接管原满员排队闸的位置与原子性保证）：
    在同一把 capacity-0.lock 临界区内 {数活租约 → 达上限即刹停红 → 未达限写
    占位租约}。占位即计数的原子性原样保留（R4：N 路并发不可能都数到 N-1 全进）。
    与旧闸的两点差异：
      ①不再排队——达限立即 env 红刹停点名（旧排队实测只制造假拥堵：上限 12 时
        12 台并发 3 台卡 150s；上限 30 时 12/12 共 5.3s——闸不保护任何东西）；
      ②timeout 参数只用于**锁获取的有界等待**（C5：防 capacity-0.lock 被残留
        进程长期持有把起台永久挂起——比排队更糟的面），排队预算语义退役。
    kind=env 的归属理由（失败分类协议 v1）：刹停的原因是宿主面活租约头寸
    （环境状态），不是被测代码缺陷；红行附活租约清单（holder pid+票号）=
    协议要求的 evidence，不是无证据免责。失控样本（一次起 200 台）在场景里
    以「刹停红=预期行为」被正向断言（E 验收），不靠分类器吞红。
    文案刻意不含「满员」二字：lib_transient_retry 白名单按「满员」自动重试
    一次，失控循环不该被重试放大（t260912-02 review C1）。"""
    path = lock_root() / "capacity-0.lock"
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    t0 = time.time()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.time() - t0 >= timeout:
                    raise StageError("起台保险丝锁等待超时（%ds）：capacity-0.lock 被"
                                     "长期持有——查残留进程" % timeout, kind="env")
                time.sleep(0.5)
                continue
            try:
                live = enumerate_leases()
                if len(live) < max_stages():
                    write_lease(project, lease)   # 占位即计数（state=booting）
                    return lease
                raise StageError(
                    "起台保险丝（SANDBAR_STAGE_MAX_STAGES=%d）触发：活租约 %d 已达"
                    "上限——疑似失控循环，刹停不排队。当前活租约清单（含 holder "
                    "pid/票号，供人工核对）：\n%s"
                    % (max_stages(), len(live), live_lease_manifest(live)), kind="env")
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _spawn_hold(project, lease_id, keep=False):
    """Spawn the hold leg (detached session so signals to the caller's process
    group don't reach it; it dies only via its own seven terminal states).
    keep=True → hold argv 带 --keep：常驻基建台（verify.yaml supply 语义）的锚
    =短命调用方 shell，hold 对其禁③锚死回收（arbitrate 打回修复）。stderr
    goes to hold-<project>.log under the lock root — diagnostics
    survive the CLI's exit and the pipe is never broken by the spawner.
    Returns the Popen once the hold has proven it is running (pid file written
    = parsed args + handlers registered). Bounded wait (R1'a): Popen returning
    ≠ the child actually started (interpreter/permission); timeout = honest
    env red naming the hold leg — never a lease with a bogus holder pid."""
    hold_script = pathlib.Path(__file__).resolve()
    hold_argv = [sys.executable, str(hold_script), "hold", "--project", project,
                 "--anchor-pid", str(os.getppid()), "--lease-id", lease_id]
    if keep:
        hold_argv.append("--keep")
    proc = subprocess.Popen(
        hold_argv,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=open(str(lock_root() / ("hold-%s.log" % project)), "ab"),
        start_new_session=True, env=dict(os.environ))
    pidfile = lock_root() / ("holder-%s.pid" % project)
    try:
        pidfile.unlink()
    except FileNotFoundError:
        pass
    t0 = time.time()
    while time.time() - t0 < hold_wait_s():
        if proc.poll() is not None:
            raise StageError("hold 腿启动即退（rc=%s，日志 %s）"
                             % (proc.returncode, lock_root() / ("hold-%s.log" % project)),
                             kind="env")
        try:
            got = int(pidfile.read_text(encoding="utf-8").strip())
            if got == proc.pid:
                return proc
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    _harvest_hold(proc)
    raise StageError("hold 腿未在 %ds 内就绪（pid 文件未落/不匹配）——起台放弃，"
                     "绝不带空 holder pid 起台" % hold_wait_s(), kind="env")


def _harvest_hold(proc, grace=5.0):
    """Reap a hold child we spawned: SIGTERM → bounded wait → SIGKILL. Used on
    every failure path (R1'a: a failed boot must not leak a hold). Never
    raises."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
    except (OSError, ProcessLookupError):
        pass
    t0 = time.time()
    while time.time() - t0 < grace:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    try:
        proc.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=5)
    except (subprocess.SubprocessError, OSError):
        pass


def _stop_hold_by_pid(pid, grace=5.0):
    """down-side hold harvest: the down process has no Popen handle, only the
    pid recorded in the lease. SIGTERM → bounded wait → SIGKILL. Self-target
    skipped (the orphan-reclaim path runs INSIDE the hold itself). Window
    where the pid was reused in the last seconds = we signal an innocent
    process — accepted, noted in KI (same family as pid-reuse misalive); the
    alternative (leaked hold heartbeating a downed stage) is worse."""
    if not pid or pid == os.getpid() or not pid_alive(pid):
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except (OSError, ProcessLookupError, TypeError, ValueError):
        return
    t0 = time.time()
    while time.time() - t0 < grace:
        if not pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(int(pid), signal.SIGKILL)
    except (OSError, ProcessLookupError, TypeError, ValueError):
        pass


def cmd_hold(project, anchor_pid, lease_id=None, keep=False):
    """The hold leg: heartbeats the lease for exactly as long as it is held.
    Seven terminal states (t260910-12 gen2, review R1'/R1'a/R1'b):
      ① released: lease file gone or lease_id ≠ mine → exit 0, write nothing,
         tear down nothing (down owns the teardown);
      ② state=downing (including the pre-write re-check, R1'b) → exit 0;
      ③ anchor dead (the long-lived caller tree is gone) → orphan reclaim:
         down the stage + release the lease + exit 0 (accelerated path — the
         ONLY reclaim criterion stays "expired AND holder pid gone");
         **keep 租约例外（arbitrate 打回修复）**：常驻基建台（--keep，verify.yaml
         supply 语义「闸后有意常驻不拆」）的锚=短命调用方 shell，锚死≠弃台——
         跳过本腿继续心跳，台由租约+hold 持有直至显式 down / ⑥帽 / ⑦崩
         （帽后心跳停=过期 AND holder 死=同一判据交判死回收，无启发式）;
      ③' booting-orphan: lease still booting AND the booting CLI (this hold's
         original parent, captured at spawn) is dead → the boot can never
         complete (nobody will flip the state) → reclaim + release + exit 0.
         Without this leg a crashed booter would leave an eternal booting
         lease heartbeated by the anchor-alive hold — waiters would wait
         forever;（keep 台同样适用：起台未完成即死=起台孤儿，与常驻无关）
      ④ heartbeat write fails / foreign lease appeared → honest non-zero exit
         with a stderr line, stop writing (never overwrite someone's lease);
      ⑤ SIGTERM/SIGINT → exit 130, no down (the signal sender owns teardown —
         usually down's harvest or a test injection);
      ⑥ SANDBAR_STAGE_MAX_HOLD_S cap exceeded → honest exit, stderr line, the
         stage is left to expiry reclaim / manual down (anchor-pid-reuse
         damage cap; calling up from an interactive shell makes the anchor
         that shell — see header, review C2; keep 台同帽约束=常驻的损害上限，
         缺省 14400s ≥ 10×TTL 满足 supply 批跑窗);
      ⑦ own crash → heartbeat stops → expiry+pid-death reclaim (the designed
         crash path).
    Plus the bounded lease-wait self-exit: if no lease with my holder pid
    appears within HOLD_WAIT_S, the ensure that spawned me died — exit
    non-zero, no lease is ever created for a dead hold."""
    hold_pid = os.getpid()
    if not anchor_pid or int(anchor_pid) <= 0:
        print("STAGE_USAGE: hold 缺 --anchor-pid（孤儿锚=长命调用方进程 pid）",
              file=sys.stderr)
        return EXIT_USAGE
    anchor_pid = int(anchor_pid)
    pidfile = lock_root() / ("holder-%s.pid" % project)
    try:
        pidfile.write_text(str(hold_pid), encoding="utf-8")
    except OSError as e:
        print("STAGE_ENV: hold pid 文件不可写（%s：%s；锁根 %s）"
              % (type(e).__name__, e, lock_root()), file=sys.stderr)
        return EXIT_ENV

    stopping = {"flag": False}

    def _on_signal(signum, frame):
        # ⑤：只立标志不就地 sys.exit——handler 里 sys.exit 会从 sleep 中炸出
        # SystemExit 绕过一切清理（t260912-02 验收 E 实锤：保险丝刹停 196 路
        # 的 hold 被 _harvest_hold TERM，pid 文件全数泄漏）；两处循环顶部都查
        # flag，走正常退出面（130）=终态回收（pid 文件）必经。最长延迟=一个
        # sleep 片（0.2s/心跳间隔），远小于 _harvest_hold 的宽限。
        stopping["flag"] = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _on_signal)

    # ⓪ 有界等待租约出现（R1'a）：预算=起台者（本 hold 的原始父进程）存活期
    # ——起台前的残台清扫与保险丝临界区都控制在秒级（t260912-02 起无排队），
    # 但共机慢化/清扫长尾仍可能拖过固定秒数，预算保守取起台者存活期，hold
    # 不得提前自退。先读租约再判起台者死：租约已落即算数（主循环的 ③' 起台
    # 孤儿腿接管后续），只有「租约确实未落且起台者已死」才为一具尸体自退。
    # t260912-02（验收 E 教训）：等待期所有自退路径必须回收 pid 文件——保险丝
    # 刹停 196 路的 hold 全走本阶段退出，不清=锁根堆孤儿 holder-*.pid。
    def _cleanup_pidfile():
        try:
            pidfile.unlink()
        except FileNotFoundError:
            pass

    booter_pid = os.getppid()   # 起台 CLI：③' 孤儿起台判据同款
    lease = None
    while True:
        if stopping["flag"]:
            _cleanup_pidfile()
            return 130
        lease = read_lease(project)
        if isinstance(lease, dict) and holder_pid(lease) == hold_pid:
            break
        if not pid_alive(anchor_pid) and not keep:
            _cleanup_pidfile()
            return 0   # 锚死且租约未落：调用方树没了，无可清理——静默退
        # keep 台例外：锚死≠弃台（常驻基建锚=短命 shell），继续等起台者落租约
        if not pid_alive(booter_pid):
            # 起台者死且租约未落=为一具尸体起租（keep/非 keep 同判——起台者
            # 一死 boot 永不可完成，keep 也不等）
            print("STAGE_ENV: 起台进程 %d 已亡且租约未落——hold 自退，绝不带空"
                  "租约滞留" % booter_pid, file=sys.stderr)
            _cleanup_pidfile()
            return EXIT_ENV
        time.sleep(0.2)
    if lease.get("lease_id") != lease_id and lease_id:
        # ensure 用它自己的 lease_id 建了租约——本 hold 是孤儿握手残留
        print("STAGE_ENV: hold lease_id 与租约不符——握手残留自退", file=sys.stderr)
        _cleanup_pidfile()
        return EXIT_ENV
    if not lease_id:
        lease_id = lease["lease_id"]
    # keep 的权威面=租约记录（argv 是起台注入；翻面/心跳读改写全链路透传）
    keep = keep or bool(lease.get("keep"))

    start_ts = float(lease.get("ts") or time.time())
    while True:
        if stopping["flag"]:
            return 130                                                       # ⑤
        lease = read_lease(project)
        if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:  # ①
            # ① 先于 ③（t260915-18 调序对齐 docstring 原语义）：租约消失/易主=
            # down 拥有拆台权，本腿只退不拆；账外孤儿容器由 sweep 孤儿清扫接管。
            try:
                pidfile.unlink()
            except FileNotFoundError:
                pass
            return 0
        if not lease_anchor_alive(lease, anchor_pid) and not keep:           # ③
            print("[hold] 锚进程 %d 已亡（%s）——调用方树消失，回收孤儿台" %
                  (anchor_pid,
                   "锚令牌不匹配=pid 重用嫌疑" if pid_alive(anchor_pid) else "pid 消失"),
                  file=sys.stderr)
            try:
                do_down(project, harvest_hold=False)
            except Exception as e:
                # t260915-18（C4:863）：回收失败**保留租约**——租约是容器唯一账本，
                # 账先于容器销=孤儿失明根因（KI-077 当日 37 只实证）。心跳随本腿
                # 退出停更 → sweep crit_iii/孤儿清扫/人工接管，fail-visible 不静默。
                print("STAGE_FAIL: [hold] 孤儿台回收失败（%s：%s）——租约保留，"
                      "台交 sweep/人工回收" % (type(e).__name__, e), file=sys.stderr)
            try:
                pidfile.unlink()
            except FileNotFoundError:
                pass
            return 0
        # keep 台：锚死跳过回收（常驻基建例外）——心跳继续，台交显式 down /
        # ⑥帽 / ⑦崩处置；锚死+心跳停的组合态由 ⑥ 帽封顶损害
        if lease.get("state") == "booting" and not pid_alive(booter_pid):     # ③'
            print("[hold] 起台进程 %d 已亡而租约仍 booting——起台孤儿，回收" % booter_pid,
                  file=sys.stderr)
            try:
                do_down(project, harvest_hold=False)
            except Exception as e:
                # t260915-18（C4:886）：同 ③ 修法——失败保留租约不销账。
                print("STAGE_FAIL: [hold] 起台孤儿回收失败（%s：%s）——租约保留，"
                      "台交 sweep/人工回收" % (type(e).__name__, e), file=sys.stderr)
            return 0
        if lease.get("state") not in ("booting", "up"):                       # ②
            return 0
        if time.time() - start_ts > max_hold_s():                             # ⑥
            print("STAGE_HOLD_CAP: hold 超过最大持有期 %ds 自退——台留给租约过期"
                  "回收或人工 down（提示：人工直调 up 的台锚=你的 shell，属明示"
                  "行为；可调小 SANDBAR_STAGE_MAX_HOLD_S 或显式 down）" % max_hold_s(),
                  file=sys.stderr)
            _cleanup_pidfile()
            return 6
        if holder_pid(lease) != hold_pid:                                     # ④
            print("STAGE_ENV: 租约 holder 变更（pid=%s）——外来租约，停写自退"
                  % holder_pid(lease), file=sys.stderr)
            _cleanup_pidfile()
            return EXIT_ENV
        lease["heartbeat_ts"] = time.time()
        try:
            write_lease(project, lease)
        except OSError as e:                                                  # ④
            print("STAGE_ENV: 心跳写失败（%s：%s）——诚实停写自退，台交判死回收"
                  % (type(e).__name__, e), file=sys.stderr)
            return EXIT_ENV
        time.sleep(lease_heartbeat_s())


def state_busy_ports(now=None, alive=None):
    """Ports held by live leases — choose_band's second busy check, lease-based
    (t260910-12). The old heuristic stack (mtime freshness grace + docker ps
    triple sampling + ports-all-refused double confirmation) is deleted: all
    three guessed at other holders' liveness and all three misfired in
    concurrent windows (run L/M/O/Q/U/X). Now: live lease → ports busy; dead
    lease (expired AND holder gone) / legacy record / malformed record →
    reclaimed in place (no docker call — residue containers are handled by the
    next cold boot's idempotent do_down; the bind probe still protects against
    ports the daemon still holds)."""
    busy = set()
    for project, lease in enumerate_leases(now=now, alive=alive).items():
        busy.update(int(p) for p in (lease.get("ports") or {}).values())
    return busy


def choose_band(ephemeral=None):
    """Atomically reserve one port band: flock placeholder -> bind probe +
    running-stage state face; occupy it only if all checks pass.
    Returns (band_index, ports, fd). The lock only guards the "probe -> daemon
    really bound" window and is released as soon as up finishes (from then on
    the daemon's binding + the state face take over collision avoidance — a
    crash releases the lock, so no deadlock). All bands exhausted =
    StageError(env)."""
    busy_state = state_busy_ports()
    for i in range(BAND_COUNT):
        ports = band_ports(i)
        if not band_ports_ok(ports, ephemeral):
            continue
        if set(ports.values()) & busy_state:
            continue
        fd = _lock_band(i)
        if fd is None:
            continue          # band taken by a concurrent entrant -> slide to the next (non-blocking, no queueing; see the header trade-off)
        # re-check inside the lock: a concurrent entrant may have probed before
        # locking/booting, so probe once more after taking the lock
        if not band_ports_ok(ports, ephemeral) or (set(ports.values()) & state_busy_ports()):
            os.close(fd)
            continue
        return i, ports, fd
    raise StageError(
        "端口段耗尽：%d 档（%d~%d）全忙或被锁——查残留舞台（docker ps）与 "
        "SANDBAR_STAGE_LOCK_DIR=%s 下的锁锚" % (BAND_COUNT, band_base(),
                                                band_base() + BAND_COUNT * BAND_STEP, lock_root()),
        kind="env")


def state_path(project) -> pathlib.Path:
    """Compatibility alias of lease_path (t260910-12: the state file IS the
    lease record now)."""
    return lease_path(project)


def read_state(project):
    return read_lease(project)


def write_state(project, data):
    """Compatibility shim: bare state dict (pre-lease shape) → merge into the
    existing lease when one is live, else write through. do_up's up-flip uses
    _flip_lease_up instead — this shim only serves ad-hoc external callers."""
    lease = read_lease(project)
    if isinstance(lease, dict) and lease.get("lease_id"):
        lease.update(data)
        write_lease(project, lease)
    else:
        write_lease(project, data)


def clear_state(project):
    release_lease(project)


# ---------------------------------------------------------------- docker gates

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


def agent_image_present():
    """agent 执行面镜像在场（t260913-04；tag 单点=agent_runtime.agent_image()）。"""
    try:
        sys.path.insert(0, str(REPO / "server" / "engine"))
        import agent_runtime   # stdlib-only；缺省 tag 版本三处同步的单点
        _run(["docker", "image", "inspect", agent_runtime.agent_image()], timeout=30)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def compose_env(project, services, ports, opts):
    """Env for rendering compose (the SANDBAR_TEST_* knobs of
    docker-compose.test.yml)."""
    env = dict(os.environ)
    env["SANDBAR_TEST_TEMPORAL_NAME"] = "%s-temporal" % project
    env["SANDBAR_TEST_DSH_NAME"] = "%s-dsh" % project
    env["SANDBAR_TEST_NAMESPACE"] = opts.get("namespace") or "sandbar-test"  # 契约缺省值随 server/docker-compose.test.yml 声明（t260917-07 补完 d342b46 终切；原 naming-compat 旧名欠账随本票清，看守=t260917-07/sc_test_ns_consistency）
    env["SANDBAR_TEST_TEMPORAL_PORT"] = str(ports["temporal"])
    env["SANDBAR_TEST_TEMPORAL_UI_PORT"] = str(ports["ui"])
    env["SANDBAR_TEST_CONSOLE_PORT"] = str(ports["console"])
    if opts.get("repo_dir"):
        env["SANDBAR_TEST_REPO_DIR"] = str(opts["repo_dir"])
    # Plugin dependency tree decoupled from the tested tree: /repo = the tested
    # workbench tree,
    # /repo-nm = a tree with profile/node_modules installed (falls back to the main tree by default).
    env["SANDBAR_TEST_NM_REPO_DIR"] = str(opts.get("nm_repo_dir") or default_repo_dir())
    # Pre-create the admin.log shadow file (the host side of a compose
    # single-file bind must exist, otherwise docker creates a directory): one
    # independent tmp copy per stage, so the main tree's/lane's real admin.log
    # is never touched by tests.
    admin_log = pathlib.Path(tempfile.gettempdir()) / ("sandbar-admin-log-%s.log" % project)
    if not admin_log.exists():
        admin_log.touch()
    env["SANDBAR_TEST_ADMIN_LOG"] = str(admin_log)
    # Pre-create the container-side mount points (proven in a lane by
    # t260905-08): compose single-file binds admin.log at both /repo and
    # /repo-nm, and /repo is mounted :ro — if the mounted tree has no
    # server/admin.log, docker creating the mount point = EROFS and the boot
    # explodes (the main tree usually has the file while running; a lane
    # worktree as /repo exposes it).
    # *.log is a gitignored runtime artifact, so touching an empty file never
    # touches the deliverable surface.
    for tree in (opts.get("repo_dir") or str(REPO), opts.get("nm_repo_dir") or default_repo_dir()):
        server_dir = pathlib.Path(tree) / "server"
        if server_dir.is_dir():
            shadow = server_dir / "admin.log"
            if not shadow.exists():
                shadow.touch()
    # Materialize credentials: a container stage without credentials = the
    # shell-access overlay blocking the pointer full-screen (proven against a
    # self-built stage).
    # Source: env SANDBAR_TEST_CREDENTIALS > ~/.sandbar/projects/suyou > <repo>/.dsh > main-tree .dsh.
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
        os.chmod(cred_dst, 0o600)  # dsh credentials-local is fail-closed: 644 = refuses to start (proven in gen4)
        env["SANDBAR_TEST_CREDENTIALS"] = str(cred_dst)
    # agent preset materialization (session creation depends on the  # naming-compat
    # sandbar-integration preset; source = host ~/.dsh/.agent-presets/<project>
    # or the in-repo .dsh sibling). Missing = an empty directory (preset
    # absence shown honestly), boot not blocked.
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
    # 受管网段（t260912-02 病灶三）：compose 文件的 default 网络 ipam.subnet 由本
    # env 指定——建网显式带子网，不再向 docker 分配器申请库存（fully subnetted
    # 从根上消失）。缺省值=保留尾槽（compose 文件侧同值），给手工直跑 compose
    # 的路径；stage_docker 路径由 claim_subnet 分配并回写租约（C2）。
    env["SANDBAR_TEST_SUBNET"] = str(opts.get("subnet") or net_table()[-NET_RESERVED_TAIL])
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
        # dsh-only stage: pin the in-container engine address to an unreachable
        # loopback port (the scenario's "Temporal unreachable" assertion face;
        # 127.0.0.1:1 always refuses inside the container). Never a production 7233.
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
    """Residual container list under that project name (the zero-residue check
    face)."""
    try:
        p = _run(["docker", "ps", "-a", "--filter",
                  "label=com.docker.compose.project=%s" % project,
                  "--format", "{{.Names}}"], timeout=15)
        return [x for x in (p.stdout or "").splitlines() if x.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        return ["<docker ps 不可用>"]


# （residue_containers_stable 三次采样已随租约化退役——t260910-12 删除
# 「猜别人死没死」启发式的最后一个采样点；存活判断只有租约事实。


# --------------------------------------- 台面清点与孤儿清扫（t260915-18）

def _parse_created_ts(text, now=None):
    """docker CreatedAt（形如 '2026-09-13 20:11:31 +0800 +08'）→ epoch 秒。
    取本地时间前 19 位按 %Y-%m-%d %H:%M:%S 解析（CreatedAt 本就是本地钟面）；
    解析失败=None（调用方 fail-closed 不判拆）。纯函数可单测。"""
    try:
        st = time.strptime(str(text).strip()[:19], "%Y-%m-%d %H:%M:%S")
        return time.mktime(st)
    except (ValueError, TypeError):
        return None


def compose_container_rows():
    """全机 compose 容器清单（一次 docker ps -a，按 compose 工程标签聚合）：
    [{project, working_dir, names[], created_ts}]。docker 不可用/解析失败=[]
    + stderr 留痕（绝不假装查过——「查不了」≠「没有」）。"""
    try:
        p = _run(["docker", "ps", "-a", "--filter", "label=com.docker.compose.project",
                  "--format",
                  "{{.Label \"com.docker.compose.project\"}}\t"
                  "{{.Label \"com.docker.compose.project.working_dir\"}}\t"
                  "{{.CreatedAt}}\t{{.Names}}"],
                 timeout=20, check=False)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        print("STAGE_ENV: docker ps 不可用——容器面不可见（孤儿判定本轮缺席）",
              file=sys.stderr)
        return []
    rows = {}
    for line in (p.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or not parts[0].strip():
            continue
        proj, wd, created, name = (x.strip() for x in parts)
        r = rows.setdefault(proj, {"project": proj, "working_dir": wd or None,
                                   "names": [], "created_ts": _parse_created_ts(created)})
        r["names"].append(name)
        ts = _parse_created_ts(created)
        if ts and (r["created_ts"] is None or ts < r["created_ts"]):
            r["created_ts"] = ts   # 工程年龄=最早容器（起台时刻）
    return sorted(rows.values(), key=lambda r: r["project"])


def managed_repo_root(repo_root=None):
    """本管域根（t260915-18）：泳道 worktree 里跑时 REPO=泳道根，但台面清点的
    「本管」必须覆盖主仓+全部兄弟泳道（.lane/*）——剥掉路径里的 /.lane/ 段取
    主仓根；非泳道布局=REPO 原样。纯函数可单测。"""
    repo = os.path.realpath(str(repo_root) if repo_root else str(REPO))
    marker = os.sep + ".lane" + os.sep
    idx = repo.find(marker)
    return repo[:idx] if idx != -1 else repo


def in_managed_domain(working_dir, repo_root=None):
    """本管域判定（t260915-18，fail-closed）：compose working_dir 落在主仓真实
    子树（主仓本体或其 .lane/* 全部泳道，经 managed_repo_root 归一）或测试基线
    临时树（路径含 sandbar-baseline-，场景基线树随用随删）。标签缺失/域外目录=
    不在本管——只报告绝不拆（防误伤手工台/他项目台）。纯函数可单测。"""
    if not working_dir or not str(working_dir).strip():
        return False
    try:
        repo = managed_repo_root(repo_root)
        real = os.path.realpath(str(working_dir))
    except (OSError, ValueError, TypeError):
        return False
    if real == repo or real.startswith(repo + os.sep):
        return True
    return "sandbar-baseline-" in real


def build_inventory(leases=None, rows=None, now=None, repo_root=None):
    """台面清点（t260915-18 工单②，纯函数核心，leases/rows/repo_root 可注入=
    UT 零 docker）：租约×容器 join。孤儿=本管域容器工程而无租约文件（账先于
    容器销/隔离锁根随 tmp 树删除等形态，KI-077 当日 37 只实证）；域外容器只列
    不判。容量面=容器数/工程数/活租约数/孤儿数 vs SANDBAR_STAGE_MAX_STAGES——
    保险丝只数租约不看容器的可见性缺口由此回执补齐。每台带归属（holder.ticket=
    票号/attempt、pid、锚、owner、心跳年龄）——人工排障不再猜哈希台名。"""
    now = time.time() if now is None else now
    live = enumerate_leases(now=now) if leases is None else leases
    rows = compose_container_rows() if rows is None else rows
    stages, out_of_domain = [], []
    container_count = 0

    def _blank_stage(proj):
        return {"project": proj, "orphan": False, "containers": 0, "names": [],
                "working_dir": None, "state": None, "services": [],
                "holder_ticket": "unknown",
                "holder_pid": None, "anchor_pid": None, "owner_root": None,
                "heartbeat_age_s": None, "age_s": None}

    for proj, lease in sorted(live.items()):
        s = _blank_stage(proj)
        holder = lease.get("holder") or {}
        s.update({
            "state": lease.get("state"),
            "services": list(lease.get("services") or []),
            # 票号缺省 unknown（不编造归属——报错精确纪律；场景③断言面）
            "holder_ticket": holder.get("ticket") or "unknown",
            "holder_pid": holder.get("pid"),
            "anchor_pid": lease.get("anchor_pid"),
            "owner_root": lease.get("owner_root"),
            "heartbeat_age_s": (round(now - float(lease["heartbeat_ts"]), 1)
                                if lease.get("heartbeat_ts") else None),
            "age_s": (round(now - float(lease["ts"]), 1) if lease.get("ts") else None),
        })
        stages.append(s)
    by_lease = {s["project"]: s for s in stages}
    for r in rows:
        container_count += len(r["names"])
        s = by_lease.get(r["project"])
        if s is not None:
            s["containers"] = len(r["names"])
            s["names"] = r["names"]
            s["working_dir"] = r["working_dir"]
            continue
        if not in_managed_domain(r["working_dir"], repo_root=repo_root):
            out_of_domain.append({"project": r["project"],
                                  "working_dir": r["working_dir"],
                                  "containers": len(r["names"])})
            continue
        s = _blank_stage(r["project"])
        s.update({"orphan": True, "containers": len(r["names"]), "names": r["names"],
                  "working_dir": r["working_dir"],
                  "age_s": (round(now - r["created_ts"], 1)
                            if r["created_ts"] else None)})
        stages.append(s)
    return {
        "capacity": {"containers": container_count, "projects": len(rows),
                     "leases": len(live),
                     "orphans": sum(1 for s in stages if s["orphan"]),
                     "max_stages": max_stages(),
                     "out_of_domain_projects": len(out_of_domain)},
        "stages": sorted(stages, key=lambda s: (not s["orphan"], s["project"])),
        "out_of_domain": out_of_domain,
    }


def orphan_condemn_projects(inv=None, now=None, enabled=None, prefix=None):
    """孤儿判拆集合（C10：开关+最短年龄阀双保险+半径前缀，纯函数可注入）。
    返回 (condemn, skipped)——skipped 逐条带原因供点名，绝不静默：
    开关关/年龄不足/前缀外/CreatedAt 不可解析（fail-closed）各归各的 why。
    enabled/prefix 缺省=读旋钮（UT 显式注入，场景经 env 旋钮驱动）。"""
    inv = inv if inv is not None else build_inventory(now=now)
    now = time.time() if now is None else now
    if enabled is None:
        enabled = sweep_orphans_enabled()
    if prefix is None:
        prefix = orphan_prefix()
    skipped = [{"project": s["project"],
                "why": "SANDBAR_STAGE_SWEEP_ORPHANS 显式关闭（明示不静默）"}
               for s in inv["stages"] if s["orphan"]] \
        if not enabled else []
    if skipped:
        return [], skipped
    min_age = orphan_min_age_s()
    condemn = []
    for s in inv["stages"]:
        if not s["orphan"]:
            continue
        proj = s["project"]
        if prefix and not proj.startswith(prefix):
            skipped.append({"project": proj,
                            "why": "前缀外（SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX=%s）"
                                   "——孤儿是全局可见面，无半径即无授权清场" % prefix})
            continue
        age = s.get("age_s")
        if age is None:
            skipped.append({"project": proj,
                            "why": "容器 CreatedAt 不可解析——fail-closed 不拆"})
        elif age < min_age:
            skipped.append({"project": proj,
                            "why": "年龄 %.0fs < 阀 %.0fs（SANDBAR_STAGE_ORPHAN_MIN_AGE_S）"
                                   % (age, min_age)})
        else:
            condemn.append(proj)
    return condemn, skipped


# --------------------------------------- 受管网段与残台清扫（t260912-02）

_NET_DAEMON_CACHE = None      # (ts, subnets) —— daemon 现存网段探针的进程内缓存
_WORKTREE_CACHE = None        # (ts, roots|None) —— git worktree list 的进程内缓存

# 网段撞号签名（C3 换槽重试的触发面；窄列——配置类错误不重试，compose up 自报真错）
_SUBNET_CONFLICT_PAT = re.compile(
    r"overlaps with (another|other) (network )?on this address space"
    r"|fully subnetted", re.I)


def net_table():
    """受管网段表全部 /24 槽（base /16 → 256 槽，含保留尾槽）。"""
    parts = net_base().split("/")[0].split(".")
    prefix = "%s.%s" % (parts[0], parts[1])
    return ["%s.%d.0/24" % (prefix, i) for i in range(2 ** (NET_PREFIXLEN - 16))]


def daemon_subnets():
    """daemon 现存网段（一次 ls+inspect，10s 进程内缓存）。查询失败=空集 +
    stderr 留痕——分配照走（还有在册租约那半边防撞），但绝不假装查过。"""
    global _NET_DAEMON_CACHE
    now = time.time()
    if _NET_DAEMON_CACHE is not None and now - _NET_DAEMON_CACHE[0] < 10:
        return _NET_DAEMON_CACHE[1]
    subnets = set()
    try:
        p = _run(["docker", "network", "ls", "-q"], timeout=15, check=False)
        ids = [x for x in (p.stdout or "").split() if x.strip()]
        if p.returncode == 0 and ids:
            q = _run(["docker", "network", "inspect", "--format",
                      "{{range .IPAM.Config}}{{.Subnet}} {{end}}"] + ids,
                     timeout=20, check=False)
            if q.returncode == 0:
                subnets = {s for s in (q.stdout or "").split() if s.strip()}
            else:
                print("[stage_docker] 注：daemon 网段查询失败（rc=%d）——分配仅对照"
                      "在册租约防撞" % q.returncode, file=sys.stderr)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print("[stage_docker] 注：daemon 网段查询不可用（%s: %s）——分配仅对照在册"
              "租约防撞" % (type(e).__name__, e), file=sys.stderr)
    _NET_DAEMON_CACHE = (now, subnets)
    return subnets


def _subnet_overlap(cidr, used):
    """CIDR 重叠判定（strict=False 容忍主机位；畸形项跳过不炸）。"""
    try:
        c = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return cidr in used
    for u in used:
        try:
            un = ipaddress.ip_network(u, strict=False)
        except ValueError:
            continue
        if c.version == un.version and (c.subnet_of(un) or un.subnet_of(c)):
            return True
    return False


def net_free_slots():
    """（可用槽数, 占用明细）——只读视角，供耗尽红与验收 G/C8 的回落断言。"""
    slots = net_table()
    reserved = set(slots[-NET_RESERVED_TAIL:])
    leased = {l.get("subnet") for l in enumerate_leases().values()
              if isinstance(l.get("subnet"), str) and l["subnet"]}
    daemon = daemon_subnets()
    free, used_by = [], []
    for s in slots:
        if s in reserved:
            used_by.append("%s（保留：手工直跑 compose 缺省）" % s)
            continue
        if s in leased:
            used_by.append("%s（在册租约）" % s)
            continue
        hit = [d for d in daemon if _subnet_overlap(s, {d})]
        if hit:
            used_by.append("%s（daemon：%s）" % (s, ",".join(sorted(hit))[:60]))
            continue
        free.append(s)
    return free, used_by


def alloc_subnet(project, exclude=()):
    """为台选一个受管 /24 槽（C2/C8 口径）：随机选槽（同批不序列、网段随台不同
    不可猜），排除 = 保留尾槽 ∪ 在册租约已占 ∪ daemon 现存网段（CIDR 重叠）
    ∪ 调用方排除。表耗尽 = 诚实 env 红，点名剩余槽数与占用者清单。调用方拿到
    槽后必须立刻写进租约（占位态对并发分配器可见）再 compose up；TOCTOU 残余
    由 claim_subnet 写后复核 + do_up 的 overlaps 换槽重试兜底（C3）。"""
    free, used_by = net_free_slots()
    for s in exclude:
        if s in free:
            free.remove(s)
    if not free:
        raise StageError(
            "受管网段表耗尽：base=%s 可分配槽 0（表 %d 槽，其中保留尾槽 %s 给"
            "手工直跑缺省路径）——占用明细（前 16 条）：\n  %s\n可用 "
            "SANDBAR_STAGE_NET_BASE 重指网段表，或清理在册残台"
            "（stage_docker.py sweep）"
            % (net_base(), len(net_table()), net_table()[-NET_RESERVED_TAIL],
               "\n  ".join(used_by[:16])), kind="env")
    return random.SystemRandom().choice(free)


def claim_subnet(project, lease):
    """C2：择槽后立刻写进租约（state 仍 booting 的占位态，并发分配器可见），
    写后复核在册集——他台已占同槽则换槽重写（有界 4 次）。随机只管「同批不
    序列」的不可猜性，确定性由写后复核与 do_up 重试共同保证。"""
    last = None
    for _ in range(4):
        subnet = alloc_subnet(project)
        lease["subnet"] = subnet
        write_lease(project, lease)
        others = {l.get("subnet") for p, l in enumerate_leases(reclaim=False).items()
                  if p != project}
        if subnet not in others:
            return subnet
        last = subnet
    raise StageError("受管网段分配竞态：连续 4 次择槽均与他台在册租约撞号"
                     "（last=%s）——查是否有异常高频起台" % last, kind="env")


def _clear_project_network(project, force=False):
    """幂等清本工程同名网络（compose 默认网 <project>_default）。冷启动 compose
    up 前调用：保证网段必来自受管表当前分配（验收 B 的 inspect 断言面）；
    网段撞号换槽前也调（C3：遗留网络+新子网的配置漂移报错字面不一定是
    overlaps）。不存在=成功；其余失败 force=False 时 stderr 留痕不阻断
    （compose up 自会报真错），force=True 上抛。"""
    name = NET_NAME_FMT % project
    try:
        p = _run(["docker", "network", "rm", name], timeout=15, check=False)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        p = None
        err = "%s: %s" % (type(e).__name__, e)
    else:
        err = ((p.stderr or "") + (p.stdout or "")).strip() if p else ""
    if p is None or p.returncode != 0:
        if p is not None and ("not found" in err.lower() or "no such network" in err.lower()):
            return
        msg = "docker network rm %s 失败（%s）" % (name, err[:120] or "无输出")
        if force:
            raise StageError(msg, kind="env")
        print("[stage_docker] 注：%s——继续（compose up 自会报真错）" % msg, file=sys.stderr)


def _worktree_roots():
    """git worktree list --porcelain → 真实路径集合（10s 进程内缓存——同进程
    多次起台不重复扫）。git 不可得返回 None：crit_ii 本轮 fail-closed 跳过
    （绝不因工具缺席误拆台），报告留一行。"""
    global _WORKTREE_CACHE
    now = time.time()
    if _WORKTREE_CACHE is not None and now - _WORKTREE_CACHE[0] < 10:
        return _WORKTREE_CACHE[1]
    roots = None
    try:
        p = _run(["git", "worktree", "list", "--porcelain"], timeout=20, check=False)
        if p.returncode == 0:
            roots = set()
            for line in (p.stdout or "").splitlines():
                if line.startswith("worktree "):
                    roots.add(os.path.realpath(line[len("worktree "):].strip()))
    except (subprocess.SubprocessError, FileNotFoundError):
        roots = None
    _WORKTREE_CACHE = (now, roots)
    return roots


def owner_anchor(lease):
    """清扫锚：优先 owner_root（t260912-02 起新租约自带 = compose 工作目录），
    旧格式回落 repo_dir。回落语义=被测树/挂载源（bench-shot 传主树、
    lib_stage_console 传 tmp 树），可能有偏差 → 活台+目录在时 crit_ii 一律
    fail-closed（C4b），另辅以容器 working_dir 探针补刀（见 sweep_stages）。"""
    for key in ("owner_root", "repo_dir"):
        val = (lease or {}).get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def judge_residue(lease, now=None, worktree_roots=None, alive=None, stale_s=None,
                  owner_exists=None, anchor_alive_fn=None):
    """残台判拆谓词（纯函数，全参可注入=单测防恒真的面）。返回 (verdict, why)，
    verdict ∈ condemn（判拆）/ keep（不碰）/ report（C4b 仅报告不拆）。
      阀1：state=booting 且心跳新鲜 → keep（起台进行中一律不碰）；
      crit_iv：锚已亡（令牌不匹配=pid 重用嫌疑）而 hold 仍续心跳 → condemn
              （t260915-18：「愿主已结束 hold 腿仍续心跳」形态——KI-077 当日
              38h 老台同族；在阀2 之前：owner_root 在册+目录在救不了锚已亡的
              台；令牌缺席的旧格式租约 fail-closed 跳过，不引入纯 pid 误拆面）；
      阀2：主人在 worktree list 且目录在且心跳新鲜 → keep（健康供给台/常驻台）；
      crit_i：主人工作目录已不存在 → condemn（心跳再新鲜也是残台——260912 主形态）；
      crit_ii：主人不在 worktree list → condemn；但「活台（up+心跳新鲜+holder 活）
              且目录在」→ report（C4b fail-closed，正对 repo_dir 回落失真）；
      crit_iii：心跳陈旧 > 阈 → condemn（hold 死后的僵台——现 ensure 只诚实红，
              本判据交清道夫拆）；
      worktree_roots=None（git 不可得）→ crit_ii 跳过，其余判据照判。"""
    now = time.time() if now is None else now
    stale_s = sweep_stale_s() if stale_s is None else float(stale_s)
    alive_fn = alive if alive is not None else pid_alive
    anchor_fn = anchor_alive_fn if anchor_alive_fn is not None else anchor_alive
    if not isinstance(lease, dict) or not lease.get("lease_id"):
        return "keep", "非租约记录（畸形/旧格式由 sweep_stages 按无主处理）"
    hb = lease.get("heartbeat_ts")
    try:
        hb_age = now - float(hb)
    except (TypeError, ValueError):
        hb_age = None
    fresh = bool(hb_age is not None and hb_age <= float(lease.get("ttl_sec") or lease_ttl_s()))
    state = lease.get("state")
    pid = holder_pid(lease)
    holder_alive = bool(pid) and bool(alive_fn(pid))
    anchor = owner_anchor(lease)
    if owner_exists is None:
        owner_exists = (os.path.isdir(os.path.realpath(anchor))
                        if anchor else None)
    in_worktree = bool(anchor and worktree_roots is not None
                       and os.path.realpath(anchor) in worktree_roots)
    if state == "booting" and fresh:                                   # 阀1
        return "keep", "阀1：booting 且心跳新鲜（起台进行中）"
    anchor_pid_v = lease.get("anchor_pid")
    anchor_tok = lease.get("anchor_token")
    if (state == "up" and fresh and holder_alive and anchor_pid_v and anchor_tok
            and not anchor_fn(anchor_pid_v, anchor_tok)):                # crit_iv
        return "condemn", ("crit_iv：锚 %s 已亡（令牌不匹配=pid 重用嫌疑）而 hold"
                           " 仍续心跳——主人已亡的续跳台（t260915-18）" % anchor_pid_v)
    if in_worktree and owner_exists and fresh:                          # 阀2
        return "keep", "阀2：主人在 git worktree list 且目录在且心跳新鲜"
    if anchor and owner_exists is False:
        return "condemn", "crit_i：主人工作目录已不存在：%s" % anchor
    if anchor and worktree_roots is not None and not in_worktree:
        if state == "up" and fresh and holder_alive and owner_exists:
            return "report", ("C4b：活台（holder 活+心跳新鲜）而主人锚非工作树"
                              "（%s，疑被测树/挂载源回落）——fail-closed 不拆" % anchor)
        return "condemn", "crit_ii：主人不在 git worktree list（%s）" % anchor
    if hb_age is not None and hb_age > stale_s:
        return "condemn", "crit_iii：心跳陈旧 %.0fs > 阈 %.0fs（holder%s）" % (
            hb_age, stale_s, "活" if holder_alive else "亡")
    if worktree_roots is None and anchor:
        return "keep", "git worktree list 不可得——crit_ii fail-closed 跳过（余判据未命中）"
    return "keep", "无判据命中"


def sweep_stages(dry_run=False, budget_s=None, now=None, worktree_roots=None,
                 alive=None, owner_probe=None, do_down_fn=None,
                 anchor_alive_fn=None, rows=None, repo_root=None,
                 orphan_face="cli"):
    """残台清扫主体（t260912-02）。逐条租约文件判定（含畸形/旧格式/已死——
    它们的容器面可能仍在跑，一并列管），判拆项幂等 do_down（容器+网络+卷）
    并逐条点名；判定与拆台之间复核租约（翻成 booting 新鲜=有新起台者进场，
    让位）。失败收集上抛（CLI sweep 非零退出），绝不静默；预算超限把未处理
    项点名进 skipped_budget。owner_probe(project)→path|None：旧格式租约（无
    owner_root）的容器 working_dir 探针（生产=docker ps label；260912 存量
    残台「工作目录已删仍心跳新鲜」的补刀面——repo_dir 回落是 tmp 树探不到，
    working_dir 才是真 compose 工作目录）。do_down_fn：L1 注入口（缺省真
    do_down），UT 零 docker 依赖跑全链。"""
    t0 = time.time()
    budget = sweep_budget_s() if budget_s is None else float(budget_s)
    teardown = do_down_fn or do_down
    if worktree_roots is None:
        worktree_roots = _worktree_roots()
    git_note = None
    if worktree_roots is None:
        git_note = "git worktree list 不可得——crit_ii 本轮 fail-closed"
    stale_s = sweep_stale_s()
    condemned, kept, report_only, errors, skipped = [], [], [], [], []
    orphans_skipped = []
    seen_projects = set()
    scanned = 0
    for f in sorted(lock_root().glob("project-*.json")):
        if time.time() - t0 > budget:
            skipped.append(f.name)
            continue
        scanned += 1
        project = f.name[len("project-"):-len(".json")]
        seen_projects.add(project)
        lease = read_lease(project)
        if isinstance(lease, dict) and lease.get("lease_id"):
            verdict, why = judge_residue(lease, now=now, worktree_roots=worktree_roots,
                                         alive=alive, stale_s=stale_s,
                                         anchor_alive_fn=anchor_alive_fn)
            if (owner_probe and not isinstance(lease.get("owner_root"), str)
                    and verdict in ("keep", "report")):
                # 旧租约（无 owner_root）：repo_dir 回落失真面——上容器 working_dir
                # 探针看真 compose 工作目录：已删=crit_i 补刀坐实判拆；仍在=维持
                # 不拆（keep 静默 / report 落 C4b 报告行）。探针不可得/无容器=维持
                # 原判定。探针只对心跳新鲜的台跑（陈旧的 crit_iii 已接管）。
                try:
                    wd = owner_probe(project)
                except Exception as e:                      # noqa: BLE001 探针失败不炸清扫
                    wd = None
                    why += "（working_dir 探针失败 %s: %s）" % (type(e).__name__, e)
                if wd and not os.path.isdir(os.path.realpath(wd)):
                    verdict = "condemn"
                    why = ("crit_i（working_dir 补刀）：真 compose 工作目录已不存在：%s"
                           "（repo_dir 回落=%s 失真）" % (wd, lease.get("repo_dir")))
                elif wd and verdict == "report":
                    why = ("C4b：working_dir=%s 仍在（心跳新鲜 holder 活）——fail-closed "
                           "不拆（repo_dir 回落=%s 仅辅证）" % (wd, lease.get("repo_dir")))
                if wd:
                    lease = dict(lease)
                    lease["_working_dir"] = wd
            row = {"project": project, "why": why,
                   "pid_alive": bool(holder_pid(lease)) and pid_alive(holder_pid(lease))
                   if holder_pid(lease) else False}
            if verdict == "keep":
                kept.append(row)
                continue
            if verdict == "report":
                report_only.append(row)
                continue
            # condemn：拆前复核（判定窗内有新起台者进场写 booting 新鲜租约 → 让位）
            cur = read_lease(project)
            if (isinstance(cur, dict) and cur.get("state") == "booting"
                    and not lease_expired(cur)):
                kept.append({"project": project,
                             "why": "判定窗内翻成 booting 新鲜——让位给在起的台"})
                continue
            if dry_run:
                condemned.append(dict(row, dry_run=True))
                continue
            try:
                teardown(project)
                condemned.append(row)
            except Exception as e:                          # noqa: BLE001 清理失败必须可见
                errors.append({"project": project, "why": why,
                               "err": "%s: %s" % (type(e).__name__, e)})
        else:
            # 畸形/旧格式（t260904-19 前格式，无租约契约无 hold 腿）→ 无主面全拆
            row = {"project": project,
                   "why": "租约文件不可读或旧格式（无 lease_id）——按无主处理全拆",
                   "pid_alive": False}
            if dry_run:
                condemned.append(dict(row, dry_run=True))
                continue
            try:
                teardown(project)
                condemned.append(row)
            except Exception as e:                          # noqa: BLE001
                errors.append({"project": project, "why": row["why"],
                               "err": "%s: %s" % (type(e).__name__, e)})

    # ---- 孤儿容器清扫（t260915-18）：无租约文件而容器在本管域=账先于容器销/
    # 隔离锁根随 tmp 树删除等形态（KI-077 当日 37 只实证的清道夫补刀面）。
    # 判定（开关+最短年龄阀+半径前缀三保险）→ 复核（判定窗内租约刚出现=新起台
    # 者进场，让位）→ 幂等 do_down → 逐条点名；skipped/errors 全点名不静默。
    # 缺省开关：CLI sweep（操作员显式发起）=开；up/ensure 挂点钩子=关（F1：
    # 260915 实爆——挂点无半径清场=无授权真拆宿主存量；孤儿面须显式启用）。
    inv = build_inventory(rows=rows if rows is not None else compose_container_rows(),
                          repo_root=repo_root)
    condemn, orphan_skipped = orphan_condemn_projects(
        inv=inv, enabled=sweep_orphans_enabled(default=(orphan_face == "cli")),
        prefix=orphan_prefix())
    for s in inv["stages"]:
        if not s["orphan"] or s["project"] in seen_projects:
            continue
        proj = s["project"]
        if proj not in condemn:
            continue
        if time.time() - t0 > budget:
            orphan_skipped.append({"project": proj,
                                   "why": "清扫预算超限（SANDBAR_STAGE_SWEEP_BUDGET_S）"})
            continue
        cur = read_lease(proj)
        if isinstance(cur, dict) and cur.get("lease_id"):
            orphan_skipped.append({"project": proj,
                                   "why": "判定窗内租约出现——让位（交租约面判定）"})
            continue
        row = {"project": proj, "pid_alive": False, "orphan": True,
               "why": "孤儿容器：无租约文件而容器在本管域（账先于容器销/隔离锁根"
                      "随 tmp 树删除等形态，t260915-18）"}
        if dry_run:
            condemned.append(dict(row, dry_run=True))
            continue
        try:
            teardown(proj)
            condemned.append(row)
        except Exception as e:                          # noqa: BLE001 清理失败必须可见
            errors.append({"project": proj, "why": row["why"],
                           "err": "%s: %s" % (type(e).__name__, e)})
    orphans_skipped.extend(orphan_skipped)
    return {
        "scanned": scanned, "files": scanned + len(skipped),
        "condemned": condemned, "kept": kept, "report_only": report_only,
        "errors": errors, "skipped_budget": skipped, "orphans_skipped": orphans_skipped,
        "git_note": git_note,
        "dry_run": bool(dry_run), "duration_s": round(time.time() - t0, 2),
    }


def sweep_residues_quiet(budget=None):
    """起台/ensure 路径的清扫挂点：判拆项真拆；失败**响亮不阻断**（清道夫
    失败不该烧掉起台——stderr 留痕，残留交下一次清扫/人工；CLI `sweep` 子命令
    才是「失败上抛非零」的机械入口，验收 D 两面各司其职）。"""
    if str(os.environ.get("SANDBAR_STAGE_SWEEP", "")).strip().lower() in ("0", "off", "no"):
        print("STAGE_SWEEP_WARN: 残台清扫已由 SANDBAR_STAGE_SWEEP=%s 显式关闭——"
              "残留交套件前清扫/人工（明示关闭，不静默降级）"
              % os.environ["SANDBAR_STAGE_SWEEP"], file=sys.stderr)
        return None
    try:
        rpt = sweep_stages(budget_s=budget, orphan_face="hook")
    except Exception as e:                                  # noqa: BLE001
        print("STAGE_SWEEP_WARN: 残台清扫异常（%s: %s）——继续起台，残留交下次清扫"
              % (type(e).__name__, e), file=sys.stderr)
        return None
    noisy = (rpt["condemned"] or rpt["errors"] or rpt["skipped_budget"]
             or rpt["report_only"] or rpt.get("git_note") or rpt.get("orphans_skipped"))
    if noisy:
        print("[stage-sweep] 判拆 %d / 仅报告 %d / 失败 %d / 跳过 %d（%.1fs）%s"
              % (len(rpt["condemned"]), len(rpt["report_only"]), len(rpt["errors"]),
                 len(rpt["skipped_budget"]), rpt["duration_s"],
                 "；%s" % rpt["git_note"] if rpt.get("git_note") else ""), file=sys.stderr)
        for c in rpt["condemned"]:
            print("[stage-sweep] 判拆 %s：%s" % (c["project"], c["why"]), file=sys.stderr)
        for c in rpt["report_only"]:
            print("[stage-sweep] 仅报告 %s：%s" % (c["project"], c["why"]), file=sys.stderr)
        for c in rpt.get("orphans_skipped") or []:
            print("[stage-sweep] 孤儿跳过 %s：%s" % (c["project"], c["why"]), file=sys.stderr)
        for e in rpt["errors"]:
            print("[stage-sweep] 清理失败 %s：%s（%s）" % (e["project"], e["why"], e["err"]),
                  file=sys.stderr)
    return rpt


def fuse_precheck():
    """保险丝只读预检（C6a）：权威判定在 capacity_acquire 临界区，这里只在
    生成 hold 腿之前做廉价早停——失控循环（一次起 200 台）不必先孵 200 个
    hold 进程再刹停。预检与临界区之间的 TOCTOU 由权威判定兜底。"""
    live = enumerate_leases()
    if len(live) >= max_stages():
        raise StageError(
            "起台保险丝（SANDBAR_STAGE_MAX_STAGES=%d）触发：活租约 %d 已达上限——"
            "疑似失控循环，刹停不排队。当前活租约清单：\n%s"
            % (max_stages(), len(live), live_lease_manifest(live)), kind="env")


def cmd_sweep(dry_run=False):
    """`sweep` 子命令：残台清扫机械入口（验收 C/D）。判拆全拆逐条点名；失败
    上抛=非零退出；stdout 末行=JSON 报告（脚本消费面）。"""
    rpt = sweep_stages(dry_run=dry_run)
    print("[stage-sweep] 扫描 %d 条租约：判拆 %d、保留 %d、仅报告 %d、失败 %d、"
          "预算跳过 %d、孤儿跳过 %d（%.1fs）" % (
              rpt["scanned"], len(rpt["condemned"]), len(rpt["kept"]),
              len(rpt["report_only"]), len(rpt["errors"]), len(rpt["skipped_budget"]),
              len(rpt.get("orphans_skipped") or []), rpt["duration_s"]))
    for c in rpt["condemned"]:
        print("[stage-sweep] 判拆 %s：%s%s" % (c["project"], c["why"],
                                               "（dry-run 未执行）" if dry_run else ""))
    for c in rpt["report_only"]:
        print("[stage-sweep] 仅报告 %s：%s" % (c["project"], c["why"]))
    for c in rpt.get("orphans_skipped") or []:
        print("[stage-sweep] 孤儿跳过 %s：%s" % (c["project"], c["why"]))
    for e in rpt["errors"]:
        print("[stage-sweep] 清理失败 %s：%s（%s）" % (e["project"], e["why"], e["err"]),
              file=sys.stderr)
    print(json.dumps(rpt, ensure_ascii=False))
    return EXIT_FAIL if (rpt["errors"] or rpt["skipped_budget"]) else EXIT_OK


def cmd_inventory():
    """`inventory` 子命令（t260915-18 工单②，只读）：台面清点 JSON 回执——
    容量面（容器/工程/活租约/孤儿 vs SANDBAR_STAGE_MAX_STAGES）+ 每台归属
    （holder.ticket=票号/attempt、pid、锚、owner、心跳年龄）+ 工程名全列——
    人工排障不再猜哈希台名。docker 缺席=ok:false（CLI exit 2），绝不假装查过。"""
    if not docker_present():
        return {"ok": False,
                "error": "docker 不可用（docker info 失败）——容器面不可见，"
                         "容量/孤儿口径本轮缺席（不假绿）"}
    inv = build_inventory()
    inv["ok"] = True
    return inv


# ---------------------------------------------------------------- validation

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
    """Validate explicit port knobs: numeric/range/forbidden/taken — every
    failure names what to check."""
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
    """The env-explicit-port path (all or nothing, so half-specified ambiguity
    is impossible)."""
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


# ---------------------------------------------------------------- health probes

def wait_temporal(port, timeout):
    """Readiness of the stage's temporal frontend.

    Bare TCP is NOT sufficient on Docker Desktop (Mac): the host-side port
    forwarder accepts connections as soon as the container exists, so
    connect_ex succeeds while the server inside is still starting, and the
    very next real client dial gets connection refused on the same port
    (final-verification flake of campaign ③, 260909: wait_temporal passed,
    register_namespace's namespace create then got
    "dial tcp 127.0.0.1:<port>: connect: connection refused" through all
    of its 3x2s retries). Readiness therefore means: TCP open AND an
    end-to-end probe with the temporal CLI (operator namespace list — the
    same dial the namespace/SA registration will perform) succeeds. When
    the CLI is unavailable we fall back to TCP-only (the registration step
    reports that honestly in the JSON afterwards).

    The probe's patience is bounded (PROBE_BUDGET_S, default 180s, 6-9x an
    idle boot): campaign-3 final verification run I showed an unbounded probe
    letting a starved boot burn the whole 900s executor cap (SIGKILL loses
    attribution and skips the scenario's own teardown). If temporal is not
    CLI-ready within the budget the stage is sick and we fail loud and fast
    with an env error — strictly better attribution than a silent hang, and
    strictly more patient than the pre-probe behavior (bare TCP plus a 3x2s
    SA retry that never outlived a real boot)."""
    PROBE_BUDGET_S = 180
    t0 = time.time()
    cli = resolve_temporal_cli()
    while time.time() - t0 < min(timeout, PROBE_BUDGET_S):
        if not port_open(port, timeout=1.0):
            time.sleep(0.5)
            continue
        if not cli:
            return  # TCP-only fallback: no CLI to probe with
        remaining = max(1, int(timeout - (time.time() - t0)))
        try:
            p = subprocess.run([cli, "operator", "namespace", "list",
                                "--address", "127.0.0.1:%d" % port],
                               capture_output=True, text=True,
                               timeout=min(5, remaining))
            if p.returncode == 0:
                return
        except (subprocess.SubprocessError, OSError):
            pass  # not speaking yet — keep waiting
        time.sleep(1.0)
    raise StageError("temporal %ds 内未就绪（127.0.0.1:%d，CLI 端到端探针未过）"
                     % (min(timeout, PROBE_BUDGET_S), port), kind="env")


def wait_console(port, timeout):
    t0 = time.time()
    url = "http://127.0.0.1:%d/" % port
    while time.time() - t0 < timeout:
        if http_ok(url):
            return
        time.sleep(1.0)
    raise StageError("console %ds 内未就绪（%s）" % (timeout, url), kind="env")


def stage_healthy(state):
    """ensure 的复用判据（t260910-12 起为租约事实，R3 主信号）：state=up 且
    心跳新鲜且 holder 进程在 → 复用，零 docker 查询。容器在场与否不进本判定
    ——docker ps 采样空窗（run L/M/O 互拆根因）绝不能把活租约翻进拆台路径。
    容器查询只出现在两处次要角色：过期租约的回收确认、幂等复用的证据面
    （container_ids）。"""
    return lease_reusable(state)


# ---------------------------------------------------------------- namespace/SA

def resolve_temporal_cli():
    """Resolve the temporal CLI (env pointer > lane location > main-tree
    fallback)."""
    # env pointer nonexistent / both the lane and the main tree missing it =
    # explicitly unavailable, never swallowed: swallowing the exception would
    # let the L1 cases depending on it drift their assumptions (proven once
    # supply's self-heal created the lane's bin symlink).
    try:
        import bench  # noqa: PLC0415 同目录共享库
        return str(bench.resolve_temporal_bin())
    except bench.MissingAsset:
        return None
    except Exception:
        cand = REPO / "server" / "engine" / "bin" / "temporal"
        return str(cand) if cand.exists() else None


def register_namespace(ns, addr, timeout=30):
    """namespace + ProjectKey/EpicCode SA + retention period (idempotent;
    tolerate "already exist").
    Returns (ok, note). A missing/failing temporal CLI does not block the boot —
    the False is reported honestly in the JSON, and scenarios depending on the
    SA (ticket-start with a project) fail loudly client-side (never silently)."""
    cli = resolve_temporal_cli()
    if not cli or not pathlib.Path(cli).exists():
        return False, "temporal CLI 不可得（%s 缺失，env SANDBAR_TEMPORAL_BIN 可指路）——SA/保留期未注册" % cli
    last_err = ""

    def cli_ok(args, tolerate):
        # the namespace service still has a short not-ready window after TCP is
        # up — retry briefly on failure (3 x 2s);
        # attach the CLI stderr tail to a failure (swallowing stderr turns it
        # into a bare "create failed" with nothing to attribute, breaking the
        # error-precision discipline).
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
    # t260916-02：巡检票显式去重（实例+期号）的两个新 SA 一并幂等注册（temporalite 无
    # start-dev 启动参，注册只能走 operator create；已注册=tolerate 已容）。
    for name in ("ProjectKey", "EpicCode", "InspectionInstance", "InspectionPeriod"):
        if not cli_ok(["operator", "search-attribute", "create", "--namespace", ns,
                       "--name", name, "--type", "Keyword", "--address", addr],
                      ("already exist", "already defined", "already registered")):
            return False, "SA %s 注册失败（ns=%s）：%s" % (name, ns, last_err)
    cli_ok(["operator", "namespace", "update", "--retention", "876000h",
            "--namespace", ns, "--address", addr], ())  # retention is best-effort; on failure only the retention is missing
    return True, "namespace+SA 就绪"


# ---------------------------------------------------------------- up / down / ensure

def _bootstrap_lane_nm():
    """Bootstrap the lane-side profile farm links (t260907-10 supply-side
    self-heal; gen4 added the headless variant).

    After the directory restructure the farm chain is five relative symlinks
    (sandbar-* -> ../../plugins/<dir>), pure runtime artifacts (gitignored),
    which every new lane/fresh clone naturally lacks — supply must self-heal
    rather than depend on manual preparation. Both variants share the chain
    (profile and profile-headless carry the same five links in node_modules;
    the cordis.patch.yml comments decree "keep the two identical") — building
    only web and missing headless is exactly the adversarial shape the
    t260907-05 farm scenario pinned. Idempotent: a no-op when the links exist.
    When a target plugin directory is absent (implementation not landed), do
    not fabricate it — hand the environment red to the caller.
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
                try:
                    link.symlink_to("../../plugins/%s" % d)
                    made += 1
                except FileExistsError:
                    # 并发 up 竞态吸收（t260917-07 实锤：场景 A/B 双台并发起 +
                    # 多泳道同宿主同起时，双方同时通过 is_symlink() 检查，后到者
                    # EEXIST——check-then-act 非并发幂等）。对方已建同链=照 no-op；
                    # 二次确认仍非 symlink（半残形态）才如实上抛。
                    if not link.is_symlink():
                        raise
    if made:
        print("注：泳道 profile*/node_modules 农场链自举 %d 条（两变体同款五链，"
              "sandbar-* → ../../plugins/*，运行期工件不入库）" % made)
    return True


def default_repo_dir():
    """Default value for the REPO mount (gen2, proven on a real container, 3):
    the in-container dsh is an npm-globally-installed console, and /repo only
    serves the profile + plugins — a lane worktree always lacks the gitignored
    profile/node_modules, so mounting the lane = plugin resolution failure
    (ERR_MODULE_NOT_FOUND). Therefore: if the lane's profile carries the plugin
    dependencies, mount the lane (bootstrapping the farm links first when they
    are missing, t260907-10); otherwise fall back to the main tree (parent of
    the git common dir, where everything is installed). capture/bench
    scenarios' tested workbench is unaffected (they point at
    /repo/server/plugins/workbench explicitly through the profile symlink, and
    that path only means anything when the tested tree is passed explicitly as
    repo_dir — lib_fix15/bench-shot both pass it explicitly)."""
    nm_complete = all(
        (REPO / "server" / prof / "node_modules" / pkg).is_symlink()
        for prof in ("profile", "profile-headless")
        for pkg in ("sandbar-admin-ui", "sandbar-workbench", "sandbar-knowledge",
                    "sandbar-providers", "sandbar-temporal-tools"))
    # Completeness test = all ten links across the two variants: the half-built
    # state (profile present, headless missing) used to short-circuit and bypass
    # the bootstrap (the t260907-05 farm scenario's profile-headless five-link
    # red was exactly this)
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
    """Diagnostic attachment for a failed wait: container status lines + log
    tail (gen2 companion 1: errors must be precise — "console not ready in
    600s" once mis-directed an EROFS crash loop as "slow")."""
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


def container_ids(project):
    """Stable container identity list for the project — the idempotent-reup
    evidence face (ticket acceptance: a second up must NOT rebuild containers;
    the id list comes back in the lease/JSON so a scenario can assert it
    unchanged). Query failure = [] honestly (evidence absence, never
    fabricated)."""
    try:
        p = _run(["docker", "ps", "-a", "--filter",
                  "label=com.docker.compose.project=%s" % project,
                  "--format", "{{.ID}}"], timeout=15)
        return [x.strip() for x in (p.stdout or "").splitlines() if x.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


def _docker_published_port(container, container_port):
    """容器已发布的宿主端口（认领判据：端口真在服务才算活着）。拿不到返 None。"""
    try:
        p = _run(["docker", "port", container, container_port], timeout=15)
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    line = ((p.stdout or "").strip().splitlines() or [""])[0]
    if ":" not in line:
        return None
    try:
        return int(line.rsplit(":", 1)[1])
    except ValueError:
        return None


def _container_running(name):
    try:
        p = _run(["docker", "inspect", "-f", "{{.State.Running}}", name], timeout=15)
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    return (p.stdout or "").strip() == "true"


def adopt_live_residue(project, services_list, opts):
    """认领「活着但本根无租约」的同名台（--keep 语义下的跨锁根自愈，t260914-01）。

    同一工程名可能在两个锁根各有一份记录（宿主根 ~/.sandbar/test-stages 与沙箱降级根
    $TMPDIR/sandbar-test-stages；声明侧供给台另用 /tmp/sandbar-test-stages）——本根租约
    缺失/已死而容器仍在跑时，旧行为一律诚实拒收（「不拆别人的台」），于是**另一上下文起的
    同名活台会把本上下文的消费者全部堵死**（t260914-01 实测：17 条 UI 场景连坐 env 红，
    且因沙箱不可写宿主根而长期无法复现）。

    本函数**不拆任何容器**：容器在跑 + 端口真在服务 ⇒ 幂等补注册 namespace/SA ⇒ 本根落一份
    state=up 的租约（并接一条 hold 腿维持心跳）；任一判据不成立（容器不在跑 / 端口不服务 /
    半残形态）⇒ 返回 None，调用方照旧诚实拒收——「不拆在跑台」的安全语义一字未动。
    """
    names = residue_containers(project)
    if not names or any(n.startswith("<") for n in names):
        return None
    temporal = next((n for n in names if n.endswith("-temporal")), None)
    if not temporal or not _container_running(temporal):
        return None
    t_port = _docker_published_port(temporal, "7233/tcp")
    if not t_port or not port_open(t_port):
        return None
    ports = {"temporal": t_port}
    u_port = _docker_published_port(temporal, "8233/tcp")
    if u_port and port_open(u_port):
        ports["ui"] = u_port
    dsh = next((n for n in names if n.endswith("-dsh")), None)
    if dsh:
        if not _container_running(dsh):
            return None                      # 半残（dsh 起不来）：不认领，照旧拒收
        c_port = _docker_published_port(dsh, "3199/tcp")
        if not c_port or not http_ok("http://127.0.0.1:%d" % c_port):
            return None
        ports["console"] = c_port
    ns = opts.get("namespace") or "sandbar-test"  # 契约缺省值随 compose 声明（t260917-07 补完终切）；认领旧台时对新名幂等补注册（register_namespace）
    sa_ok, sa_note = register_namespace(ns, "127.0.0.1:%d" % t_port)   # 幂等；失败则如实记账
    lease = _flip_lease_up(project, None, ports, services_list,
                           {"SANDBAR_TEST_NAMESPACE": ns}, opts, sa_ok, sa_note)
    try:
        _spawn_hold(project, lease.get("lease_id"), keep=True)
    except Exception:
        pass      # hold 起不来不阻断认领（心跳死后下次 ensure 会再认领）
    lease["adopted"] = True
    return _reused(lease)


def _flip_lease_up(project, lease, ports, services_list, env, opts,
                   sa_registered, sa_note):
    """boot 完成 → 翻 state=up（原子写，写前保 lease_id/holder 不变）。CLI 翻面
    自带一拍新鲜心跳，此后心跳由 hold 腿接管；container_ids 在此定格，作为
    同租约二次 up 幂等复用的证据面（验收④：容器 id 不变=未被重建）。
    翻面兜底 new_lease（租约文件丢失的退化路）同样带 anchor_pid/anchor_token
    两件套（对抗复核 F2：缺了它们，hold ③ 两段判活在这条退化路上无从谈起
    ——pid 重用形态的「愿主已亡 hold 仍续跳」判不出来）。"""
    lease = lease if isinstance(lease, dict) and lease.get("lease_id") else (
        read_lease(project) or new_lease(project, holder_pid=os.getpid(),
                                         services=services_list))
    anchor_pid = lease.get("anchor_pid") or os.getpid()
    if not lease.get("anchor_token"):
        lease["anchor_pid"] = anchor_pid
        lease["anchor_token"] = process_start_token(anchor_pid)
    used = [k for k in ("temporal", "ui", "console") if k in ports
            and ("temporal" in services_list if k in ("temporal", "ui") else "dsh" in services_list)]
    lease.update({
        "state": "up",
        "services": list(services_list),
        "namespace": env["SANDBAR_TEST_NAMESPACE"],
        "ports": {k: ports[k] for k in used},
        "repo_dir": opts.get("repo_dir"),
        "container_ids": container_ids(project),
        "sa_registered": sa_registered,
        "sa_note": sa_note,
        "booted_ts": int(time.time()),
        "heartbeat_ts": time.time(),
    })
    write_lease(project, lease)
    return lease


def do_up(project, services_list, opts, timeout, lock_fd=None, lease=None):
    """The boot itself (band lock held by the caller when band-allocated; the
    claim placeholder lease was written by _boot_new_stage. The failure path
    runs the down -v cleanup in place before re-raising; lease release is the
    caller's — the hold sees the lease vanish and exits by itself)."""
    ports = opts["ports"]
    env = compose_env(project, services_list, ports, opts)
    # Total time budget: --timeout covers the whole up+wait (previously up and
    # wait each got the full timeout independently — a 900s value was measured
    # to drag past 20 minutes without self-terminating). Cleanup (down/logs)
    # has its own short timeouts and is not counted.
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
        up_tail, up_rc = "", 0
        for attempt in range(3):
            _clear_project_network(project)   # 网段必来自受管表当前分配（验收 B/C3）
            p = compose_cmd(project, ["up", "-d", "--quiet-pull"] + list(services_list),
                            env, timeout=timeout)
            if p.returncode == 0:
                break
            up_rc = p.returncode
            up_tail = ((p.stdout or "") + (p.stderr or ""))[-2000:]
            if not (_SUBNET_CONFLICT_PAT.search(up_tail) and not container_ids(project)):
                raise StageError("docker compose up 失败（rc=%d）：\n%s" % (up_rc, up_tail),
                                 kind="env")
            # 网段撞号（C3）：先清同名遗留网络（遗留网络+新子网的配置漂移报错字面
            # 不一定是 overlaps），再换槽回写租约，逐次点名。撞号时容器必未起
            # （container_ids 为空已核），重试不会拆到半死的台。
            old = opts.get("subnet")
            _clear_project_network(project, force=True)
            new_subnet = alloc_subnet(project, exclude={old} if old else ())
            cur = read_lease(project) or lease
            cur["subnet"] = new_subnet
            write_lease(project, cur)
            opts = dict(opts)
            opts["subnet"] = new_subnet
            env["SANDBAR_TEST_SUBNET"] = str(new_subnet)
            print("[stage_docker] 网段撞号换槽重试 %d/2：%s → %s（报错尾：%s）"
                  % (attempt + 1, old, new_subnet, " ".join(up_tail.split())[-140:]))
        else:
            raise StageError("docker compose up 失败（网段撞号换槽 3 次未解决，rc=%d）：\n%s"
                             % (up_rc, up_tail), kind="env")
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
    # Red-line self-check: booted ports never include the production surface
    for name, p in ports.items():
        if p in PROD_PORTS:
            _do_down(project, env, quiet=True)
            raise StageError("起台端口 %s=%d 落在生产端口面——红线自检失败，已就地清场"
                             % (name, p), kind="env")
    return _flip_lease_up(project, lease, ports, services_list, env, opts,
                          sa_registered, sa_note)


def _do_down(project, env=None, quiet=False):
    """down -v + container list check (internal version: state-file clearing is
    managed centrally by do_down)."""
    env = env if env is not None else dict(os.environ)
    try:
        compose_cmd(project, ["down", "-v", "--remove-orphans", "--timeout", "30"],
                    env, timeout=_STOP_TIMEOUT)
    except StageError:
        if not quiet:
            raise


def do_down(project, harvest_hold=True):
    """Tear a stage down = the lease's voluntary release (ticket spec ①), in
    the order that closes the R6/R1'b races:
      1. state → downing (atomic): the reuse primary signal dies immediately —
         no third-party ensure can claim this stage from this moment;
      2. harvest the hold (SIGTERM → bounded wait → SIGKILL): guarantees no
         heartbeat lands after the lease file is gone (R6 — a post-unlink
         heartbeat would resurrect a fake up-file and cost the next entrant a
         full TTL);
      3. compose down -v (idempotent);
      4. unlink the lease (release) + hold pid file.
    Idempotent (absent project / already-cleared containers both succeed).
    harvest_hold=False is the hold's own orphan-reclaim path (it IS the hold —
    signaling itself is skipped; _stop_hold_by_pid also self-guards)."""
    validate_project(project)
    lease = read_lease(project)
    if isinstance(lease, dict) and lease.get("lease_id"):
        if lease.get("state") != "downing":
            lease["state"] = "downing"
            try:
                write_lease(project, lease)
            except OSError:
                pass   # downing 翻面失败不阻断拆台：hold 仍会在 unlink 后自退
        if harvest_hold:
            _stop_hold_by_pid(holder_pid(lease))
    if os.environ.pop("SANDBAR_STAGE_INJECT_DOWN_FAIL", None) is not None:
        # 测试注入缝（t260915-18 腿 C；R3：**触发即自清**——pop 原子取走，绝不
        # 跨用例污染；env 注入缝惯例同 SANDBAR_UI_CAPTURE_STUB/SANDBAR_STAGE_LOCK_DIR）。
        # 模拟「compose down 真失败」：翻面/收割照走，随后失败上抛+租约保留——
        # 与下方 compose down rc!=0 分支同语义（t260912-02 验收 D 样板）。
        print("STAGE_FAIL: [inject] SANDBAR_STAGE_INJECT_DOWN_FAIL 触发（已自清）——"
              "模拟拆台失败，租约保留", file=sys.stderr)
        raise StageError("[inject] 模拟拆台失败（SANDBAR_STAGE_INJECT_DOWN_FAIL，一次性）"
                         "——租约保留待重试/人工", kind="fail")
    if not docker_present():
        # t260915-18（C4:2078）：docker 缺席不再销账——daemon 恢复后容器可能
        # 还在，租约（state=downing）是它们唯一的账本；保留交 sweep crit_iii/
        # 孤儿清扫/人工，fail-visible（sweep 拆台失败本就走 errors 响亮上抛）。
        raise StageError("docker 不可用（docker info 失败）——拆台需要 docker"
                         "（租约保留 state=downing，不销账）", kind="env")
    env = dict(os.environ)
    env.setdefault("SANDBAR_TEST_TEMPORAL_NAME", "%s-temporal" % project)
    env.setdefault("SANDBAR_TEST_DSH_NAME", "%s-dsh" % project)
    comp = compose_cmd(project, ["down", "-v", "--remove-orphans", "--timeout", "30"],
                       env, timeout=_STOP_TIMEOUT)
    if comp.returncode != 0:
        # t260912-02（验收 D）：compose down 真失败必须上抛可见——失败时租约
        # 保留（state=downing），sweep 重试或人工接手可再判；不静默释放成
        # 「无租约可追的残留」。缺工程/已清场的幂等 down 返回 0，不受影响。
        tail = " ".join((((comp.stderr or "") + (comp.stdout or ""))
                         .splitlines() or [""])[-1].split())
        raise StageError("compose down 失败（rc=%d）：%s——租约保留待重试/人工"
                         % (comp.returncode, tail[:200]), kind="fail")
    release_lease(project)
    try:
        (lock_root() / ("holder-%s.pid" % project)).unlink()
    except FileNotFoundError:
        pass
    residue = residue_containers(project)
    return {"project": project, "down": True, "residue": residue}


def _gates(services_list):
    """docker / image presence gates (the honest three-state ENV_FAIL face —
    preserved verbatim, ticket spec ⑤)."""
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
    # t260913-04（C5①）：agent 执行面镜像门——opt-in（不设 env 的台零变化，不破既有台
    # 契约）；设 SANDBAR_REQUIRE_AGENT_IMAGE=1 的台（容器执行面回归族）缺镜像=点名
    # ENV_FAIL（exit 2）+ 构建命令。判定放 gates 层而非 boot 窗口内自动 build——
    # 联网构建分钟级，混进 boot 超时会把诊断引向「起台超时」错方向（review C5）。
    if os.environ.get("SANDBAR_REQUIRE_AGENT_IMAGE") == "1" and not agent_image_present():
        sys.path.insert(0, str(REPO / "server" / "engine"))
        import agent_runtime
        raise StageError(
            "ENV_FAIL: agent 执行面镜像缺席：%s（引擎「每票一容器」的运行时基座；"
            "本机自建、无 registry 拉取）——先跑 sh server/engine/build_agent_image.sh "
            "重建，再重试" % agent_runtime.agent_image(), kind="env")


def _boot_failure_cleanup(project, hold_proc):
    """起台半途失败的清场（t260915-18 C4:2181 裁决）：先就地尽力拆
    （harvest_hold=False——hold 若已死也不复活它，只在拆成功后收割进程）；
    拆成功=租约随 do_down 释放、hold 见 ① 自退；拆失败=**保留租约**（state=
    booting，hold 见「起台者亡+booting」走 ③' 重试回收；hold 也已死则心跳停更
    → sweep crit_iii/孤儿清扫接管），且**不收割 hold**。原序（直接 release+
    收割）会把 do_up 半途建出的容器变成无账孤儿（KI-077 当日 37 只实证的同族
    形态——账先于容器销=工具链永久失明）。"""
    try:
        do_down(project, harvest_hold=False)
        _harvest_hold(hold_proc)   # 拆成功：租约已释，收割 hold 进程兜底
    except Exception as e:         # noqa: BLE001 清场失败必须响亮，绝不静默销账
        print("STAGE_FAIL: 起台半途失败且就地拆台失败（%s：%s）——租约保留，"
              "台交 hold ③'/sweep/人工回收" % (type(e).__name__, e), file=sys.stderr)


def _boot_new_stage(project, services_list, opts, timeout, cold_cleanup=False,
                    keep=False):
    """The full boot sequence, shared by `up` and ensure's cold path:
    gates → 残台清扫（t260912-02 挂点②）→ 保险丝只读预检（C6a）→ (idempotent
    cold cleanup) → hold leg → capacity claim（保险丝权威判定+占位，同一临界区）
    → ports (explicit env or band) → subnet claim（C2：择槽即写租约占位）→
    boot → flip state=up. Every failure path releases the lease and reaps the
    hold — no half-claimed occupancy is ever left (R1'a; the hold also
    self-exits via its bounded lease-wait as a backstop).
    keep=True：常驻基建台——租约记 keep 标，hold 腿据此禁③锚死回收（锚=
    短命调用方 shell）；其余终态与判死回收判据原样，绝不引入存活启发式。"""
    _gates(services_list)
    sweep_residues_quiet()      # 起台时扫一遍（t260912-02 清理挂点②；失败响亮不阻断）
    fuse_precheck()             # 保险丝预检：失控循环在孵 hold 前刹停（权威判定在临界区）
    if cold_cleanup:
        # 冷清理幂等：无台=快速 no-op；有残留（过期死租约的孤儿容器）就地清——
        # compose 同名二次起台的容器名冲突根，正是 run L/M/O 互拆族的一个面。
        # 清理失败不阻断（do_down 内部已尽力），后续 compose up 自会报真错。
        try:
            do_down(project)
        except StageError:
            pass
    lease_id = "%s-%d-%s" % (project, int(time.time() * 1000), os.urandom(4).hex())
    hold_proc = _spawn_hold(project, lease_id, keep=keep)
    try:
        validate_holder_pid(hold_proc.pid)
        anchor_pid = os.getppid()
        lease = new_lease(project, holder_pid=hold_proc.pid, services=services_list,
                          anchor_pid=anchor_pid, lease_id=lease_id,
                          anchor_token=process_start_token(anchor_pid))
        if keep:
            lease["keep"] = True   # 占位/心跳读改写全链路透传（常驻标记随租约存续）
        capacity_acquire(project, lease, timeout)   # 保险丝判定+占位同临界区（R4 原样）
        try:
            ports = explicit_ports(services_list)
            lock_fd = None
            try:
                if ports is None:
                    _, ports, lock_fd = choose_band(ephemeral_range())
                lease["ports"] = dict(ports)
                # C2：择槽后立刻写进租约（state 仍 booting 的占位态）——booting
                # 窗口内网段对并发分配器可见，32 并发不靠概率避让；写后复核 +
                # do_up 的 overlaps 换槽重试只是兜底（C3）。
                subnet = claim_subnet(project, lease)
                opts = dict(opts)
                opts["ports"] = ports
                opts["subnet"] = subnet
                return do_up(project, services_list, opts, timeout,
                             lock_fd=lock_fd, lease=lease)
            finally:
                if lock_fd is not None:
                    os.close(lock_fd)   # daemon 已真绑端口，释放无冲突窗（header trade-off）
        except BaseException:
            # t260915-18（C4:2181）：半途失败不再直接销账——就地尽力拆、拆不
            # 动则保留租约（见 _boot_failure_cleanup：原序=半途容器失明）。
            _boot_failure_cleanup(project, hold_proc)
            raise
    except BaseException:
        _harvest_hold(hold_proc)
        raise


def _reused(st):
    st = dict(st)
    st["reused"] = True
    return st


def _wait_booting(project, lock_fd, deadline):
    """booting 等待（ticket ② state=booting → 等待其完成；review R5）：轮询
    时不持项目锁（os.replace 原子写保证无锁读安全；持锁轮询会让起台者永远拿
    不到锁=自锁死）。预算=调用方剩余 timeout。返回时已重新持锁。"""
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        while time.time() < deadline:
            st = read_lease(project)
            if not isinstance(st, dict) or st.get("state") != "booting":
                return st   # 翻 up / downing / 被回收 / 消失 → 回锁终判
            time.sleep(1.0)
        return read_lease(project)
    finally:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    raise StageError(
                        "供给台 %s booting 等待后回锁超时：同项目起台者未在预算内"
                        "交付也未消亡——查 docker 与 hold 日志" % project, kind="env")
                time.sleep(0.5)


def _wait_heartbeat_recovery(project, lock_fd, deadline):
    """心跳停更宽限（t260913-02 arbitrate gen12）：租约已过期但 holder 进程仍在时，轮询
    等心跳恢复（hold 腿被负载压住的一次停顿，约数秒~数十秒）——恢复即返回新租约
    （调用方走复用），holder 亡 / 租约消失 / state 翻面也立即返回（调用方按冷路径或
    精确红收口），宽限到期返回最后读到的租约（调用方按「真僵死」诚实红点名）。

    锁语义：与 _wait_booting 同源——等待期不持项目锁，免得把同项目其它 ensure 排到
    预算外；hold 腿自身从不取 ensure 项目锁（只写 pidfile + 心跳文件），故释放锁不会
    与心跳互相阻塞。返回时重新持锁（拿不到也不阻塞收口：判据全在租约读数上）。"""
    grace = min(stall_grace_s(), max(0.0, deadline - time.time()))
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        end = time.time() + grace
        st = read_lease(project)
        while time.time() < end:
            st = read_lease(project)
            if lease_reusable(st) or lease_dead(st) or not isinstance(st, dict) \
                    or st.get("state") != "up":
                return st
            time.sleep(1.0)
        return st
    finally:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= end + 5:
                    break
                time.sleep(0.5)


def do_ensure(project, services_list, opts, timeout, keep=False):
    """Idempotent ensure (ticket spec ②), as a lease state machine:
      快路径（无锁）：state=up + heartbeat fresh + holder alive → 复用，
      零 docker 查询（R3 主信号——docker ps 采样空窗绝进不了本判定）；
      state=booting 且租约活 → 不持锁等待其翻面（R5），绝不并发再起；
      state=downing / 缺失 / 过期死（租约过期 AND holder 不存在）/ 旧格式 →
      冷路径：幂等清残留 → hold 腿 → 满员占位 → 择带 → 起台；
      租约过期但 holder pid 仍在 → 拒收诚实红（疑似 pid 复用/僵死，不对抗）。
    --keep：在跑面（活租约已在上面复用返回；无主容器在跑的孤儿台）一律不拆，
    诚实环境红交人工。冷/半残路径按项目串行化（run K 雷群回归锚保留）。"""
    validate_project(project)
    st = read_lease(project)
    if lease_reusable(st):
        return _reused(st)
    lock_path = lock_root() / ("ensure-%s.lock" % project)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    t0 = time.time()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - t0 >= timeout:
                    raise StageError(
                        "供给台 %s ensure 互斥等待超时（%ds）：同项目并发 ensure 未在"
                        "预算内完成——疑似起台卡死，查 docker 后重试" % (project, timeout),
                        kind="env")
                time.sleep(1.0)
        # 持锁终判：等待窗口里先到者可能已完成起台。
        deadline = t0 + timeout
        # 起台时扫一遍（t260912-02 挂点②）：僵尸台（心跳陈旧等残态）在本项目
        # 的拒收/冷起判定前先被清道夫处置——ensure 对僵尸台从「诚实红拒收且
        # 永卡」变为「清扫后冷起自愈」；清扫失败响亮不阻断（见挂点函数注）。
        sweep_residues_quiet()
        st = read_lease(project)
        if lease_reusable(st):
            return _reused(st)
        if isinstance(st, dict) and st.get("state") == "booting" and not lease_dead(st):
            # 他人在起台：不持锁等待（R5），绝不并发再起
            st = _wait_booting(project, fd, deadline)
            if lease_reusable(st):
                return _reused(st)
        if keep and residue_containers(project):
            # --keep 消费者（常驻基建台/夹具台）在「本根租约不可复用 + 同名容器在跑」时
            # 一律**先认领后拒收**（t260914-01，跨锁根自愈）。覆盖三副面孔：
            #   ①本根无租约、容器在跑（宿主根 vs 沙箱降级根的 split-brain）；
            #   ②租约已死/缺失但容器仍在服务；
            #   ③租约在册但已不可用（心跳停更 + holder pid 僵死/被复用）而容器仍在服务
            #     ——旧行为在此先抛「不对抗，人工核查后 down」，于是同一堵死面换个签名复发。
            # 认领不拆任何容器、不与僵死 holder 对抗：只在活体判据（容器 Running + 端口真在
            # 服务）全过时，把本根租约刷成一份带新 lease_id 的活租约并接 hold 腿——旧 hold
            # 见 lease_id 更换即自退（其终止态之一）。认领不成 ⇒ 落到下面两条原有拒收分支，
            # 「不拆在跑台」的安全语义与文案一字未动。
            adopted = adopt_live_residue(project, services_list, opts)
            if adopted is not None:
                return adopted
        if isinstance(st, dict) and st.get("state") == "up" and not lease_dead(st):
            # 心跳停更（过期）而 holder 进程仍在：先给一段**宽限窗**等心跳恢复，恢复不了
            # 才按原语义诚实红交人工（t260913-02 arbitrate gen12）。
            # 为什么必须给宽限：260914 23:17 本泳道闸跑实测 17 条 console 族齐瞬时
            # ENV_FAIL（0.2~1.2s），根因=共享 console 台的 hold 腿被负载压住 >TTL(90s)
            # 心跳停更，而**同一个 hold 腿（lease_id/pid 自 21:56 未换）事后仍在正常
            # 心跳**——即一次调度停顿把整族场景打成环境红，场景一条没跑。判据不变
            # （只有 过期 AND pid 死 才回收，绝不硬拆活 holder），只是把「瞬时停顿」
            # 与「真僵死」分开：等到截止仍不恢复=真僵死，文案照旧点名人工。
            st = _wait_heartbeat_recovery(project, fd, deadline)
            if lease_reusable(st):
                return _reused(st)
            if not lease_dead(st):
                # 报错必须精确（失败分类协议）：holder 活=心跳停更（僵死嫌疑）；
                # holder 亡而租约未过期=等待窗内未见恢复（旧文案会误称「holder 仍在」）。
                hp = holder_pid(st)
                if hp and pid_alive(hp):
                    raise StageError(
                        "供给台 %s 心跳停更（holder pid=%s 仍在，租约已过期，宽限 %ds 内"
                        "未恢复）——疑似 pid 复用或 holder 僵死；绝不硬拆，人工核查后 down"
                        "（可查 hold-%s.log）"
                        % (project, hp, stall_grace_s(), project), kind="env")
                raise StageError(
                    "供给台 %s 心跳停更（holder pid=%s 已不存在，租约尚未过期不可回收，"
                    "宽限 %ds 内未见恢复）——再等一次 ensure 或人工 down（可查 hold-%s.log）"
                    % (project, hp, stall_grace_s(), project), kind="env")
        if keep and residue_containers(project):
            raise StageError("供给台 %s 有无主容器在跑（租约已死/缺失）——--keep 语义"
                             "不拆在跑台，且认领失败（容器不在跑／端口不服务／半残）；"
                             "人工核查或去旗重跑" % project, kind="env")
        # 冷路径：缺失 / downing / 过期死 / 旧格式 → 完整起台序列
        return _boot_new_stage(project, services_list, opts, timeout,
                               cold_cleanup=True, keep=keep)
    finally:
        os.close(fd)


def do_up_public(project, services_list, opts, timeout, keep=False):
    """`up` subcommand full flow: validate → live-lease conflict gate → boot
    sequence. A live lease on the same project = refuse (exit 3, conflict):
    idempotent reuse belongs to ensure; fighting a second compose-up over the
    same project name is exactly the mutual-teardown root this ticket kills,
    so `up` never does it. keep=True：直调 up --keep 同样落常驻租约（hold 禁
    ③锚死回收；C2 提示照旧）。"""
    validate_project(project)
    st = read_lease(project)
    if st and not lease_dead(st):
        raise StageError(
            "项目 %s 已有活租约（state=%s holder pid=%s 起租=%s）——幂等复用走 ensure；"
            "确认无主先 down 再 up（对抗式二次起台=互拆根因，up 拒收）"
            % (project, st.get("state"), holder_pid(st),
               time.strftime("%H:%M:%S", time.localtime(st.get("ts") or 0))),
            kind="conflict")
    return _boot_new_stage(project, services_list, opts, timeout,
                           cold_cleanup=True, keep=keep)


# ---------------------------------------------------------------- selftest (white box, never touches docker)

def selftest():
    fails = []

    def ok(cond, label):
        print(("ok    " if cond else "FAIL  ") + label)
        if not cond:
            fails.append(label)

    # 1. constructive forbidden/ephemeral exclusion: no band port ever lands in
    # the forbidden set or the ephemeral range
    eph = ephemeral_range()
    all_ports = [p for i in range(BAND_COUNT) for p in band_ports(i).values()]
    ok(not (set(all_ports) & FORBIDDEN_PORTS),
       "全部 %d 个档位端口 ∩ 禁区端口 = ∅" % len(all_ports))
    if eph:
        overlap = [p for p in all_ports if eph[0] <= p <= eph[1]]
        ok(not overlap, "档位端口与内核临时区间 %s 零重叠（重叠 %d 个）" % (eph, len(overlap)))
    else:
        ok(True, "临时区间读取不可得（非 Linux）——纵深防御缺席不算红（N2）")
    ok(all(band_base() <= p < band_base() + BAND_COUNT * BAND_STEP for p in all_ports),
       "档位端口全部落在 %d~%d 预留窗内" % (band_base(), band_base() + BAND_COUNT * BAND_STEP))
    ok(len({tuple(sorted(band_ports(i).items())) for i in range(BAND_COUNT)}) == BAND_COUNT,
       "档位端口两两不重叠")

    # 2. band lock mutual exclusion: a second OFD flock in the same process
    # must fail (kernel semantics)
    fd = _lock_band(0)
    ok(fd is not None, "band-0 首次上锁成功")
    if fd is not None:
        ok(_lock_band(0) is None, "band-0 二次上锁非阻塞失败（互斥成立）")
        os.close(fd)
        fd2 = _lock_band(0)
        ok(fd2 is not None, "释放后 band-0 立即可复抢（崩溃自释语义）")
        if fd2 is not None:
            os.close(fd2)

    # 3. malformed-input rejection (each naming what it checks, zero side effects)
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
        os.environ["SANDBAR_TEST_CONSOLE_PORT"] = "21001"  # console only = half-specified
        explicit_ports(("temporal",))
        ok(False, "端口半指定应拒收")
    except StageError as e:
        ok("半指定" in str(e), "端口半指定拒收文案可辨")
    finally:
        os.environ.pop("SANDBAR_TEST_CONSOLE_PORT", None)

    # 4. service-set validation
    for bad in ("", "all", "temporal,dsh"):
        try:
            validate_service_set(bad)
            ok(False, "--services %r 应拒收" % bad)
        except StageError:
            ok(True, "--services %r 拒收" % bad)

    # 5. wait_temporal readiness discipline (the 260909 campaign-③ flake:
    # Docker Desktop's host forwarder accepts bare TCP while the server is
    # still starting, so a plain listener must NOT count as ready — only an
    # end-to-end CLI probe may pass the gate; and a closed port must fail
    # fast with an env-kind error). Uses a stub thread that accepts TCP but
    # never speaks gRPC; never touches docker.
    import threading
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()  # port now guaranteed closed
    try:
        wait_temporal(closed_port, timeout=1)
        ok(False, "拒连端口应判未就绪")
    except StageError as e:
        ok(e.kind == "env", "拒连端口 → env 红专名")
    stub = socket.socket()
    stub.bind(("127.0.0.1", 0))
    stub.listen(1)
    stub_port = stub.getsockname()[1]

    def _stub_accept():
        try:
            conn, _ = stub.accept()
            conn.close()
        except OSError:
            pass
    for _ in range(4):
        threading.Thread(target=_stub_accept, daemon=True).start()
    try:
        wait_temporal(stub_port, timeout=3)
        # Only acceptable when the CLI is missing everywhere (TCP fallback):
        # then the gate is documented to be TCP-only. With a CLI resolvable
        # the stub must be rejected.
        ok(resolve_temporal_cli() is None,
           "哑 TCP 桩未骗过就绪门（CLI 可得时不得仅凭 TCP 判就绪）")
    except StageError as e:
        ok(e.kind == "env", "哑 TCP 桩 → env 红（端到端探针生效）")
    finally:
        stub.close()

    print(("SELFTEST 全绿" if not fails else "SELFTEST %d 项红" % len(fails)))
    return EXIT_FAIL if fails else EXIT_OK


# ---------------------------------------------------------------- CLI

def _parse_opts(argv, i, opts):
    flags = {"--namespace": "namespace", "--fixtures-dir": "fixtures_dir",
             "--profile-dir": "profile_dir", "--profile-name": "profile_name",
             "--repo-dir": "repo_dir", "--nm-repo-dir": "nm_repo_dir",
             "--services": "_services", "--anchor-pid": "anchor_pid",
             "--lease-id": "lease_id"}
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
        elif a == "--dry-run":
            opts["dry_run"] = True
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
                state = do_up_public(project, services, clean_opts, timeout,
                                     keep=opts.get("keep", False))
            else:
                state = do_ensure(project, services, clean_opts, timeout, keep=opts.get("keep", False))
            print(json.dumps(state, ensure_ascii=False))
            return EXIT_OK
        if cmd == "hold":
            if not project:
                raise StageError("hold 缺 --project <名>", kind="usage")
            return cmd_hold(project, opts.get("anchor_pid"),
                            lease_id=opts.get("lease_id") or None,
                            keep=opts.get("keep", False))
        if cmd == "sweep":
            if project:
                raise StageError("sweep 不接受 --project（清扫是全锁根动作）", kind="usage")
            return cmd_sweep(dry_run=bool(opts.get("dry_run")))
        if cmd == "inventory":
            if project:
                raise StageError("inventory 不接受 --project（清点是全锁根+全机动作）",
                                 kind="usage")
            rpt = cmd_inventory()
            print(json.dumps(rpt, ensure_ascii=False))
            return EXIT_OK if rpt.get("ok") else EXIT_ENV
        if cmd == "down":
            if not project:
                raise StageError("down 缺 --project <名>", kind="usage")
            result = do_down(project)
            print(json.dumps(result, ensure_ascii=False))
            return EXIT_OK if not result["residue"] else EXIT_FAIL
        raise StageError("未知子命令：%s（可选 up/ensure/down/hold/sweep/inventory/selftest）"
                         % cmd, kind="usage")
    except StageError as e:
        print("STAGE_%s: %s" % (e.kind.upper(), e), file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("STAGE_INTERRUPT: 起台被中断（SIGINT）——就地清场", file=sys.stderr)
        return 130


def _signal_teardown(project_holder):
    """SIGTERM path: clean up whenever the project name is available (the
    signal leg of the multi-path reclamation)."""
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
    # The signal leg needs the project name — coarse approach: grab --project
    # from argv, then register the handler.
    _holder = {}
    if "--project" in sys.argv:
        idx = sys.argv.index("--project")
        if idx + 1 < len(sys.argv):
            _holder["project"] = sys.argv[idx + 1]
            _signal_teardown(_holder)
    sys.exit(main(sys.argv[1:]))
