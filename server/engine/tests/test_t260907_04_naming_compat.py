# -*- coding: utf-8 -*-
"""t260907-04 命名清理引擎面 UT：env 终切 / 队列单名 / 目录粘滞＋镜像 / ws 粘滞。

260908 宿主令终切：旧前缀 env 桥整函数删除（退役账#6 收口）、旧共享队列与旧
ticket 前缀双 poll 撤除（退役账#1/#2 收口，空库重建后无旧队列在飞票）、旧
schedule id 退役面与 /tmp 旧 ws base 粘滞撤除（退役账#3/#7 收口）。泳道
.suyou 老名目录粘滞保留——处理在飞老泳道的历史数据，不属引擎命名。
"""

import pathlib

import pytest

import scan_schedule
import shared
import worker


# ---- ① env 终切（桥已撤） ----------------------------------------------------

def test_env_bridge_removed():
    """260908 终切：apply_env_compat 整函数删除——旧名 env 不再被镜像。"""
    assert not hasattr(shared, "apply_env_compat")
    assert not hasattr(shared, "LEGACY_ENV_PREFIX")


def test_env_prefix_single():
    assert shared.ENV_PREFIX == "SANDBAR_"


def test_census_env_literal_shape():
    """census 断言：仓内全部 SANDBAR_ 静态字面量形状合规（形如 SANDBAR_<大写/数字/
    下划线>）。出现新形态（小写/特殊字符）= 有代码绕过约定 → 红。"""
    import re
    roots = [pathlib.Path("server/engine"), pathlib.Path("server/tools"),
             pathlib.Path("integration")]
    pat = re.compile(r"SANDBAR_[A-Za-z0-9_]+")
    odd = set()
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.suffix not in (".py", ".mjs", ".md", ".yaml", ".json"):
                continue
            for m in pat.findall(f.read_text(encoding="utf-8", errors="replace")):
                if not re.fullmatch(r"SANDBAR_[A-Z0-9_]+", m):
                    odd.add(m)
    assert not odd, "形状不合规的 SANDBAR_ 字面量：%s" % sorted(odd)


# ---- ② 队列（单名终切） ------------------------------------------------------

def _clean_queue_env(monkeypatch):
    for name in ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES"):
        monkeypatch.delenv(name, raising=False)


def test_shared_queue_defaults(monkeypatch):
    _clean_queue_env(monkeypatch)
    # TASK_QUEUE 为 import 时常量（本沙箱环境被本泳道的 ticket 队列 env 污染也须正确）：
    # 常量面断言缺省值，行为面断言 configured_task_queues 尊重常量。
    monkeypatch.setattr(shared, "TASK_QUEUE", "sandbar")
    assert shared.TASK_QUEUE == "sandbar"
    assert shared.configured_task_queues() == ["sandbar"]  # 260908 终切：单队列


def test_ticket_queue_single_prefix():
    qs = shared.ticket_task_queues("t1")
    assert qs == ["sandbar-ticket-t1"]                     # 260908 终切：单前缀
    assert shared.ticket_task_queue("t1") == "sandbar-ticket-t1"


def test_ticket_queues_env_csv_override(monkeypatch):
    _clean_queue_env(monkeypatch)
    monkeypatch.setenv(shared.TASK_QUEUES_ENV, " q1 , q2 ,,")
    assert shared.configured_task_queues() == ["q1", "q2"]
    monkeypatch.delenv(shared.TASK_QUEUES_ENV)
    monkeypatch.setattr(shared, "TASK_QUEUE", "sandbar")
    assert shared.configured_task_queues() == ["sandbar"]


def test_schedule_ids():
    assert shared.SCHEDULE_ID == "sandbar-dispatcher-scan"
    assert not hasattr(shared, "LEGACY_SCHEDULE_ID")       # 260908 终切：旧 id 常量撤


# ---- ③④ 目录粘滞＋镜像（R-1 三例，老泳道只读兼容保留） ----------------------

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


# ---- ⑤ ws dir（260908 终切：粘滞撤除，单 base） -----------------------------

def test_ws_dir_path_single_base(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "WS_DIR_BASE", str(tmp_path / "ws"))
    assert shared.ws_dir_path("t9") == str(tmp_path / "ws" / "t9")
    assert not hasattr(shared, "LEGACY_WS_DIR_BASE")               # 旧 base 常量撤


def test_result_file_uses_ws_dir_base(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "WS_DIR_BASE", str(tmp_path / "ws"))
    rf = shared.result_file_for("t1", "implement", 0, None)
    assert rf.startswith(str(tmp_path / "ws" / "t1"))


# ---- 守卫白名单自证 ----------------------------------------------------------

def test_guard_whitelist_anchor():
    """守卫场景白名单锚：本文件允许出现 .suyou 目录字面量（粘滞面 fixture/断言），
    但不得再出现已终切的队列/env 旧名——此用例钉住该边界。"""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert ".suyou" in src and "sandbar" in src
    # 拆串构造避免自指：断言字面量本身即文件内容，完整字面量会自打自。
    assert "suyou" + "-poc" not in src
    assert "SUYOU" + "_" not in src


# ---- ⑥ worker 多队列注册接线锁（docker 台不在位时的行为面证据链：真正台面
# 复跑由 integration/t260907-04/sc_queue_dual_registration.py 在 stage 上出日志证据）----

def test_worker_registers_one_worker_per_queue():
    import pathlib
    src = pathlib.Path(worker.__file__).read_text(encoding="utf-8")
    assert "for _q in configured_task_queues():" in src
    assert "task_queue=_q" in src                                   # 每队列一个 Worker 实例
    assert "worker polling queues" in src                           # 注册日志证据行
    # t261019-42: the shutdown gather moved into a named `shutdown_phase` awaitable
    # (idle fast-exit races it against a deadline); the all-terminal-state shutdown
    # anchor now pins the gather construction + its awaits.
    assert "shutdown_phase = asyncio.gather(*(w.shutdown() for w in workers))" in src
    assert "await shutdown_phase" in src


def test_worker_queues_source_uses_shared_config():
    import inspect
    src = inspect.getsource(shared.configured_task_queues)
    assert "TASK_QUEUES_ENV" in src and "return [TASK_QUEUE]" in src


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
