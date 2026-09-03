# -*- coding: utf-8 -*-
"""t260903-10 集成场景共享夹具（不带 sc_ 前缀=共享代码，不登记场景清单）。

只服务本票场景：安装器入口定位、临时 HOME 隔离、fixture 仓注入、假 temporal、
stub 进程、ps 观测缝桩、端口 guard。铁律：
- 场景绝不向真环境（3099/7233/8233 现有占用者）发任何信号——运行时场景一律走
  安装器公共旗标 --server-port/--ui-port 用自选空闲端口演练，与真端口零接触；
- 一切状态写临时 HOME；stub 进程收尾必杀（TERM→KILL 兜底），临时目录必清；
- 进程观测缝：安装器读 argv/ppid 走 runtime.proc_cmdline/proc_ppid（/proc 或
  ps 兜底）。本沙箱禁 /bin/ps（exec 拒绝），故经 PATH 前置注入 ps 桩按场景
  登记表供数——桩只供「内核/真 ps 本会告诉安装器的数字」（argv 伪装面与 ppid），
  存活与信号判定仍全走真 os.kill：安装器对 ppid 做真实 pid_state 交叉核对，
  桩给不出能让死人变活或活人变死的数字。

t260903-11 arbitrate 环境无关化重造（原夹具三处前提在本环境不成立，均属测试集
前提错而非实现错）：
① 原夹具把 stub 塞 PATH 期待安装器按 PATH 找 temporal——实现按
   <root>/server/dsh/temporal-poc/bin/temporal 定位，PATH 注入是无效缝；
   改走公共旗标 --root 注入 fixture 仓（temporal 桩落 fixture 仓内）；
② 原夹具占死 7233/8233——真环境常态占用（引擎自己就在跑），运行时三场景
   在调度环境永远 exit 3；改自选空闲端口（安装器旗标本就声明端口可换）；
③ 原幂等断言数全机 ps 的 start-dev 进程数——机器全局断言（真环境自带
   start-dev 即假红）且本沙箱禁 ps；改 lsof 监听者 + stub 自报 pid 双观测。

argv 伪装口径：POSIX 下 Popen(argv, executable=X) 的 ps command 面=argv，
真身=X；stub 内部一律从 env 读参数（sys.argv 属 argv 面，会被伪装占用）。
"""
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT_CONSOLE = 3099   # 只可探测，绝不可 spawn/kill/重启（红线，场景层零触碰）

# 断言口径：运行时场景在自选空闲端口上演练；所选端口万一被占=环境冲突（exit 3），
# 不与任何在位者对抗。
ENV_CONFLICT_EXIT = 3
MISSING_EXIT = 2


class Fail:
    """行式断言收集器：失败输出自明（执行器只取末 6 行 tail）。"""

    def __init__(self, title):
        self.title = title
        self.fails = []

    def check(self, cond, msg):
        print(("ok    " if cond else "FAIL  ") + msg, flush=True)
        if not cond:
            self.fails.append(msg)
        return cond

    def bail(self, msg, code=1):
        print("FAIL  %s" % msg, flush=True)
        sys.exit(code)

    def finish(self):
        if self.fails:
            print("FAIL  %s：%d 项断言未过（首因：%s）" % (self.title, len(self.fails), self.fails[0]), flush=True)
            sys.exit(1)
        print("PASS  %s" % self.title, flush=True)
        sys.exit(0)


