"""t260921-09 多仓 merge_check 三态判据 UT：纯函数矩阵 + 判定项四态（真 git tmp）+
聚合层全局闸 + 接线钉子。

覆盖面（对应方案 S1-S4 与工单验收 第 0 条/①②③⑤⑥ + review C1/C2/C3）：
  - lane_commit_verdict 纯函数矩阵：has_commits / no_changes_no_diff / no_commits
    两差异面 / commit_query_failed（-1 哨兵与畸形输入不抛 fail-closed）；
  - multirepo_zero_commit_error：全零点名、有 commit 放行、no_file_changes 豁免、
    -1 跳过（C1：单仓查询失败 / 多仓部分失败两态）、畸形不抛；
  - _lane_commits_check_item 四态（真 git tmp 夹具，沿 test_t26091620 模式）：
    green（无 reason_code=旧契约绿项只带 id）/ amber 点名（绿项带 reason_code=新
    形状，review C2）/ red 两支文案分叉（未提交面→实现未落盘+C3 互指；提交面→
    位点异常）/ 查询失败红（不断言未落盘）；
  - merge_check 聚合（桩法沿 test_t26091620）：第 0 条粒度锁（多目录写集同仓=1
    scope 且有 commit 不红）、①多仓某仓零改动推进不红且点名、②零 commit 有 diff
    仍红、③整票零 commit 全局红（位次=rehearsal 保持 checks[-1]、非冲突类）、
    no_file_changes 豁免、单仓防伪保持、C1 聚合态（含 -1 仓不产全局闸文案）、
    桩缺 lane_commits 键兼容；
  - 接线钉子：dev_lane 透传 no_file_changes、聚合层消费 args.no_file_changes
    （源码锚；字段存在性由 test_activity_arg_fields 的 AST 钉把守）。

畸形输入用例全走纯函数/桩/tmp git 夹具，不靠外部源（零网络/零 Temporal server）。
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import shared  # noqa: E402
from shared import MergeCheckArgs  # noqa: E402


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", branch, cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "f.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "base", cwd=path)
    return path


# ---------- 纯函数：lane_commit_verdict ----------

def test_verdict_has_commits_green():
    assert shared.lane_commit_verdict(1, 0, 0) == (True, "has_commits")
    # 有 commit 不看差异面（差异面只用于 0 commit 时的三态分叉）
    assert shared.lane_commit_verdict(3, 5, 2) == (True, "has_commits")


def test_verdict_no_changes_no_diff_amber():
    assert shared.lane_commit_verdict(0, 0, 0) == (True, "no_changes_no_diff")


def test_verdict_no_commits_red_both_faces():
    assert shared.lane_commit_verdict(0, 0, 2) == (False, "no_commits")  # 未提交面
    assert shared.lane_commit_verdict(0, 1, 0) == (False, "no_commits")  # 提交面
    assert shared.lane_commit_verdict(0, 2, 3) == (False, "no_commits")  # 两面


def test_verdict_query_failed_sentinel_and_malformed():
    # -1 哨兵：git 故障绝不记 0，也绝不断言「未落盘」（review C1）
    assert shared.lane_commit_verdict(-1, 0, 0) == (False, "commit_query_failed")
    for bad_n in (None, "x", True, -2, 1.5):
        assert shared.lane_commit_verdict(bad_n, 0, 0) == (False, "commit_query_failed")
    # 差异面畸形=不可证「无差异」→ 不给 amber（宁可红，不可假绿）
    for bad in (None, "x", True, -2):
        assert shared.lane_commit_verdict(0, bad, 0) == (False, "commit_query_failed")
        assert shared.lane_commit_verdict(0, 0, bad) == (False, "commit_query_failed")


def test_verdict_face_query_failed_sentinel_is_not_no_commits():
    """t261019-02: a face that failed to answer (-1) is a query failure, never
    "no_commits". The old fall-through read as "0 commits;  — implementation not
    persisted" with an empty face list and blamed a branch-position fault."""
    for failed in (shared.LANE_COMMITS_QUERY_FAILED,):
        assert shared.lane_commit_verdict(0, failed, 0) == (False, "commit_query_failed")
        assert shared.lane_commit_verdict(0, 0, failed) == (False, "commit_query_failed")
        assert shared.lane_commit_verdict(0, failed, failed) == (False, "commit_query_failed")
    # real-diff control: a real diff still reads no_commits (never launder a true red into a query failure)
    assert shared.lane_commit_verdict(0, 0, 1) == (False, "no_commits")
    assert shared.lane_commit_verdict(0, 1, 0) == (False, "no_commits")


