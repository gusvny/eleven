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
  selftest                   white-box self test (never touches docker):
                              forbidden-port exclusion / band locks / lease
                              criteria / malformed input rejection

Exit codes (three-state contract, integration/README.md):
  0=ok; 2=ENV_FAIL (docker absent / image absent / unhealthy boot / port band
  exhausted / capacity full past queueing budget — the message names what is
  missing, for capacity the live-lease manifest with holder pid+ticket);
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

State and locks (t260910-12 lease semantics):
  lock/state root = $SANDBAR_STAGE_LOCK_DIR > ~/.sandbar/test-stages > platform
  temp fallback (the fallback prints one stderr line, never silent).
  band-<n>.lock is the band lock;
  capacity-0.lock is the满员闸 global lock (count + placeholder written inside
  ONE flock critical section — count-then-claim is atomic, no oversell);
  ensure-<project>.lock serializes same-project cold boots;
  project-<name>.json is the LEASE record — the single liveness fact:
    {lease_id, holder:{ticket,pid}, anchor_pid, state: booting|up|downing,
     ports, heartbeat_ts, ttl_sec, container_ids, ...}
  Reclaim criterion (the ONLY one): lease expired (now - heartbeat > TTL) AND
  holder process does not exist. No docker ps sampling, no mtime freshness
  grace, no foreign-activity yielding — every "guess whether the other guy is
  dead" heuristic is gone (all three failed in concurrent windows: run
  L/M/O/Q/U/X recorded in the old code comments).

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
BAND_BASE, BAND_STEP, BAND_COUNT = 21000, 10, 400
SLOT_OFFSET = {"console": 0, "temporal": 1, "ui": 2}

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
    """满员闸：活租约并发上限。档位有 400 个，真实约束是 daemon 面压力
    （260910 实证 herd ~4-6 即产品红）——闸的职责是排队而不是硬挤。"""
    return int(os.environ.get("SANDBAR_STAGE_MAX_STAGES", 12))


def hold_wait_s():
    """双向有界握手预算（秒）：ensure 等 hold 写就绪 pid 文件 / hold 等租约
    出现，都以此为帽（R1'a：Popen 返回 ≠ 子进程真起来了）。"""
    return float(os.environ.get("SANDBAR_STAGE_HOLD_WAIT_S", 10))


PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
DEFAULT_TIMEOUT = 600          # health-wait ceiling (covers the measured dsh container first-boot npm i + apt budget)
_STOP_TIMEOUT = 120            # compose down ceiling

EXIT_OK, EXIT_ENV, EXIT_CONFLICT, EXIT_FAIL, EXIT_USAGE = 0, 2, 3, 1, 64


class StageError(Exception):
    """Stage error carrying exit-code semantics: kind ∈ env/conflict/usage."""

    def __init__(self, message, kind="env"):
        super().__init__(message)
        self.kind = kind
        self.exit_code = {"env": EXIT_ENV, "conflict": EXIT_CONFLICT, "usage": EXIT_USAGE}[kind]


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
    base = BAND_BASE + band_index * BAND_STEP
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


