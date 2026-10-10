"""宿主 260930 当面令（无票）：`server/tools/engine_ops.py` 的判定面 UT。

intent（守护的用户可感知行为）：**一条命令答得出「这张票是谁在服务、它吃哪份代码、
离 main 漂了多远」** —— 而这条命令的判断不许靠猜、不许把「刚被换下的旧颗」读成第二颗。

覆盖口径（纯函数可判定面；端到端与真 Temporal 面归 L3 场景
`integration/engine-ops/sc_engine_ops_offline.py` 与真台场景）：
  ① pidfile 解析四态（shared.read_pidfile_state：absent/malformed/stale/live）+
     engine_ops.read_pidfile 的旁车 meta/起时拼接；
  ② 代码指纹比较（stamp_for：基准时刻晚于/早于模块 mtime 的两态——stale 判据的真值表）；
  ③ 漂移分类（repo_root_from_tree：cwd=`<repo>/server/engine` 要上溯到仓根，拼歪=指纹全空）；
  ④ poller **活计数**（classify_pollers：活/历史残留/无 pid 三栏；host 段只作附注）；
  ⑤ `who` 的解析面（_history_rows：proto3 oneof 未设置时**取属性会拿到默认实例**——
     必须 HasField 判定，否则 Completed 等事件会被读成「identity 空的 started」）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

POC = pathlib.Path(__file__).resolve().parent.parent
REPO = POC.parents[1]
sys.path.insert(0, str(POC))
sys.path.insert(0, str(REPO / "server" / "tools"))

import shared  # noqa: E402
sys.path.insert(0, str(REPO / "server" / "tools"))
import engine_ops as eo  # noqa: E402


def _spawn_sleeper() -> subprocess.Popen:
    """起一个活进程当夹具；stdio 一律 DEVNULL——否则子进程持有 pytest 的捕获管道，
    残留时会让 pytest 收尾挂住（本文件实测过一次 600s 挂死）。"""
    return subprocess.Popen([sys.executable, "-c", "import time\nwhile True: time.sleep(0.2)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL)


class PidfileParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-ops-ut-"))
        self.pf = self.tmp / "worker.pid"
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_four_states_and_meta_started_at(self):
        # absent
        row = eo.read_pidfile(self.pf)
        self.assertEqual(row["state"], "absent")
        self.assertEqual(row["started_at"], "")
        # malformed（脏值=陈旧可接管，但留痕）
        for bad in ("abc", "", "-1", "0"):
            self.pf.write_text(bad, encoding="utf-8")
            self.assertEqual(eo.read_pidfile(self.pf)["state"], "malformed", bad)
        # stale（合法 pid 但不在）
        self.pf.write_text("999999", encoding="utf-8")
        self.assertEqual(eo.read_pidfile(self.pf)["state"], "stale")
        # live + 旁车 meta 的 ts 进 started_at
        p = _spawn_sleeper()
        self.procs.append(p)
        self.pf.write_text(str(p.pid), encoding="utf-8")
        ts = int(time.time()) - 60
        (self.tmp / "worker.pid.meta").write_text(
            '{"version": 1, "pid": %d, "repo_root": "%s", "ts": %d}'
            % (p.pid, str(REPO), ts), encoding="utf-8")
        row = eo.read_pidfile(self.pf)
        self.assertEqual(row["state"], "live")
        self.assertEqual(row["pid"], p.pid)
        self.assertEqual(row["meta"].get("repo_root"), str(REPO))
        self.assertTrue(row["started_at"].startswith(
            datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")[:16]))


class StampCompareTest(unittest.TestCase):
    """stamp_for：`stale` = 模块 mtime 晚于**该 worker 自己的启动基准**（真值表两态）。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-ops-stamp-"))
        for _n, rel in shared.CODE_STAMP_MODULES:
            fp = self.tmp / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text("# module\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_not_stale_when_baseline_after_mtime(self):
        base = datetime.datetime.now().isoformat(timespec="seconds")
        st = eo.stamp_for(None, str(self.tmp), base)
        self.assertTrue(st["available"])
        self.assertEqual(st["stale"], [], "基准晚于模块 mtime ⇒ 不该判 stale")
        self.assertEqual(st["tree"], str(self.tmp))

    def test_stale_when_module_newer_than_baseline(self):
        base = (datetime.datetime.now()
                - datetime.timedelta(minutes=5)).isoformat(timespec="seconds")
        st = eo.stamp_for(None, str(self.tmp), base)
        self.assertTrue(st["stale"], "模块 mtime 晚于基准 ⇒ 必须判 stale（保守提示）")
        self.assertIn("agent_activities", st["stale"])
        self.assertIn("stale=", eo.shared.code_stamp_line(st))


class DriftClassificationTest(unittest.TestCase):
    def test_repo_root_from_tree_climbs_to_repo_root(self):
        # 泳道/中央 worker 的 cwd 都是 <repo>/server/engine（spawn 面 cwd=poc）
        self.assertEqual(eo.repo_root_from_tree(str(POC)), str(REPO))
        self.assertEqual(eo.repo_root_from_tree(str(REPO)), str(REPO))
        # 上游任意目录都上溯到仓根（`<repo>/server` → `<repo>`；这是「吃的树」的正确读法）
        self.assertEqual(eo.repo_root_from_tree(str(REPO / "server")), str(REPO))
        # 仓外目录 / 空串：原样返回（不静默编一个仓根出来）
        self.assertEqual(eo.repo_root_from_tree(str(self.tmp if hasattr(self, "tmp") else "/tmp")),
                         str(self.tmp if hasattr(self, "tmp") else "/tmp"))
        self.assertEqual(eo.repo_root_from_tree(""), "")

    def test_doc_files_are_not_drift(self):
        """漂移告警面只算代码：`.md` 单列不告警（少一个假红面）。"""
        src = (REPO / "server" / "tools" / "engine_ops.py").read_text(encoding="utf-8")
        self.assertIn('endswith(".md")', src)
        self.assertIn("doc_files_in_main_not_in_lane", src)


class PollerLiveCountTest(unittest.TestCase):
    """poller 三栏分类（活/历史残留/无法验活）——假红与漏红两种误读都要被挡住。"""

    class _P:
        def __init__(self, identity, last="seconds: 1"):
            self.identity = identity
            self.last_access_time = last

    def test_live_stale_and_unverifiable_are_separated(self):
        me = os.getpid()
        pollers = [self._P("%d@192.0.2.132" % me),      # 活（就是本进程）
                   self._P("999999@192.0.2.132"),       # 已死 ⇒ 历史残留，不算活
                   self._P("no-pid@host")]                # 无 pid ⇒ 无法验活
        live, stale_hist, unver = eo.classify_pollers(pollers, {"192.0.2.132"}, shared.pid_alive)
        self.assertEqual([x["identity"] for x in live], ["%d@192.0.2.132" % me])
        self.assertEqual([x["identity"] for x in stale_hist], ["999999@192.0.2.132"])
        self.assertEqual([x["identity"] for x in unver], ["no-pid@host"])
        self.assertIn("历史残留", stale_hist[0]["note"])
        self.assertIn("无法验活", unver[0]["note"])

    def test_foreign_host_alias_is_annotation_only(self):
        """host 段不在本机别名集里**不**等于不可验：实测 identity 用 192.0.2.132，
        而我们连的是 127.0.0.1:7233 —— 若按 host 判就会把活 poller 读成 0（假红）。"""
        me = os.getpid()
        live, _s, unver = eo.classify_pollers([self._P("%d@10.0.0.9" % me)], set(),
                                              shared.pid_alive)
        self.assertEqual(len(live), 1)
        self.assertFalse(live[0]["host_is_local_alias"])
        self.assertIn("仍按 pid 验活", live[0]["host_note"])
        self.assertEqual(unver, [])


class WhoParsingTest(unittest.TestCase):
    """`who` 的事件解析：oneof 未设置时取属性会拿到**默认实例**（identity=''）。"""

    class _T:
        def __init__(self, iso="2026-09-30T12:00:00"):
            self._iso = iso

        def ToDatetime(self):
            return datetime.datetime.fromisoformat(self._iso)

    class _Attrs:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class _Type:
        def __init__(self, name):
            self.name = name

    class _Ev:
        def __init__(self, eid, attrs_name=None, **attrs):
            self.event_id = eid
            self.event_time = WhoParsingTest._T()
            self._set = set()
            for an in ("activity_task_scheduled_event_attributes",
                       "activity_task_started_event_attributes"):
                setattr(self, an, WhoParsingTest._Attrs())
            if attrs_name:
                self._set.add(attrs_name)
                setattr(self, attrs_name, WhoParsingTest._Attrs(**attrs))

        def HasField(self, name):
            return name in self._set

    def test_started_events_are_paired_with_scheduled_activity_type(self):
        evs = [
            self._Ev(1, "activity_task_scheduled_event_attributes",
                     activity_type=self._Type("run_integration_tests")),
            self._Ev(2, "activity_task_started_event_attributes",
                     identity="63268@host", scheduled_event_id=1, attempt=1),
            # oneof 未设置的事件（Completed/TimedOut 等）：不得被读成「identity 空的 started」
            self._Ev(3),
            self._Ev(4, "activity_task_scheduled_event_attributes",
                     activity_type=self._Type("append_event_ledger")),
            self._Ev(5, "activity_task_started_event_attributes",
                     identity="36741@host", scheduled_event_id=4, attempt=2),
        ]
        rows = eo._history_rows(evs)
        self.assertEqual(len(rows), 2, "未设置 oneof 的事件不许混进来")
        self.assertEqual(rows[0]["activity"], "run_integration_tests")
        self.assertEqual(rows[0]["identity"], "63268@host")
        self.assertEqual(rows[1]["activity"], "append_event_ledger")
        self.assertEqual(rows[1]["attempt"], 2)
        self.assertEqual(rows[0]["at"], "2026-09-30T12:00:00")


class RestartIsKillOnlyTest(unittest.TestCase):
    """宿主 260930 纠正：`restart` **只 kill、等 supervisor 自动拉起**，绝不自己起 worker。

    为什么（实况）：从 agent 会话起的 worker 会继承该会话沙箱（workspace-write）→ 工作区外
    写 fail-closed，真票 t260930-09 归档直接
    `PermissionError: [Errno 1] Operation not permitted: '…/.sandbar/projects/sandbar/data/tickets/t260930-09'`
    → merge/blocked。所以「自己起」这条路必须在**源码面**被钉死（机械断言，不靠自觉）。"""

    def test_restart_module_has_no_self_spawn_path(self):
        src = pathlib.Path(eo.__file__).read_text("utf-8")
        body = src[src.index("def _kill_and_wait_for_respawn"):
                   src.index("# ---------------------------------------------------------------- CLI")]
        for frag in ("spawn_ticket_worker", "reap_ticket_worker", "Popen(",
                     "subprocess.run(", "--daemon", "worker.py"):
            self.assertNotIn(frag, body,
                             "restart 路径里出现自起 worker 的痕迹：%s" % frag)
        # 全模块层面也不许再引用既有 spawn 面（`ticket_worker` 只用于 pidfile 定位）
        for frag in ("spawn_ticket_worker", "reap_ticket_worker", "--daemon"):
            self.assertNotIn(frag, src, "模块里残留自起面：%s" % frag)
        # 纪律必须出现在输出提示里（人读到的话术不许再出现「自己起」的鼓励）
        self.assertIn("绝不自己起 worker", src)
        self.assertIn("kill-and-wait-for-respawn", src)

    def _fixture(self, tmp, drain_s=0.0):
        """夹具：一个「旧 worker」进程（TERM 后按 drain_s 慢排空）+ 一个假 supervisor 线程。

        假 supervisor = console keepalive 的替身：看到 pidfile 里那颗死了 ⇒ 把**新**的活
        进程 pid 写进去。poller 面在本 UT 里被注入（`eo._queue_pollers`）——真面要 Temporal，
        而这里要钉的是**四段判据本身的时序**（宿主 26090 打回：单次采样 + 旧进程排空中
        必然假红）。"""
        (tmp / "server" / "engine" / "data").mkdir(parents=True, exist_ok=True)
        pf = tmp / "server" / "engine" / "data" / "worker-t9.pid"

        ready = tmp / "old-ready"

        def _slow_old():
            code = ("import signal, sys, time, pathlib\n"
                    "signal.signal(signal.SIGTERM, lambda *a: (time.sleep(%r), sys.exit(0)))\n"
                    "pathlib.Path(%r).write_text('ready')\n"
                    "while True: time.sleep(0.1)\n" % (drain_s, str(ready)))
            return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

        old = _slow_old()
        # 必须等它**装好信号处理**再发 TERM：否则 TERM 早到=默认动作直接杀死，
        # 测的就不是「排空慢」（实测这条把「永不排空」子用例变成了 respawn）。
        t_ready = time.time()
        while not ready.exists() and time.time() - t_ready < 10:
            time.sleep(0.05)
        pf.write_text(str(old.pid), encoding="utf-8")
        state = {"new": None}

        def _supervisor():
            """**旧进程还在排空时**就把新 worker 拉起来（宿主实报的那一帧）：

            真 console keepalive 的判据是 pidfile 里的 pid 死没死；换手瞬间 pidfile 可能已被
            新进程改写、而旧进程仍在优雅排空 ⇒「旧仍活 + 新已在」是**合法中间态**。
            本替身直接模拟这一帧（不依赖旧进程何时死），因为 UT 要钉的是**工具的判据**。"""
            time.sleep(0.5)
            newp = _spawn_sleeper()                  # 本文件的 helper 返回 Popen
            state["new"] = newp.pid
            pf.write_text(str(newp.pid), encoding="utf-8")

        state["stop"] = False
        import threading
        th = threading.Thread(target=_supervisor, daemon=True)
        th.start()
        return pf, old, state, th

    def _patch_poller_face(self, live_pids_fn):
        """注入 poller 面：活 poller = live_pids_fn() 给出的 pid 集（其余分栏照实现）。"""
        orig = eo._queue_pollers

        def _fake(host, ns, queue):
            pids = [int(x.pid if hasattr(x, "pid") else x) for x in live_pids_fn()]
            return {"queue": queue, "available": True,
                    "live": [{"identity": "%d@127.0.0.1" % p, "last_access_time": "seconds: 1",
                              "host": "127.0.0.1", "host_is_local_alias": True}
                             for p in pids],
                    "stale_history": [], "unverifiable": [], "live_count": len(pids),
                    "note": "注入面（UT：只钉四段时序）"}

        eo._queue_pollers = _fake
        self.addCleanup(lambda: setattr(eo, "_queue_pollers", orig))

    def test_slow_draining_old_worker_is_not_a_failure(self):
        """宿主打回 ①：旧进程**慢排空**（排空期间新 pid 已在）⇒ 不判失败、中间态具名、最终成功。"""
        import argparse
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-ops-drain-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        pf, old, state, th = self._fixture(tmp, drain_s=4.0)
        self.addCleanup(lambda: state.update(stop=True))
        # poller 面：新 pid 一出现就在轮询；旧 pid 在它活着时**也**算活 poller（真实世界如此）
        self._patch_poller_face(lambda: ([state["new"]] if state["new"] else []) +
                                ([old.pid] if shared.pid_alive(old.pid) else []))
        data_backup, engine_backup = eo.DATA, eo.ENGINE
        tw_backup = (eo.tw.POC_DIR, eo.tw.DATA_DIR, eo.tw.VENV_PY)
        eo.DATA, eo.ENGINE = tmp, tmp / "server" / "engine"
        eo.tw.set_root(tmp / "server" / "engine")
        try:
            ns = argparse.Namespace(host="127.0.0.1:1", ns="default", repo="", scope="lane:t9",
                                    replace=True, wait=20.0, old_drain=30.0)
            res = eo.cmd_restart(ns)
        finally:
            eo.DATA, eo.ENGINE = data_backup, engine_backup
            eo.tw.POC_DIR, eo.tw.DATA_DIR, eo.tw.VENV_PY = tw_backup
        if res.get("ok") is not True:
            print("res:", str(res)[:700])
        self.assertTrue(res["ok"], "慢排空 + supervisor 已起新 pid ⇒ 必须判成功（不给假红）")
        r = res["result"]
        self.assertEqual(r["phase_failed"] if "phase_failed" in r else "", "")
        drain = next(p for p in r["phases"] if p["phase"] == "old-drain")
        self.assertTrue(drain["drained"])
        self.assertTrue(drain["new_pid_seen_while_draining"],
                        "排空期间的「新 pid 已在」这一合法中间态必须具名")
        # 采样序列里必须出现「旧仍在 + 新已见」那一帧（正是单次采样会误判的那一帧）
        mid = [x for x in r["samples"]
               if x["phase"] == "old-drain" and x["old_alive"]
               and x["new_pid_seen_while_draining"]]
        self.assertTrue(mid, "采样里没有中间态帧（判据不是轮询式）")
        self.assertEqual(int(r["new_pid"]), int(state["new"]))
        old.kill()
        if state["new"]:
            os.kill(int(state["new"]), signal.SIGKILL)

    def test_old_worker_never_drains_names_that_phase_and_starts_nothing(self):
        """宿主打回 ②：旧进程**永不排空** ⇒ 具名超时（点名 old-drain 段）且没起任何东西。"""
        import argparse
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-ops-nodrain-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "server" / "engine" / "data").mkdir(parents=True, exist_ok=True)
        pf = tmp / "server" / "engine" / "data" / "worker-t9.pid"
        ready = tmp / "stubborn-ready"
        code = ("import signal, time, pathlib\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "pathlib.Path(%r).write_text('ready')\n"
                "while True: time.sleep(0.1)\n" % str(ready))
        stubborn = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        t_ready = time.time()
        while not ready.exists() and time.time() - t_ready < 10:
            time.sleep(0.05)
        self.addCleanup(lambda: stubborn.kill() if stubborn.poll() is None else None)
        pf.write_text(str(stubborn.pid), encoding="utf-8")
        self._patch_poller_face(lambda: [stubborn.pid])
        data_backup, engine_backup = eo.DATA, eo.ENGINE
        tw_backup = (eo.tw.POC_DIR, eo.tw.DATA_DIR, eo.tw.VENV_PY)
        eo.DATA, eo.ENGINE = tmp, tmp / "server" / "engine"
        eo.tw.set_root(tmp / "server" / "engine")
        try:
            ns = argparse.Namespace(host="127.0.0.1:1", ns="default", repo="", scope="lane:t9",
                                    replace=True, wait=2.0, old_drain=1.5)
            res = eo.cmd_restart(ns)
        finally:
            eo.DATA, eo.ENGINE = data_backup, engine_backup
            eo.tw.POC_DIR, eo.tw.DATA_DIR, eo.tw.VENV_PY = tw_backup
        self.assertFalse(res["ok"])
        self.assertEqual(res["result"]["phase_failed"], "old-drain")
        self.assertIn("未排空", res["error"])
        self.assertIn("不自己起 worker", res["error"])
        self.assertEqual(pf.read_text(encoding="utf-8").strip(), str(stubborn.pid))
        self.assertEqual(sorted(p.name for p in pf.parent.iterdir()), [pf.name],
                         "旧未排空路径不得产生任何新文件（没起东西）")

    def test_absent_supervisor_times_out_named_and_starts_nothing(self):
        """supervisor 缺席：有界等待超时 ⇒ 具名告警（点名查 supervisor）且**零新进程/文件**。"""
        import argparse
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-ops-killonly-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "server" / "engine" / "data").mkdir(parents=True, exist_ok=True)
        pf = tmp / "server" / "engine" / "data" / "worker-t9.pid"
        proc = _spawn_sleeper()
        self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
        pf.write_text(str(proc.pid), encoding="utf-8")
        data_backup, engine_backup = eo.DATA, eo.ENGINE
        tw_mod = eo.tw
        tw_backup = (tw_mod.POC_DIR, tw_mod.DATA_DIR, tw_mod.VENV_PY)
        eo.DATA, eo.ENGINE = tmp, tmp / "server" / "engine"
        # lane 档的 pidfile 由 ticket_worker 按「目标仓」推导 ⇒ 必须一起重定向（=--repo 的行为）
        tw_mod.set_root(tmp / "server" / "engine")
        try:
            ns = argparse.Namespace(host="127.0.0.1:1", ns="default", repo="", scope="lane:t9",
                                    replace=True, wait=1.5, old_drain=5.0)
            res = eo.cmd_restart(ns)
        finally:
            eo.DATA, eo.ENGINE = data_backup, engine_backup
            tw_mod.POC_DIR, tw_mod.DATA_DIR, tw_mod.VENV_PY = tw_backup
        self.assertFalse(res["ok"])
        self.assertEqual(res["exit"], 1)
        self.assertIn("supervisor 未在", res["error"])
        self.assertEqual(res["result"]["phase_failed"], "respawn")
        self.assertIn("不自己起 worker", res["error"])
        self.assertEqual(pf.read_text(encoding="utf-8").strip(), str(proc.pid),
                         "超时路径不得改写 pidfile（没起任何东西）")
        self.assertEqual(sorted(p.name for p in pf.parent.iterdir()), [pf.name],
                         "超时路径不得产生新文件（日志/pid/.meta 都不许有）")
        # 旧 worker 确实收到了 TERM（kill-only 的那一半是真的）
        self.assertTrue(_wait_gone(proc))


