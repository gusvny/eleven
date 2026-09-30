#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_engine_ops_offline.py —— `server/tools/engine_ops.py` 的离线面（宿主 260930 当面令）。

intent（守护的用户可感知行为）：**推票前「谁在服务 / 吃哪份代码 / 漂没漂」三问必须
离线也答得出来，且答不出时具名（不静默、不假绿）**。

场景构造（全在场景私有 tmp，零生产接触）：
  · 夹具仓：`main` 上一次提交（含 `server/engine/*.py`、`server/tools/verify_lane.py`）；
  · 泳道：`<夹具>/.lane/<tid>` 作为 branch `lane/<tid>` 的 worktree，钉在那一刻；
  · 之后 **main 再落一个引擎修 + 一个 .md**（⇒ 泳道落后、代码面漂移、文档面不告警）；
  · 一条**活进程**的 pid 写进夹具 `data/worker.pid`（测重启守卫的「活进程拒启」）；
  · Temporal 打到一个**死端口**（127.0.0.1:1）——依赖它的面必须**具名 ENV_FAIL**，
    不许静默 skip、不许假装验过。

判据：
  L1 `drift`（离线）= 告警退出 1，且逐条点名：泳道缺哪些**代码**文件（.md 单列不告警）、
     泳道 worker 是否 stale（指纹基准=旁车 meta 的 ts）、活 poller 数**不可得**要明说
     「不能证明恰好一颗 ⇒ 不许推票」；
  L2 `.md` 不误报：文档漂移进 `doc_files_in_main_not_in_lane` 而**不**进告警面；
  L3 `sync --dry-run` 只读：报出会并进来的文件，且**不动泳道**（HEAD 与 merge 提交数不变）；
  L4 `who`（Temporal 不可达）= 退出 2 + 具名原因（事件历史只有 server 有，绝不假装）；
  L5 `sync`（非 dry-run，Temporal 不可达）= 退出 2 + 具名原因（**不退化手写 git merge**）；
  L6 `restart --scope central`（夹具 pidfile 指向活进程）= 拒绝启动（退出 1）且具名 pid，
     且**没有**产生后台进程/日志（没 fork）——守卫先于一切；
  L7 `workers`（Temporal 不可达）= 队列 poller 面**不可得**要具名，且不得把「不可得」当作
     「0 颗」静默放过（本工具的 workers 在告警面里点名）。

三态：0=绿；1=被测红；2=环境红（git/python 缺件）。零生产接触：`--repo` 指向夹具仓、
`--host` 指死端口、pidfile/日志全在夹具 tmp；不碰 3099、不碰真仓 `.lane/`。
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOL = os.path.join(REPO, "server", "tools", "engine_ops.py")
PY = os.path.join(REPO, "server", "engine", ".venv", "bin", "python")
DEAD_HOST = "127.0.0.1:1"
TID = "t-offline-ops-%d" % os.getpid()
ENGINE_FILES = ("server/engine/agent_activities.py", "server/engine/dev_lane.py",
                "server/engine/light_lane.py", "server/engine/shared.py",
                "server/tools/verify_lane.py")


def sh(argv, cwd=None, timeout=120):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def git(args, cwd):
    return sh(["git", "-C", cwd] + list(args))


def run_tool(*args, repo=""):
    argv = [PY, TOOL]
    if repo:
        argv += ["--repo", repo]
    argv += list(args)
    p = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=REPO)
    out = (p.stdout or "").strip()
    try:
        payload = json.loads(out) if out else {}
    except ValueError:
        payload = {"_raw": out[:400]}
    return p.returncode, payload, (p.stderr or "").strip()


class Fail:
    def __init__(self, title):
        self.title = title
        self.fails = []
        self.n = 0

    def check(self, cond, msg):
        self.n += 1
        print(("ok    " if cond else "FAIL  ") + msg, flush=True)
        if not cond:
            self.fails.append(msg)
        return bool(cond)

    def finish(self):
        print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (self.n - len(self.fails),
                                                           len(self.fails)), flush=True)
        if self.fails:
            print("FAIL  %s：%d 项断言未过（首因：%s）"
                  % (self.title, len(self.fails), self.fails[0]), flush=True)
            sys.exit(1)
        print("PASS  %s" % self.title, flush=True)
        sys.exit(0)


