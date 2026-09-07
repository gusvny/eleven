# -*- coding: utf-8 -*-
"""t260907-04 命名清理引擎面 UT：env 双向桥 / 队列双 poll / 目录粘滞＋镜像 / ws 粘滞。

设计依据 = .suyou/stage_create_plan_gen2.json（review gen2 conditional 放行案）。
env 桥语义：SANDBAR_* 新名优先；双向桥单侧互补；畸形输入不炸不静默丢。
"""

import json
import pathlib

import pytest

import demo_schedule
import scan_schedule
import shared
import worker


# ---- ① env 双向桥 -----------------------------------------------------------

def test_env_bridge_legacy_only():
    env = {"SUYOU_AGENT_CMD": "stub"}
    shared.apply_env_compat(env)
    assert env["SANDBAR_AGENT_CMD"] == "stub"


def test_env_bridge_new_only_backfills_legacy():
    env = {"SANDBAR_AGENT_CMD": "stub"}
    shared.apply_env_compat(env)
    assert env["SUYOU_AGENT_CMD"] == "stub"          # 插件面旧读侧过渡期仍可读


def test_env_bridge_conflict_new_wins():
    env = {"SUYOU_AGENT_CMD": "old", "SANDBAR_AGENT_CMD": "new"}
    shared.apply_env_compat(env)
    assert env["SANDBAR_AGENT_CMD"] == "new"
    assert env["SUYOU_AGENT_CMD"] == "new"           # 冲突时旧名被新名覆盖


def test_env_bridge_malformed_values_no_crash():
    env = {"SUYOU_EMPTY": "", "SUYOU_JSON": "{bad json", "SUYOU_BIG": "x" * 100000}
    shared.apply_env_compat(env)
    assert env["SANDBAR_EMPTY"] == ""                # 空值是合法值，不丢
    assert env["SANDBAR_JSON"] == "{bad json"        # 非结构内容原样透传
    assert env["SANDBAR_BIG"] == "x" * 100000


def test_env_bridge_idempotent():
    env = {"SUYOU_AGENT_CMD": "stub"}
    shared.apply_env_compat(env)
    once = dict(env)
    shared.apply_env_compat(env)
    assert env == once


def test_census_bridge_covers_write_set_literals():
    """census 自愈断言：写集内全部 SUYOU_ 静态字面量必须能被前缀桥映射覆盖
    （即形如 SUYOU_<大写/数字/下划线>）。出现新形态（小写/特殊字符）= 桥失效 → 红。"""
    import re
    roots = [pathlib.Path("server/dsh/temporal-poc"), pathlib.Path("server/tools"),
             pathlib.Path("integration")]
    pat = re.compile(r"SUYOU_[A-Za-z0-9_]+")
    odd = set()
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.suffix not in (".py", ".mjs", ".md", ".yaml", ".json"):
                continue
            for m in pat.findall(f.read_text(encoding="utf-8", errors="replace")):
                if not re.fullmatch(r"SUYOU_[A-Z0-9_]+", m):
                    odd.add(m)
    assert not odd, "前缀桥覆盖不了的 SUYOU_ 字面量：%s" % sorted(odd)


# ---- ② 队列 ----------------------------------------------------------------

def _clean_queue_env(monkeypatch):
    for name in ("SANDBAR_TASK_QUEUE", "SUYOU_TASK_QUEUE", shared.TASK_QUEUES_ENV):
        monkeypatch.delenv(name, raising=False)


def test_shared_queue_defaults(monkeypatch):
    _clean_queue_env(monkeypatch)
    # TASK_QUEUE 为 import 时常量（本沙箱环境被本泳道的 ticket 队列 env 污染也须正确）：
    # 常量面断言缺省值，行为面断言 configured_task_queues 尊重常量。
    monkeypatch.setattr(shared, "TASK_QUEUE", "sandbar")
    assert shared.TASK_QUEUE == "sandbar"
    assert shared.LEGACY_TASK_QUEUE == "suyou-poc"
    assert shared.configured_task_queues() == ["sandbar", "suyou-poc"]  # 双 poll 证据口径


def test_ticket_queue_dual_prefix():
    qs = shared.ticket_task_queues("t1")
    assert qs == ["sandbar-ticket-t1", "suyou-ticket-t1"]
    assert shared.ticket_task_queue("t1") == "sandbar-ticket-t1"