def _wait_gone(proc, timeout=10.0) -> bool:
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < timeout:
        if proc.poll() is not None:
            return True
        _t.sleep(0.1)
    return proc.poll() is not None


class WiringStaleFaceTest(unittest.TestCase):
    """t261011-04 L3: the operator faces must NAME a stale wiring module.

    A worker stale only on ``workflows.py``/``activities.py`` used to be
    invisible (the stamp did not track them). Both operator faces
    (``engine_ops workers`` / ``engine_ops drift``) render ``stamp["stale"]``
    and ``stamp["stamp_line"]`` verbatim — into the worker row and into the
    drift alert text — so this pins that the module names reach both faces
    instead of only a count or an empty list.
    """

    FAKE_STAMP = {
        "available": True,
        "worker_started_at": "2026-10-09T20:20:59",
        "worker_pid": 28404,
        "modules": {},
        "stale": ["workflows", "activities"],
        "stamp_line": "worker pid=28404 started=2026-10-09T20:20:59 "
                      "stale=workflows,activities",
    }

    def test_stamp_for_names_wiring_modules_on_fixture_repo(self):
        # Real stamp_for, fixture repo: workflows.py/activities.py newer than
        # the worker baseline => the payload the faces embed names them.
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-ops-wiring-"))
        try:
            for name in ("workflows", "activities"):
                fp = tmp / "server" / "engine" / ("%s.py" % name)
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text("# wiring\n", encoding="utf-8")
            base = (datetime.datetime.now()
                    - datetime.timedelta(minutes=5)).isoformat(timespec="seconds")
            st = eo.stamp_for(None, str(tmp), base)
            self.assertTrue(st["available"])
            self.assertEqual(sorted(st["stale"]), ["activities", "workflows"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _patched_drift_env(self, tmp):
        lane = {"path": str(tmp / "lane"), "branch": "lane/t-x",
                "source": "fixture", "available": True, "note": ""}
        pid_row = {"state": "live", "pid": 28404, "raw": "28404",
                   "started_at": "2026-10-09T20:20:59", "detail": "", "meta": {}}

        def _fake_git(args, cwd):
            # merge-base -> a ref; rev-list --count -> 0; diff --name-only -> none.
            if "merge-base" in args:
                return (0, "abc123def")
            if "--count" in args:
                return (0, "0")
            if "--name-only" in args:
                return (0, "")
            return (0, "")

        return (
            mock.patch.object(eo, "_lane_paths", return_value=lane),
            mock.patch.object(eo, "git", side_effect=_fake_git),
            mock.patch.object(eo, "DATA", tmp),
            mock.patch.object(eo, "read_pidfile", return_value=pid_row),
            mock.patch.object(eo, "tree_of_pid",
                              return_value={"tree": str(tmp / "tree"),
                                            "available": True, "note": "",
                                            "pid": 28404, "exe": "",
                                            "cwd": str(tmp / "tree")}),
            mock.patch.object(eo, "repo_root_from_tree", return_value=str(tmp)),
            mock.patch.object(eo, "stamp_for",
                              return_value=dict(self.FAKE_STAMP)),
            mock.patch.object(eo, "_queues_of", return_value=["q1"]),
            mock.patch.object(eo, "_queue_pollers",
                              return_value={"queue": "q1", "available": False,
                                            "live": [], "stale_history": [],
                                            "unverifiable": [],
                                            "live_count": 0, "note": "fixture"}),
        )

    def test_workers_face_carries_wiring_module_names(self):
        # The workers row embeds stamp["stale"] + stamp_line verbatim.
        w = {"kind": "central", "ticket": "", "pid": 28404,
             "pidfile": "/tmp/worker.pid", "state": "live", "detail": "",
             "started_at": "2026-10-09T20:20:59", "meta_repo_root": "/r",
             "cwd": "/r", "tree": "/r", "tree_available": True,
             "tree_note": "", "queues": [], "stamp": dict(self.FAKE_STAMP)}
        with mock.patch.object(eo, "_enumerate_workers", return_value=[w]), \
                mock.patch.object(eo, "_queue_pollers",
                                  return_value={"queue": "sandbar",
                                                "available": False, "live": [],
                                                "stale_history": [],
                                                "unverifiable": [],
                                                "live_count": 0,
                                                "note": "fixture"}):
            args = argparse.Namespace(host=None, ns=None)
            res = eo.cmd_workers(args)
        rendered = json.dumps(res["result"]["workers"])
        self.assertIn("workflows", rendered)
        self.assertIn("activities", rendered)
        self.assertIn("stale=workflows,activities", rendered,
                      "stamp_line (what the operator reads) must name the module")

    def test_drift_alert_names_wiring_modules(self):
        # cmd_drift gates the stamp on the pidfile existing under DATA — that
        # gate stays real code; only the process-side lookups are fixtures.
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-ops-drift-"))
        (tmp / "worker-t-x.pid").write_text("28404", encoding="utf-8")
        try:
            patches = self._patched_drift_env(tmp)
            with patches[0], patches[1], patches[2], patches[3], patches[4], \
                    patches[5], patches[6], patches[7], patches[8]:
                args = argparse.Namespace(host=None, ns=None, ticket="t-x")
                res = eo.cmd_drift(args)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        stamp = res["result"]["lane_worker"]["stamp"]
        self.assertEqual(sorted(stamp["stale"]), ["activities", "workflows"])
        # The alert text names the module, not only a count.
        self.assertTrue(any("workflows" in a and "activities" in a
                            for a in res["result"]["alerts"]),
                        res["result"]["alerts"])
        # The one-line error names each module, not only a count.
        self.assertIn("workflows", res["error"])
        self.assertIn("activities", res["error"])


if __name__ == "__main__":
    unittest.main()