def holder_pid(lease):
    """Extract holder.pid, tolerating missing/malformed holder blocks (→ None
    = un-judgeable, treated as dead downstream)."""
    try:
        pid = (lease or {}).get("holder", {}).get("pid")
        return int(pid) if pid is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def new_lease(project, holder_pid, services, ticket=None, anchor_pid=None, ttl=None,
              lease_id=None):
    """A complete occupancy granted at claim time (ticket spec ①): holder =
    ticket+pid, state=booting, TTL + fresh heartbeat. Written atomically inside
    the caller's flock critical section. lease_id injectable so the hold leg
    can be spawned knowing the id it must find (handshake)."""
    now = time.time()
    return {
        "lease_id": lease_id or ("%s-%d-%s" % (project, int(now * 1000), os.urandom(4).hex())),
        "project": project,
        "holder": {"ticket": ticket or os.environ.get("SANDBAR_STAGE_TICKET") or "unknown",
                   "pid": int(holder_pid)},
        "anchor_pid": int(anchor_pid) if anchor_pid else None,
        "state": "booting",
        "services": list(services),
        "ports": {},
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
    """满员排队闸（ticket spec ③; review R4 atomicity): count live leases and
    claim the slot (write the placeholder lease — the placeholder IS the
    count) inside ONE global flock critical section, so N concurrent entrants
    can never all count N-1 and all enter. Full = queue honestly: sleep-poll
    outside the lock, re-enter to reclaim-then-count, until budget out. Never
    steals, never fakes; timeout = honest env red carrying the live-lease
    manifest (review R2 format)."""
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
                    raise StageError("满员闸锁等待超时（%ds）：capacity-0.lock 被"
                                     "长期持有——查残留进程" % timeout, kind="env")
                time.sleep(0.5)
                continue
            try:
                live = enumerate_leases()
                if len(live) < max_stages():
                    write_lease(project, lease)   # 占位即计数（state=booting）
                    return lease
                manifest = live_lease_manifest(live)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
            if time.time() - t0 >= timeout:
                raise StageError(
                    "起台面满员：并发上限 %d 已用尽，排队 %ds 未等到释放——"
                    "当前活租约清单（含 holder pid/票号，供人工核对 pid 复用）：\n%s"
                    % (max_stages(), timeout, manifest), kind="env")
            time.sleep(1.0)
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
        stopping["flag"] = True     # ⑤：心跳循环下轮退出，不在 handler 里做任何 IO/拆台
        sys.exit(130)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _on_signal)

    # ⓪ 有界等待租约出现（R1'a）：预算=起台者（本 hold 的原始父进程）存活期
    # ——容量排队（capacity_acquire）可远超固定秒数，hold 不得提前自退。先读
    # 租约再判起台者死：租约已落即算数（主循环的 ③' 起台孤儿腿接管后续），
    # 只有「租约确实未落且起台者已死」才为一具尸体自退。
    booter_pid = os.getppid()   # 起台 CLI：③' 孤儿起台判据同款
    lease = None
    while True:
        if stopping["flag"]:
            return 130
        lease = read_lease(project)
        if isinstance(lease, dict) and holder_pid(lease) == hold_pid:
            break
        if not pid_alive(anchor_pid) and not keep:
            return 0   # 锚死且租约未落：调用方树没了，无可清理——静默退
        # keep 台例外：锚死≠弃台（常驻基建锚=短命 shell），继续等起台者落租约
        if not pid_alive(booter_pid):
            # 起台者死且租约未落=为一具尸体起租（keep/非 keep 同判——起台者
            # 一死 boot 永不可完成，keep 也不等）
            print("STAGE_ENV: 起台进程 %d 已亡且租约未落——hold 自退，绝不带空"
                  "租约滞留" % booter_pid, file=sys.stderr)
            return EXIT_ENV
        time.sleep(0.2)
    if lease.get("lease_id") != lease_id and lease_id:
        # ensure 用它自己的 lease_id 建了租约——本 hold 是孤儿握手残留
        print("STAGE_ENV: hold lease_id 与租约不符——握手残留自退", file=sys.stderr)
        return EXIT_ENV
    if not lease_id:
        lease_id = lease["lease_id"]
    # keep 的权威面=租约记录（argv 是起台注入；翻面/心跳读改写全链路透传）
    keep = keep or bool(lease.get("keep"))

    start_ts = float(lease.get("ts") or time.time())
    while True:
        if stopping["flag"]:
            return 130                                                       # ⑤
        if not pid_alive(anchor_pid) and not keep:                           # ③
            print("[hold] 锚进程 %d 已亡——调用方树消失，回收孤儿台" % anchor_pid,
                  file=sys.stderr)
            try:
                do_down(project, harvest_hold=False)
            except Exception as e:
                print("[hold] 孤儿台回收失败（%s：%s）——台交判死回收" %
                      (type(e).__name__, e), file=sys.stderr)
                release_lease(project)
            try:
                pidfile.unlink()
            except FileNotFoundError:
                pass
            return 0
        # keep 台：锚死跳过回收（常驻基建例外）——心跳继续，台交显式 down /
        # ⑥帽 / ⑦崩处置；锚死+心跳停的组合态由 ⑥ 帽封顶损害
        lease = read_lease(project)
        if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:  # ①
            try:
                pidfile.unlink()
            except FileNotFoundError:
                pass
            return 0
        if lease.get("state") == "booting" and not pid_alive(booter_pid):     # ③'
            print("[hold] 起台进程 %d 已亡而租约仍 booting——起台孤儿，回收" % booter_pid,
                  file=sys.stderr)
            try:
                do_down(project, harvest_hold=False)
            except Exception as e:
                print("[hold] 起台孤儿回收失败（%s：%s）——台交判死回收" %
                      (type(e).__name__, e), file=sys.stderr)
                release_lease(project)
            return 0
        if lease.get("state") not in ("booting", "up"):                       # ②
            return 0
        if time.time() - start_ts > max_hold_s():                             # ⑥
            print("STAGE_HOLD_CAP: hold 超过最大持有期 %ds 自退——台留给租约过期"
                  "回收或人工 down（提示：人工直调 up 的台锚=你的 shell，属明示"
                  "行为；可调小 SANDBAR_STAGE_MAX_HOLD_S 或显式 down）" % max_hold_s(),
                  file=sys.stderr)
            return 6
        if holder_pid(lease) != hold_pid:                                     # ④
            print("STAGE_ENV: 租约 holder 变更（pid=%s）——外来租约，停写自退"
                  % holder_pid(lease), file=sys.stderr)
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
        "SANDBAR_STAGE_LOCK_DIR=%s 下的锁锚" % (BAND_COUNT, BAND_BASE,
                                                BAND_BASE + BAND_COUNT * BAND_STEP, lock_root()),
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


