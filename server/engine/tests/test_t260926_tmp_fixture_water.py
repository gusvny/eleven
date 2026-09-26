#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试夹具临时目录的**生产者回收**与**巡检水位判据**（260926 磁盘泄漏收口）。

背景（宿主追问「巡检为什么没发现」两次 + 实测）：`$TMPDIR` 顶层 407,294 个目录，其中
401,578 个 >6 小时未动（98.6%）——大头是各测试面 `mkdtemp` 出来的夹具。存量由
`integration/tools/sweep_tmp_fixtures.py` 清扫（一次性、可复核），**半边的生产者侧**在
本文件钉住：

  A. 引擎侧夹具回收（`_tmp_reclaim`）：注册表 + 进程退出 atexit 兜底 + 幂等回收；
  B. 两个真实泄漏源（`test_multirepo_anchor.py` / `test_multirepo_root_activity.py`）
     的**子进程级**回归：私有 $TMPDIR 里真跑一支用例，进程退出后前缀目录必须一个不留
     （配裸 `mkdtemp` 的**反证**：不经注册表就是会留下——证明本断言有牙不是恒真）；
  C. 拆台回收（`integration/stage_docker.py`）：`do_down` 收口回收本台三件临时物料
     （agent-presets 目录 2 万个/~383MB 是实报病灶；admin.log 影子与凭据副本同族）；
  D. 巡检第四判据（`inspection_lane_watchdog.tmp-fixture-water`）：纯判据正反例 +
     阈值来源（声明>env>缺省）逐键点名 + 畸形逐项降级 + **入口级端到端**（真活动壳、
     桩注册表/桩 Temporal、私有临时根；零写自证）；
  E. 机械闸：L8（`integration/lint_tests.py`：mkdtemp 无回收动词 → 警告级）行为锁 +
     白名单**单源漂移锁**（引擎判据面与清扫器同一份前缀清单）。