def test_ticket_queues_env_csv_override(monkeypatch):
    _clean_queue_env(monkeypatch)
    monkeypatch.setenv(shared.TASK_QUEUES_ENV, " q1 , q2 ,,")
    assert shared.configured_task_queues() == ["q1", "q2"]
    monkeypatch.delenv(shared.TASK_QUEUES_ENV)
    monkeypatch.setattr(shared, "TASK_QUEUE", "sandbar")
    assert shared.configured_task_queues() == ["sandbar", "suyou-poc"]


def test_schedule_ids():
    assert shared.SCHEDULE_ID == "sandbar-dispatcher-scan"
    assert shared.LEGACY_SCHEDULE_ID == "suyou-dispatcher-scan"


# ---- ③④ 目录粘滞＋镜像（R-1 三例） -----------------------------------------

def test_dot_dir_new_lane_sticks_to_new_name_after_mirror(tmp_path):
    """R-1 例①：新 base 首写后（镜像已造出 .suyou）第二进程解析仍新名，不翻转。"""
    d = shared.resolve_dot_dir(tmp_path, create=True)
    assert d == tmp_path / ".sandbar"
    src = d / "screenshots" / "a.png"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("png", encoding="utf-8")
    assert shared.mirror_to_legacy(tmp_path, pathlib.Path("screenshots") / "a.png")
    assert (tmp_path / ".suyou" / "screenshots" / "a.png").exists()  # 镜像已造旧名
    d2 = shared.resolve_dot_dir(tmp_path)          # 模拟下一段独立进程现算
    assert d2 == tmp_path / ".sandbar", "镜像目录不得参与粘滞判定（R-1）"


def test_dot_dir_legacy_lane_sticky(tmp_path):
    """R-1 例②：纯 .suyou 老泳道整生命周期旧名，绝不去新名。"""
    (tmp_path / ".suyou").mkdir()
    (tmp_path / ".suyou" / "stage_old.json").write_text("{}", encoding="utf-8")
    assert shared.resolve_dot_dir(tmp_path) == tmp_path / ".suyou"
    assert shared.resolve_dot_dir(tmp_path, create=True) == tmp_path / ".suyou"


def test_engine_reads_never_touch_mirror(tmp_path):
    """R-1 例③：读点（交接/归档同序解析）永不落镜像目录——镜像侧多出新 stage
    文件也不进引擎读面。"""
    d = shared.resolve_dot_dir(tmp_path, create=True)
    (d / "stage_new.json").write_text("{}", encoding="utf-8")
    src = d / "screenshots" / "a.png"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("png", encoding="utf-8")
    assert shared.mirror_to_legacy(tmp_path, pathlib.Path("screenshots") / "a.png")
    (tmp_path / ".suyou" / "stage_ghost.json").write_text("{}", encoding="utf-8")
    found = sorted(p.name for p in d.glob("stage_*.json"))
    assert found == ["stage_new.json"]


def test_mirror_scope_whitelist(tmp_path):
    """镜像只保插件面真实读点（screenshots/epic-next）；stage json 等不镜像。"""
    shared.resolve_dot_dir(tmp_path, create=True)
    for rel in ("screenshots/a.png", "epic-next/e1/pre.json", "stage_x.json", "evidence/a.png"):
        p = tmp_path / ".sandbar" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        shared.mirror_to_legacy(tmp_path, pathlib.Path(rel))
    assert (tmp_path / ".suyou" / "screenshots" / "a.png").exists()
    assert (tmp_path / ".suyou" / "epic-next" / "e1" / "pre.json").exists()
    assert not (tmp_path / ".suyou" / "stage_x.json").exists()
    assert not (tmp_path / ".suyou" / "evidence").exists()


def test_lane_dot_path_result_file_legacy_lane(tmp_path):
    """写点走帮手：老泳道 result/agent log 落旧名（不许盲 sed 绕过粘滞）。"""
    (tmp_path / ".suyou").mkdir()
    ws = {"path": str(tmp_path)}
    rf = shared.result_file_for("t1", "implement", 0, ws)
    lf = shared.agent_log_for("t1", "implement", 0, ws)
    assert rf.startswith(str(tmp_path / ".suyou" / "stage_implement_gen0.json"))
    assert lf.startswith(str(tmp_path / ".suyou" / "agent_implement_gen0.log"))


def test_result_file_new_lane(tmp_path):
    ws = {"path": str(tmp_path)}
    rf = shared.result_file_for("t1", "implement", 0, ws)
    assert ".sandbar/stage_implement_gen0.json" in rf


# ---- ⑤ ws dir 粘滞 ----------------------------------------------------------

