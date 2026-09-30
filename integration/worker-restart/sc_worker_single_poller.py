#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_worker_single_poller.py —— worker 重启唯一性（宿主 260930 实报的运作缺陷）。

intent（守护的用户可感知行为）：**重启之后，同一队列上只可能有一颗 worker 在轮询**。

为什么（宿主实报，一天撞四次）：`server/engine/data/worker.log` 里成对出现间隔 3~5 秒的
两行「worker 起来了」；那个窗口里两颗 worker 都在轮询同一队列 —— 谁先领到 workflow task
谁执行，于是真票 t260930-09 第 4 轮出现「票面文案是旧格式 + 票面 ran=0 而泳道报告
ran=13」这种**不可归因到确定代码版本**的结果。daemon 档原先只单 fork、不读也不回收已有
worker；pidfile 是单槽（最后一次覆盖），第二个启动于是静默改写它。

判据（本场景的执行面；白盒真值分支归 UT
`server/engine/tests/test_worker_single_poller_guard.py`）：
  ① 活 pid 在场 → 第二颗**被拒**：非零退出 + stderr 具名（旧 pid/pidfile/出路）+ pidfile
     内容不被改写 + 旧进程不受扰动 + 日志里「worker 起来了」计数**不增**（没有第二颗 poller）；
  ② 陈旧/畸形/缺席 pidfile → 正常接管（新 pid 落盘、进程真活）；
  ③ `--replace` → 先 TERM 旧 worker、**有界等待**其优雅退出，再起新的一颗；旧的真死、
     pidfile 指向新的、日志计数 +1、旧的留下「优雅停止」行（没被静默 KILL）；
  ④ 逐点互证「起过的 worker 行数 ↔ 活着的 worker 数」（唯一性的过程面）；
  ⑤ 前台档不受守卫保护（不写 pidfile）但**响亮点名**：落在共享队列且已有活 daemon 时，
     stderr 给出该 daemon 的 pid 与两条出路。

pollers 面（宿主指定的等价物）：`describe_task_queue(report_pollers=True)` 在**真 worker.py
轮询**时给出 `pid@host` 身份（本场景实测恰一颗、且 identity 就是被起的那颗 ⇒ 唯一性从
server 侧得到硬证）。该面在别的 build/桩上取不到时**如实记 na**（不冒充「已从 server 侧
验过 poller 数」），由①②③与「第二颗必被拒」三面兜住。

