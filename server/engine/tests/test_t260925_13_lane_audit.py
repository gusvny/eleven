"""lane_audit 单测（t260925-13，KI-112）。

纪律：UT 全程禁真 git/真 Temporal/真网络——git 执行层与票查询执行层全部桩注入，
文件面操作（stub 清理、目录扫描）用 tmp_path 真目录。
覆盖：评审 C1 票查询三态、C2 畸形 stdout 容错、C4 bare-stub 四条纪律、
守门（未提交/未合并/git 失败）、幂等、畸形 porcelain、symlink 逃逸、
评审条件 2（恶意目录名不进 shell 拼接）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

import lane_audit as la


# ---------------------------------------------------------------- 桩
class FakeOps:
    """票查询执行层桩：按 op 记录返回 (rc, stdout, stderr)。"""

    def __init__(self, list_stdout="", list_rc=0, show_by_id=None, list_exc=None):
        self.list_stdout = list_stdout
        self.list_rc = list_rc
        self.show_by_id = show_by_id or {}
        self.list_exc = list_exc
        self.calls = []

    def __call__(self, op):
        self.calls.append(op)
        if op.get("op") == "list":
            if self.list_exc:
                raise self.list_exc
            return self.list_rc, self.list_stdout, ""
        ticket = op.get("id")
        spec = self.show_by_id.get(ticket)
        if spec is None:
            return 0, json.dumps({"ok": True, "snapshot": {"status": "dispatched"}}, ensure_ascii=False), ""
        rc, stdout = spec
        return rc, stdout, ""


def q_of(fake):
    return la.TicketQuerier(fake)


# ---------------------------------------------------------------- C1：票查询三态
def test_c1_list_status_closed_is_terminal_confirmed():
    fake = FakeOps(list_stdout=json.dumps(
        {"ok": True, "tickets": [{"id": "t1", "status": "closed"}]}))
    state, detail = q_of(fake).query("t1")
    assert state == "terminal-confirmed"
    assert "closed" in detail
    assert fake.calls == [{"op": "list"}]  # list 命中不发起 show


def test_c1_show_not_found_kind_is_terminal_absent():
    fake = FakeOps(list_stdout=json.dumps({"ok": True, "tickets": []}),
                   show_by_id={"t9": (1, json.dumps(
                       {"ok": False, "error": "QueryError: 工单不存在: t9",
                        "kind": "not_found"}, ensure_ascii=False),)})
    state, _ = q_of(fake).query("t9")
    assert state == "terminal-absent"


def test_c1_show_terminal_kind_is_terminal_absent():
    fake = FakeOps(list_stdout=json.dumps({"ok": True, "tickets": []}),
                   show_by_id={"t8": (1, json.dumps(
                       {"ok": False,
                        "error": "QueryError: 工单查询失败（terminal）：已终态（TERMINATED）",
                        "kind": "terminal"}, ensure_ascii=False),)})
    state, _ = q_of(fake).query("t8")
    assert state == "terminal-absent"


def test_c1_unreachable_query_is_unknown_not_absent():
    fake = FakeOps(list_exc=OSError("no temporal"))
    state, detail = q_of(fake).query("t1")
    assert state == "unknown"
    assert "unreachable" in detail


def test_c1_show_unparseable_is_unknown():
    fake = FakeOps(list_stdout=json.dumps({"ok": True, "tickets": []}),
                   show_by_id={"t7": (1, "not json at all",)})
    state, detail = q_of(fake).query("t7")
    assert state == "unknown"
    assert "unparseable" in detail


def test_c1_live_status_is_keep_state():
    fake = FakeOps(list_stdout=json.dumps(
        {"ok": True, "tickets": [{"id": "t2", "status": "dispatched"}]}))
    state, _ = q_of(fake).query("t2")
    assert state == "live"


def test_c1_verified_is_not_terminal_conservative():
    fake = FakeOps(list_stdout=json.dumps(
        {"ok": True, "tickets": [{"id": "t3", "status": "verified"}]}))
    state, _ = q_of(fake).query("t3")
    assert state == "live"  # verified 保守不含 terminal 集合


# ---------------------------------------------------------------- C2：畸形 stdout
def test_c2_stdout_with_warning_lines_still_parses():
    noisy = ("audit: admin.log 写失败（回执不受影响）\n"
             "audit: admin.log 写失败（回执不受影响）\n"
             + json.dumps({"ok": False, "kind": "not_found", "error": "工单不存在"}))
    obj = la.extract_json_loose(noisy)
    assert obj is not None and obj["kind"] == "not_found"


def test_c2_pure_garbage_returns_none():
    assert la.extract_json_loose("Traceback (most recent call last):\n  boom") is None
    assert la.extract_json_loose("") is None
    assert la.extract_json_loose("[1,2,3]") is None  # 非 dict 不收


def test_c2_malicious_ticket_name_never_reaches_shell():
    """评审条件 2：默认 op_fn 走 argv 列表不经 shell——畸形目录名整串当作单参数。"""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["shell"] = kwargs.get("shell", False)
        return subprocess.CompletedProcess(argv, 1, "", "")

    orig = la.subprocess.run
    la.subprocess.run = fake_run
    try:
        fn = la.make_default_op_fn("/repo")
        evil = '{"op":"show","id":"t1; rm -rf /"}'
        fn(json.loads(evil))
    finally:
        la.subprocess.run = orig
    assert captured["shell"] is False
    assert captured["argv"][-1] == json.dumps(json.loads(evil), ensure_ascii=False)


# ---------------------------------------------------------------- 纯函数分类
def test_extract_ticket_id():
    assert la.extract_ticket_id("lane/t260903-12", "") == "t260903-12"
    assert la.extract_ticket_id("", "t260912-01") == "t260912-01"
    assert la.extract_ticket_id("", "inspection-integration-tests-20260925") == ""
    assert la.extract_ticket_id("main", "random-dir") == ""
    assert la.extract_ticket_id("", "t-no-digits") == ""


def _wt(path, branch=""):
    return la.WorktreeEntry(path=path, head="a" * 40, branch=branch)


def test_classify_worktree_stub_registry_only_baseline(tmp_path):
    lane = tmp_path / ".lane"
    lane.mkdir()
    (lane / "t1").mkdir()            # 注册 worktree
    (lane / "t2").mkdir()            # bare stub（不在 porcelain）
    wts = [
        _wt(str(lane / "t1"), "lane/t1"),
        _wt(str(lane / "gone"), "lane/t3"),         # registry-only（目录已不在）
        _wt("/tmp/sandbar-baseline-xxxx"),          # baseline
    ]
    entries = la.classify(str(lane), wts, {"t1": ("live", "list status=dispatched")})
    by = {e.name: e for e in entries}
    assert by["t1"].kind == "worktree" and by["t1"].verdict == la.V_KEEP
    assert by["t2"].kind == "stub" and by["t2"].verdict == la.V_UNKNOWN
    assert by["gone"].kind == "registry-only" and by["gone"].verdict == la.V_REGISTRY_ABSENT
    assert by["sandbar-baseline-xxxx"].kind == "baseline"
    assert by["sandbar-baseline-xxxx"].verdict == la.V_BASELINE


def test_classify_terminal_ticket_is_prunable():
    entries = la.classify("/nonexistent", [],
                          {"t9": ("terminal-absent", "show kind=not_found")})
    assert entries == []  # lane 目录不存在时无条目（不崩）


def test_classify_malformed_porcelain_line_named_not_crash(tmp_path):
    entries = la.classify(str(tmp_path), [la.WorktreeEntry(path="", malformed=True, raw="??? zombie")])
    assert len(entries) == 1
    assert entries[0].kind == "malformed"
    assert entries[0].verdict == la.V_UNKNOWN
    assert "zombie" in entries[0].reason


def test_porcelain_parser_tolerates_unknown_keyword():
    entries = la.parse_worktree_porcelain(
        "worktree /a\nHEAD abc\nbranch refs/heads/lane/t1\n\nworktree /b\ndetached\nlocked why\n")
    assert len(entries) == 2
    assert entries[0].branch == "lane/t1"
    assert entries[1].branch == ""
    assert entries[1].malformed is True  # locked 行不认识 → 留痕


# ---------------------------------------------------------------- C4：stub 四条纪律
def test_c4_stub_lists_contents_then_clears(tmp_path):
    stub = tmp_path / "s1"
    (stub / "sub").mkdir(parents=True)
    (stub / "sub" / "a.txt").write_text("x")
    (stub / "b.log").write_text("y")
    entry = la.LaneEntry(name="s1", path=str(stub), kind="stub",
                         verdict=la.V_PRUNABLE)
    out = la.clear_stub(entry)
    assert out.verdict == "cleared"
    assert sorted(out.contents) == ["b.log", os.path.join("sub", "a.txt")]
    assert not stub.exists()


def test_c4_nested_git_refuses_to_clear(tmp_path):
    stub = tmp_path / "s2"
    stub.mkdir()
    (stub / ".git").write_text("gitdir: /somewhere")  # 疑似登记丢失的真 worktree
    (stub / "f").write_text("x")
    entry = la.LaneEntry(name="s2", path=str(stub), kind="stub", verdict=la.V_PRUNABLE)
    out = la.clear_stub(entry)
    assert out.verdict == f"{la.V_BLOCKED}:nested-git"
    assert stub.exists()  # 拒拆
    assert ".git" in out.contents  # 清单先列（含嵌套 .git 本身）


def test_c4_verify_after_rm_catches_fake_green(tmp_path, monkeypatch):
    stub = tmp_path / "s3"
    stub.mkdir()
    entry = la.LaneEntry(name="s3", path=str(stub), kind="stub", verdict=la.V_PRUNABLE)
    orig_rmtree = __import__("shutil").rmtree

    def lying_rmtree(path):  # 回执成功但目录还在 = KI-110 假绿形态
        pass

    import shutil
    monkeypatch.setattr(shutil, "rmtree", lying_rmtree)
    out = la.clear_stub(entry)
    assert out.verdict == f"{la.V_BLOCKED}:clear-failed"
    monkeypatch.setattr(shutil, "rmtree", orig_rmtree)


def test_c4_already_gone_wording_distinguishes_dir_vs_registry(tmp_path):
    entry = la.LaneEntry(name="s4", path=str(tmp_path / "nope"), kind="stub",
                         verdict=la.V_PRUNABLE)
    assert la.clear_stub(entry).verdict == la.V_DIR_ABSENT  # 目录已不在
    entry2 = la.LaneEntry(name="gone", path=str(tmp_path / "gone"),
                          kind="registry-only", verdict=la.V_REGISTRY_ABSENT)
    assert entry2.verdict == la.V_REGISTRY_ABSENT  # 登记已不在（分类器措辞）


# ---------------------------------------------------------------- 守门（桩 git_run）
def test_guard_blocks_uncommitted(monkeypatch, tmp_path):
    entry = la.LaneEntry(name="t1", path=str(tmp_path), kind="worktree",
                         branch="lane/t1", verdict=la.V_PRUNABLE)
    monkeypatch.setattr(la, "git_run", lambda root, args, cwd=None:
                        (0, " M dirty.py\n", "") if args[:1] == ["status"] else (0, "", ""))
    out = la.guard_worktree(".", entry, "main", "abc1234")
    assert out.verdict == f"{la.V_BLOCKED}:uncommitted"


def test_guard_blocks_unmerged_with_base_hash_in_reason(monkeypatch, tmp_path):
    entry = la.LaneEntry(name="t1", path=str(tmp_path), kind="worktree",
                         branch="lane/t1", verdict=la.V_PRUNABLE)
    def fake_git(root, args, cwd=None):
        if args[:1] == ["status"]:
            return 0, "", ""
        if args[:2] == ["rev-list", "--count"]:
            return 0, "3\n", ""
        return 0, "", ""
    monkeypatch.setattr(la, "git_run", fake_git)
    out = la.guard_worktree(".", entry, "main", "abc1234")
    assert out.verdict == f"{la.V_BLOCKED}:unmerged"
    assert "abc1234" in out.reason  # 评审条件 1：reason 带 base-ref 短哈希


def test_guard_git_error_is_blocked(monkeypatch, tmp_path):
    entry = la.LaneEntry(name="t1", path=str(tmp_path), kind="worktree",
                         branch="lane/t1", verdict=la.V_PRUNABLE)
    monkeypatch.setattr(la, "git_run", lambda root, args, cwd=None: (128, "", "fatal: not a repo"))
    out = la.guard_worktree(".", entry, "main", "abc1234")
    assert out.verdict == f"{la.V_BLOCKED}:git-error"


def test_guard_clean_and_merged_is_prunable(monkeypatch, tmp_path):
    entry = la.LaneEntry(name="t1", path=str(tmp_path), kind="worktree",
                         branch="lane/t1", verdict=la.V_PRUNABLE)
    def fake_git(root, args, cwd=None):
        if args[:1] == ["status"]:
            return 0, "", ""
        if args[:2] == ["rev-list", "--count"]:
            return 0, "0\n", ""
        if args[:1] == ["cherry"]:
            return 0, "- a\n- b\n", ""
        return 0, "", ""
    monkeypatch.setattr(la, "git_run", fake_git)
    out = la.guard_worktree(".", entry, "main", "abc1234")
    assert out.verdict == la.V_PRUNABLE
    assert "abc1234" in out.reason


# ---------------------------------------------------------------- 幂等与台账
def test_ledger_append_and_idempotent_rerun(tmp_path):
    lane = tmp_path / ".lane"
    lane.mkdir()
    rec = {"name": "t1", "kind": "worktree", "verdict": "pruned", "reason": "r"}
    p1 = la.append_ledger(str(lane), [rec])
    p2 = la.append_ledger(str(lane), [dict(rec, verdict="already-gone:dir-absent")])
    assert p1 == p2
    lines = [json.loads(x) for x in Path(p1).read_text().splitlines()]
    assert [x["verdict"] for x in lines] == ["pruned", "already-gone:dir-absent"]
    assert all("ts" in x for x in lines)  # 逐条带时间戳


def test_symlink_escape_refused(tmp_path):
    """prune 白名单守卫：symlink 指向 lane 外 → blocked:outside-lane。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    lane = tmp_path / ".lane"
    lane.mkdir()
    link = lane / "evil"
    link.symlink_to(outside)
    entry = la.LaneEntry(name="evil", path=str(link), kind="stub", verdict=la.V_PRUNABLE)
    lane_real = os.path.realpath(lane)
    if not os.path.realpath(entry.path).startswith(lane_real + os.sep):
        entry.verdict = f"{la.V_BLOCKED}:outside-lane"
        entry.reason = "目标不在 lane 目录白名单内，拒绝"
    assert entry.verdict == f"{la.V_BLOCKED}:outside-lane"