跑法：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t260926_tmp_fixture_water.py -q`（全程零网络/零真 Temporal/
零真 docker；子进程用例只跑 pytest 单支、且 $TMPDIR 指向私有目录）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent          # server/engine
REPO = POC.parent.parent
INTEG = REPO / "integration"
sys.path.insert(0, str(POC))
sys.path.insert(0, str(POC / "tests"))                # 同目录 _tmp_reclaim
sys.path.insert(0, str(INTEG))                        # integration/stage_docker.py（拆台面）

import activities  # noqa: E402
import inspection_decl as decl  # noqa: E402
import inspection_flow as flow  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import inspection_lane_watchdog as lw  # noqa: E402
import stage_docker as sd  # noqa: E402
import _tmp_reclaim as tr  # noqa: E402
from shared import PROJECT_SA_NAME  # noqa: E402
from temporalio.common import SearchAttributeKey  # noqa: E402

NOW = 1_790_430_000.0


# ========================================================================================
# A. 引擎侧夹具回收（注册表 + exit 钩子 + 幂等）
# ========================================================================================

def test_a1_registry_reaps_and_is_idempotent():
    """注册表的正常路径：建→在册→回收→出册；重复回收零条且不抛（幂等）。"""
    before = len(tr.live_tmp_dirs())
    p = tr.mkdtemp_reclaimed("t260926-water-ut-")
    assert p.is_dir() and len(tr.live_tmp_dirs()) == before + 1
    (p / "inner").mkdir()
    (p / "inner" / "f.txt").write_text("x", encoding="utf-8")
    n = tr.reap_live_tmp_dirs()
    assert n == before + 1 and not p.exists()
    assert tr.live_tmp_dirs() == []
    assert tr.reap_live_tmp_dirs() == 0            # 幂等：第二次零条
    assert tr.REAP_FAILURES == 0


def test_a2_externally_deleted_dir_is_not_a_failure():
    """别人先删了（或 rmtree 竞态）→ 回收面吞掉但不抛、不计失败（清理面不把套件跑红）。"""
    p = tr.mkdtemp_reclaimed("t260926-water-gone-")
    import shutil
    shutil.rmtree(str(p))
    fails = tr.REAP_FAILURES
    assert tr.reap_live_tmp_dirs() >= 1
    assert tr.REAP_FAILURES == fails and not p.exists()


def test_a3_atexit_hook_is_registered_at_import():
    """进程级兜底**真在**（正常/异常/早退都走解释器退出路径）——不是只写在注释里。"""
    import atexit as _atexit
    src = (POC / "tests" / "_tmp_reclaim.py").read_text(encoding="utf-8")
    assert "atexit.register(reap_live_tmp_dirs)" in src
    # 注册发生在 import 期（本测试已 import 过 → 检查模块标志而不是私有注册表）
    assert _atexit is not None and tr.reap_live_tmp_dirs.__name__ == "reap_live_tmp_dirs"


# ========================================================================================
# B. 两个真实泄漏源的子进程级回归（私有 $TMPDIR；含裸 mkdtemp 反证）
# ========================================================================================

LEAK_PREFIXES = ("t260907-06-ut-", "t260907-12-")


def _leftovers(root: Path):
    return sorted(n for n in os.listdir(root) if n.startswith(LEAK_PREFIXES))


def _run_child_pytest(tmp_root: Path, nodeid: str):
    env = dict(os.environ, TMPDIR=str(tmp_root))
    p = subprocess.run([sys.executable, "-m", "pytest", nodeid, "-q", "-p", "no:cacheprovider"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=600, env=env)
    assert p.returncode == 0, (nodeid, p.stdout[-1500:], p.stderr[-800:])
    return p


def _run_child_python(tmp_root: Path, code: str):
    env = dict(os.environ, TMPDIR=str(tmp_root))
    p = subprocess.run([sys.executable, "-c", code], cwd=str(REPO),
                       capture_output=True, text=True, timeout=180, env=env)
    assert p.returncode == 0, (p.stdout[-800:], p.stderr[-800:])
    return p


def test_b0_bare_mkdtemp_child_leaves_the_dir_behind(tmp_path):
    """**反证（本组断言有牙）**：不经注册表的裸 `mkdtemp` 在子进程退出后确实留下目录——
    所以下面两条「一个不留」不是恒真断言，而是真的在判回收。"""
    root = tmp_path / "bare"
    root.mkdir()
    _run_child_python(root, "import tempfile;"
                            "tempfile.mkdtemp(prefix='t260907-06-ut-bare-probe')")
    left = _leftovers(root)
    assert len(left) == 1 and left[0].startswith("t260907-06-ut-bare-probe")


def test_b1_multirepo_anchor_child_leaves_nothing(tmp_path):
    """真跑一支用例（夹具真建真删），进程退出后前缀目录零残留。"""
    root = tmp_path / "anchor"
    root.mkdir()
    _run_child_pytest(root, "server/engine/tests/test_multirepo_anchor.py"
                            "::test_repos_under_no_repo_and_nested_not_scanned")
    assert _leftovers(root) == []


def test_b2_multirepo_root_activity_child_leaves_nothing(tmp_path):
    """同上（`t260907-12-ch-/-ch1-` 也是本文件产的，前缀不止 -ut-）。"""
    root = tmp_path / "rootact"
    root.mkdir()
    _run_child_pytest(root, "server/engine/tests/test_multirepo_root_activity.py"
                            "::test_prepare_workspace_channel_mixed_vs_single")
    assert _leftovers(root) == []


def test_b3_static_lock_no_bare_mkdtemp_in_the_two_producers():
    for name in ("test_multirepo_anchor.py", "test_multirepo_root_activity.py"):
        src = (POC / "tests" / name).read_text(encoding="utf-8")
        assert "tempfile.mkdtemp(" not in src, name           # 裸 mkdtemp 一个不剩
        assert "mkdtemp_reclaimed(" in src, name
        assert "from _tmp_reclaim import mkdtemp_reclaimed" in src, name
        assert "import tempfile" not in src, name             # 拿掉不再需要的 import


# ========================================================================================
# C. 拆台回收（integration/stage_docker.py）
# ========================================================================================

def test_c1_reclaim_removes_all_three_artifacts_and_is_idempotent(tmp_path):
    paths = sd.stage_tmp_artifact_paths("utdemo", str(tmp_path))
    paths["presets"].mkdir(parents=True)
    (paths["presets"] / "sandbar-integration").mkdir()
    (paths["presets"] / "sandbar-integration" / "preset.json").write_text("{}", encoding="utf-8")
    paths["admin_log"].write_text("log\n", encoding="utf-8")
    paths["credentials"].write_text("secret\n", encoding="utf-8")
    out = sd.reclaim_stage_tmp_artifacts("utdemo", str(tmp_path))
    assert sorted(out["removed"]) == ["admin_log", "credentials", "presets"]
    assert out["missing"] == [] and out["errors"] == []
    assert not paths["presets"].exists() and not paths["admin_log"].exists()
    second = sd.reclaim_stage_tmp_artifacts("utdemo", str(tmp_path))
    assert second["removed"] == [] and sorted(second["missing"]) == [
        "admin_log", "credentials", "presets"] and second["errors"] == []


def test_c2_reclaim_never_follows_a_symlink(tmp_path):
    """占位符被换成符号链接时只删链接本身（绝不递归删到链接目标——那是别人的东西）。"""
    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep.txt").write_text("keep\n", encoding="utf-8")
    link = sd.stage_tmp_artifact_paths("utdemo", str(tmp_path))["presets"]
    link.symlink_to(target)
    out = sd.reclaim_stage_tmp_artifacts("utdemo", str(tmp_path))
    assert out["errors"] == [] and not link.exists() and not link.is_symlink()
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_c3_do_down_reclaims_tmp_artifacts_after_the_stage_is_gone(monkeypatch, tmp_path):
    """拆台收口真回收（compose/leash 面打桩，只验收口顺序与回收结果）：
    容器已归零后，本台三件临时物料必须消失，且回执带 tmp_artifacts 收据。"""
    monkeypatch.setattr(sd.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sd, "read_lease", lambda project: None)
    monkeypatch.setattr(sd, "release_lease", lambda project: None)
    monkeypatch.setattr(sd, "lock_root", lambda: tmp_path)
    monkeypatch.setattr(sd, "docker_present", lambda: True)
    monkeypatch.setattr(sd, "compose_cmd",
                        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(sd, "residue_containers", lambda project: [])
    monkeypatch.setattr(sd, "_stop_hold_by_pid", lambda *a, **kw: None)
    paths = sd.stage_tmp_artifact_paths("utdemo")
    paths["presets"].mkdir(parents=True)
    paths["admin_log"].write_text("log\n", encoding="utf-8")
    out = sd.do_down("utdemo")
    assert out["down"] is True and out["residue"] == []
    assert sorted(out["tmp_artifacts"]["removed"]) == ["admin_log", "presets"]
    assert not paths["presets"].exists() and not paths["admin_log"].exists()


def test_c4_creation_and_reclaim_share_one_path_source():
    """物化侧与回收侧**同源**（今天这个病灶的形态就是「物化侧拼字符串、回收侧不存在」）。"""
    src = (INTEG / "stage_docker.py").read_text(encoding="utf-8")
    assert src.count('"sandbar-agent-presets-%s"') == 1       # 只在 helper 里出现一次
    assert src.count('"sandbar-admin-log-%s.log"') == 1
    assert src.count('"sandbar-credentials-%s.yaml"') == 1
    assert src.count("stage_tmp_artifact_paths(project)") >= 3   # compose_env 三处物化都用它
    # 顺序锚：回收只在 release_lease 之后（容器已归零；presets 目录是容器 bind 的挂载点）
    assert src.index("release_lease(project)") < src.index("reclaim_stage_tmp_artifacts(project)")
    # 两类拆台路径都回收：do_down（显式拆台 / sweep / hold 回收）与 _do_down（起台半途失败
    # 的就地清场——最频繁的一路，此前同样一个不回收）
    do_down_src = src[src.index("def do_down("):src.index("def _gates(")]
    assert "reclaim_stage_tmp_artifacts(project)" in do_down_src
    assert '"tmp_artifacts": tmp_artifacts' in do_down_src          # 回执带收据（可对账）
    _do_down_src = src[src.index("def _do_down("):src.index("def do_down(")]
    assert "reclaim_stage_tmp_artifacts(project)" in _do_down_src
    assert 'getattr(comp, "returncode", 1) != 0' in _do_down_src    # rc!=0=容器可能还在，不抽挂载点
    # 失败点名不静默（拆台结论不被清理失败改写，但残留可见）
    assert 'print("STAGE_TMP_RECLAIM: %s" % line, file=sys.stderr)' in src


# ========================================================================================
# D. 巡检第四判据：纯判据正反例 + 阈值来源 + 入口级端到端
# ========================================================================================

def _scan(entries, *, root="/tmp/staged", seen=None, untouched=0, scanned_at=NOW,
          scan_error="", truncated=False, skipped=None):
    """桩扫描回执（与活动壳 `scan_tmp_fixture_dirs` 同形）。"""
    return {"root": root, "entries": entries, "entries_seen": seen if seen is not None
            else len(entries), "untouched": untouched, "skipped": list(skipped or []),
            "scan_error": scan_error, "truncated": truncated, "scanned_at": scanned_at}


def _dirs(n, prefix="fix10-", age_h=1.0):
    return [{"name": "%s%02d" % (prefix, i), "mtime": NOW - age_h * 3600} for i in range(n)]


def test_d1_count_threshold_hit_and_counterexample():
    thr = {"tmp_fixture_max_dirs": 10, "tmp_fixture_max_age_h": 6}
    hit = lw.tmp_fixture_scan_result(_scan(_dirs(11, age_h=1.0)), thr, source="declaration",
                                     note="threshold source=declaration")
    assert len(hit["findings"]) == 1 and hit["section"]["finding_count"] == 1
    f = hit["findings"][0]
    assert f["legs"] == [lw.LEG_TMP_FIXTURE] and f["severity"] == "med" and f["suggest"] is False
    assert f["scope"] == "host" and f["ticket_id"] == ""
    assert "11 dirs (threshold 10)" in f["subject"]
    assert "dirs=11 (threshold 10)" in f["evidence"]
    assert hit["section"]["by_leg"] == {lw.LEG_RERUN: 0, lw.LEG_FAULT_LOOP: 0,
                                        lw.LEG_INFLIGHT: 0, lw.LEG_TMP_FIXTURE: 1}
    # 反例①：恰好=阈值（严格大于才报，与票级三族同口径）
    edge = lw.tmp_fixture_scan_result(_scan(_dirs(10, age_h=1.0)), thr)
    assert edge["findings"] == [] and edge["section"]["dirs"] == 10      # 扫过、没越线=可见
    # 反例②：空扫描（扫描结果本身畸形 → 另走「扫不到」具名发现，见 d4）
    empty = lw.tmp_fixture_scan_result(_scan([]), thr)
    assert empty["findings"] == [] and empty["section"]["dirs"] == 0


def test_d2_age_threshold_hit_and_both_legs_go_high():
    thr = {"tmp_fixture_max_dirs": 100, "tmp_fixture_max_age_h": 6}
    old = lw.tmp_fixture_scan_result(_scan(_dirs(3, age_h=7.0)), thr)
    assert len(old["findings"]) == 1 and old["findings"][0]["severity"] == "med"
    assert "oldest is 7.0h old (threshold 6h)" in old["findings"][0]["subject"]
    # 两条同时越线 → high（今天的实况：27.7 万目录 / 300+ 小时）
    both = lw.tmp_fixture_scan_result(_scan(_dirs(101, age_h=300.0)), thr)
    assert both["findings"][0]["severity"] == "high"
    assert both["findings"][0]["subject"].startswith("test fixture temp dirs: 101 dirs")
    # 反例：恰在阈值上（6.0h）不报
    edge = lw.tmp_fixture_scan_result(_scan(_dirs(3, age_h=6.0)), thr)
    assert edge["findings"] == [] and edge["section"]["oldest_age_h"] == 6.0


def test_d3_whitelist_discipline_and_malformed_entries():
    """白名单外的目录**不计**（宿主 temp 里有别的程序的东西）；畸形条目逐条点名不抛。"""
    entries = _dirs(2, prefix="integ-e2e-fixture-") + [
        {"name": "com.google.Chrome.AeLvzV", "mtime": NOW - 900 * 3600},
        {"name": "nusuyou-integ-run-x.lock", "mtime": NOW - 900 * 3600},
        {"name": "fix10-no-mtime"},                      # 白名单内但测不到年龄
        "not-an-object",
    ]
    out = lw.tmp_fixture_scan_result(_scan(entries, untouched=4),
                                     {"tmp_fixture_max_dirs": 1, "tmp_fixture_max_age_h": 6})
    sec = out["section"]
    assert sec["dirs"] == 3 and sec["by_prefix"]["integ-e2e-fixture-"] == 2
    assert sec["by_prefix"]["fix10-"] == 1
    assert sec["untouched"] == 4
    notes = " ".join(sec["malformed"])
    assert "outside the whitelist" in notes and "Chrome" in notes    # 不静默吞异常输入
    assert "mtime missing/unparseable" in notes and "not an object" in notes
    assert sec["age_unknown"] is True                                # 有条目测不到年龄
    # 有一条 low 发现点名「跳过 N 条读不懂的条目」（不静默，也不假装是漏水）
    assert any("unreadable/malformed entry" in f["subject"] for f in out["findings"])


def test_d4_unreadable_scan_is_named_not_rendered_green():
    thr = {"tmp_fixture_max_dirs": 1, "tmp_fixture_max_age_h": 6}
    for bad in (_scan([], scan_error="PermissionError: [Errno 13]"), None,
                {"root": "/tmp/x", "entries_seen": 3}):
        out = lw.tmp_fixture_scan_result(bad, thr)
        assert len(out["findings"]) == 1, bad
        f = out["findings"][0]
        assert f["severity"] == "med" and "could not be scanned" in f["subject"]
        assert out["section"]["finding_count"] == 1
        assert ins.finding_language_violations([f]) == []
    # 截断（计数是下界）也点名，但不冒充「漏水」
    trunc = lw.tmp_fixture_scan_result(_scan(_dirs(3, age_h=1.0), truncated=True), thr)
    assert any("scan was truncated" in f["subject"] for f in trunc["findings"])
    assert "LOWER bound" in [f["evidence"] for f in trunc["findings"]
                             if "truncated" in f["subject"]][0]
    src = (POC / "activities.py").read_text(encoding="utf-8")
    assert "TMP_SCAN_MAX_ENTRIES" in src


def test_d5_threshold_sources_declaration_env_default_and_ticket_face_unaffected():
    """水位阈值优先级：声明 > env > 缺省，逐键点名；**票级三族阈值不受新键影响**。"""
    thr, src, note, probs = lw.resolve_tmp_thresholds(None, None)
    assert (thr, src) == (lw.TMP_WATCHDOG_DEFAULTS, lw.THRESHOLD_SOURCE_DEFAULT)
    assert "tmp_fixture_max_dirs=1000/default" in note and probs
    thr, src, note, probs = lw.resolve_tmp_thresholds(
        {"tmp_fixture_max_dirs": "5", "tmp_fixture_max_age_h": "7"}, None)
    assert (thr, src, probs) == ({"tmp_fixture_max_dirs": 5, "tmp_fixture_max_age_h": 7},
                                lw.THRESHOLD_SOURCE_DECL, [])
    # env 只补声明**没写**的键，且来源点名（绝不静默覆盖声明值）
    thr, src, note, _ = lw.resolve_tmp_thresholds(
        {"tmp_fixture_max_dirs": "5"}, {lw.TMP_ENV_MAX_DIRS: "9", lw.TMP_ENV_MAX_AGE_H: "8"})
    assert (thr["tmp_fixture_max_dirs"], src) == (5, lw.THRESHOLD_SOURCE_ENV)
    assert (thr["tmp_fixture_max_age_h"], "tmp_fixture_max_age_h=8/env" in note) == (8, True)
    # 畸形（越界/非数字/非映射）逐键回落并点名，绝不抛
    thr, src, note, probs = lw.resolve_tmp_thresholds(
        {"tmp_fixture_max_dirs": "0", "tmp_fixture_max_age_h": "abc"})
    assert thr == lw.TMP_WATCHDOG_DEFAULTS and src == lw.THRESHOLD_SOURCE_DEFAULT
    assert len(probs) == 2 and "fallbacks" in note
    # **票级三族**：声明带水位键时不再被当成「未知字段」→ 阈值来源仍是 declaration
    # （否则一次扩键会把票级面悄悄打回缺省——本断言就是这个坑的锁）
    thr3, src3, _, probs3 = lw.resolve_thresholds(
        {"rerun_rounds": "3", "fault_loop_min": "90", "inflight_silent_min": "120",
         "tmp_fixture_max_dirs": "1000", "tmp_fixture_max_age_h": "6"})
    assert (thr3, src3, probs3) == (lw.WATCHDOG_DEFAULTS, lw.THRESHOLD_SOURCE_DECL, [])


def test_d6_merge_section_keeps_counts_and_findings_in_lockstep():
    lane = lw.lane_section([], {"scanned": 2, "by_leg": {}}, source="declaration")
    tmp = lw.tmp_fixture_scan_result(_scan(_dirs(5)), {"tmp_fixture_max_dirs": 4,
                                                       "tmp_fixture_max_age_h": 6})["section"]
    merged = lw.merge_lane_section(lane, tmp)
    assert merged["finding_count"] == 1 and merged["max_severity"] == "med"
    assert merged["by_leg"][lw.LEG_TMP_FIXTURE] == 1
    assert merged["tmp_fixture"]["dirs"] == 5 and merged["scanned"] == 2
    # 畸形/缺失一律不抛：老回执（无水位段）逐字段不变
    assert lw.merge_lane_section(lane, None) == lane
    assert lw.merge_lane_section(None, None) == {}


def test_d7_declaration_side_validates_the_water_keys():
    """声明侧（fail-closed）：新增两键在闸内；越界/非数字/未知键照旧点名拒收。"""
    txt = (REPO / "inspection.yaml").read_text(encoding="utf-8")
    d = decl.parse_decl_text(txt, "inspection.yaml")
    inst = d.instance("integration-tests")
    assert inst.watchdog["tmp_fixture_max_dirs"] == "1000"
    assert inst.watchdog["tmp_fixture_max_age_h"] == "6"
    assert decl._plan_from_decl(d, "integration-tests")["watchdog"] == inst.watchdog
    for bad, target in (("      tmp_fixture_max_dirs: 0\n", "      tmp_fixture_max_dirs: 1000\n"),
                        ("      tmp_fixture_max_age_h: abc\n", "      tmp_fixture_max_age_h: 6\n"),
                        ("      tmpfixture: 1\n", "      tmp_fixture_max_dirs: 1000\n")):
        with pytest.raises(decl.DeclError):
            decl.parse_decl_text(txt.replace(target, bad), "bad.yaml")


# ---------------- 入口级端到端（真活动壳；桩注册表/Temporal；私有临时根） ----------------

class _FakeWF:
    def __init__(self, wid, project):
        self.id, self.run_id = wid, "run-1"
        self.typed_search_attributes = {
            SearchAttributeKey.for_keyword(PROJECT_SA_NAME): project}


class _FakeHandle:
    def __init__(self, snap, calls):
        self._snap, self._calls = snap, calls

    async def query(self, name):
        self._calls.append(("query", name))
        return self._snap


class _FakeClient:
    def __init__(self, wfs, snaps, calls):
        self._wfs, self._snaps, self._calls = wfs, snaps, calls

    async def list_workflows(self, query):
        self._calls.append(("list", query))
        for wf in self._wfs:
            yield wf

    def get_workflow_handle(self, wid, run_id=None):
        return _FakeHandle(self._snaps.get(wid, {}), self._calls)


def _patch_io(monkeypatch, wfs=(), snaps=None):
    calls: list = []

    async def _connect(host, **kw):
        calls.append(("connect", host))
        return _FakeClient(list(wfs), snaps or {}, calls)

    monkeypatch.setattr(activities.Client, "connect", _connect)
    monkeypatch.setattr(activities, "list_registered_projects",
                        lambda: ([{"key": "sandbar", "name": "sandbar", "dirs": ["/x"]}], []))
    return calls


def _run_activity(args):
    return asyncio.run(activities.run_inspection_lane_watchdog(args))


def _stage_tmp_root(tmp_path, *, live=0, stale=0, prefix="integ-e2e-fixture-", other=("other",)):
    """私有临时根：真目录 + 真 mtime（白名单前缀 live 新 / stale 老；other=白名单外）。"""
    root = tmp_path / "tmp-root"
    root.mkdir()
    old = time.time() - 9 * 3600
    for i in range(live):
        (root / ("%slive%d" % (prefix, i))).mkdir()
    for i in range(stale):
        d = root / ("%sstale%d" % (prefix, i))
        d.mkdir()
        os.utime(d, (old, old))
    for name in other:
        (root / name).mkdir()
    return root


def test_e1_entry_level_water_finding_and_zero_interference(monkeypatch, tmp_path):
    """入口级端到端：真活动壳扫**私有**临时根 → 出 `tmp-fixture-water` 发现，且票级面
    （findings / section / scanned / by_leg）逐字段零污染；只读零写（暂存目录原样）。"""
    root = _stage_tmp_root(tmp_path, live=1, stale=3, other=("com.google.Chrome.X",))
    before = sorted((n, os.stat(root / n).st_mtime) for n in os.listdir(root))
    calls = _patch_io(monkeypatch)
    out = _run_activity({"tmp_fixture_root": str(root),
                         "tmp_fixture_scan_ttl_sec": 0,
                         "watchdog": {"tmp_fixture_max_dirs": "2",
                                      "tmp_fixture_max_age_h": "6"}})
    assert out["ok"] is True, out
    res = out["result"]
    assert res["findings"] == []                     # 没有票发现（桩注册表零非终态票）
    assert res["section"]["finding_count"] == 0       # 票级段不被水位发现污染（旧口径零回归）
    tmp = res["tmp_fixture"]
    assert tmp["scan_mode"] == "scanned" and tmp["scan_cached"] is False
    assert tmp["section"]["dirs"] == 4 and tmp["section"]["untouched"] == 1
    assert tmp["section"]["threshold_source"] == lw.THRESHOLD_SOURCE_DECL
    assert len(tmp["findings"]) == 1
    f = tmp["findings"][0]
    assert f["legs"] == [lw.LEG_TMP_FIXTURE] and f["scope"] == "host"
    assert "Chrome" not in f["evidence"]             # 白名单外的东西只计数不进证据
    merged = res["section_merged"]
    assert merged["finding_count"] == 1 and merged["by_leg"][lw.LEG_TMP_FIXTURE] == 1
    assert merged["tmp_fixture"]["dirs"] == 4 and merged["scanned"] == 0
    assert ins.finding_language_violations(tmp["findings"]) == []
    # 只读零写：暂存目录的内容与 mtime 一个没动
    assert sorted((n, os.stat(root / n).st_mtime) for n in os.listdir(root)) == before
    # 只读铁律：零 update/signal/start/cancel/terminate
    assert {c[0] for c in calls} == {"connect", "list"}


def test_e2_entry_level_counterexamples(monkeypatch, tmp_path):
    """入口级反例：水位在阈内 → 零发现但段里**看得见**（扫过、没越线）。"""
    root = _stage_tmp_root(tmp_path, live=2, stale=0)
    _patch_io(monkeypatch)
    out = _run_activity({"tmp_fixture_root": str(root), "tmp_fixture_scan_ttl_sec": 0,
                         "watchdog": {"tmp_fixture_max_dirs": "100",
                                      "tmp_fixture_max_age_h": "6"}})
    tmp = out["result"]["tmp_fixture"]
    assert tmp["findings"] == [] and tmp["section"]["dirs"] == 2
    assert tmp["section"]["finding_count"] == 0 and tmp["section"]["max_severity"] == ""
    assert out["result"]["section_merged"]["finding_count"] == 0
    assert out["result"]["meta"]["tmp_fixture"]["scan_mode"] == "scanned"


def test_e3_entry_level_scan_failure_is_named(monkeypatch, tmp_path):
    """入口级三态：临时根读不到 → 具名 med 发现（绝不渲染成「水位 0 = 绿」）。"""
    _patch_io(monkeypatch)
    out = _run_activity({"tmp_fixture_root": str(tmp_path / "nope-missing"),
                         "tmp_fixture_scan_ttl_sec": 0})
    tmp = out["result"]["tmp_fixture"]
    assert tmp["section"]["scan_error"] and len(tmp["findings"]) == 1
    assert "could not be scanned" in tmp["findings"][0]["subject"]
    assert tmp["findings"][0]["severity"] == "med"


def test_e4_entry_level_default_scan_is_bounded_and_cached(monkeypatch):
    """缺省 = 真扫系统临时根（只读）：形状合规、无异常；同 root 第二次命中 TTL 缓存。"""
    _patch_io(monkeypatch)
    activities._TMP_SCAN_CACHE.clear()        # 会话内兄弟用例可能已扫过同 root（缓存是刻意的）
    root = tempfile.gettempdir()
    out1 = _run_activity({})
    tmp1 = out1["result"]["tmp_fixture"]
    assert tmp1["scan_mode"] == "scanned" and tmp1["scan_cached"] is False
    assert tmp1["section"]["scan_error"] == ""            # 读得到（读不到=上面那条具名发现）
    assert tmp1["section"]["root"] == root
    assert isinstance(tmp1["section"]["entries_seen"], int)
    out2 = _run_activity({})
    assert out2["result"]["tmp_fixture"]["scan_cached"] is True   # 有界：同 root 不重复扫


def test_e5_flow_merges_host_finding_and_stays_replay_compatible(monkeypatch):
    """工作流接线：水位发现进**同一发现清单**+合并段；老回执（无 tmp_fixture）逐字段同旧形。"""
    wf = object.__new__(flow.InspectionPeriodicWorkflow)
    tmp_sec = lw.tmp_fixture_scan_result(
        _scan(_dirs(5, age_h=9.0)), {"tmp_fixture_max_dirs": 4,
                                     "tmp_fixture_max_age_h": 6})["section"]
    tmp_finds = lw.tmp_fixture_scan_result(
        _scan(_dirs(5, age_h=9.0)), {"tmp_fixture_max_dirs": 4,
                                     "tmp_fixture_max_age_h": 6})["findings"]
    lane_sec = lw.lane_section([], {"scanned": 3, "by_leg": {}}, source="declaration")
    merged = lw.merge_lane_section(lane_sec, tmp_sec)

    async def _ok(*a, **kw):
        return {"ok": True, "result": {"findings": [], "section": lane_sec,
                                       "section_merged": merged, "tmp_fixture":
                                       {"findings": tmp_finds, "section": tmp_sec},
                                       "meta": {}}}
    monkeypatch.setattr(flow, "workflow", SimpleNamespace(execute_activity=_ok))
    sec, finds = asyncio.run(wf._lane_watchdog(object(), {}))
    assert len(finds) == 1 and finds[0]["scope"] == "host" and finds[0]["suggest"] is False
    assert sec["finding_count"] == 1 and sec["tmp_fixture"]["dirs"] == 5
    assert ins.finding_language_violations(finds) == []
    # 合并段进票面 → 心跳不再假绿（宿主水位越线也是「这期不是全绿」）
    face = flow.build_ticket_face("t1", "inst", "20260926",
                                  {"findings": [], "summary": {"high": 0, "med": 0, "low": 0},
                                   "heartbeat": True}, extra_findings=finds, lane=sec)
    assert face["heartbeat"] is False and face["lane"]["tmp_fixture"]["dirs"] == 5
    assert face["summary"]["high"] == 1     # 目录数 + 年龄两条都越线 → high（进摘要）

    # 老回执（老 worker 无 tmp_fixture/section_merged 字段）→ 逐字段同旧实现
    async def _legacy(*a, **kw):
        return {"ok": True, "result": {"findings": [], "section": lane_sec, "meta": {}}}
    monkeypatch.setattr(flow, "workflow", SimpleNamespace(execute_activity=_legacy))
    sec2, finds2 = asyncio.run(wf._lane_watchdog(object(), {}))
    assert finds2 == [] and sec2 == lane_sec and "tmp_fixture" not in sec2


# ========================================================================================
# E. 机械闸：L8（lint）+ 白名单单源漂移锁
# ========================================================================================

def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_f1_prefix_whitelist_single_source():
    """引擎判据面与清扫器的白名单**同一份清单**（两处各写一份必然漂移：清扫器删掉的
    前缀与水位面统计的前缀一旦错位，就会出现「清扫器删了但不报警」或反之的静默缺口）。"""
    sweep = _load_module(INTEG / "tools" / "sweep_tmp_fixtures.py", "sweep_probe")
    assert tuple(sweep.TMP_FIXTURE_PREFIXES) == tuple(lw.TMP_FIXTURE_PREFIXES)
    assert sweep.DEFAULT_MAX_AGE_H == lw.DEFAULT_TMP_FIXTURE_MAX_AGE_H   # 龄线同口径
    # 清扫器是 dry-run 缺省的（宿主 temp 里可能有别的程序的东西）：--apply 才删 + 龄闸硬地板
    src = (INTEG / "tools" / "sweep_tmp_fixtures.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--apply", action="store_true"' in src
    assert "APPLY_MIN_AGE_H" in src and "not a real directory" in src


def test_f2_l8_lint_gate_behaviour(monkeypatch, tmp_path):
    """L8 行为：基线外的新漏点 → **警告级**（不阻断，exit 仍 0）；基线内新增调用点 → 警告；
    基线内的存量债 → 不报（防新债，不追缴存量）。"""
    lint = _load_module(INTEG / "lint_tests.py", "lint_probe")
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"files": {"old/lib.py": 1}}), encoding="utf-8")
    monkeypatch.setattr(lint, "TMPDIR_BASELINE", base)
    monkeypatch.setattr(lint, "warns", [])
    monkeypatch.setattr(lint, "errors", [])
    monkeypatch.setattr(lint, "tmpdir_users", lambda: {"new/fresh_test.py": 1,
                                                       "old/lib.py": 1})
    lint.lint_tmpdir_hygiene()
    assert len(lint.warns) == 1 and lint.errors == []
    assert "new/fresh_test.py" in lint.warns[0] and "old/lib.py" not in lint.warns[0]
    # 存量债自证：只剩基线内文件 → 不报
    monkeypatch.setattr(lint, "warns", [])
    monkeypatch.setattr(lint, "tmpdir_users", lambda: {"old/lib.py": 1})
    lint.lint_tmpdir_hygiene()
    assert lint.warns == []
    # 基线内**新增**调用点 → 报
    monkeypatch.setattr(lint, "tmpdir_users", lambda: {"old/lib.py": 2})
    lint.lint_tmpdir_hygiene()
    assert len(lint.warns) == 1 and "2 > baseline 1" in lint.warns[0]
    # 真基线在册且两个修好的生产者已出册（修完的产物=L8 认它干净）
    real = json.loads((INTEG / "tmpdir-baseline.json").read_text(encoding="utf-8"))
    assert "files" in real and len(real["files"]) >= 50
    for fixed in ("server/engine/tests/test_multirepo_anchor.py",
                  "server/engine/tests/test_multirepo_root_activity.py",
                  "integration/stage_docker.py"):
        assert fixed not in real["files"], fixed


def test_f3_activity_source_is_read_only_and_wired():
    """活动壳只读自证（静态）：扫描面没有任何写动词/进程/网络调用；三态显式化在场。"""
    src = (POC / "activities.py").read_text(encoding="utf-8")
    fn = src[src.index("def scan_tmp_fixture_dirs("):src.index("def _scan_tmp_fixture_cached(")]
    for forbidden in ("rmtree", "unlink", "write_text", "open(", "shutil.move", "os.remove"):
        assert forbidden not in fn, forbidden
    assert "os.scandir" in fn and "follow_symlinks=False" in fn   # 不跟符号链接（别人家的东西）
    names = [getattr(a, "__name__", "") for a in activities.ALL_ACTIVITIES]
    assert names.count("run_inspection_lane_watchdog") == 1        # 没新增活动（面数不变）
    body = src[src.index("async def run_inspection_lane_watchdog("):]
    assert "tmp_fixture_scan_result" in body and "resolve_tmp_thresholds" in body
    assert '"section_merged"' in body                              # 合并段在活动侧算好