def test_gate_probe_retries_transient_git_fault():
    """t261019-02: the diff-face probes go through _git_retry (bounded retry of a
    transient git fault, e.g. index.lock under parallel lanes), and the mutating
    call sites stay on plain _git."""
    src = (Path(__file__).resolve().parents[1] / "agent_activities.py").read_text()
    assert 'pd = _git_retry(["diff", "--name-only", base_ref, branch], repo)' in src
    assert '"status", "--porcelain", "-z", "--"] + SETTLE_PATHSPEC, tree)' in src
    assert 'ps = _git_retry(["status", "--porcelain", "-z", "--"]' in src
    # bounded: at most a few attempts, short delay (a frozen probe must not stall the gate)
    assert "def _git_retry(" in src and "attempts: int = 3" in src


# ---------- 纯函数：multirepo_zero_commit_error（整票零 commit 全局闸） ----------

def test_global_gate_all_zero_names_repos():
    err = shared.multirepo_zero_commit_error({"a": 0, "b": 0}, False)
    assert "a" in err and "b" in err and "zero commits across the whole ticket" in err
    assert "allow_empty_write_set" in err  # 出路一：确无改动走建票声明


def test_global_gate_passes_when_any_repo_has_commits():
    assert shared.multirepo_zero_commit_error({"a": 2, "b": 0}, False) == ""


def test_global_gate_exempt_no_file_changes():
    assert shared.multirepo_zero_commit_error({"a": 0, "b": 0}, True) == ""


def test_global_gate_skips_query_failed_c1():
    # C1 两态：单仓查询失败 / 多仓部分失败——都不得产出「整票零 commit」文案
    assert shared.multirepo_zero_commit_error({"a": -1}, False) == ""
    assert shared.multirepo_zero_commit_error({"a": 0, "b": -1}, False) == ""


def test_global_gate_malformed_no_throw():
    assert shared.multirepo_zero_commit_error({}, False) == ""
    assert shared.multirepo_zero_commit_error(None, False) == ""
    assert shared.multirepo_zero_commit_error({"a": None}, False) == ""
    assert shared.multirepo_zero_commit_error({"a": "x"}, False) == ""
    assert shared.multirepo_zero_commit_error({3: 0}, False)  # 非 str 键 str() 化点名，不抛


# ---------- 判定项：_lane_commits_check_item（真 git tmp 夹具） ----------