FIXTURE_SUPERVISOR_SRC = r"""
# 夹具 supervisor（= console temporal-tools supervisor 的**忠实替身**，keepalive 式）：
# 持续看 pidfile —— 里面那颗死了/缺位 ⇒ 起一颗真 worker（--daemon，同 pidfile/logfile，
# 私有队列）。为什么夹具可以起 worker：它只轮询私有队列、只写夹具 tmp，不碰任何生产路径；
# 宿主纠正的是「**工具**不该自己起」，不是「测试不许有 supervisor 替身」。
import os, subprocess, sys, time
repo, pf, log, py, host, queue, sidecar = sys.argv[1:8]

def _pid():
    try:
        return int(open(pf).read().strip())
    except Exception:
        return 0

def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

env = dict(os.environ)
env.update({"SANDBAR_TARGET_HOST": host, "SANDBAR_NAMESPACE": "default",
            "SANDBAR_TASK_QUEUE": queue, "SANDBAR_TASK_QUEUES": queue})
for k in ("SANDBAR_WORKER_META", "SANDBAR_WATCH_WORKFLOW", "SANDBAR_WATCH_PPID"):
    env.pop(k, None)
while True:
    if not _alive(_pid()):
        try:
            subprocess.run([py, os.path.join(repo, "server", "engine", "worker.py"),
                            "--daemon", "--pidfile", pf, "--logfile", log],
                           cwd=os.path.join(repo, "server", "engine"), env=env, timeout=120)
            # 记下本次 spawn 的 pid（收尾据此全收）：后续子用例会把 pidfile 覆盖成别的 pid，
            # 只按 pidfile 收会漏掉先前那颗（实测残留）。
            try:
                with open(sidecar, "a", encoding="utf-8") as f:
                    f.write(str(_pid()) + "\n")
            except Exception:
                pass
        except Exception:
            pass
        time.sleep(1.0)
    time.sleep(0.5)
"""


def pid_alive_of(pid):
    """活探测（夹具自用；与引擎同口径：kill0 + 本进程自家子进程的僵尸修正）。"""
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def spawn_detached(py, code, ready_path, timeout=20.0):
    """双 fork 起一个**归 init 收养**的进程（生产同形：旧 worker 的父进程会收割它）。

    返回 pid。为什么不能在场景里直接 Popen：被 TERM 后它成**僵尸**，而僵尸在外进程看来
    仍是「活」（`shared.pid_alive` 的僵尸修正只能对自己是父进程的情形生效）——实测这条把
    「旧进程已排空」永远判成未排空（保守方向，但夹具在测错东西）。"""
    wrap = ("import os, pathlib, sys, time\n"
            "if os.fork() > 0:\n"
            "    os._exit(0)\n"
            "pathlib.Path(%r).write_text(str(os.getpid()))\n"
            % ready_path) + code
    p = subprocess.run([py, "-c", wrap], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=timeout)
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < timeout:
        try:
            raw = open(ready_path, encoding="utf-8").read().strip()
        except OSError:
            raw = ""
        if raw.isdigit():
            return int(raw)
        _t.sleep(0.05)
    raise RuntimeError("detached 进程没起来（pid 文件 %s 未落；rc=%s）" % (ready_path, p.returncode))


def _gone(proc, timeout=15.0):
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < timeout:
        if proc.poll() is not None:
            return True
        _t.sleep(0.1)
    return proc.poll() is not None


def wait_pidfile_change(pf, old_pid, timeout=90.0):
    """等 pidfile 落一个「存在、活、且不是 old_pid」的 pid（换手判据的一半）。"""
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < timeout:
        try:
            pid = int(open(pf, encoding="utf-8").read().strip())
        except Exception:
            pid = 0
        if pid and pid != old_pid:
            try:
                os.kill(pid, 0)
                return pid
            except OSError:
                pass
        _t.sleep(0.3)
    return None