三态：0=绿；1=被测红；2=环境红（引擎 venv 无 temporalio / 本地测试服务器起不来 / 真 worker
起不来）。零生产接触：全部子进程 TARGET_HOST=**本地测试服务器**（随机端口，绝非 7233/8233）、
pidfile/日志全在场景私有 tmp（连前台告警子用例也显式带 --pidfile 指到 tmp，绝不读生产
pidfile）；不碰 3099。
"""
import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "t260904-02"))
from lib_gate import Fail  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO, "server", "engine")
WORKER_PY = os.path.join(ENGINE, "worker.py")
PROD_PORTS = (7233, 8233, 3099)
READY_MARK = "worker 起来了"
STOP_MARK = "worker 已优雅停止"


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


async def wait_dead(pid, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not pid_alive(pid):
            return True
        await asyncio.sleep(0.2)
    return not pid_alive(pid)


async def wait_until(pred, timeout=60.0, step=0.3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        await asyncio.sleep(step)
    return bool(pred())


def read_pid(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def log_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def log_count(path, mark):
    return sum(1 for ln in log_text(path).splitlines() if mark in ln)


def worker_env(host, queue):
    """子进程 env：指向本地台 + 本场景队列；剥掉会改变语义的旋钮。"""
    env = dict(os.environ)
    for k in ("SANDBAR_WORKER_META", "SANDBAR_WATCH_WORKFLOW", "SANDBAR_WATCH_PPID",
              "SANDBAR_TASK_QUEUES", "SANDBAR_TASK_QUEUE"):
        env.pop(k, None)
    env["SANDBAR_TARGET_HOST"] = host
    env["SANDBAR_NAMESPACE"] = "default"
    env["SANDBAR_TASK_QUEUE"] = queue
    env["SANDBAR_TASK_QUEUES"] = queue
    return env


async def start_daemon(py, host, queue, pidfile, logfile, extra=()):
    """起一颗真 daemon worker；返回 (rc, stderr)。真身是孙进程，pid 只看 pidfile。"""
    argv = [py, WORKER_PY, "--daemon", "--pidfile", pidfile, "--logfile", logfile] + list(extra)
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=ENGINE, env=worker_env(host, queue),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=180)
    return proc.returncode, (err_b or out_b).decode("utf-8", "replace")


def identity_pid(identity):
    """poller identity 形如 `pid@host` → pid（取不到返回 None）。"""
    head = str(identity or "").split("@", 1)[0].strip()
    return int(head) if head.isdigit() else None


def live_pollers(poll):
    """**活着的** poller（唯一性的正确读法）。

    为什么不能直接数 pollers：server 会保留刚退出 worker 的 poller 历史（实测：--replace
    换手后那 0.x 秒里旧的 8206 仍在列表里），直接数会把「刚停掉的旧颗」读成第二颗 poller
    ——假红。真判据=**同一队列上活着的 poller 恰一颗**（identity 的 pid 必须真活）。"""
    out = []
    for p in poll or []:
        pid = identity_pid(getattr(p, "identity", ""))
        if pid is not None and pid_alive(pid):
            out.append({"pid": pid, "identity": getattr(p, "identity", "")})
    return out


async def pollers_of(client, queue):
    """server 侧 pollers 面（宿主指定的等价物）；面不可用返回 None（记 na，不冒充）。"""
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
    from temporalio.api.taskqueue.v1 import TaskQueue
    try:
        ns = getattr(client, "namespace", None) or "default"
        resp = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(namespace=ns, task_queue=TaskQueue(name=queue),
                                     report_pollers=True))
        return list(getattr(resp, "pollers", None) or [])
    except Exception:  # noqa: BLE001——面不可用=na（不冒充断言）
        return None


async def run(fail, stats):
    def check(cond, msg):
        if fail.check(cond, msg):
            stats["pass"] += 1
        return cond

    def na(msg):
        stats["na"] += 1
        print("N/A:  %s" % msg, flush=True)

    py = os.path.join(ENGINE, ".venv", "bin", "python")
    if not os.path.isfile(py):
        print("ENV_FAIL: 引擎 venv 解释器不在位（%s）——exit 2" % py)
        return 2
    try:
        from temporalio.testing import WorkflowEnvironment
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: temporalio 不可用：%r（exit 2）" % (e,))
        return 2
    try:
        env_ctx = await WorkflowEnvironment.start_local()
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: 本地测试服务器起不来：%r（exit 2）" % (e,))
        return 2

    tmp = tempfile.mkdtemp(prefix="sandbar-worker-poller-")
    pidfile = os.path.join(tmp, "worker.pid")
    logfile = os.path.join(tmp, "worker.log")
    started = []
    async with env_ctx as env:
        client = env.client
        host = client.service_client.config.target_host
        port = int(host.rsplit(":", 1)[1])
        queue = "worker-single-poller-%d" % os.getpid()
        try:
            check(port not in PROD_PORTS,
                  "L0 写守卫：全部子进程指向本地测试服务器 %s（端口 %d ∉ 生产/控制台端口集）"
                  % (host, port))
            check(os.path.isfile(WORKER_PY), "L0 被测对象在场：%s" % WORKER_PY)

            # ---------- L1 第一颗：起得来、pidfile 落盘、日志就绪 ----------
            rc1, err1 = await start_daemon(py, host, queue, pidfile, logfile)
            check(rc1 == 0, "L1 第一颗 daemon 启动 rc=0（实得 %r：%s）"
                  % (rc1, err1[-200:]))
            ok_ready = await wait_until(
                lambda: read_pid(pidfile).isdigit() and pid_alive(read_pid(pidfile))
                and log_count(logfile, READY_MARK) >= 1, 60)
            p1 = int(read_pid(pidfile)) if read_pid(pidfile).isdigit() else None
            check(ok_ready and p1, "L1 第一颗就绪（pidfile 落盘 + 进程活 + 日志「%s」）"
                  % READY_MARK)
            if not (ok_ready and p1):
                print("ENV_FAIL: 真 worker 起不来，后续子用例无从进行（exit 2）")
                return 2
            started.append(p1)
            check(log_count(logfile, READY_MARK) == 1,
                  "L1 就绪行计数=1（实得 %d）——起点就是「恰好一颗」"
                  % log_count(logfile, READY_MARK))
            check(queue in log_text(logfile),
                  "L1 第一颗真在轮询本场景队列 %s" % queue)

            # ---------- L2 第二颗：必须被拒 ----------
            before = log_text(logfile)
            rc2, err2 = await start_daemon(py, host, queue, pidfile, logfile)
            check(rc2 != 0, "L2 第二颗被拒（非零退出；实得 %r）" % rc2)
            check("拒绝启动" in err2, "L2 拒绝是具名的（stderr 有「拒绝启动」）")
            for frag in (str(p1), pidfile):
                check(frag in err2, "L2 拒绝面点名 %s" % frag)
            check("--replace" in err2, "L2 拒绝面给出显式出路（--replace / kill -TERM）")
            check(read_pid(pidfile).strip() == str(p1),
                  "L2 拒绝路径不改写 pidfile（仍指向 pid=%d）" % p1)
            check(pid_alive(p1), "L2 拒绝路径不扰动旧 worker（pid=%d 仍活）" % p1)
            check(log_count(logfile, READY_MARK) == 1,
                  "L2 就绪行计数仍=1（第二颗没起来 ⇒ 同队列没多出 poller；实得 %d）"
                  % log_count(logfile, READY_MARK))
            check(log_text(logfile) == before,
                  "L2 拒绝路径不产生后台日志（没 fork、没后台进程）")

            # ---------- L3 pollers 面（不可用则如实记 na） ----------
            poll = await pollers_of(client, queue)
            if poll is None:
                na("server 侧 describe_task_queue.pollers 面在本机 build 不返回 poller"
                   "（探针实证：本地台上真 Worker 在轮询时同样为空）——唯一性由「第二颗必被"
                   "拒 + pidfile 单槽 + 活进程计数」三面钉住，不冒充「已从 server 侧验过 poller 数」")
            else:
                live = live_pollers(poll)
                check(len(live) == 1, "L3 同队列**活着的** poller 恰一颗（实得 %d：%r）"
                      % (len(live), live))
                check(bool(live) and live[0]["pid"] == p1,
                      "L3 那一颗就是本场景第一颗 worker（实得 %r，pid=%d）" % (live, p1))

            # ---------- L4 --replace：先停旧的（有界等待优雅退出）再起新的 ----------
            rc3, err3 = await start_daemon(py, host, queue, pidfile, logfile,
                                           extra=["--replace"])
            check(rc3 == 0, "L4 --replace 放行并起新的一颗（rc=0；%s）" % err3[-200:])
            check(await wait_dead(p1, 60), "L4 --replace 真停了旧 worker（pid=%d 已退）" % p1)
            ok2 = await wait_until(
                lambda: read_pid(pidfile).isdigit() and read_pid(pidfile) != str(p1)
                and pid_alive(read_pid(pidfile)), 60)
            p2 = int(read_pid(pidfile)) if read_pid(pidfile).isdigit() else None
            check(ok2 and p2, "L4 新 worker 接管该槽（pidfile=%r，旧=%d）"
                  % (read_pid(pidfile), p1))
            if p2:
                started.append(p2)
            await wait_until(lambda: log_count(logfile, READY_MARK) >= 2, 60)
            check(log_count(logfile, READY_MARK) == 2,
                  "L4 就绪行计数=2（两次真启动：起过的行数 ↔ 活的进程数互证；实得 %d）"
                  % log_count(logfile, READY_MARK))
            check(log_count(logfile, STOP_MARK) >= 1,
                  "L4 旧 worker 是**优雅**退的（日志有「%s」；没被静默 KILL）" % STOP_MARK)
            poll = await pollers_of(client, queue)
            if poll is not None:
                live = live_pollers(poll)
                check(len(live) == 1, "L4 换手后同队列**活着的** poller 仍恰一颗"
                      "（实得 %d：%r；面内全部=%r）"
                      % (len(live), live, [x.identity for x in poll]))
                check(bool(live) and bool(p2) and live[0]["pid"] == p2,
                      "L4 换手后活着的那颗=新的 worker（实得 %r，新 pid=%r）" % (live, p2))
                # 面里的**其余**条目只许是已死进程（=刚被换下的那颗的历史残留）——
                # 「活着的不超过一颗」才是该面的正确判据
                check(all(not pid_alive(identity_pid(x.identity)) for x in poll
                          if identity_pid(x.identity) not in
                          [y["pid"] for y in live]),
                      "L4 面内其余 poller 全是已死进程的历史残留（无第二颗活着）")

            # ---------- L5 陈旧 pidfile：正常接管 ----------
            if p2:
                os.kill(p2, signal.SIGTERM)
                check(await wait_dead(p2, 60), "L5 前置：优雅停掉当前 worker（pid=%d）" % p2)
            with open(pidfile, "w", encoding="utf-8") as f:
                f.write("999999\n")
            rc4, err4 = await start_daemon(py, host, queue, pidfile, logfile)
            check(rc4 == 0, "L5 陈旧 pidfile 不拦启动（rc=0）")
            check("陈旧已接管" in err4, "L5 接管留痕（stderr 点名陈旧值）")
            ok3 = await wait_until(
                lambda: read_pid(pidfile).isdigit() and read_pid(pidfile) != "999999"
                and pid_alive(read_pid(pidfile)), 60)
            p3 = int(read_pid(pidfile)) if read_pid(pidfile).isdigit() else None
            check(ok3 and p3, "L5 pidfile 被新进程重写且进程真活（实得 %r）" % read_pid(pidfile))
            if p3:
                started.append(p3)

            # ---------- L6 前台档：不受守卫保护，但响亮点名 ----------
            fg_log = os.path.join(tmp, "foreground.log")
            fh = open(fg_log, "wb")
            try:
                fg = subprocess.Popen(
                    [py, WORKER_PY, "--pidfile", pidfile], cwd=ENGINE,
                    env=worker_env(host, "sandbar"),   # 共享队列名：触发告警的那个形态
                    stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                fh.close()
            try:
                await wait_until(lambda: "不受唯一性守卫保护" in log_text(fg_log), 30)
                warn = log_text(fg_log)
                check("不受唯一性守卫保护" in warn,
                      "L6 前台档响亮提示唯一性风险（落在共享队列且已有活 daemon）")
                warn_line = next((ln for ln in warn.splitlines()
                                  if "不受唯一性守卫保护" in ln), "")
                check(bool(p3) and str(p3) in warn_line,
                      "L6 告警行内点名现存 daemon 的 pid（实得 %r）" % warn_line[-200:])
                check(read_pid(pidfile).strip() == str(p3),
                      "L6 前台档不写 pidfile（仍指向 daemon pid=%r）" % read_pid(pidfile))
            finally:
                fg.terminate()
                try:
                    fg.wait(timeout=20)
                except Exception:  # noqa: BLE001
                    fg.kill()
                check(fg.poll() is not None, "L6 前台档收尾（TERM 后退出）")

            # ---------- L6b 前台档 + 陈旧 pidfile：同样点名（宿主实报窗口一的形态） ----------
            # 窗口一实况：前台档不写 pidfile，而 pidfile 里还是刚被 TERM 掉那颗的旧值 ⇒
            # console supervisor 的 keepalive 读成「worker 不在位」→ ≤5s 后另起一颗。
            with open(pidfile, "w", encoding="utf-8") as f:
                f.write("999999\n")
            fg2_log = os.path.join(tmp, "foreground-stale.log")
            fh2 = open(fg2_log, "wb")
            try:
                fg2 = subprocess.Popen([py, WORKER_PY, "--pidfile", pidfile], cwd=ENGINE,
                                       env=worker_env(host, "sandbar"), stdout=fh2,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                fh2.close()
            try:
                await wait_until(lambda: "另起一颗" in log_text(fg2_log), 30)
                warn2 = log_text(fg2_log)
                check("另起一颗" in warn2,
                      "L6b 陈旧 pidfile 的前台档同样点名（supervisor keepalive 会另起一颗）")
                check("999999" in next((ln for ln in warn2.splitlines()
                                        if "另起一颗" in ln), ""),
                      "L6b 告警行内点名陈旧值（实得 %r）"
                      % next((ln for ln in warn2.splitlines() if "另起一颗" in ln), "")[-160:])
            finally:
                fg2.terminate()
                try:
                    fg2.wait(timeout=20)
                except Exception:  # noqa: BLE001
                    fg2.kill()
                check(fg2.poll() is not None, "L6b 前台档收尾（TERM 后退出）")

            # ---------- L7 收尾：逐个优雅停 + 零残留 ----------
            alive = [p for p in started if pid_alive(p)]
            for p in alive:
                os.kill(p, signal.SIGTERM)
            gone = [await wait_dead(p, 60) for p in alive]
            check(all(gone), "L7 逐个 TERM 后全部真退出（逐个结果=%r）" % gone)
            stale = [p for p in started if pid_alive(p)]
            check(not stale, "L7 起过的 worker 全部已回收（存活残留=%r）" % stale)
            # 优雅停行数 ≥ 本场景停过的颗数（TERM 走的是优雅停，不是 KILL）
            check(log_count(logfile, STOP_MARK) >= 1 + len(alive),
                  "L7 收尾是**优雅**的（日志「%s」行数=%d ≥ 1+%d）"
                  % (STOP_MARK, log_count(logfile, STOP_MARK), len(alive)))
        finally:
            for p in list(started):
                if pid_alive(p):
                    try:
                        os.kill(int(p), signal.SIGKILL)
                    except OSError:
                        pass
            for f in os.listdir(tmp):
                pass
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main():
    fail = Fail("worker restart uniqueness (single poller) — host report 260930")
    stats = {"pass": 0, "na": 0}
    try:
        rc = asyncio.run(run(fail, stats))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        fail.check(False, "场景中途异常：%s: %s" % (type(e).__name__, str(e)[:200]))
        rc = 1
    print("SUMMARY pass=%d fail=%d env_fail=0 na=%d"
          % (stats["pass"], len(fail.fails), stats["na"]), flush=True)
    if rc == 2:
        sys.exit(2)
    fail.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
