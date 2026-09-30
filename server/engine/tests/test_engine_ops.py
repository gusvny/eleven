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

import datetime
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

POC = pathlib.Path(__file__).resolve().parent.parent
REPO = POC.parents[1]
sys.path.insert(0, str(POC))
sys.path.insert(0, str(REPO / "server" / "tools"))

import shared  # noqa: E402
sys.path.insert(0, str(REPO / "server" / "tools"))
import engine_ops as eo  # noqa: E402


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time\nwhile True: time.sleep(0.2)"])


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
        import shutil
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
        import shutil
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


if __name__ == "__main__":
    unittest.main()