def pollers_live(host, queue):
    """私有队列的**活** poller 数（工具外的独立复算，防自证自洽）。"""
    snippet = (
        "import asyncio, os, sys\n"
        "from temporalio.client import Client\n"
        "from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest\n"
        "from temporalio.api.taskqueue.v1 import TaskQueue\n"
        "async def m():\n"
        "    c = await Client.connect(%r, namespace='default')\n"
        "    r = await c.workflow_service.describe_task_queue(DescribeTaskQueueRequest(\n"
        "        namespace='default', task_queue=TaskQueue(name=%r), report_pollers=True))\n"
        "    n = 0\n"
        "    for p in (r.pollers or []):\n"
        "        h = str(p.identity).split('@')[0]\n"
        "        if h.isdigit():\n"
        "            try:\n"
        "                os.kill(int(h), 0); n += 1\n"
        "            except OSError:\n"
        "                pass\n"
        "    print(n)\n"
        "asyncio.run(m())\n" % (host, queue))
    p = subprocess.run([PY, "-c", snippet], capture_output=True, text=True, timeout=120)
    try:
        return int((p.stdout or "0").strip().splitlines()[-1])
    except Exception:
        return -1


def build_fixture(tmp):
    """夹具仓 + 泳道（落后 main 一个引擎修）。返回 (repo, lane, files)。"""
    repo = os.path.join(tmp, "fixture")
    os.makedirs(repo)
    git(["init", "-q", "-b", "main"], repo)
    git(["config", "user.email", "ops@e2e.test"], repo)
    git(["config", "user.name", "engine-ops-e2e"], repo)
    for rel in ENGINE_FILES + ("server/engine/README.md",):
        fp = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("# fixture module %s\n" % rel)
    os.makedirs(os.path.join(repo, "server", "engine", "data"), exist_ok=True)
    git(["add", "-A"], repo)
    git(["commit", "-qm", "fixture baseline"], repo)
    lane = os.path.join(repo, ".lane", TID)
    os.makedirs(os.path.dirname(lane), exist_ok=True)
    rc, out = git(["worktree", "add", "-q", "-b", "lane/%s" % TID, lane], repo)
    if rc != 0:
        return None, None, "worktree add 失败：%s" % out[:200]
    # main 前进：一个引擎修（代码面）+ 一个说明（文档面，**不该**告警）
    with open(os.path.join(repo, "server", "engine", "light_lane.py"), "a",
              encoding="utf-8") as f:
        f.write("# main-side engine fix (must be synced into the lane before pushing)\n")
    with open(os.path.join(repo, "server", "engine", "README.md"), "a",
              encoding="utf-8") as f:
        f.write("doc-only change (must NOT raise a drift alert)\n")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "engine fix + doc change on main"], repo)
    return repo, lane, ""


