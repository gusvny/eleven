"""t260916-20 嵌套仓守卫 UT：纯判定 + 双 settle 站点 + 合并/拆道闸（真 git tmp 夹具）。

覆盖面（对应方案步骤 2/3/4 与验收 ①③④ 的 UT 面）：
  - staged_gitlinks：--raw 解析 160000、畸形行丢弃不猜（纯函数）；
  - gitlink_risk_from_dirty：untracked 目录折叠形态 × .git 存在（repo/worktree 两形）、
    畸形条目跳过（纯函数 + tmp 目录构形，零 git 子进程）；
  - unregistered_nested_repos：BFS 扫描、在册树跳过（含内部）、协调目录/符号链接
    跳过、容器缺失=空清单（幂等）、IO 故障=RuntimeError（守卫自身故障 fail-closed）；
  - _settle_worktree_lane (a)/(b)：两形态各拒一次、无 commit、现场保留；无嵌套仓
    的普通 settle 回归（仍正常代落盘）；
  - settle_conflict_resolution (a)/(b)：MERGE_HEAD 在场的旁路站点同拒（R2 洞闭合）；
  - _gitlink_check_item：绿/红(gitlink_present)/不可判(failed)/skip 四态；
  - merge_check 聚合分类：gitlink 红项落 checks[:-1] → conflict=False（KI-047 位置
    契约，桩法同 test_t260910_03_fuses）；接线位次用源码序钉死（gitlink 追加点在
    verify_lane 段之前）；
  - _squash_merge 0.6 前置红灯：failed(reason=gitlink_present)、主树未动；
  - _squash_merge 内联清理守卫：落账后停拆、嵌套仓对象库完好；
  - teardown_lane 拆除守卫：blocked 点名、对象库完好、泳道保留；守卫自身故障=
    failed 点名。

畸形输入用例全走 tmp git 夹具/桩，不靠外部源（零网络/零 Temporal server/零模型）。
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
from shared import (ConflictSettleArgs, MergeArgs, MergeCheckArgs,  # noqa: E402
                    MergeResult)


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path, fname="f.txt", branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", branch, cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / fname).write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def _make_nested_repo(path, committed=True):
    """泳道内从零建成员仓的事故形态：git init（默认分支 main）+ 可选一笔提交。"""
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    if committed:
        (path / "data.txt").write_text("nested\n", encoding="utf-8")
        _git("add", "-A", cwd=path)
        _git("commit", "-m", "nested base", cwd=path)
    return path


def _head(repo):
    return _git("rev-parse", "HEAD", cwd=repo)


# ---------- 纯判定：staged_gitlinks ----------

def test_staged_gitlinks_parses_add_and_modify():
    raw = (":000000 160000 0000000000000000000000000000000000000000 abc123 A\tcontent\n"
           ":000000 100644 0000000000000000000000000000000000000000 abc123 A\tcode.py\n"
           ":160000 160000 111 222 M\tsub/nested\n")
    assert aa.staged_gitlinks(raw) == ["content", "sub/nested"]


@pytest.mark.parametrize("bad", [
    "", None, 123,
    "refactoring\n",                                   # 非 : 开头
    ":000000 100644 000 111 A\tcode.py\n",             # 无 160000
    ":000000 160000 000\n",                            # 列数不足
    ":000000 160000 000 111 A\t\n",                    # 路径段为空
])
def test_staged_gitlinks_malformed_dropped(bad):
    assert aa.staged_gitlinks(bad) == []


# ---------- 纯判定：gitlink_risk_from_dirty ----------

def test_risk_flags_nested_repo_and_worktree_forms(tmp_path):
    tree = tmp_path / "lane"
    tree.mkdir()
    _make_nested_repo(tree / "content", committed=True)          # .git 目录
    (tree / "wt-nested").mkdir()                                 # .git 文件（worktree 形态）
    (tree / "wt-nested" / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    (tree / "plain").mkdir()                                     # 普通目录：不命中
    dirty = ["content/", "wt-nested/", "plain/", "code.py"]
    risks = aa.gitlink_risk_from_dirty(dirty, tree)
    assert [(r["name"], r["form"]) for r in risks] == [("content", "repo"),
                                                       ("wt-nested", "worktree")]


def test_risk_ignores_malformed_and_non_slash_entries(tmp_path):
    tree = tmp_path / "lane"
    tree.mkdir()
    _make_nested_repo(tree / "content")
    dirty = ["content", "/abs/", "../esc/", "a\\b/", "g*/", "a/../b/", None, 123, ""]
    assert aa.gitlink_risk_from_dirty(dirty, tree) == []


def test_risk_empty_or_bad_tree(tmp_path):
    assert aa.gitlink_risk_from_dirty(["content/"], tmp_path) == []  # 目录不在=无命中
    assert aa.gitlink_risk_from_dirty([], tmp_path) == []
    assert aa.gitlink_risk_from_dirty(["content/"], "not-a-path") == []


# ---------- 纯判定：unregistered_nested_repos ----------

def test_scan_flags_unregistered_skips_registered_and_excluded(tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    _make_nested_repo(lane / "content")
    # 在册成员树（含 .git gitfile 与其内部嵌套）→ 整树跳过
    member = lane / "repo_a"
    member.mkdir()
    (member / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    _make_nested_repo(member / "inner", committed=False)
    # 协调目录内部不扫（与 _SETTLE_RESET_PATHS 同真源）
    coord = lane / aa._SETTLE_RESET_PATHS[1]
    _make_nested_repo(coord / "deep", committed=False)
    # 符号链接目录跳过（链接目标在外）
    target = tmp_path / "outside"
    _make_nested_repo(target)
    os.symlink(str(target), str(lane / "linked"))
    found = aa.unregistered_nested_repos(lane, [lane, member])
    assert [(f["path"], f["form"]) for f in found] == [("content", "repo")]


def test_scan_missing_lane_root_returns_empty(tmp_path):
    assert aa.unregistered_nested_repos(tmp_path / "nope", []) == []


def test_scan_unreadable_dir_raises_guard_fault(tmp_path):
    lane = tmp_path / "lane"
    dark = lane / "dark"
    dark.mkdir(parents=True)
    os.chmod(dark, 0o000)
    try:
        with pytest.raises(RuntimeError):
            aa.unregistered_nested_repos(lane, [lane])
    finally:
        os.chmod(dark, 0o755)


def test_scan_deep_repo_not_double_flagged(tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    _make_nested_repo(lane / "outer" / "inner", committed=False)
    (lane / "outer" / ".git").mkdir()  # outer 也是仓形
    found = aa.unregistered_nested_repos(lane, [lane])
    assert [f["path"] for f in found] == ["outer"]


# ---------- 夹具：带泳道 worktree 的单仓项目 ----------

@pytest.fixture
def lane_repo(tmp_path):
    """根仓 + .lane/<id> 泳道 worktree（引擎路径约定形态），返回 (root, lane)。"""
    root = _init_repo(tmp_path / "proj")
    lane = root / ".lane" / "t26091620ut"
    _git("worktree", "add", "-b", "lane/t26091620ut", str(lane), cwd=root)
    return root, lane


# ---------- _settle_worktree_lane (a)/(b) ----------

def test_settle_refuses_untracked_nested_repo(lane_repo):
    root, lane = lane_repo
    _make_nested_repo(lane / "content", committed=False)  # 0 提交：会被吞成普通文件的形态
    (lane / "code.py").write_text("work\n", encoding="utf-8")
    head_before = _head(lane)  # 泳道分支尖（settle 的 commit 落泳道分支，不落 main）
    refusal = {}
    note = aa._settle_worktree_lane(lane, "t26091620ut", "implement", 0,
                                    repo=root, refusal=refusal)
    assert "path_gate_reason=gitlink_nested_repo" in note and "content" in note
    assert refusal.get("reason_code") == "gitlink_nested_repo"
    assert refusal.get("files") == ["content"]
    assert _head(lane) == head_before, "拒绝落盘=不得产生 commit"
    assert (lane / "content" / ".git").exists(), "现场保留：嵌套仓不得被动"


def test_settle_refuses_staged_gitlink(lane_repo):
    root, lane = lane_repo
    _make_nested_repo(lane / "content", committed=True)
    _git("add", "content", cwd=lane)  # 预暂存 gitlink（(a) 的判脏清单不再有尾斜杠条目）
    (lane / "code.py").write_text("work\n", encoding="utf-8")
    head_before = _head(lane)
    note = aa._settle_worktree_lane(lane, "t26091620ut", "implement", 0, repo=root)
    assert "gitlink_nested_repo" in note and "content" in note
    assert _head(lane) == head_before
    # 现场保留：gitlink 仍在暂存区（不 reset）
    raw = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--cached", "--raw"],
                         cwd=str(lane), capture_output=True, text=True).stdout
    assert aa.staged_gitlinks(raw) == ["content"]


def test_settle_normal_path_still_commits(lane_repo):
    root, lane = lane_repo
    (lane / "code.py").write_text("work\n", encoding="utf-8")
    head_before = _head(lane)
    note = aa._settle_worktree_lane(lane, "t26091620ut", "implement", 0, repo=root)
    assert "代落盘" in note
    assert _head(lane) != head_before


# ---------- settle_conflict_resolution (a)/(b)（R2 旁路站点） ----------

@pytest.fixture
def conflict_lane(tmp_path):
    """main × lane 相邻行冲突（MERGE_HEAD 在场），泳道即 worktree。"""
    root = _init_repo(tmp_path / "proj", "f.txt")
    _git("worktree", "add", "-b", "lane/t26091620ut", str(root / ".lane" / "t26091620ut"),
         cwd=root)
    lane = root / ".lane" / "t26091620ut"
    (lane / "f.txt").write_text("line1\nline2\nLANE\nline3\n", encoding="utf-8")
    _git("commit", "-qam", "lane side", cwd=lane)
    (root / "f.txt").write_text("line1\nline2\nMAIN\nline3\n", encoding="utf-8")
    _git("commit", "-qam", "main side", cwd=root)
    # 期望中的冲突：rc=1 + MERGE_HEAD 在场 + f.txt=UU（不走 assert 版 _git）
    p = subprocess.run(["git", "merge", "main"], cwd=str(lane),
                       capture_output=True, text=True)
    assert p.returncode == 1 and "CONFLICT" in (p.stdout + p.stderr), p.stdout + p.stderr
    return root, lane


def test_conflict_settle_refuses_untracked_nested_repo(conflict_lane):
    root, lane = conflict_lane
    assert subprocess.run(["git", "rev-parse", "--verify", "MERGE_HEAD"], cwd=str(lane),
                          capture_output=True).returncode == 0
    _make_nested_repo(lane / "content", committed=False)
    head_before = _head(lane)
    res = asyncio.run(aa.settle_conflict_resolution(ConflictSettleArgs(
        ticket_id="t26091620ut", worktree=str(lane), branch="lane/t26091620ut", round_no=1)))
    assert res.ok is False and "content" in (res.error or "") and "嵌套仓" in (res.error or "")
    assert _head(lane) == head_before, "拒绝=不得落合并提交"
    assert subprocess.run(["git", "rev-parse", "--verify", "MERGE_HEAD"], cwd=str(lane),
                          capture_output=True).returncode == 0, "现场保留：MERGE_HEAD 原样"


def test_conflict_settle_refuses_staged_gitlink(conflict_lane):
    root, lane = conflict_lane
    _make_nested_repo(lane / "content", committed=True)
    _git("add", "content", cwd=lane)
    head_before = _head(lane)
    res = asyncio.run(aa.settle_conflict_resolution(ConflictSettleArgs(
        ticket_id="t26091620ut", worktree=str(lane), branch="lane/t26091620ut", round_no=1)))
    assert res.ok is False and "content" in (res.error or "")
    assert _head(lane) == head_before


# ---------- _gitlink_check_item（merge_check 检查项） ----------

def test_gitlink_check_item_green_without_gitlink(lane_repo):
    root, lane = lane_repo
    (lane / "code.py").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "work", cwd=lane)
    base = _git("merge-base", "main", "lane/t26091620ut", cwd=root)
    item = aa._gitlink_check_item(base, "lane/t26091620ut", root)
    assert item["green"] is True and item["id"] == "no_gitlink"


def test_gitlink_check_item_red_names_gitlink(lane_repo):
    root, lane = lane_repo
    _make_nested_repo(lane / "content", committed=True)
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "accident: gitlink", cwd=lane)
    base = _git("merge-base", "main", "lane/t26091620ut", cwd=root)
    item = aa._gitlink_check_item(base, "lane/t26091620ut", root)
    assert item["green"] is False and item["reason_code"] == "gitlink_present"
    assert item["files"] == ["content"]
    assert "勿摘 gitlink 绕行" in item["next_action"]


def test_gitlink_check_item_skip_and_fault(lane_repo):
    root, lane = lane_repo
    skipped = aa._gitlink_check_item("", "lane/t26091620ut", root)
    assert skipped["reason_code"] == "gitlink_check_skipped" and skipped["green"] is False
    fault = aa._gitlink_check_item("HEAD", "lane/definitely-not-a-branch", root)
    assert fault["reason_code"] == "gitlink_check_failed" and fault["green"] is False


# ---------- merge_check 聚合分类（KI-047 位置契约，桩法同 t260910-03） ----------

async def _stub_scope_gitlink_red(args, sc, lane_root, multi):
    """标准项绿 + gitlink 红项（中段位）+ rehearsal 绿且在最后（同真实函数形）。"""
    return {"checks": [
        {"item": "泳道分支有 commit", "green": True, "detail": ""},
        {"item": "工作区干净", "green": True, "detail": ""},
        {"item": "泳道差集无 gitlink（嵌套仓）", "green": False,
         "reason_code": "gitlink_present", "files": ["content"], "detail": "红"},
        {"item": aa.MERGE_REHEARSAL_ITEM, "green": True, "detail": "无冲突"},
    ], "rehearsal_green": True, "conflict_files": [], "merge_tree_excerpt": ""}


def test_merge_check_gitlink_red_is_not_conflict_class(lane_repo, monkeypatch):
    root, lane = lane_repo
    monkeypatch.setattr(aa, "_merge_check_one_scope", _stub_scope_gitlink_red)
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="t26091620ut", worktree=str(lane), branch="lane/t26091620ut",
        base_ref=_head(root), write_set=["content/"])))
    assert res.green is False
    assert res.conflict is False, "gitlink 红=blocked 交人工，绝不进自动消解回路"
    red = [c for c in res.checks if c.get("reason_code") == "gitlink_present"]
    assert red and red[0]["files"] == ["content"]


def test_merge_check_gitlink_item_wired_before_verify_lane_segment():
    """接线位次源码序钉死：_merge_check_one_scope 内 gitlink 追加点必须出现在
    verify_lane 段（item 3）之前——位次是「gitlink 权威红先于越界写误诊文案」与
    checks[:-1] 非冲突类的共同前提（R3.1）。"""
    import inspect
    src = inspect.getsource(aa._merge_check_one_scope)
    assert src.index("checks.append(_gitlink_check_item(") < src.index("# 3. verify_lane")


# ---------- _squash_merge 0.6 前置红灯 ----------

def test_squash_merge_red_lights_gitlink(lane_repo):
    root, lane = lane_repo
    (lane / "code.py").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "work", cwd=lane)
    _make_nested_repo(lane / "content", committed=True)
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "accident: gitlink", cwd=lane)
    head_before = _head(root)
    res = aa._squash_merge(root, lane, "lane/t26091620ut", "t26091620ut")
    assert res.ok is False and res.reason == "gitlink_present"
    assert res.files == ["content"]
    assert _head(root) == head_before, "主树未动（取舍 b）"
    st = subprocess.run(["git", "status", "--porcelain"], cwd=str(root),
                        capture_output=True, text=True).stdout.splitlines()
    assert all(ln.startswith("?? .lane") for ln in st), \
        "主树无暂存/已跟踪改动（.lane/ 在真引擎为 gitignore，tmp 夹具例外）：%s" % st


def test_squash_merge_gitlink_preflight_fault_fail_closed(lane_repo):
    root, lane = lane_repo
    res = aa._squash_merge(root, lane, "lane/definitely-not-a-branch", "t26091620ut")
    assert res.ok is False and res.reason == "merge_fault"
    assert "merge-base 失败" in (res.error or "")


# ---------- _squash_merge 内联清理守卫（老票唯一拆道通道） ----------

def test_squash_merge_inline_teardown_stops_on_nested_repo(lane_repo):
    root, lane = lane_repo
    (lane / "code.py").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "work", cwd=lane)
    _make_nested_repo(lane / "content", committed=False)  # 未注册嵌套仓（未 add，不进 diff）
    head_before = _head(root)
    res = aa._squash_merge(root, lane, "lane/t26091620ut", "t26091620ut",
                           defer_teardown=False)
    assert res.ok is False and res.reason == "teardown_guard"
    assert res.files == ["content"]
    assert _head(root) != head_before, "落账已完成（守卫在收尾段）"
    assert lane.is_dir() and (lane / "content" / ".git").exists(), "泳道保留=对象库可抢救"


# ---------- teardown_lane 拆除守卫 ----------

def test_teardown_blocked_names_nested_repo_objects_intact(lane_repo):
    root, lane = lane_repo
    _make_nested_repo(lane / "content", committed=True)
    nested_head = _git("rev-parse", "HEAD", cwd=lane / "content")
    res = asyncio.run(aa.teardown_lane(MergeArgs(
        ticket_id="t26091620ut", worktree=str(lane), branch="lane/t26091620ut")))
    assert res.ok is False and res.action == "failed"
    assert "拆除守卫" in (res.error or "") and "content" in (res.error or "")
    assert _git("rev-parse", "HEAD", cwd=lane / "content") == nested_head, "对象库完好"
    assert lane.is_dir(), "一物不拆"


def test_teardown_guard_own_fault_fail_closed(lane_repo):
    root, lane = lane_repo
    dark = lane / "dark"
    dark.mkdir()
    os.chmod(dark, 0o000)
    try:
        res = asyncio.run(aa.teardown_lane(MergeArgs(
            ticket_id="t26091620ut", worktree=str(lane), branch="lane/t26091620ut")))
    finally:
        os.chmod(dark, 0o755)
    assert res.ok is False and "守卫自身故障" in (res.error or "")
    assert lane.is_dir()


def test_teardown_clean_lane_still_tears_down(lane_repo):
    root, lane = lane_repo  # 无嵌套仓：既有语义零回归（拆干净）
    res = asyncio.run(aa.teardown_lane(MergeArgs(
        ticket_id="t26091620ut", worktree=str(lane), branch="lane/t26091620ut")))
    assert res.ok is True and res.action == "teardown"
    assert not lane.exists()
    assert subprocess.run(["git", "branch", "--list", "lane/t26091620ut"], cwd=str(root),
                          capture_output=True, text=True).stdout.strip() == ""


# ---------- 幂等红灯（重试同拒） ----------

def test_settle_refusal_idempotent_on_retry(lane_repo):
    root, lane = lane_repo
    _make_nested_repo(lane / "content", committed=False)
    (lane / "code.py").write_text("work\n", encoding="utf-8")
    note1 = aa._settle_worktree_lane(lane, "t26091620ut", "implement", 0, repo=root)
    note2 = aa._settle_worktree_lane(lane, "t26091620ut", "implement", 0, repo=root)
    assert note1 == note2 and "gitlink_nested_repo" in note2


def test_merge_result_files_field_exists():
    # MergeResult 契约面：files 字段在（红灯点名载荷的承载字段，t260910-03 同款）
    assert "files" in MergeResult.__dataclass_fields__