def test_ws_dir_path_sticky(tmp_path, monkeypatch):
    legacy_root = tmp_path / "old-ws"
    (legacy_root / "t9").mkdir(parents=True)
    monkeypatch.setattr(shared, "WS_DIR_BASE", str(tmp_path / "new-ws"))
    monkeypatch.setattr(shared, "LEGACY_WS_DIR_BASE", str(legacy_root))
    assert shared.ws_dir_path("t9") == str(legacy_root / "t9")     # 在飞粘滞
    assert shared.ws_dir_path("t-new") == str(tmp_path / "new-ws" / "t-new")


def test_result_file_uses_ws_dir_sticky_base(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "WS_DIR_BASE", str(tmp_path / "new-ws"))
    monkeypatch.setattr(shared, "LEGACY_WS_DIR_BASE", str(tmp_path / "old-ws"))
    (tmp_path / "old-ws" / "t1").mkdir(parents=True)
    rf = shared.result_file_for("t1", "implement", 0, None)
    assert rf.startswith(str(tmp_path / "old-ws" / "t1"))


# ---- 守卫白名单自证 ----------------------------------------------------------

def test_guard_whitelist_anchor():
    """守卫场景白名单锚：本文件允许出现旧名字面量（fixture/断言），此用例钉住该约定。"""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "suyou-poc" in src and ".suyou" in src


# ---- ⑥ worker 多队列注册接线锁（docker 台不在位时的行为面证据链：真正台面
# 复跑由 integration/t260907-04/sc_queue_dual_registration.py 在 stage 上出日志证据）----

def test_worker_registers_one_worker_per_queue():
    import pathlib
    src = pathlib.Path(worker.__file__).read_text(encoding="utf-8")
    assert "for _q in configured_task_queues():" in src
    assert "task_queue=_q" in src                                   # 每队列一个 Worker 实例
    assert "worker polling queues" in src                           # 双注册日志证据行
    assert "await asyncio.gather(*(w.shutdown() for w in workers))" in src  # 全终态停机


def test_worker_queues_source_uses_shared_config():
    import inspect
    src = inspect.getsource(shared.configured_task_queues)
    assert "TASK_QUEUES_ENV" in src and "LEGACY_TASK_QUEUE" in src


# ---- ⑦ schedule 删旧接线（arbitrate gen0 打回项：创建走廊必须接删旧，
# 不得只挂人工运维路径——双调度窗口无界即打回形态）----

def test_retire_legacy_schedule_idempotent_with_stub():
    class FakeHandle:
        def __init__(self, log):
            self._log = log
        async def delete(self):
            self._log.append("delete")
    class FakeClient:
        def __init__(self, log):
            self._log = log
        def get_schedule_handle(self, schedule_id):
            assert schedule_id == shared.LEGACY_SCHEDULE_ID
            return FakeHandle(self._log)
    import asyncio
    log = []
    assert asyncio.run(scan_schedule.retire_legacy_schedule(FakeClient(log))) is True
    assert log == ["delete"]
    # 幂等：句柄不存在（RPCError）不炸且返回 False
    class GoneClient:
        def get_schedule_handle(self, schedule_id):
            class H:
                async def delete(self):
                    raise scan_schedule.RPCError("not found", None, None)
            return H()
    assert asyncio.run(scan_schedule.retire_legacy_schedule(GoneClient())) is False


def test_create_corridor_wires_legacy_retire():
    """创建走廊（demo_schedule）删旧接线锁：retire 调用须位于 create_schedule 之前——
    删旧只挂人工 resume 路径=双调度窗口无界（arbitrate gen0 打回形态）。"""
    import pathlib
    src = pathlib.Path(demo_schedule.__file__).read_text(encoding="utf-8")
    assert "await retire_legacy_schedule(client)" in src
    assert src.index("retire_legacy_schedule(client)") < src.index("create_schedule(")


# ---- ⑧ doc-gate 写失败降级（arbitrate gen1 打回项：粘滞解析的 mkdir 必须被
# 降级契约覆盖——只读 base 下 register 返回 error 不抛，main 行为即契约锚）----

def test_register_pending_doc_sync_readonly_base_degrades(tmp_path):
    import agent_activities
    import stat
    ro = tmp_path / "ro-base"
    ro.mkdir()
    conflicts = [{"ticket": "t1", "doc": "a.md", "claim": "c", "actual": "r"}]
    try:
        ro.chmod(0o500)  # 只读 base：mkdir 必败
        info = agent_activities.register_pending_doc_sync(ro, "t1", conflicts)
    finally:
        ro.chmod(0o755)
    assert info["registered"] == 0
    assert info["error"], "降级必须点名原因"
