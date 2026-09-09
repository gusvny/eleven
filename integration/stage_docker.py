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
                              a healthy stage is reused; a half-dead one is torn
                              down and rebuilt; --keep = never tear down or swap
                              a running stage (supply-stage semantics: on a
                              clash, re-check health and retry)
  down --project <name>      tear the stage down (down -v + zero-residue check);
                              idempotent, exits 0 when absent too
  selftest                   white-box self test (never touches docker):
                              forbidden-port exclusion / band locks / malformed
                              input rejection

Exit codes (three-state contract, integration/README.md):
  0=ok; 2=ENV_FAIL (docker absent / image absent / unhealthy boot / port band
  exhausted — the message names what is missing);
  3=environment conflict (an explicitly requested port is taken; do not fight
  it); 64=usage/malformed input (scenario-code bug class).

## Failure-mode handling (item by item against the old stage's failures, with the verdict)

| old-stage failure | this module's handling |
| --- | --- |
| port collision (pinned ports) | band flock atomic reservation + forbidden-zone exclusion + bind probe. The lock spans the whole "probe -> compose up -> healthy" window; by release time the daemon has really bound the port = TOCTOU closed |
| concurrent cross-talk | own compose project name + own container names + own volume prefix + band lock. Isolation granularity raised to container level |
| holder crash keeps the lock | the lock fd lives only in this process: process death = kernel closes the fd = the lock releases itself. If the container already bound the port before the crash, the next entrant's bind probe sees it busy and slides to the next band |
| teardown re-entry crash | down is idempotent: missing project / already-cleared containers both exit 0, safe to call three times in a row |
| detached process leaks | containers are held by the docker daemon, no host grandchild process tree; down kills everything — dockerization removes this failure surface |
| service start times out with no diagnosis | the timeout carries a `docker compose logs` tail (2000 bytes) + an in-place down -v cleanup before exiting |
| accidental production connect, fail-closed | hard forbidden set {3099,3199,7233,8233,17233,18233} + a post-boot self-check that the JSON ports are outside the production set |
| preset missing refuses to run | it does not: stay on the capture lane (stage and evidence semantics stay layered) |
| five-path terminal reclamation | CLI side: normal/error/timeout/SIGINT/SIGTERM all run the down -v cleanup |

State and locks:
  lock/state root = $SANDBAR_STAGE_LOCK_DIR > ~/.sandbar/test-stages > platform
  temp fallback (the fallback prints one stderr line, never silent).
  band-<n>.lock is the band lock;
  project-<name>.json is the running-stage state (ensure's reuse credential).
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


def state_busy_ports():
    """Ports held by running stages (state file present + containers present) —
    choose_band's second busy check. A bind probe cannot see the window where
    "the daemon bound it but the holder just died"; state + containers both
    present = the stage is alive, so leave its ports alone even when they look
    momentarily free. No containers = stale state (a boot that crashed before
    down) -> clean it up in place without blocking the band."""
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
                f.unlink()   # stale state: containers gone, the band is given up (crash-residue self-heal)
        except (OSError, ValueError):
            continue
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
    reports that honestly in the JSON afterwards)."""
    t0 = time.time()
    cli = resolve_temporal_cli()
    while time.time() - t0 < timeout:
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
                     % (timeout, port), kind="env")


def wait_console(port, timeout):
    t0 = time.time()
    url = "http://127.0.0.1:%d/" % port
    while time.time() - t0 < timeout:
        if http_ok(url):
            return
        time.sleep(1.0)
    raise StageError("console %ds 内未就绪（%s）" % (timeout, url), kind="env")


def stage_healthy(state):
    """ensure's reuse test: containers running + ports alive."""
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


def do_up(project, services_list, opts, timeout, lock_fd=None):
    """The boot itself (lock held by the caller; the failure path runs the
    down -v cleanup in place before re-raising)."""
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
    used = [k for k in ("temporal", "ui", "console") if k in ports
            and ("temporal" in services_list if k in ("temporal", "ui") else "dsh" in services_list)]
    state = {"project": project, "services": services_list, "namespace": env["SANDBAR_TEST_NAMESPACE"],
             "ports": {k: ports[k] for k in used}, "repo_dir": opts.get("repo_dir"),
             "ts": int(time.time()), "sa_registered": sa_registered, "sa_note": sa_note}
    write_state(project, state)
    return state


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


def do_down(project):
    """Tear a stage down: down -v + zero-residue check + clear the state file.
    Idempotent (succeeds when the project does not exist too)."""
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
    """Idempotent ensure: reuse a healthy stage; tear down and rebuild a
    half-dead one; --keep = never tear down a running stage (N3: on a clash,
    re-check health first)."""
    validate_project(project)
    state = read_state(project)
    if state and stage_healthy(state):
        state = dict(state)
        state["reused"] = True
        return state
    if state and keep and residue_containers(project):
        # --keep: running but unhealthy — do not tear it down (another lane may
        # be using it in the same window); report the environment red honestly
        raise StageError("供给台 %s 在跑但不健康（ports=%s）；--keep 语义不拆在跑台——"
                         "人工核查或去旗重跑" % (project, state.get("ports")), kind="env")
    if state:
        do_down(project)
    return do_up_public(project, services_list, opts, timeout)


def do_up_public(project, services_list, opts, timeout):
    """Full up flow: validate -> docker/image gates -> ports (explicit env or
    band allocation) -> boot."""
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
            os.close(lock_fd)   # the daemon has really bound the ports; releasing now leaves no conflict window (header trade-off)


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