def test_item_green_keeps_old_shape(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("checkout", "-qb", "lane/x", cwd=repo)
    (repo / "f.txt").write_text("change\n", encoding="utf-8")
    _git("commit", "-aqm", "lane work", cwd=repo)
    item, n = aa._lane_commits_check_item("main", "lane/x", repo, repo)
    assert item["green"] is True and n == 1
    assert "1 commit(s)" in item["detail"]
    # 旧契约：绿项只带 id，不带 reason_code（has_commits 路径零回归）
    assert "reason_code" not in item


def test_item_amber_names_no_change(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("checkout", "-qb", "lane/x", cwd=repo)  # 同点建支，零 commit 零 diff
    item, n = aa._lane_commits_check_item("main", "lane/x", repo, repo)
    assert item["green"] is True and n == 0
    assert item["reason_code"] == "no_changes_no_diff"
    assert "zero-change confirmed" in item["item"] and "no changes genuinely needed" in item["detail"]


def test_item_red_uncommitted_face_names_not_landed(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("checkout", "-qb", "lane/x", cwd=repo)
    (repo / "dirty.txt").write_text("late\n", encoding="utf-8")  # 未提交面有差异
    item, n = aa._lane_commits_check_item("main", "lane/x", repo, repo)
    assert item["green"] is False and n == 0
    assert item["reason_code"] == "no_commits"
    assert "not persisted" in item["next_action"]  # t261018-05: copy in English
    # review C3：脏文件越写集形态互指「工作区干净」项处置，不再误导发 rework
    assert "pull them back into the write set" in item["next_action"]
    assert "uncommitted working-tree changes" in item["detail"]


def test_item_red_committed_face_names_position_anomaly(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("checkout", "-qb", "lane/x", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    (repo / "f.txt").write_text("main moved\n", encoding="utf-8")
    _git("commit", "-aqm", "main ahead", cwd=repo)  # main 前进，lane/x 停旧点
    item, n = aa._lane_commits_check_item("main", "lane/x", repo, repo)
    assert item["green"] is False and n == 0
    assert item["reason_code"] == "no_commits"
    assert "position abnormal" in item["next_action"]
    assert "diverges from base" in item["detail"]


def test_item_query_failed_never_asserts_not_landed(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    item, n = aa._lane_commits_check_item("main", "lane/definitely-missing", repo, repo)
    assert item["green"] is False and n == shared.LANE_COMMITS_QUERY_FAILED
    assert item["reason_code"] == "commit_query_failed"
    assert "不得断言实现未落盘" in item["next_action"]


# ---------- 聚合层：整票零 commit 全局闸（桩法沿 test_t26091620） ----------

def _rehearsal_item():
    return {"item": aa.MERGE_REHEARSAL_ITEM, "green": True, "detail": "无冲突",
            "id": "merge_rehearsal"}


def _amber_item():
    return {"item": "泳道分支有 commit——零改动确认", "green": True,
            "detail": "0 个 commit 且提交面/未提交面均无差异",
            "id": "lane_commits", "reason_code": "no_changes_no_diff"}


def _green_item(n=2):
    return {"item": "泳道分支有 commit", "green": True,
            "detail": "%d 个 commit" % n, "id": "lane_commits"}


def _scope_stub(checks, lane_commits=0, with_key=True):
    """聚合桩：返回给定 checks 与逐仓计数（with_key=False 模拟旧桩形态缺键）。"""
    async def _stub(args, sc, lane_root, multi):
        core = {"checks": list(checks), "rehearsal_green": True,
                "conflict_files": [], "merge_tree_excerpt": ""}
        if with_key:
            core["lane_commits"] = lane_commits
        return core
    return _stub


def _mk_multi_lane(tmp_path, repos=("r1", "r2")):
    """Real manifest lane fixture: _lane_scopes reads it into multi scopes. Since
    t261008-24 each member dir must be a real git repo (merge_check's green-run
    precondition rev-parses the branch on scopes[0]'s repo - the stubs stay
    judgment-free but the repos themselves must exist); branches = manifest-named
    lane/tkt-<r>."""
    lane = tmp_path / "proj" / ".lane" / "tkt"
    lane.mkdir(parents=True)
    import subprocess
    for r in repos:
        rp = _init_repo(tmp_path / "proj" / r, branch="main")
        # fuse B materialization face: the declared subdir must be committed so the
        # lane worktree carries a materialized tree
        (rp / "src").mkdir()
        (rp / "src" / "keep.txt").write_text("k\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(rp), "add", "-A"], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(rp), "commit", "-qm", "materialize"],
                       check=True, capture_output=True)
        # register lane/<repo> as a REAL worktree of the repo (same source as the
        # is_worktree_of predicate)
        subprocess.run(["git", "-C", str(rp), "worktree", "add", "-b",
                        "lane/tkt-%s" % r, str(lane / r)], check=True,
                       capture_output=True)
    mf = shared.multi_manifest_path(lane)
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps([{"repo": r, "name": r, "branch": "lane/tkt-%s" % r}
                              for r in repos]), encoding="utf-8")
    return lane


def T_git_add_commit(rp):
    import subprocess
    subprocess.run(["git", "-C", str(rp), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(rp), "commit", "-qm", "materialize"],
                   check=True, capture_output=True)


def _head(lane, repo="r1"):
    """Real HEAD of the manifest's first repo branch (the green-run face sha anchor,
    the same identity merge_check resolves as scopes[0])."""
    proj = Path(lane).parent.parent
    return _git("rev-parse", "--verify", "lane/tkt-%s" % repo, cwd=proj / repo)


def _run_mc(lane, monkeypatch, stub, no_file_changes=False,
            write_set=("r1/src/", "r2/lib/"), green_run=False):
    """green_run=True: inject the real-sha green-run face (the t261008-24
    precondition item is red fail-closed without a face / on a sha mismatch, so
    green-expecting cases must inject it or they drown in an intent-irrelevant
    red)."""
    monkeypatch.setattr(aa, "_merge_check_one_scope", stub)
    kwargs = {}
    if green_run:
        kwargs["last_green_run"] = {"sha": _head(lane), "ran": 1}
    return asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="tkt", worktree=str(lane), branch="lane/tkt", base_ref="basesha",
        write_set=list(write_set), no_file_changes=no_file_changes, **kwargs)))


def test_granularity_lock_multi_dirs_single_repo_one_scope(tmp_path):
    # 工单第 0 条（粒度锁）：多目录写集（部分目录零改动）同仓 → 仍 1 scope，
    # 绝不逐条目化判定
    root = tmp_path / "proj"
    wt = root / ".lane" / "tkt"
    wt.mkdir(parents=True)
    scopes = aa._lane_scopes(wt, "lane/tkt", "basesha", ["a/", "b/", "c/f.txt"])
    assert len(scopes) == 1
    assert scopes[0]["write_set"] == ["a/", "b/", "c/f.txt"]  # 单仓原样透传


def test_granularity_lock_multidir_write_set_with_commit_not_red(tmp_path, monkeypatch):
    # 工单第 0 条：多目录写集×有 commit → 不红（防改成逐条目要求落盘）
    lane = _mk_multi_lane(tmp_path)
    res = _run_mc(lane, monkeypatch,
                  _scope_stub([_green_item(1), _rehearsal_item()], lane_commits=1),
                  write_set=("r1/a/", "r1/b/", "r2/c/"), green_run=True)
    assert res.green is True
    assert not [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]


def test_merge_check_multirepo_one_repo_zero_changes_passes(tmp_path, monkeypatch):
    # 工单验收①：多仓×某仓零改动×零 diff → 推进不红，且该仓点名可见（不静默）
    lane = _mk_multi_lane(tmp_path)

    async def stub(args, sc, lane_root, multi):  # r1 确实零改动（amber），r2 有 commit
        if sc["name"] == "r1":
            return {"checks": [_amber_item(), _rehearsal_item()], "rehearsal_green": True,
                    "conflict_files": [], "merge_tree_excerpt": "", "lane_commits": 0}
        return {"checks": [_green_item(3), _rehearsal_item()], "rehearsal_green": True,
                "conflict_files": [], "merge_tree_excerpt": "", "lane_commits": 3}

    res = _run_mc(lane, monkeypatch, stub, green_run=True)
    assert res.green is True
    amber = [c for c in res.checks if c.get("reason_code") == "no_changes_no_diff"]
    assert amber and "r1" in amber[0]["item"]  # multi 前缀点名仓名
    assert not [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]


def test_merge_check_zero_commit_with_diff_still_red(tmp_path, monkeypatch):
    # 工单验收②：多仓×某仓零 commit×有 diff → 仍红，非冲突类（blocked 交人）
    lane = _mk_multi_lane(tmp_path)
    red = {"item": "泳道分支有 commit", "green": False,
           "detail": "0 个 commit；工作区有未提交改动（1 个文件）——实现未落盘",
           "id": "lane_commits", "reason_code": "no_commits",
           "next_action": "实现未落盘（有改动未入轨）"}

    async def stub(args, sc, lane_root, multi):
        if sc["name"] == "r1":
            return {"checks": [dict(red), _rehearsal_item()], "rehearsal_green": True,
                    "conflict_files": [], "merge_tree_excerpt": "", "lane_commits": 0}
        return {"checks": [_green_item(3), _rehearsal_item()], "rehearsal_green": True,
                "conflict_files": [], "merge_tree_excerpt": "", "lane_commits": 3}

    res = _run_mc(lane, monkeypatch, stub)
    assert res.green is False and res.conflict is False
    assert any(c.get("reason_code") == "no_commits" for c in res.checks)
    assert not [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]


def test_merge_check_all_repos_zero_commit_global_red(tmp_path, monkeypatch):
    # 工单验收③：整票零 commit（非 no_file_changes）→ 全局红；位次契约=rehearsal
    # 保持 checks[-1]、全局红落 checks[:-1]（非冲突类，绝不进自动消解回路）
    lane = _mk_multi_lane(tmp_path)
    res = _run_mc(lane, monkeypatch,
                  _scope_stub([_amber_item(), _rehearsal_item()], lane_commits=0))
    assert res.green is False and res.conflict is False
    gate = [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]
    assert len(gate) == 1 and "zero commits across the whole ticket" in gate[0]["detail"]
    assert gate[0]["reason_code"] == "all_repos_zero_commits"
    assert "allow_empty_write_set" in gate[0]["next_action"]
    assert res.checks[-1]["id"] == "merge_rehearsal"
    # t261008-24 的 green-run 前置项曾坐在 rehearsal 之前（KI-047 槽位契约扩展面）；
    # **261009 宿主直修令已把它从现行门摘除**（理由见 agent_activities.py 该处注释与
    # docs/design/develop-buffer-v1.md：判据绑 sha 相等，别人合票即作废本票的绿，
    # 四张票被永久挡住）⇒ 现行门的 rehearsal 之前一项回到 all_repos_zero_commits。
    # 本断言随之回到摘除前的形状；判据函数本身的 UT 仍在
    # test_t261008_24_zero_run_supply.py（只测函数，不再钉接线）。
    assert res.checks[-2]["id"] == "all_repos_zero_commits"


def test_merge_check_no_file_changes_exempt_global_gate(tmp_path, monkeypatch):
    # 工单验收③豁免面：no_file_changes 票全仓零 commit → 放行（与 review gate 同口径）
    lane = _mk_multi_lane(tmp_path)
    res = _run_mc(lane, monkeypatch,
                  _scope_stub([_amber_item(), _rehearsal_item()], lane_commits=0),
                  no_file_changes=True, green_run=True)
    assert res.green is True
    assert not [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]


def test_merge_check_query_failed_repo_skips_global_gate(tmp_path, monkeypatch):
    # review C1 聚合态：含 -1 仓时全局闸不产「整票零 commit」文案；红由逐仓
    # commit_query_failed 承担
    lane = _mk_multi_lane(tmp_path)

    async def stub(args, sc, lane_root, multi):
        if sc["name"] == "r1":
            return {"checks": [{"item": "泳道分支有 commit", "green": False,
                                "detail": "git log 失败", "id": "lane_commits",
                                "reason_code": "commit_query_failed"},
                               _rehearsal_item()],
                    "rehearsal_green": True, "conflict_files": [],
                    "merge_tree_excerpt": "", "lane_commits": -1}
        return {"checks": [_amber_item(), _rehearsal_item()], "rehearsal_green": True,
                "conflict_files": [], "merge_tree_excerpt": "", "lane_commits": 0}

    res = _run_mc(lane, monkeypatch, stub)
    assert not [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]
    assert res.green is False  # 红在，但红的是「查询失败」不是「零 commit」


def test_merge_check_single_repo_zero_commit_still_red(tmp_path, monkeypatch):
    # 工单验收⑤（单仓防伪保持）：单仓 0 commit 全零 diff → amber 点名 + 全局闸红
    # （宿主裁定②「整票至少一个仓有 commit」在单仓同样成立；旧判定=红，新判定仍红）
    wt = tmp_path / "solo" / ".lane" / "tkt"  # 无清单 → 单仓 fallback scope
    monkeypatch.setattr(aa, "_merge_check_one_scope",
                        _scope_stub([_amber_item(), _rehearsal_item()], lane_commits=0))
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="tkt", worktree=str(wt), branch="lane/tkt", base_ref="basesha",
        write_set=["a/"], no_file_changes=False)))
    assert res.green is False
    assert any(c.get("reason_code") == "no_changes_no_diff" for c in res.checks)
    assert any(c.get("id") == "all_repos_zero_commits" for c in res.checks)