def compose_env(project, services, ports, opts):
    """Env for rendering compose (the SANDBAR_TEST_* knobs of
    docker-compose.test.yml)."""
    env = dict(os.environ)
    env["SANDBAR_TEST_TEMPORAL_NAME"] = "%s-temporal" % project
    env["SANDBAR_TEST_DSH_NAME"] = "%s-dsh" % project
    env["SANDBAR_TEST_NAMESPACE"] = opts.get("namespace") or "suyou-test"  # naming-compat
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
    for name in ("ProjectKey", "EpicCode"):
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
                link.symlink_to("../../plugins/%s" % d)
                made += 1
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


def _flip_lease_up(project, lease, ports, services_list, env, opts,
                   sa_registered, sa_note):
    """boot 完成 → 翻 state=up（原子写，写前保 lease_id/holder 不变）。CLI 翻面
    自带一拍新鲜心跳，此后心跳由 hold 腿接管；container_ids 在此定格，作为
    同租约二次 up 幂等复用的证据面（验收④：容器 id 不变=未被重建）。"""
    lease = lease if isinstance(lease, dict) and lease.get("lease_id") else (
        read_lease(project) or new_lease(project, holder_pid=os.getpid(),
                                         services=services_list))
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
    if not docker_present():
        release_lease(project)
        raise StageError("docker 不可用（docker info 失败）——拆台需要 docker", kind="env")
    env = dict(os.environ)
    env.setdefault("SANDBAR_TEST_TEMPORAL_NAME", "%s-temporal" % project)
    env.setdefault("SANDBAR_TEST_DSH_NAME", "%s-dsh" % project)
    compose_cmd(project, ["down", "-v", "--remove-orphans", "--timeout", "30"],
                env, timeout=_STOP_TIMEOUT)
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


def _boot_new_stage(project, services_list, opts, timeout, cold_cleanup=False,
                    keep=False):
    """The full boot sequence, shared by `up` and ensure's cold path:
    gates → (idempotent cold cleanup) → hold leg → capacity claim → ports
    (explicit env or band) → boot → flip state=up. Every failure path releases
    the lease and reaps the hold — no half-claimed occupancy is ever left
    (R1'a; the hold also self-exits via its bounded lease-wait as a backstop).
    keep=True：常驻基建台——租约记 keep 标，hold 腿据此禁③锚死回收（锚=
    短命调用方 shell）；其余终态与判死回收判据原样，绝不引入存活启发式。"""
    _gates(services_list)
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
        lease = new_lease(project, holder_pid=hold_proc.pid, services=services_list,
                          anchor_pid=os.getppid(), lease_id=lease_id)
        if keep:
            lease["keep"] = True   # 占位/心跳读改写全链路透传（常驻标记随租约存续）
        capacity_acquire(project, lease, timeout)   # R4：数+占位同一把全局锁
        try:
            ports = explicit_ports(services_list)
            lock_fd = None
            try:
                if ports is None:
                    _, ports, lock_fd = choose_band(ephemeral_range())
                lease["ports"] = dict(ports)
                write_lease(project, lease)   # 择带结果回填（仍 state=booting，占位计数不变）
                opts = dict(opts)
                opts["ports"] = ports
                return do_up(project, services_list, opts, timeout,
                             lock_fd=lock_fd, lease=lease)
            finally:
                if lock_fd is not None:
                    os.close(lock_fd)   # daemon 已真绑端口，释放无冲突窗（header trade-off）
        except BaseException:
            release_lease(project)   # hold 见租约消失 → ①自退；外层收割兜底
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
        st = read_lease(project)
        if lease_reusable(st):
            return _reused(st)
        if isinstance(st, dict) and st.get("state") == "booting" and not lease_dead(st):
            # 他人在起台：不持锁等待（R5），绝不并发再起
            st = _wait_booting(project, fd, deadline)
            if lease_reusable(st):
                return _reused(st)
        if isinstance(st, dict) and st.get("state") == "up" and not lease_dead(st):
            # 租约过期但 holder pid 仍在：不对抗（判据唯一化），点名交人工
            raise StageError(
                "供给台 %s 租约过期但 holder pid=%s 仍在（心跳停更）——疑似 pid 复用"
                "或 holder 僵死；绝不硬拆，人工核查后 down（可查 hold-%s.log）"
                % (project, holder_pid(st), project), kind="env")
        if keep and residue_containers(project):
            # --keep：无主容器在跑（租约已死）——不拆别人的台，诚实环境红
            raise StageError("供给台 %s 有无主容器在跑（租约已死/缺失）——--keep 语义"
                             "不拆在跑台，人工核查或去旗重跑" % project, kind="env")
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
    ok(all(21000 <= p < BAND_BASE + BAND_COUNT * BAND_STEP for p in all_ports),
       "档位端口全部落在 %d~%d 预留窗内" % (BAND_BASE, BAND_BASE + BAND_COUNT * BAND_STEP))
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
        if cmd == "down":
            if not project:
                raise StageError("down 缺 --project <名>", kind="usage")
            result = do_down(project)
            print(json.dumps(result, ensure_ascii=False))
            return EXIT_OK if not result["residue"] else EXIT_FAIL
        raise StageError("未知子命令：%s（可选 up/ensure/down/hold/selftest）" % cmd, kind="usage")
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