def main():
    fail = Fail("engine_ops offline faces (host order 260930)")
    tmp = tempfile.mkdtemp(prefix="engine-ops-e2e-")
    procs = []
    try:
        try:
            py = PY if os.path.isfile(PY) else sys.executable
            rc, _ = sh(["git", "--version"])
            if rc != 0:
                raise RuntimeError("git 不可用")
        except Exception as e:  # noqa: BLE001
            print("ENV_FAIL: 环境缺件（%s）——exit 2" % e)
            return 2
        repo, lane, err = build_fixture(tmp)
        if repo is None:
            print("ENV_FAIL: 夹具构造失败（%s）——exit 2" % err)
            return 2
        # 夹具 data/worker.pid 指向一个**活**进程（测「活进程拒启」）
        sleeper = subprocess.Popen([py, "-c", "import time\nwhile True: time.sleep(0.2)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(sleeper)
        pidfile = os.path.join(repo, "server", "engine", "data", "worker.pid")
        with open(pidfile, "w", encoding="utf-8") as f:
            f.write(str(sleeper.pid))
        # 旁车 meta：ts 设为 1 分钟前（指纹基准）
        with open(pidfile + ".meta", "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": 1, "pid": sleeper.pid, "repo_root": repo,
                                "ts": int(time.time()) - 60}))

        # ---------- L1/L2 drift：告警 + 逐条点名 + .md 不误报 ----------
        rc, d, _err = run_tool("drift", TID, "--host", DEAD_HOST, repo=repo)
        res = d.get("result") or {}
        fail.check(rc == 1, "L1 drift 有漂移 ⇒ 告警退出 1（实得 %r）" % rc)
        fail.check(res.get("verdict") == "drift", "L1 verdict=drift（实得 %r）"
                  % res.get("verdict"))
        code_files = res.get("engine_files_in_main_not_in_lane") or []
        fail.check("server/engine/light_lane.py" in code_files,
                   "L1 点名泳道缺的**代码**文件（实得 %r）" % code_files[:4])
        fail.check(res.get("behind_commits") in (1, 2),
                   "L1 报出落后提交数（实得 %r）" % res.get("behind_commits"))
        docs = res.get("doc_files_in_main_not_in_lane") or []
        fail.check("server/engine/README.md" in docs,
                   "L2 文档漂移单列（实得 %r）" % docs[:3])
        fail.check(all(not f.endswith(".md") for f in code_files),
                   "L2 **.md 不进漂移告警面**（实得 %r）" % code_files[:4])
        alerts = "；".join(res.get("alerts") or [])
        fail.check("已落 main 的引擎面文件" in alerts, "L1 告警人话点名（实得 %r）" % alerts[:120])
        fail.check("不可得" in alerts and "poller" in alerts,
                   "L1 Temporal 不可达 ⇒ 活 poller 数**具名不可得**并拦住推票（实得 %r）"
                   % alerts[-160:])

        # ---------- L3 sync --dry-run：只读（不动泳道） ----------
        _rc, head0 = git(["rev-parse", "HEAD"], lane)
        _rc, cnt0 = git(["rev-list", "--count", "HEAD"], lane)
        rc, sres, _err = run_tool("sync", TID, "--dry-run", "--host", DEAD_HOST, repo=repo)
        r = sres.get("result") or {}
        fail.check(rc == 0 and r.get("dry_run") is True,
                   "L3 sync --dry-run 正常返回（rc=%r）" % rc)
        fail.check("server/engine/light_lane.py" in (r.get("engine_files_incoming") or []),
                   "L3 dry-run 报出会并进来的引擎文件（实得 %r）"
                   % (r.get("engine_files_incoming") or [])[:4])
        _rc, head1 = git(["rev-parse", "HEAD"], lane)
        _rc, cnt1 = git(["rev-list", "--count", "HEAD"], lane)
        fail.check(head0.strip() == head1.strip() and cnt0.strip() == cnt1.strip(),
                   "L3 dry-run **不动泳道**（HEAD %s→%s，提交数 %s→%s）"
                   % (head0.strip()[:8], head1.strip()[:8], cnt0.strip(), cnt1.strip()))

        # ---------- L4 who（Temporal 不可达）= 具名 ENV_FAIL ----------
        rc, wres, _err = run_tool("who", TID, "--host", DEAD_HOST, repo=repo)
        fail.check(rc == 2 and wres.get("ok") is False
                   and "事件历史" in str(wres.get("error") or ""),
                   "L4 who 不可得 ⇒ 退出 2 + 具名原因（实得 rc=%r err=%r）"
                   % (rc, str(wres.get("error"))[:120]))

        # ---------- L5 sync（真跑，Temporal 不可达）= 具名 ENV_FAIL，**不退化手写 merge** ----------
        rc, sres2, _err = run_tool("sync", TID, "--host", DEAD_HOST, repo=repo)
        fail.check(rc == 2 and sres2.get("ok") is False,
                   "L5 sync 真跑遇 Temporal 不可达 ⇒ 退出 2（实得 %r）" % rc)
        _e5 = str(sres2.get("error") or "")
        fail.check(any(k in _e5 for k in ("prepare_conflict_resolution", "temporalio",
                                         "activity", "不可得")),
                   "L5 报错点名走的是 activity 单点（不退化手写 merge；实得 %r）"
                   % _e5[:160])
        rc4, out4 = git(["log", "--oneline", "-1", "HEAD"], lane)
        fail.check(rc4 == 0 and "fixture baseline" in out4,
                   "L5 失败路径**没有**手写 merge 落盘（泳道 HEAD 仍=夹具基线：%r）"
                   % out4.strip()[:80])

        # ---------- L6 换手=kill-only：夹具 supervisor 在场 / 缺席 两条子用例 ----------
        # 宿主 260930 纠正：`restart` **只 kill、等 supervisor 自动拉起**，绝不自己起 worker
        # （agent 会话起的 worker 继承沙箱 ⇒ 工作区外写 fail-closed ⇒ 票归档 EPERM，真票实案）。
        # 夹具 supervisor = 忠实替身（在**私有队列**上起真 worker、只写夹具 tmp）：
        #   · 子用例A：supervisor 在场 ⇒ 换手后 pidfile 变新 pid、真在轮询、活 poller=1 ⇒ 报成功；
        #   · 子用例B：supervisor 缺席 ⇒ 有界等待超时 ⇒ 具名告警 + exit 1 且**没有产生任何新进程/文件**。
        lane_pf = os.path.join(repo, "server", "engine", "data", "worker-%s.pid" % TID)
        lane_log = os.path.join(repo, "server", "engine", "data", "worker-%s.log" % TID)
        real_temporal = os.environ.get("SANDBAR_OPS_E2E_HOST", "127.0.0.1:7233")
        private_q = "sandbar-ticket-%s" % TID
        rc_p, _o = sh([PY, "-c", "import socket,sys\n"
                       "s=socket.socket()\ns.settimeout(1.5)\n"
                       "sys.exit(0 if s.connect_ex(('%s',%d))==0 else 1)"
                       % (real_temporal.split(":")[0], int(real_temporal.split(":")[1]))])
        if rc_p != 0:
            print("ENV_FAIL: 子用例A 需真 Temporal（%s 不可达）——该子用例具名不可得（不静默 skip）"
                  % real_temporal)
        else:
            sup = os.path.join(tmp, "fixture_supervisor.py")
            sidecar = os.path.join(tmp, "spawned.jsonl")
            with open(sup, "w", encoding="utf-8") as f:
                f.write(FIXTURE_SUPERVISOR_SRC)
            # 起 worker 的**代码根=本仓**（生产事实：泳道 worker 由 console 从它自己的仓起，
            # 跑的是那份引擎代码；夹具仓只提供 pidfile/log 与队列名）——见 ops 文档 §1。
            sup_proc = subprocess.Popen([PY, sup, REPO, lane_pf, lane_log, PY,
                                         real_temporal, private_q, sidecar],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        start_new_session=True)
            procs.append(sup_proc)
            # 先让夹具 supervisor 起第一颗（等价于 console 已拉起），再让工具体换手。
            # 触发条件=pidfile 里那颗**已死**（真 supervisor 的判据同样是 workerAlive()=false，
            # 含 pidfile 缺席/陈旧）——所以先写一个死 pid，再等它拉起。
            with open(lane_pf, "w", encoding="utf-8") as f:
                f.write("999999\n")
            first = wait_pidfile_change(lane_pf, 999999, timeout=90)
            fail.check(first is not None, "L6 前置：夹具 supervisor 起了第一颗 worker（pid=%r）"
                       % first)
            if first:
                p0 = int(first)
                poll0 = pollers_live(real_temporal, private_q)
                fail.check(poll0 == 1, "L6 前置：私有队列活 poller=1（实得 %r）" % poll0)
                rc, r6, _e6 = run_tool("restart", "--scope", "lane:%s" % TID,
                                       "--host", real_temporal, "--ns", "default",
                                       "--wait", "60", repo=repo)
                res6 = (r6.get("result") or {})
                fail.check(rc == 0 and r6.get("ok") is True,
                           "L6A supervisor 在场 ⇒ 换手成功（rc=%r err=%r）"
                           % (rc, str(r6.get("error"))[:140]))
                new_pid = res6.get("new_pid")
                fail.check(bool(new_pid) and int(new_pid) != p0,
                           "L6A pidfile 变成**新** pid（old=%s new=%r）" % (p0, new_pid))
                fail.check(str(res6.get("mode")) == "kill-and-wait-for-respawn",
                           "L6A 模式=kill-and-wait-for-respawn（实得 %r）" % res6.get("mode"))
                proof = res6.get("pollers_proof") or {}
                fail.check(proof.get("ok") is True and pollers_live(real_temporal, private_q) == 1,
                           "L6A 换手后活 poller=1（工具自证=%r）" % proof.get("ok"))
                fail.check("自己起" not in json.dumps(res6, ensure_ascii=False).replace(
                    "不自己起", "").replace("绝不自己起", ""),
                    "L6A 输出里不再出现「自己起」的鼓励语（只允许作为禁止语）")
        # ---- 子用例B/C 的前提：**夹具 supervisor 必须真的缺席** ----
        # 不杀掉它的话，它会在 B/C 里继续 keepalive 补起 worker（=leg A 的新 pid 出现），
        # 工具于是报「poller 面不可得」而不是「supervisor 未拉起」——测的就不是缺席面了。
        if 'sup_proc' in dir() and sup_proc.poll() is None:
            sup_proc.kill()
            sup_proc.wait(timeout=10)
        # 顺便把 leg A 那颗 worker 也收掉（它还在轮询私有队列，与 B/C 的判据无关但会混淆观测）
        for f in glob.glob(os.path.join(tmp, "**", "worker-*.pid"), recursive=True):
            try:
                os.kill(int(open(f, encoding="utf-8").read().strip()), signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1.5)

        # ---- 子用例B：supervisor 缺席（死 Temporal + 夹具 pidfile 指向活进程）----
        old_b_pid = spawn_detached(py, "import time\nwhile True: time.sleep(0.2)\n",
                                   os.path.join(tmp, "oldB.pid"))
        procs.append(type("X", (), {"poll": staticmethod(lambda: 0), "pid": old_b_pid,
                                    "kill": staticmethod(lambda: None)})())
        with open(lane_pf, "w", encoding="utf-8") as f:
            f.write(str(old_b_pid))
        files_before = sorted(os.listdir(os.path.join(repo, "server", "engine", "data")))
        rc, r6b, _e6b = run_tool("restart", "--scope", "lane:%s" % TID, "--host", DEAD_HOST,
                                 "--wait", "2", repo=repo)
        fail.check(rc == 1 and r6b.get("ok") is False, "L6B 超时 ⇒ 告警退出 1（实得 %r）" % rc)
        e6b = str(r6b.get("error") or "")
        fail.check("supervisor 未在" in e6b and "不自己起 worker" in e6b,
                   "L6B 具名告警（点名查 supervisor + 不自己起；实得 %r）" % e6b[:160])
        fail.check(open(lane_pf, encoding="utf-8").read().strip() == str(old_b_pid),
                   "L6B 超时路径**不改写** pidfile（没起任何东西）")
        fail.check(sorted(os.listdir(os.path.join(repo, "server", "engine", "data")))
                   == files_before,
                   "L6B 超时路径**零新文件**（无 pid/.meta/日志冒出来）")
        fail.check(not os.path.exists(lane_log) or "supervisor" in json.dumps(r6b,
                   ensure_ascii=False),
                   "L6B 无自起痕迹（日志缺席或只是前置子用例留下的）")

        # ---------- L6C 旧进程**慢排空**：必须走四段序列、不判「poller 数不为 1」 ----------
        # 宿主 260930 打回：优雅停要等在飞活动收口（负载高的机器上几十秒），换手瞬间旧进程仍
        # 在排空是**合法中间态**——单次采样 + 直接判 poller 数会必然假红。夹具里**故意**让旧
        # 进程慢排空（TERM 后逗留 6s），把这条环境敏感面固定进夹具，不再靠运气。
        slow_ready = os.path.join(tmp, "slow-old-ready")
        slow_pid = spawn_detached(py,
                                  "import signal, sys, time, pathlib\n"
                                  "signal.signal(signal.SIGTERM, lambda *a: (time.sleep(6.0), sys.exit(0)))\n"
                                  "while True: time.sleep(0.1)\n", slow_ready)
        procs.append(type("X", (), {"poll": staticmethod(lambda: 0), "pid": slow_pid,
                                    "kill": staticmethod(lambda: None)})())
        with open(lane_pf, "w", encoding="utf-8") as f:
            f.write(str(slow_pid))
        files_beforec = sorted(os.listdir(os.path.join(repo, "server", "engine", "data")))
        rc, r6c, _e6c = run_tool("restart", "--scope", "lane:%s" % TID, "--host", DEAD_HOST,
                                 "--wait", "3", "--old-drain", "25", repo=repo)
        res6c = r6c.get("result") or {}
        fail.check(rc == 1 and r6c.get("ok") is False, "L6C 慢排空 + 无 supervisor ⇒ 告警退出 1（实得 %r）" % rc)
        phases = {p["phase"]: p for p in (res6c.get("phases") or [])}
        fail.check(phases.get("old-drain", {}).get("drained") is True,
                   "L6C 等到了旧进程真排空（有界，不判失败；phases=%r）" % list(phases))
        fail.check(res6c.get("phase_failed") == "respawn",
                   "L6C 失败段点名 **respawn**（不是 poller 计数！实得 %r）"
                   % res6c.get("phase_failed"))
        fail.check("supervisor 未在" in str(r6c.get("error") or ""),
                   "L6C 告警点名 supervisor 未拉起（实得 %r）" % str(r6c.get("error"))[:140])
        samples = res6c.get("samples") or []
        fail.check(len(samples) >= 2 and any(x.get("old_alive") for x in samples),
                   "L6C 判据是**轮询式采样**（样本数=%d，含旧进程仍活帧）" % len(samples))
        t_gone = time.time()
        while pid_alive_of(slow_pid) and time.time() - t_gone < 20:
            time.sleep(0.2)
        fail.check(not pid_alive_of(slow_pid),
                   "L6C 慢排空进程最终真的退出（TERM 后 6s 排空完成）")
        fail.check(sorted(os.listdir(os.path.join(repo, "server", "engine", "data")))
                   == files_beforec,
                   "L6C 全程**零新文件**（工具没起任何东西）")

        # ---------- L7 workers：poller 不可得必须具名 ----------
        rc, wres, _err = run_tool("workers", "--host", DEAD_HOST, repo=repo)
        res7 = wres.get("result") or {}
        q = (res7.get("queues") or [{}])[0]
        fail.check(q.get("available") is False and "不可得" in str(q.get("note") or ""),
                   "L7 队列 poller 面不可得 ⇒ 具名（实得 %r）" % q.get("note"))
        fail.check(any("不可得" in a for a in (res7.get("alerts") or [])),
                   "L7 告警面点名不可得（不得当作 0 颗静默放过；实得 %r）"
                   % (res7.get("alerts") or [])[:1])
        fail.check(str(sleeper.pid) in json.dumps(res7, ensure_ascii=False),
                   "L7 workers 面列出夹具里的活 worker（pid）")
    finally:
        # 收尾纪律（次序要紧）：**先杀夹具 supervisor，再 TERM 它起的 worker**。
        # 反过来的话 supervisor 的 keepalive 会在我们 TERM 之后又拉起一颗（实测残留）。
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
        pick = [os.path.join(tmp, "**", "worker-*.pid"),
                os.path.join(tmp, "spawned.jsonl")]
        for pat in pick:
            for f in glob.glob(pat, recursive=True):
                try:
                    for ln in open(f, encoding="utf-8").read().split():
                        os.kill(int(ln.strip()), signal.SIGTERM)
                except Exception:  # noqa: BLE001
                    pass
        time.sleep(1.5)
        # 兜底清扫：按**命令行里的夹具 tmp 路径**扫（pgrep 面）——supervisor 与它起的 worker
        # argv 都含该路径，且该前缀唯一（本场景私有）；比只按 pidfile 收更可靠（子用例会把
        # pidfile 覆盖成别的 pid，实测漏收）。先 TERM、再复核，仍在则 KILL 兜底。
        for _sig, _wait in (("TERM", 4.0), ("KILL", 2.0)):
            subprocess.run(["pkill", "-%s" % _sig, "-f", tmp], check=False)
            time.sleep(_wait)
        left = []
        try:
            out = subprocess.run(["pgrep", "-fl", "-f", tmp], capture_output=True,
                                 text=True, timeout=30).stdout
            for ln in (out or "").splitlines():
                head = ln.split()[0] if ln.split() else ""
                if head.isdigit():
                    left.append(int(head))
        except Exception:  # noqa: BLE001
            left = []
        print("  fixture residue check: %r" % left, flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
