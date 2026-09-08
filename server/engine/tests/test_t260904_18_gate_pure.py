"""t260904-18 三门单测（KI-049 门② / KI-050 门③ / 开票闸·背景文件校验 门①）。

覆盖（零 Temporal server / 零模型 / 零网络，临时 git 仓自足）：
  门①：validate_background_refs——已提交干净绿 / 未跟踪红 / 脏改红 / 暂存新文件红 /
        畸形（非列表/绝对路径/../不存在）/ 缺省放行 / git 故障 fail-closed。
  门②：normalize_files_changed 四形态（absent/ok/空 ok/malformed：字符串/数字/含非串
        元素）；_refresh_write_set_after_plan 四分支（malformed 红零污染 / absent 跳过 /
        空数组红 / 合法非空「授权扩展」+ no_file_changes 豁免）——消费外部回执的
        畸形输入桩内复现，不靠真 agent。
  门③：load_ui_evidence 三态（ok/absent/malformed）与解析畸形（行内标量/坏行）。

消费外部输入的畸形用例（岗位纪律）：全走桩/临时仓，字符串回执、坏 verify.yaml 均
固定形状复现，不依赖真外部源。
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))
TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import pytest  # noqa: E402

import shared  # noqa: E402
from shared import (  # noqa: E402
    load_ui_evidence,
    normalize_files_changed,
    validate_background_refs,
)


# ---------- 门①：validate_background_refs ----------

def _git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


@pytest.fixture()
def repo():
    """临时 git 仓：一个已提交干净文件 docs/note.md。"""
    tmp = tempfile.mkdtemp(prefix="t260904-18-ut-")
    _git("init", "-b", "main", cwd=tmp)
    _git("config", "user.email", "ut@example.com", cwd=tmp)
    _git("config", "user.name", "ut", cwd=tmp)
    f = Path(tmp) / "docs" / "note.md"
    f.parent.mkdir(parents=True)
    f.write_text("背景\n", encoding="utf-8")
    _git("add", "-A", cwd=tmp)
    _git("commit", "-m", "base", cwd=tmp)
    yield Path(tmp)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def test_refs_clean_committed_green(repo):
    ok, err = validate_background_refs(["docs/note.md"], repo)
    assert ok and err == ""


def test_refs_none_or_empty_pass(repo):
    assert validate_background_refs(None, repo) == (True, "")
    assert validate_background_refs([], repo) == (True, "")


def test_refs_untracked_named(repo):
    (repo / "notes" / "fresh.md").parent.mkdir(parents=True)
    (repo / "notes" / "fresh.md").write_text("未提交\n", encoding="utf-8")
    ok, err = validate_background_refs(["notes/fresh.md"], repo)
    assert not ok and "notes/fresh.md" in err and "未提交" in err


def test_refs_dirty_tracked_named(repo):
    (repo / "docs" / "note.md").write_text("脏改\n", encoding="utf-8")
    ok, err = validate_background_refs(["docs/note.md"], repo)
    assert not ok and "docs/note.md" in err and "未提交改动" in err


def test_refs_staged_new_file_named(repo):
    """git add 暂存的未跟踪文件（A 态）=未提交，拒（保留面：两查组合）。"""
    (repo / "notes" / "staged.md").parent.mkdir(parents=True)
    (repo / "notes" / "staged.md").write_text("暂存\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    ok, err = validate_background_refs(["notes/staged.md"], repo)
    assert not ok and "notes/staged.md" in err


def test_refs_multiple_problems_all_named(repo):
    (repo / "docs" / "note.md").write_text("脏\n", encoding="utf-8")
    ok, err = validate_background_refs(["docs/note.md", "nope.md"], repo)
    assert not ok and "docs/note.md" in err and "nope.md" in err


def test_refs_malformed_inputs(repo):
    ok, err = validate_background_refs("docs/note.md", repo)  # 字符串=假清单判例
    assert not ok and "假清单" in err
    ok, err = validate_background_refs(["/abs/note.md"], repo)
    assert not ok and "非法条目" in err
    ok, err = validate_background_refs(["../escape.md"], repo)
    assert not ok and "非法条目" in err
    ok, err = validate_background_refs([42], repo)
    assert not ok and "非法条目" in err


def test_refs_git_broken_fail_closed(repo):
    """git 不可用（非仓目录）=拒收 fail-closed，不静默放行。"""
    ok, err = validate_background_refs(["docs/note.md"], tempfile.mkdtemp())
    assert not ok and ("未提交" in err or "fail-closed" in err)


# ---------- 门②：normalize_files_changed ----------

def test_normalize_absent():
    assert normalize_files_changed(None) == ([], "absent")


def test_normalize_ok_list():
    assert normalize_files_changed(["a.py", " b.py ", ""]) == (["a.py", "b.py"], "ok")
    assert normalize_files_changed([]) == ([], "ok")  # 空数组=合法形状，emptiness 在消费点


def test_normalize_malformed_shapes():
    # 字符串=单字符假列表的根（评审 R1 实锤形态）
    assert normalize_files_changed("server/foo.py") == ([], "malformed")
    assert normalize_files_changed(42) == ([], "malformed")
    assert normalize_files_changed({"a": 1}) == ([], "malformed")
    assert normalize_files_changed(["ok.py", 7]) == ([], "malformed")  # 含非串元素
    assert normalize_files_changed(True) == ([], "malformed")


# ---------- 门②：_refresh_write_set_after_plan 四分支 ----------

def _mk_lane(patched_ids):
    """免 Temporal 运行时的 DevLaneWorkflow 壳：stub patched 门 + meta/results。"""
    import datetime
    import dev_lane
    orig = dev_lane.workflow
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid in patched_ids,
        now=lambda: datetime.datetime(2026, 9, 4, 12, 0, 0))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"write_set": ["server/a.py"], "ticket_id": "t-ut"}
    wf.results = {}
    wf.timeline = []
    yield wf, dev_lane, orig
    dev_lane.workflow = orig


def test_refresh_malformed_visible_red_zero_pollution():
    for bad in ("server/foo.py", 42, ["x", 1]):
        for wf, dev_lane, _orig in _mk_lane(
                {"dev-lane-refresh-write-set", "dev-lane-write-set-fault"}):
            wf.results["create_plan"] = {
                "files_changed": bad if not isinstance(bad, list) else bad,
                "files_changed_shape": "malformed"}
            dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
            assert wf.meta.get("write_set_refresh_fault", {}).get("stage") == "create_plan"
            assert wf.meta["write_set"] == ["server/a.py"]  # 写集零污染
            assert any("红灯" in ln for e in wf.meta.get("log", []) for ln in [e["note"]])  # 告警日志在场
            assert not any("授权扩展" in ln for e in wf.meta.get("log", []) for ln in [e["note"]])


def test_refresh_empty_visible_red_and_exemption():
    for wf, dev_lane, _orig in _mk_lane(
            {"dev-lane-refresh-write-set", "dev-lane-write-set-fault"}):
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "ok"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert "write_set_refresh_fault" in wf.meta
        assert wf.meta["write_set"] == ["server/a.py"]
        assert any("空数组" in ln for e in wf.meta.get("log", []) for ln in [e["note"]])
    # no_file_changes 声明在案=豁免（不亮红，走中性刷新日志）
    for wf, dev_lane, _orig in _mk_lane(
            {"dev-lane-refresh-write-set", "dev-lane-write-set-fault"}):
        wf.meta["no_file_changes"] = True
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "ok"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert "write_set_refresh_fault" not in wf.meta


def test_refresh_absent_skip_and_valid_extend():
    # absent（旧回执）：跳过+留痕，语义不变
    for wf, dev_lane, _orig in _mk_lane(
            {"dev-lane-refresh-write-set", "dev-lane-write-set-fault"}):
        wf.results["create_plan"] = {"files_changed_shape": "absent"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert "write_set_refresh_fault" not in wf.meta
        assert any("写集刷新跳过" in ln for e in wf.meta.get("log", []) for ln in [e["note"]])
    # 合法非空：现行刷新+「授权扩展」（活性巡检的断言面）
    for wf, dev_lane, _orig in _mk_lane(
            {"dev-lane-refresh-write-set", "dev-lane-write-set-fault"}):
        wf.results["create_plan"] = {
            "files_changed": ["server/b.py", "integration/sc_x.py"],
            "files_changed_shape": "ok"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert wf.meta["write_set"] == ["server/a.py", "server/b.py", "integration/sc_x.py"]
        assert any("授权扩展：+server/b.py" in ln for e in wf.meta.get("log", []) for ln in [e["note"]])
        assert "write_set_refresh_fault" not in wf.meta


def test_refresh_unpatched_keeps_legacy_semantics():
    """未 patch 新门（存量实例重放）：空/畸形回执走原刷新路径，零新增突变。"""
    for wf, dev_lane, _orig in _mk_lane({"dev-lane-refresh-write-set"}):
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "malformed"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert "write_set_refresh_fault" not in wf.meta
        assert any("写集已随方案定稿刷新" in ln for e in wf.meta.get("log", []) for ln in [e["note"]])


# ---------- 门③：load_ui_evidence 三态与解析畸形 ----------

def test_ui_evidence_absent():
    assert load_ui_evidence(tempfile.mkdtemp())[0] == "absent"


def test_ui_evidence_ok():
    d = Path(tempfile.mkdtemp())
    (d / "verify.yaml").write_text(
        "schema: v1\nui_evidence:\n  dirs:\n    - web/src/\n    - app/index.html\n"
        "  supply: playwright-core\n", encoding="utf-8")
    mode, dirs, note = load_ui_evidence(d)
    assert mode == "ok" and dirs == ["web/src/", "app/index.html"] and note == ""


def test_ui_evidence_malformed_shapes():
    cases = {
        "缺 dirs": "schema: v1\nui_evidence:\n  supply: x\n",
        "行内标量": "schema: v1\nui_evidence: hello\n",
        "坏行": "schema: v1\nui_evidence:\n  dirs:\n    - a/\n    孤儿行\n",
    }
    for name, text in cases.items():
        d = Path(tempfile.mkdtemp())
        (d / "verify.yaml").write_text(text, encoding="utf-8")
        mode, dirs, note = load_ui_evidence(d)
        assert mode == "malformed", name
        assert dirs == [] and note


def test_ui_evidence_flow_list_ok():
    """行内流列表是 verify.yaml 子集合法形态（②a write_allow 同款），判 ok。"""
    d = Path(tempfile.mkdtemp())
    (d / "verify.yaml").write_text(
        "schema: v1\nui_evidence:\n  dirs: [web/src/, app/]\n", encoding="utf-8")
    mode, dirs, _ = load_ui_evidence(d)
    assert mode == "ok" and dirs == ["web/src/", "app/"]