def port_open(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(1.0)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def pick_free_ports(n=2):
    """自选空闲端口：bind(0) 预占后统一释放（后取的不会撞先取的）；
    释放到真正使用之间的窗口由 guard_runtime_ports 兜底（冲突=exit 3）。"""
    ports, socks = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        ports.append(s.getsockname()[1])
        socks.append(s)
    for s in socks:
        s.close()
    return ports


def guard_runtime_ports(fail, ports):
    """运行时场景前置：所选演练端口必须空闲；被占=环境冲突，打印占用者后 exit 3。"""
    for p in ports:
        if port_open(p):
            fail.bail(
                "环境冲突 exit%d：%d 已被占用（pid=%s）。本场景要求独占演练端口，"
                "不与任何在位者对抗——自选端口仍撞车属环境异常，请重跑。"
                % (ENV_CONFLICT_EXIT, p, _pid_of_port(p) or "?"), ENV_CONFLICT_EXIT)


def _pid_of_port(port):
    try:
        out = subprocess.run(["lsof", "-ti", "tcp:%d" % port],
                             capture_output=True, text=True, timeout=5).stdout
        return out.strip().splitlines()[0] if out.strip() else None
    except Exception:
        return None


def lsof_listeners(port):
    """端口监听者 pid 列表（lsof -sTCP:LISTEN；lsof 缺失/失败=空表，调用方自行判）。"""
    try:
        out = subprocess.run(["lsof", "-ti", "tcp:%d" % port, "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5).stdout
        return sorted({int(x) for x in out.split() if x.strip().isdigit()})
    except Exception:
        return []


def find_installer_entry():
    """安装器入口定位（review 附条件1 推荐落点）；返回路径或 None。

    bin/sandbar 是禁用落点（.gitignore `bin/` 吞交付物），即便文件物理存在也不认
    ——它进不了 commit，场景对它红就是对抗面。
    """
    for rel in ("sandbar", os.path.join("scripts", "sandbar")):
        p = os.path.join(REPO, rel)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def require_installer_entry(fail):
    p = find_installer_entry()
    if p is None:
        fail.bail(
            "安装器入口不存在（候选 ./sandbar 或 ./scripts/sandbar 均缺或不可执行）。"
            "implement 未交付或落点变更；bin/sandbar 为禁用落点（.gitignore bin/ 吞交付物，review 附条件1）。",
            MISSING_EXIT)
    return p


def state_home(tmp):
    """HOME 桩下的安装状态家（~/.sandbar 口径）：安装器缺省路径正好落这里。"""
    return os.path.join(tmp, ".sandbar")


def make_temp_home():
    """临时 HOME + env（状态真源 ~/.sandbar/run 全随 HOME 桩隔离）。"""
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26090310-")
    env = dict(os.environ)
    env["HOME"] = tmp
    env.pop("XDG_CONFIG_HOME", None)
    return tmp, env


def _write_stub(path, body):
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, 0o755)


# ---------- ps 观测缝（沙箱禁 /bin/ps 的供数桩） ----------

PS_STUB_SRC = '''#!/usr/bin/env python3
"""ps 观测缝桩：按登记表（<SANDBAR_PS_DIR>/<pid>.cmd|.ppid）供数；
未登记 pid 按真 ps「无此进程」语义 exit 3 无输出。"""
import os, sys
args = sys.argv[1:]
rec = os.environ["SANDBAR_PS_DIR"]
pid = args[args.index("-p") + 1] if "-p" in args else None
if pid is None:
    sys.exit(2)
what = "cmd"
for i, a in enumerate(args):
    if a == "-o" and i + 1 < len(args):
        what = "ppid" if "ppid" in args[i + 1] else "cmd"
f = os.path.join(rec, "%s.%s" % (pid, what))
if not os.path.isfile(f):
    sys.exit(3)
sys.stdout.write(open(f).read())
sys.exit(0)
'''


def ps_seam(tmp):
    """构造 PATH 前置的 ps 观测缝。返回 (psbin, psrec)；
    场景把 psbin 前插进 CLI 的 PATH、SANDBAR_PS_DIR=psrec，用 ps_record 登记。"""
    psbin = os.path.join(tmp, "psbin")
    psrec = os.path.join(tmp, "psrec")
    os.makedirs(psbin, exist_ok=True)
    os.makedirs(psrec, exist_ok=True)
    _write_stub(os.path.join(psbin, "ps"), PS_STUB_SRC)
    return psbin, psrec


def ps_record(psrec, pid, cmdline=None, ppid=None):
    """登记一个 pid 的观测面（cmdline 伪装串 / ppid 数字）。"""
    if cmdline is not None:
        with open(os.path.join(psrec, "%d.cmd" % pid), "w") as f:
            f.write(cmdline + "\n")
    if ppid is not None:
        with open(os.path.join(psrec, "%d.ppid" % pid), "w") as f:
            f.write("%d\n" % int(ppid))


def attach_ps_seam(env, psbin, psrec):
    """把观测缝装进一份 env：psbin 前插 PATH + 登记表指路。"""
    env["PATH"] = psbin + os.pathsep + env["PATH"]
    env["SANDBAR_PS_DIR"] = psrec
    return env


def cli_args(fx, server_port, ui_port, *rest):
    """CLI 公共旗标组装：--root 注入 fixture 仓 + 演练端口（不传 --home，
    状态家随 HOME 桩走缺省 ~/.sandbar 口径）。"""
    return ["--root", fx, "--server-port", str(server_port),
            "--ui-port", str(ui_port)] + list(rest)


# ---------- fixture 仓（--root 注入缝） ----------

FAKE_TEMPORAL_SRC = '''#!/usr/bin/env python3
"""fixture temporal 桩：start-dev=解析 --port/--ui-port 绑定+TERM 感知
（端口也可经 SANDBAR_STUB_PORTS 环境变量给，supervisor 子进程无 argv 端口时用）；
operator namespace update=绿、describe=吐 876000h（§2-#8 校正复核契约）。"""
import os, signal, socket, sys, time

stamp = os.environ["SANDBAR_STUB_STAMP"]
argv = sys.argv[1:]
if argv[:2] == ["server", "start-dev"]:
    def h(*a):
        open(stamp, "w").write(str(time.time()))
        sys.exit(0)
    signal.signal(signal.SIGTERM, h)
    signal.signal(signal.SIGINT, h)
    ports = []
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            ports.insert(0, int(argv[i + 1]))
        if a == "--ui-port" and i + 1 < len(argv) and len(ports) < 2:
            ports.append(int(argv[i + 1]))
    if len(ports) < 2:
        ports = [int(x) for x in os.environ.get("SANDBAR_STUB_PORTS", "7233,8233").split(",")]
    # sock 引用必须持住：循环变量复用会让先绑的 socket 被 GC 关闭（fd 提前回收，
    # 监听静默消失——t260903-11 实测踩中）
    socks = []
    for p in ports[:2]:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", p))
        s.listen(16)
        socks.append(s)
    open(stamp + ".alive", "w").write(str(os.getpid()))
    sys.stdout.write("ready\\n")
    sys.stdout.flush()
    time.sleep(600)
elif argv[:2] == ["operator", "namespace"]:
    if "update" in argv:
        sys.exit(0)
    if "describe" in argv:
        sys.stdout.write("namespace default retention: 876000h\\n")
        sys.exit(0)
    sys.exit(1)
else:
    sys.stderr.write("fake temporal: unknown argv %r\\n" % (argv,))
    sys.exit(2)
'''

# 不带 temporal 伪装面的朴素监听桩（半 C「谓词不命中」用：命令行不像 start-dev）
# sock 引用持进列表：循环变量复用会让先绑的 socket 被 GC 关闭（fd 提前回收）
PLAIN_LISTEN_SRC = (
    "import os,signal,socket,sys,time\n"
    "stamp=os.environ['SANDBAR_STUB_STAMP']\n"
    "def h(*a):\n"
    "    open(stamp,'w').write(str(time.time()))\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGTERM,h); signal.signal(signal.SIGINT,h)\n"
    "ports=[int(x) for x in os.environ.get('SANDBAR_STUB_PORTS','7233,8233').split(',')]\n"
    "socks=[]\n"
    "for p in ports:\n"
    "    s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "    s.bind(('127.0.0.1', p)); s.listen(16); socks.append(s)\n"
    "open(stamp+'.alive','w').write(str(os.getpid()))\n"
    "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
    "time.sleep(600)\n"
)

TERM_STUB_SRC = (
    "import signal,sys,time,os\n"
    "stamp=os.environ['SANDBAR_STUB_STAMP']\n"
    "def h(*a):\n"
    "    open(stamp,'w').write(str(time.time()))\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGTERM,h); signal.signal(signal.SIGINT,h)\n"
    "open(stamp+'.alive','w').write(str(os.getpid()))\n"
    "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
    "time.sleep(600)\n"
)

# double-fork 化的 TERM 感知 stub：真身=setsid 后被 launchd 收养的孙进程
# （与真 worker.py --daemon 同拓扑）。必须 daemonize 的原因：若 stub 以场景进程
# 为父，安装器 TERM 它后由场景进程收尸——场景阻塞在 run_cli 上不 waitpid，
# stub 成 zombie，安装器 os.kill(pid,0) 探到的正是 zombie，只能如实报
# 「SIGKILL 后仍未退出——需人工介入」（down rc=1 是拓扑伪影不是实现错）。
WORKER_DAEMON_SRC = (
    "import os,signal,sys,time\n"
    "stamp=os.environ['SANDBAR_STUB_STAMP']\n"
    "pidout=os.environ['SANDBAR_DAEMON_PID_OUT']\n"
    "pid=os.fork()\n"
    "if pid==0:\n"
    "    os.setsid()\n"
    "    def h(*a):\n"
    "        open(stamp,'w').write(str(time.time()))\n"
    "        sys.exit(0)\n"
    "    signal.signal(signal.SIGTERM,h); signal.signal(signal.SIGINT,h)\n"
    "    open(stamp+'.alive','w').write(str(os.getpid()))\n"
    "    sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
    "    time.sleep(600)\n"
    "else:\n"
    "    open(pidout,'w').write(str(pid))\n"
    "    sys.exit(0)\n"
)


def spawn_daemon_term_stub(tmp, name, env=None):
    """拉起 WORKER_DAEMON_SRC，返回 (孙进程 pid, stamp 路径)；孙进程由 launchd
    收养，退出即被收尸，安装器 pid_state 口径能看到它真死。"""
    stamp = os.path.join(tmp, name)
    src = os.path.join(tmp, name + ".py")
    pidout = os.path.join(tmp, name + ".daemon-pid")
    _write_stub(src, WORKER_DAEMON_SRC)
    e = {**os.environ, **(env or {}), "SANDBAR_STUB_STAMP": stamp,
         "SANDBAR_DAEMON_PID_OUT": pidout}
    launcher = Proc([sys.executable, src], sys.executable, e)
    deadline = time.time() + 8
    pid = None
    while time.time() < deadline:
        if os.path.exists(pidout):
            pid = int(open(pidout).read().strip())
            break
        if not launcher.alive():
            break
        time.sleep(0.05)
    return pid, stamp


def make_fixture_root(tmp, mode):
    """fixture 仓：<tmp>/fxroot，只长安装器 --root 注入面需要的最小树。

    mode：'ok'=bin/temporal 可用桩；'crash'=秒退桩；'absent'=不落 temporal
    （工具面缺失注入）。worker 工具面（.venv/worker.py）一律不落——up 的
    worker 段走显式黄条跳过（非静默，输出可见），worker 进程由场景自管
    （down 时序观测需要 TERM 感知 stub）。version 面不落：安装器 import
    version 先查 <root>/server 再回落入口已挂的仓内 server/，自然用真模块
    +真 VERSION（版本面不是运行时场景的考察对象）。
    """
    fx = os.path.join(tmp, "fxroot")
    poc = os.path.join(fx, "server", "dsh", "temporal-poc")
    os.makedirs(os.path.join(poc, "data"), exist_ok=True)
    bin_dir = os.path.join(poc, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    if mode == "ok":
        _write_stub(os.path.join(bin_dir, "temporal"), FAKE_TEMPORAL_SRC)
    elif mode == "crash":
        _write_stub(os.path.join(bin_dir, "temporal"),
                    "#!/bin/sh\necho 'fake temporal: boom' >&2\nexit 1\n")
    # 'absent'：bin 留空
    return fx


def wait_pid_dead(pid, timeout=10):
    """轮询到 pid 消失（os.kill 语义；孤儿 stub 退出后由 launchd/init 收尸）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.1)
    return False


class Proc:
    """可观测 stub 进程：alive / TERM 感知 stamp。"""

    def __init__(self, argv, executable, env):
        self.proc = subprocess.Popen(argv, executable=executable, env=env, cwd=REPO,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.pid = self.proc.pid

    def alive(self):
        return self.proc.poll() is None

    def wait_ready(self, timeout=8):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.alive():
                return False
            try:
                line = self.proc.stdout.readline()
            except Exception:
                return False
            if line.strip() == "ready":
                return True
        return False

    def kill(self):
        if self.alive():
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


def spawn_term_stub(tmp, name, env=None):
    """TERM 感知朴素 stub（stamp 写收 TERM 时刻）；供 worker 角色预置。"""
    stamp = os.path.join(tmp, name)
    src = os.path.join(tmp, name + ".py")
    _write_stub(src, TERM_STUB_SRC)
    e = {**os.environ, **(env or {}), "SANDBAR_STUB_STAMP": stamp}
    # executable=真身给 sys.executable：stub 是无 shebang 的 python 源，
    # 直接 execve 会 Exec format error
    return Proc([sys.executable, src], sys.executable, e)


def wait_stamp(stamp, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(stamp):
            try:
                return float(open(stamp).read().strip())
            except Exception:
                pass
        time.sleep(0.1)
    return None


def wait_port(port, want_open, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port) == want_open:
            return True
        time.sleep(0.2)
    return False


def run_cli(entry, args, env, timeout=90):
    """跑安装器 CLI（cwd=仓库根）。返回 (rc, out)。"""
    p = subprocess.run([entry] + list(args), env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def cleanup(tmpdir, *procs):
    for pr in procs:
        try:
            pr.kill()
        except Exception:
            pass
    shutil.rmtree(tmpdir, ignore_errors=True)