def test_merge_check_single_repo_no_file_changes_green(tmp_path, monkeypatch):
    # 行为变化点名面（方案自报、review 复核认可）：no_file_changes 单仓票由红转
    # amber+豁免=绿——对齐 review gate 既有豁免
    wt = tmp_path / "solo" / ".lane" / "tkt"
    _init_repo(tmp_path / "solo", branch="lane/tkt")  # real repo: face sha resolvable
    monkeypatch.setattr(aa, "_merge_check_one_scope",
                        _scope_stub([_amber_item(), _rehearsal_item()], lane_commits=0))
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="tkt", worktree=str(wt), branch="lane/tkt", base_ref="basesha",
        write_set=[], no_file_changes=True,
        last_green_run={"sha": _git("rev-parse", "--verify", "lane/tkt",
                                    cwd=tmp_path / "solo"), "ran": 1})))
    assert res.green is True
    assert not [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]


def test_merge_check_stub_without_count_key_skips_gate(tmp_path, monkeypatch):
    # 兼容面：桩/旧回执形态缺 lane_commits 键 = 不可判 → 跳过全局闸（不误判全零）
    lane = _mk_multi_lane(tmp_path)
    res = _run_mc(lane, monkeypatch,
                  _scope_stub([_amber_item(), _rehearsal_item()], lane_commits=0,
                              with_key=False), green_run=True)
    assert res.green is True
    assert not [c for c in res.checks if c.get("id") == "all_repos_zero_commits"]


# ---------- 接线钉子（源码锚，沿 t26091620「源码序钉死」先例） ----------

def test_wiring_pins_dev_lane_and_aggregation():
    dl_src = (POC / "dev_lane.py").read_text("utf-8")
    assert re.search(r'MergeCheckArgs\(.*?no_file_changes=bool\(self\.meta\.get\('
                     r'"no_file_changes"\)\)', dl_src, re.S), \
        "dev_lane 必须向 merge_check 透传 meta.no_file_changes"
    aa_src = (POC / "agent_activities.py").read_text("utf-8")
    assert "args.no_file_changes" in aa_src, "聚合层必须消费 no_file_changes 豁免"
    assert "multirepo_zero_commit_error" in aa_src, "聚合层必须接整票零 commit 全局闸"
    assert "shared.lane_commit_verdict" in aa_src, "判定项必须走 shared 纯函数单点"
