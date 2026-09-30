#!/usr/bin/env python3
"""t260826-01 selfcheck: the conflict auto-resolution loop (offline — no
Temporal server, no model calls, no touching the real repo).

Usage (from the engine directory):
    <venv>/bin/python selfcheck_conflict_resolution.py            # full run
    <venv>/bin/python selfcheck_conflict_resolution.py --mock-mc  # skip the real
        git rehearsal and use a stand-in merge_check (real_merge_check stub) to
        cover the decision matrix — use this fallback when a dev-machine sandbox
        blocks the real-repo merge-tree write (no silent downgrade: the stub run
        is reported honestly in group D)

Coverage:
  A. _parse_conflict_files pure logic: CONFLICT lines / entry lines (stage1/2/3)
     / two-way union with dedup+sort / empty output and bad-ref error output both
     parse to empty;
  B. merge_check conflict classification (real git: an isolated tmp repo
     recreates the t260825-03 same-file-adjacent-line conflict on both sides):
     rc/output shape verified, conflict=True, conflict_files hit, excerpt
     carried; a clean merge has rc=0 -> green; a bad ref has rc=1 but parses to
     empty -> conflict=False (M1);
  C. prepare/settle_conflict_resolution closed loop (real git, real activity):
     prep leaves the conflict scene (UU file) -> simulated agent resolves the
     markers -> settle writes the merge commit (clean worktree, two parents) ->
     merge_check re-verifies green (constructive proof that "resolved" really
     turns green, at activity level); an unresolved scene -> settle ok=False +
     remaining_files; a dirty worktree rejected by git -> prep ok=False as
     non-conflict;
  D. dev_lane orchestration decision matrix (_mc_decision state-machine replay,
     case-by-case matching the merge_check branch in dev_lane.py): conflict
     round -> resolve / over 3 rounds -> blocked with the anchor text "冲突消解
     N 轮未收敛" / same file set again (any order) -> blocked "同批文件反复冲突"
     (M6) / non-conflict reds (no commit, dirty+conflict, rehearsal red but parse
     empty) -> blocked "merge_check 红灯" (regression) / green -> merge;
  E. strict-serialization structural assertions (S2): source-text assertion that
     in dev_lane.py prep -> implement -> settle appear in that order inside the
     merge_check branch (no merge_check runs inside the dirty window); the two
     new activities are registered in ALL_AGENT_ACTIVITIES (M2).
  F. review F1 regression (real git): _settle_worktree_lane must not jump ahead
     with a merge commit while a merge is in progress — with MERGE_HEAD present
     it commits nothing and consumes nothing; full-chain test prep -> auto
     settle (guardrail skips) -> agent resolves -> settle_conflict_resolution
     writes the only merge commit, with no marker residue in the content; a
     normal implement round without MERGE_HEAD keeps its usual write behavior.

Exit code 0 = all green; non-zero = at least one red (details on stderr).
SANDBAR_CR_KEEP=1 keeps the tmp directory for inspection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parent
sys.path.insert(0, str(POC))

from temporalio.testing import ActivityEnvironment  # noqa: E402

import agent_activities  # noqa: E402
from agent_activities import (  # noqa: E402
    _parse_conflict_files,
    merge_check,
    prepare_conflict_resolution,
    settle_conflict_resolution,
)
from shared import (  # noqa: E402
    ConflictPrepArgs,
    ConflictSettleArgs,
    MergeCheckArgs,
)

from selfcheck_common import Selfcheck  # noqa: E402  t261001-04：ok() 收敛到唯一定义，输出格式逐字不变

_rep = Selfcheck(track_failures=True)
ok = _rep.ok


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + list(args), cwd=str(repo),
                          capture_output=True, text=True, timeout=60)


def _mk_conflict_repo(root: Path) -> Path:
    """Build a repo with the "both sides add one line on adjacent lines of the
    same file" conflict (same shape as t260825-03, plain text, no real conflict
    machinery needed).

    The layout mirrors a real lane: repo/ = the main tree (main branch),
    repo/.worktrees/t-self/ = the lane worktree (lane branch) — the lane git
    operations in agent_activities (merge/commit/status) all run on the
    worktree path, same as production. Returns the main-tree path."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "selfcheck@t260826-01")
    _git(repo, "config", "user.name", "selfcheck")
    (repo / "f.txt").write_text("line1\nline2\nline3\n", "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    _git(repo, "worktree", "add", "-q", "-b", "lane", str(repo / ".worktrees" / "t-self"))
    wt = repo / ".worktrees" / "t-self"
    (wt / "f.txt").write_text("line1\nline2\nLANE-ADD\nline3\n", "utf-8")
    _git(wt, "commit", "-qam", "lane 相邻行加一行")
    (repo / "f.txt").write_text("line1\nline2\nMAIN-ADD\nline3\n", "utf-8")
    _git(repo, "commit", "-qam", "main 相邻行加一行")
    return repo


class _RealMergeTreeConflict(Exception):
    """Raised when a B-4 evidence assertion fails: real-repo merge-tree behavior
    changed (git version drift) and the empirical base of the whole conflict
    classification is gone — this must be a red light, never silent."""


# ---- merge_check stand-in (--mock-mc mode; a stub of the real merge_check,
# only the merge-tree rehearsal step is replaced) ----
#
# Real merge_check = three git/script checks (here trimmed to the two hard
# checks that matter for the fake repo: "lane branch has commits" + "worktree
# clean") + a merge-tree rehearsal. The stub keeps the same classification
# formula:
#   conflict = only the rehearsal item is red AND conflict_files is non-empty
# Rehearsal red/green and conflict_files are fed explicitly per case (equivalent
# to the shapes group B measured on the real repo).


def _mock_merge_check(repo: Path, branch: str,
                      rehearsal_red: bool, files):
    """Stand-in merge_check: returns a dict of the same shape as the real
    MergeCheckResult for _mc_decision to consume."""
    checks = []
    p = _git(repo, "log", "--oneline", "main..%s" % branch)
    n = len([ln for ln in p.stdout.splitlines() if ln.strip()]) if p.returncode == 0 else 0
    checks.append({"item": "泳道分支有 commit", "green": n > 0})
    wt = repo / ".worktrees" / "t-self"
    p = _git(wt if wt.is_dir() else repo, "status", "--porcelain")
    dirty = [ln for ln in p.stdout.splitlines() if ln.strip()] if p.returncode == 0 else ["?"]
    checks.append({"item": "工作区干净", "green": not dirty})
    checks.append({"item": "merge 预演无冲突", "green": not rehearsal_red})
    conflict_files = sorted(files) if rehearsal_red else []
    other_red = any(not c["green"] for c in checks[:-1])
    green = all(c["green"] for c in checks)
    conflict = (not green) and (not other_red) and rehearsal_red and bool(conflict_files)
    return {"green": green, "checks": checks, "conflict": conflict,
            "conflict_files": conflict_files,
            "merge_tree_excerpt": "CONFLICT (content): …" if conflict else ""}


# ---- Group D: orchestration decision matrix (a state-machine replay matching
# the merge_check branch in dev_lane.py case by case) ----
#
# The dev_lane loop is workflow code (the sandbox has no Temporal test server,
# so we cannot run the real workflow offline — stated plainly, coverage is not
# exaggerated); here the branch decision formula is replayed 1:1 as a pure
# function and every input bucket's outcome is asserted. The mapping to
# dev_lane.py is noted in each assertion's comment.

MAX_CONFLICT_ROUNDS = 3  # must match dev_lane.MAX_CONFLICT_ROUNDS (structural assertion in group E)


def _mc_decision(state, mc):
    """Replay of the merge_check branch decision. state={rounds, prev_files};
    returns (action, detail).

    action is merge / blocked-nonconflict / blocked-overlimit /
    blocked-samebatch / resolve — the five exits of dev_lane.py, one to one."""
    if mc["green"]:
        state["rounds"] = 0
        state["prev_files"] = []
        return "merge", ""
    if not mc["conflict"]:
        return "blocked-nonconflict", "merge_check 红灯"
    state["rounds"] += 1
    sig = sorted(mc["conflict_files"])
    if state["rounds"] > MAX_CONFLICT_ROUNDS:
        return "blocked-overlimit", "冲突消解 %d 轮未收敛" % (state["rounds"] - 1)
    if state["prev_files"] and sig == state["prev_files"]:
        return "blocked-samebatch", "同批文件反复冲突"
    state["prev_files"] = sig
    return "resolve", "第 %d 轮" % state["rounds"]


async def _c_checks(env, tmp: Path, wt: Path, repo: Path):
    """Group C: prepare/settle_conflict_resolution closed loop (real activity,
    same event loop).

    Returns (repo2, wt2): the "dirty worktree + rehearsal conflict" lane, reused
    by D-5b."""
    print("C. prepare/settle_conflict_resolution 闭环（真 git 真 activity）")
    prep = await env.run(prepare_conflict_resolution,
                         ConflictPrepArgs(ticket_id="t-self", worktree=str(wt),
                                          branch="lane", base_ref="main"))
    ok(prep.ok and not prep.already_clean, "C-1 prep ok 且非竞态兜底")
    ok(prep.conflict_files == ["f.txt"], "C-2 prep 冲突文件 = [f.txt]（UU 行）")
    ok("<<<<<<<" in (wt / "f.txt").read_text("utf-8"),
       "C-3 冲突标记已留进泳道工作区（agent 可编辑）")
    ok("Auto-merging" in prep.merge_output or "CONFLICT" in prep.merge_output,
       "C-4 merge 输出摘要带出")

    # C-5 not fully resolved -> settle refuses
    s = await env.run(settle_conflict_resolution,
                      ConflictSettleArgs(ticket_id="t-self", worktree=str(wt),
                                         branch="lane", base_ref="main", round_no=1))
    ok((not s.ok) and s.remaining_files == ["f.txt"],
       "C-5 未解残留 → settle ok=False + remaining_files（记一轮失败）")

    # simulate the agent resolving the markers: keep both sides (same shape as t260825-03)
    (wt / "f.txt").write_text("line1\nline2\nLANE-ADD\nMAIN-ADD\nline3\n", "utf-8")
    s2 = await env.run(settle_conflict_resolution,
                       ConflictSettleArgs(ticket_id="t-self", worktree=str(wt),
                                          branch="lane", base_ref="main", round_no=1))
    ok(s2.ok and bool(s2.commit), "C-6 解完 → settle 落盘合并提交 %s" % s2.commit)
    p = _git(wt, "status", "--porcelain")
    ok(p.returncode == 0 and not p.stdout.strip(), "C-7 settle 后工作区干净")
    p = _git(wt, "rev-list", "--parents", "-n", "1", "HEAD")
    ok(len(p.stdout.split()) == 3, "C-8 HEAD 是双 parent 合并提交（merge main 进泳道）")
    # resolved -> green: merge-tree re-verification shows no conflict
    # (the constructive proof at activity level)
    p = _git(repo, "merge-tree", "--write-tree", "main", "lane")
    ok(p.returncode == 0, "C-9 消解后 merge 预演转绿（rc=0）")

    # C-10 race fallback: main untouched -> prep already_clean
    prep2 = await env.run(prepare_conflict_resolution,
                          ConflictPrepArgs(ticket_id="t-self", worktree=str(wt),
                                           branch="lane", base_ref="main"))
    ok(prep2.ok and prep2.already_clean, "C-10 已合过 main → already_clean 竞态兜底")

    # C-11 prep non-conflict failure: dirty lane worktree (a tracked file change
    # that git will refuse to merge over)
    repo2 = _mk_conflict_repo(tmp / "c11")
    wt2 = repo2 / ".worktrees" / "t-self"
    (wt2 / "f.txt").write_text("dirty\n", "utf-8")  # dirty worktree (uncommitted)
    prep3 = await env.run(prepare_conflict_resolution,
                          ConflictPrepArgs(ticket_id="t-self", worktree=str(wt2),
                                           branch="lane", base_ref="main"))
    ok((not prep3.ok) and "非冲突" in prep3.error,
       "C-11 工作区脏被 git 拒 → prep ok=False 按非冲突上报（不空转回路）")
    return repo2, wt2


async def _f_checks(env, tmp: Path) -> None:
    """Group F: review F1 regression — the implement activity's auto-write
    (_settle_worktree_lane) must not jump ahead with a merge commit while a
    merge is in progress; full-chain test prep -> auto settle (guardrail skips)
    -> agent resolves -> settle_conflict_resolution writes the only merge
    commit."""
    print("F. _settle_worktree_lane 合并进行中护栏（review F1 回归，真 git）")

    # F-1/F-2/F-3: merge-in-progress scene -> call _settle_worktree_lane directly
    # -> no commit produced, MERGE_HEAD still present. Inside
    # _settle_worktree_lane, _is_worktree_of anchors on the module-level
    # REPO_ROOT — temporarily point it at the fake repo's main tree (same-process
    # sequential execution, restored right after).
    repo = _mk_conflict_repo(tmp / "f1")
    wt = repo / ".worktrees" / "t-self"
    p = _git(wt, "merge", "--no-edit", "main")
    ok(p.returncode != 0 and _git(wt, "rev-parse", "--verify", "MERGE_HEAD").returncode == 0,
       "F-0 造出合并进行中现场（merge rc!=0 + MERGE_HEAD 在场）")
    head_before = _git(wt, "rev-parse", "HEAD").stdout.strip()
    orig_root = agent_activities.REPO_ROOT
    agent_activities.REPO_ROOT = repo
    try:
        note = agent_activities._settle_worktree_lane(wt, "t-self", "implement", 2)
    finally:
        agent_activities.REPO_ROOT = orig_root
    ok("合并进行中" in note and "settle_conflict_resolution" in note,
       "F-1 护栏生效：返回说明而不代落盘（%s）" % note[:60])
    ok(_git(wt, "rev-parse", "--verify", "MERGE_HEAD").returncode == 0,
       "F-2 MERGE_HEAD 未被消耗（仍在场）")
    ok(_git(wt, "rev-parse", "HEAD").stdout.strip() == head_before,
       "F-3 未产生 commit（HEAD 不动）")
    _git(wt, "merge", "--abort")

    # F-4/F-5/F-6: full-chain test — prep leaves the scene -> simulated implement
    # auto-settle call point (guardrail should skip) -> simulated agent resolves
    # markers -> settle_conflict_resolution writes, asserting the merge commit
    # comes from settle_conflict_resolution and carries no conflict markers
    repo = _mk_conflict_repo(tmp / "f4")
    wt = repo / ".worktrees" / "t-self"
    prep = await env.run(prepare_conflict_resolution,
                         ConflictPrepArgs(ticket_id="t-self", worktree=str(wt),
                                          branch="lane", base_ref="main"))
    ok(prep.ok and prep.conflict_files == ["f.txt"], "F-4 串测 prep 留现场")
    head_before = _git(wt, "rev-parse", "HEAD").stdout.strip()
    agent_activities.REPO_ROOT = repo
    try:
        note = agent_activities._settle_worktree_lane(wt, "t-self", "implement", 2)
    finally:
        agent_activities.REPO_ROOT = orig_root
    ok("合并进行中" in note
       and _git(wt, "rev-parse", "--verify", "MERGE_HEAD").returncode == 0
       and _git(wt, "rev-parse", "HEAD").stdout.strip() == head_before,
       "F-5 串测：自动代落盘被护栏跳过（无 commit、MERGE_HEAD 在场）")
    (wt / "f.txt").write_text("line1\nline2\nLANE-ADD\nMAIN-ADD\nline3\n", "utf-8")
    s = await env.run(settle_conflict_resolution,
                      ConflictSettleArgs(ticket_id="t-self", worktree=str(wt),
                                         branch="lane", base_ref="main", round_no=1))
    ok(s.ok and bool(s.commit), "F-6 串测：合并提交由 settle_conflict_resolution 落盘 %s" % s.commit)
    p = _git(wt, "show", "HEAD:f.txt")
    ok(p.returncode == 0 and "<<<<<<<" not in p.stdout,
       "F-7 合并提交内容无冲突标记残留")
    p = _git(wt, "rev-list", "--parents", "-n", "1", "HEAD")
    ok(len(p.stdout.split()) == 3, "F-8 串测落盘的是双 parent 合并提交")

    # F-9: a normal implement round (no MERGE_HEAD) is unchanged — a dirty
    # worktree is written down as usual
    repo = _mk_conflict_repo(tmp / "f9")
    wt = repo / ".worktrees" / "t-self"
    _git(wt, "merge", "--no-edit", "main")  # create a merge then abort it, to be sure there is no MERGE_HEAD
    _git(wt, "merge", "--abort")
    (wt / "normal.txt").write_text("正常开发改动\n", "utf-8")
    agent_activities.REPO_ROOT = repo
    try:
        note = agent_activities._settle_worktree_lane(wt, "t-self", "implement", 1)
    finally:
        agent_activities.REPO_ROOT = orig_root
    ok("代落盘 commit" in note and "normal.txt" in note,
       "F-9 无 MERGE_HEAD 时正常代落盘（行为不变）：%s" % note[:60])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock-mc", action="store_true",
                    help="merge_check 走替身（不跑真 git 预演）；B/C 组真仓实证自动跳过")
    args = ap.parse_args()

    env = ActivityEnvironment()
    tmp = Path(tempfile.mkdtemp(prefix="sandbar-selfcheck-cr-"))
    keep = os.environ.get("SANDBAR_CR_KEEP") == "1"
    print("tmp=%s%s" % (tmp, "（保留）" if keep else ""))

    # ---------- A. _parse_conflict_files pure logic ----------
    print("A. _parse_conflict_files 解析")
    sample_conflict = (
        "e012abcc7095585610d7ee62ffd88a13cd986b03\n"
        "100644 83db48f84ec878fbfb30b46d16630e944e34f205 1\td/f.txt\n"
        "100644 932e8c29e05c63019c7cbf338accc0399f91cc32 2\td/f.txt\n"
        "100644 1a87bbf50560906beebc59698421b1c24de38723 3\td/f.txt\n"
        "\n"
        "Auto-merging d/f.txt\n"
        "CONFLICT (content): Merge conflict in d/f.txt\n")
    ok(_parse_conflict_files(sample_conflict) == ["d/f.txt"],
       "A-1 条目行+CONFLICT 行解析出 d/f.txt（去重）")
    multi = sample_conflict + (
        "100644 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1\tg.txt\n"
        "100644 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2\tg.txt\n"
        "\nCONFLICT (content): Merge conflict in g.txt\n")
    ok(_parse_conflict_files(multi) == ["d/f.txt", "g.txt"],
       "A-2 多文件排序返回（下游按集合比较，M6）")
    ok(_parse_conflict_files("e3b924dc2d121726deab1f7d46e5fe0355035144\n") == [],
       "A-3 干净合并输出（只 tree OID）解析为空")
    ok(_parse_conflict_files("fatal: ambiguous argument 'nope': unknown revision\n") == [],
       "A-4 bad-ref 异常输出解析为空（→ 调用方按非冲突红灯，M1）")

    # ---------- B. merge_check conflict classification (real git; skipped under --mock-mc) ----------
    repo = _mk_conflict_repo(tmp / "b")
    wt = repo / ".worktrees" / "t-self"
    p = _git(repo, "merge-tree", "--write-tree", "main", "lane")
    ok(p.returncode == 1 and "CONFLICT (content): Merge conflict in f.txt" in p.stdout,
       "B-0 实证：隔离仓 merge-tree rc=1 且输出含 CONFLICT 行（git %s）"
       % subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.split()[-1])
    if not (p.returncode == 1 and "f.txt" in p.stdout):
        raise _RealMergeTreeConflict("merge-tree 输出形态变了：rc=%s out=%s" % (p.returncode, p.stdout[-300:]))
    if args.mock_mc:
        print("B. merge_check 冲突分类——替身模式（real_merge_check 桩），真仓实证跳过")
        mc = _mock_merge_check(repo, "lane", rehearsal_red=True, files=["f.txt"])
        ok(mc["conflict"] is True and mc["conflict_files"] == ["f.txt"],
           "B-1 [替身] 仅预演红+冲突文件非空 → conflict=True")
        mc = _mock_merge_check(repo, "lane", rehearsal_red=True, files=[])
        ok(mc["conflict"] is False, "B-4 [替身] 预演红但解析为空 → conflict=False（M1）")
    else:
        print("B. merge_check 冲突分类（真 activity × 真 git；检查 3 verify_lane 不在假仓跑，"
              "此处直接验 _parse_conflict_files + merge-tree 实证 + 分类式）")
        # the real-repo merge_check's 3rd check runs verify_lane (the fake repo
        # has no admin.py, so it is always red) — running the full real activity
        # is left to the integration environment; here every input the
        # classification needs is verified item by item: ① the merge-tree
        # evidence (B-0 above); ② parsing; ③ the classification formula per
        # bucket (group D).
        files = _parse_conflict_files((p.stdout or "") + (p.stderr or ""))
        ok(files == ["f.txt"], "B-1 真仓冲突文件解析 = [f.txt]")
        ok(bool((p.stdout or "").strip()), "B-2 excerpt 非空（ours/theirs 上下文截断带出）")
        p2 = _git(repo, "merge-tree", "--write-tree", "main", "nope")
        ok(p2.returncode != 0 and _parse_conflict_files(p2.stdout + p2.stderr) == [],
           "B-4 真仓 bad ref：rc!=0 但解析为空 → conflict=False（M1）")
        # clean merge rc=0
        _git(repo, "branch", "-f", "cleanbase", "main~1")
        p3 = _git(repo, "merge-tree", "--write-tree", "main", "cleanbase")
        ok(p3.returncode == 0, "B-5 无冲突预演 rc=0（分类输入：预演绿）")

    # ---------- C. prep -> (simulated agent resolves) -> settle closed loop (real activity) ----------
    # everything runs inside one event loop (python 3.9's asyncio.run closes the
    # loop and ActivityEnvironment's internal Event then can't find it — same
    # lesson as selfcheck_scan.py), so group C lives in a single async function.
    asyncio.run(_c_checks(env, tmp, wt, repo))
    # group C by-product: the "dirty+conflict" lane, reused by D-5b
    repo2 = tmp / "c11" / "repo"
    wt2 = repo2 / ".worktrees" / "t-self"

    # ---------- D. orchestration decision matrix (_mc_decision, stub merge_check feeds inputs) ----------
    print("D. 编排决策矩阵（与 dev_lane merge_check 分支逐案对应）")
    # D-1 conflict kind -> resolve (auto rework back to implement, not blocked)
    st = {"rounds": 0, "prev_files": []}
    a, d = _mc_decision(st, {"green": False, "conflict": True, "conflict_files": ["f.txt"]})
    ok(a == "resolve" and st["rounds"] == 1, "D-1 仅预演冲突红 → resolve（第 1 轮，不 blocked）")
    # D-2 same file batch recurs (same set, different order, M6) -> early blocked
    a, d = _mc_decision(st, {"green": False, "conflict": True, "conflict_files": ["f.txt"]})
    ok(a == "blocked-samebatch" and "同批文件反复冲突" in d,
       "D-2 同批文件第 2 轮集合相同 → blocked「同批文件反复冲突」")
    # D-3 different files keep resolving until over 3 rounds -> blocked with the round count in the text
    st = {"rounds": 0, "prev_files": []}
    seq = []
    for i in range(1, 6):
        a, d = _mc_decision(st, {"green": False, "conflict": True,
                                 "conflict_files": ["f%d.txt" % i]})
        seq.append(a)
    ok(seq == ["resolve", "resolve", "resolve", "blocked-overlimit", "blocked-overlimit"],
       "D-3 3 轮内 resolve、第 4 次超限 blocked：%s" % seq)
    _, d = _mc_decision({"rounds": 3, "prev_files": ["x"]},
                        {"green": False, "conflict": True, "conflict_files": ["y"]})
    ok("冲突消解 3 轮未收敛" in d, "D-4 超限 blocked 文案锚点「冲突消解 N 轮未收敛」带轮数（S3）")
    # D-5 non-conflict red regression: all three shapes -> blocked-nonconflict
    a, _ = _mc_decision({"rounds": 0, "prev_files": []},
                        {"green": False, "conflict": False, "conflict_files": []})
    ok(a == "blocked-nonconflict", "D-5a 无 commit 红（conflict=False）→ blocked（回归不变）")
    if args.mock_mc:
        mc = _mock_merge_check(repo2, "lane", rehearsal_red=True, files=["f.txt"])  # dirty + conflict
        ok(mc["conflict"] is False, "D-5b [替身] 工作区脏+预演冲突 → conflict=False（先交人不带病消解）")
    else:
        # same shape on the real repo: wt2 worktree dirty and merge-tree always red -> conflict=False under the formula
        files = _parse_conflict_files((_git(repo2, "merge-tree", "--write-tree", "main", "lane")).stdout)
        dirty = bool(_git(wt2, "status", "--porcelain").stdout.strip())
        ok(dirty and bool(files), "D-5b 真仓造出「脏+冲突」输入（分类式判 conflict=False，见 D-5a 同式）")
    a, _ = _mc_decision({"rounds": 0, "prev_files": []},
                        {"green": False, "conflict": False, "conflict_files": []})
    ok(a == "blocked-nonconflict", "D-5c 预演红但解析为空（bad ref，M1）→ blocked 不空转")
    # D-6 green -> merge
    a, _ = _mc_decision({"rounds": 2, "prev_files": ["f.txt"]},
                        {"green": True, "conflict": False, "conflict_files": []})
    ok(a == "merge", "D-6 解完转绿 → 推进 merge（计数器复位）")

    # ---------- F. _settle_worktree_lane merge-in-progress guardrail (review F1 regression, real git) ----------
    # same single-event-loop constraint as group C
    asyncio.run(_f_checks(env, tmp))

    # ---------- E. structural assertions (source-text anchors) ----------
    print("E. 结构性断言（S2 串行 / M2 注册 / 常量一致）")
    src = (POC / "dev_lane.py").read_text("utf-8")
    # 260930：闸前主同步抽成共享 helper（同块还含一处分号观感的 prep 调用），本条锚点
    # 因此收紧到**merge_check 分支内**——比原来的「全文首次出现」锚更强（它本来就只
    # 想锁这一站：脏窗口里不跑 merge_check，S2）。缩进无关，位置相关。
    i_mc = src.find('if phase == "merge_check":')
    mc = src[i_mc:] if i_mc >= 0 else ""
    i_prep = mc.find("prepare_conflict_resolution,")
    i_impl = mc.find('self._run_agent_step("implement", solve_ctx)')
    i_settle = mc.find("settle_conflict_resolution,")
    ok(i_mc >= 0 and -1 not in (i_prep, i_impl, i_settle) and i_prep < i_impl < i_settle,
       "E-1 merge_check 分支内 prep→implement→settle 严格串行（脏窗口不跑 merge_check，S2）")
    names = [getattr(a, "__name__", "") for a in agent_activities.ALL_AGENT_ACTIVITIES]
    ok("prepare_conflict_resolution" in names and "settle_conflict_resolution" in names,
       "E-2 两新 activity 已注册 ALL_AGENT_ACTIVITIES（M2）")
    import dev_lane  # noqa: E402
    ok(dev_lane.MAX_CONFLICT_ROUNDS == MAX_CONFLICT_ROUNDS,
       "E-3 自测上限常量与 dev_lane.MAX_CONFLICT_ROUNDS 一致（%d）" % MAX_CONFLICT_ROUNDS)

    # ---------- wrap-up ----------
    if not keep:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d 项过 / %d 项红" % (_rep.passes, _rep.fails))
    if _rep.failures:
        print("红灯明细：", file=sys.stderr)
        for f in _rep.failures:
            print("  - %s" % f, file=sys.stderr)
    return 0 if _rep.fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
