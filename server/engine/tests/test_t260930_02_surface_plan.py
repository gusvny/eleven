"""面计划（t260930-02）：解析判据 + 活动三态 + 接线结构锁。

分工：执行器侧（声明式 surface 映射、未归类即全量、只读查询的黑盒行为）归
`integration/t260930-02/sc_*.py` 与其 L1；本文件锁**引擎侧**——回执解析的 fail-closed
真值表、`surface_plan` 活动在「清单空/查询起不来/超时/输出畸形」四态下**一律回全量**、
以及接线结构（门在、收口全量跑不动、活动已注册）。

为什么这几条必须有：面计划决定「一轮跑多少条」，它的失败方向只能是**更宽**（回全量），
绝不能被读成「没有要跑的」——那正是把验证面悄悄收窄、让红变绿的地方。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa  # noqa: E402
import dev_lane as dl  # noqa: E402
import shared  # noqa: E402

_ENGINE = Path(__file__).resolve().parents[1]


def _plan(payload):
    return json.dumps(payload)


# ---------------- 1. parse_surface_plan 真值表（fail-closed 方向） ----------------

def test_targeted_merges_prev_reds_sorted_deduped():
    names, mode, reason, err = shared.parse_surface_plan(
        _plan({"mode": "targeted", "reason": "ok", "names": ["b", "a", "b"]}),
        ["c", "a", "", None, "  "])
    assert mode == "targeted" and err == "" and reason == "ok"
    assert names == ["a", "b", "c"], names


def test_full_mode_passes_reason_and_empty_names():
    names, mode, reason, err = shared.parse_surface_plan(
        _plan({"mode": "full", "reason": "unclassified-path:app/x.py", "names": []}))
    assert (names, mode, err) == ([], "full", "")
    assert reason == "unclassified-path:app/x.py"


def test_every_malformed_shape_falls_back_to_full():
    cases = [
        "",                     # 无输出
        "   \n  ",              # 空白
        "not json",             # 非 JSON
        _plan({"mode": "half", "names": ["a"]}),          # mode 不在词表
        _plan({"mode": "targeted"}),                      # 缺 names
        _plan({"mode": "targeted", "names": "a"}),        # names 非列表
        _plan({"mode": "targeted", "names": ["a", 3]}),   # names 含非字符串
        _plan({"mode": "targeted", "names": []}),         # targeted 却空面
        _plan({"mode": "targeted", "names": ["  "]}),     # 只有空白名
    ]
    for raw in cases:
        names, mode, reason, err = shared.parse_surface_plan(raw, ["red"])
        assert names == [] and mode == "full", (raw, names, mode)
        assert reason and reason != "ok", (raw, reason)


def test_noise_before_the_json_line_is_tolerated():
    raw = "INTEG_RUN_LOCK 噪声行\n其他噪声\n" + _plan(
        {"mode": "targeted", "reason": "ok", "names": ["z"]})
    names, mode, _, _ = shared.parse_surface_plan(raw)
    assert (names, mode) == (["z"], "targeted")


def test_prev_reds_not_merged_on_full():
    names, mode, _, _ = shared.parse_surface_plan(
        _plan({"mode": "full", "reason": "no-changed-files", "names": []}), ["red"])
    assert (names, mode) == ([], "full")


# ---------------- 2. surface_plan 活动：四态一律回全量 ----------------

def _stub_tree(tmp_path: Path, runner_body: str, *, supports_query: bool = True) -> Path:
    """在临时树里放一个桩执行器（活动按 worktree/integration/run_scenarios.py 定位）。

    `supports_query=True` 时桩里含查询 flag 字样——**能力探测**（混合版本缝守卫）按它判
    「泳道副本认不认这次查询」；置 False 用来造旧副本形态。
    """
    root = tmp_path / "lane"
    (root / "integration").mkdir(parents=True, exist_ok=True)
    head = "# --print-surface-plan\n" if supports_query else "# 旧副本：无查询面\n"
    (root / "integration" / "run_scenarios.py").write_text(
        head + runner_body, encoding="utf-8")
    return root


def _stub_runner(payload: dict, exit_code: int = 0) -> str:
    return ("import json,sys\n"
            "print(json.dumps(%r))\n"
            "sys.exit(%d)\n" % (payload, exit_code))


def test_activity_empty_changed_files_is_full_without_spawning():
    res = asyncio.run(aa.surface_plan(shared.SurfacePlanArgs(
        ticket_id="t1", changed_files=[], prev_red_names=["red"])))
    assert res.mode == "full" and res.names == []
    assert res.reason == "no-changed-files" and res.error


def test_activity_targeted_round_trip(tmp_path):
    root = _stub_tree(tmp_path, _stub_runner(
        {"mode": "targeted", "reason": "ok", "names": ["sc-a"],
         "surfaces": ["workbench-ui"]}))
    res = asyncio.run(aa.surface_plan(shared.SurfacePlanArgs(
        ticket_id="t1", worktree=str(root), changed_files=["server/plugins/workbench/x.ts"],
        prev_red_names=["sc-red"])))
    assert res.mode == "targeted" and res.error == ""
    assert res.names == ["sc-a", "sc-red"], res.names
    assert res.surfaces == ["workbench-ui"]


def test_activity_missing_runner_is_full(tmp_path):
    root = tmp_path / "empty-lane"
    root.mkdir()
    res = asyncio.run(aa.surface_plan(shared.SurfacePlanArgs(
        ticket_id="t1", worktree=str(root), changed_files=["server/plugins/workbench/x.ts"])))
    assert res.mode == "full" and res.names == [] and res.error


def test_activity_garbage_output_is_full(tmp_path):
    root = _stub_tree(tmp_path, "print('not json at all')\n")
    res = asyncio.run(aa.surface_plan(shared.SurfacePlanArgs(
        ticket_id="t1", worktree=str(root), changed_files=["a/b.py"])))
    assert res.mode == "full" and res.names == [] and "malformed" in res.reason


def test_activity_full_payload_is_full(tmp_path):
    root = _stub_tree(tmp_path, _stub_runner(
        {"mode": "full", "reason": "unclassified-path:x/y.z", "names": []}))
    res = asyncio.run(aa.surface_plan(shared.SurfacePlanArgs(
        ticket_id="t1", worktree=str(root), changed_files=["x/y.z"])))
    assert res.mode == "full" and res.names == []
    assert res.reason == "unclassified-path:x/y.z"
    assert res.error == ""


def test_activity_old_runner_copy_is_full_without_spawning(tmp_path):
    """混合版本缝：泳道执行器副本不认识查询 flag 时必须零 spawn 回全量。

    不守这条的后果是实打实的：未知 flag 被执行器宽容忽略 → 查询变**一趟真全量跑**，
    既烧 8 分钟又把闸面搅浑（而回执还会说「查询失败」）。
    """
    root = _stub_tree(tmp_path, "print('old runner, no surface query')\n",
                      supports_query=False)
    res = asyncio.run(aa.surface_plan(shared.SurfacePlanArgs(
        ticket_id="t1", worktree=str(root), changed_files=["server/plugins/workbench/x.ts"])))
    assert res.mode == "full" and res.names == []
    assert res.reason == "runner-without-surface-query"
    assert "混合版本缝" in res.error


def test_activity_strips_narrowing_env_knobs(tmp_path):
    """查询面必须只读：执行器侧的点名/排除池/豁免旋钮不得漏进子进程（漏进去=查询顺带缩表）。"""
    body = ("import json,os,sys\n"
            "leaked=[k for k in ('SANDBAR_SCENARIO_ONLY','SANDBAR_SCENARIO_EXCLUDE_POOLS',"
            "'SANDBAR_KNOWN_RED_EXCLUDE') if k in os.environ]\n"
            "print(json.dumps({'mode':'full','reason':'leaked:'+','.join(leaked),'names':[]}))\n")
    root = _stub_tree(tmp_path, body)
    import os
    os.environ["SANDBAR_SCENARIO_ONLY"] = "x"
    os.environ["SANDBAR_SCENARIO_EXCLUDE_POOLS"] = "engine"
    os.environ["SANDBAR_KNOWN_RED_EXCLUDE"] = "1"
    try:
        res = asyncio.run(aa.surface_plan(shared.SurfacePlanArgs(
            ticket_id="t1", worktree=str(root), changed_files=["a/b.py"])))
    finally:
        for k in ("SANDBAR_SCENARIO_ONLY", "SANDBAR_SCENARIO_EXCLUDE_POOLS",
                  "SANDBAR_KNOWN_RED_EXCLUDE"):
            os.environ.pop(k, None)
    assert res.reason == "leaked:", res.reason


# ---------------- 3. 接线结构锁 ----------------

def test_devl_lane_wiring_locked():
    dev = (_ENGINE / "dev_lane.py").read_text(encoding="utf-8")
    act = (_ENGINE / "agent_activities.py").read_text(encoding="utf-8")
    # 门在、门后消费、meta 留痕
    assert 'SURFACE_PLAN_PATCH_ID = "dev-lane-surface-plan-v1"' in dev
    assert "workflow.patched(SURFACE_PLAN_PATCH_ID)" in dev
    assert "surface_plan_trace" in dev
    # 面计划只改**快反馈面**：收口全量跑（放行依据）一字不动
    assert dev.count("await self._closing_full_run()") == 2
    assert dev.count("收口全量跑有新增红") == 2
    assert "放行仍只认收口全量跑" in dev
    # 失败方向=更宽：非 targeted/空名单 → 不设 run_only（=全量跑）
    assert 'if _sp_mode == "targeted" and _sp_names:' in dev
    # 活动定义 + worker 注册（漏注册=运行时才炸）
    assert "async def surface_plan(" in act
    assert "surface_plan," in act
    # 查询面只读：剥掉会缩表的旋钮
    for knob in ("SANDBAR_SCENARIO_ONLY", "SANDBAR_SCENARIO_EXCLUDE_POOLS",
                 "SANDBAR_KNOWN_RED_EXCLUDE"):
        assert knob in act


def test_marker_id_distinct_from_existing_gates():
    assert dl.SURFACE_PLAN_PATCH_ID == "dev-lane-surface-plan-v1"
    assert dl.SURFACE_PLAN_PATCH_ID not in (
        dl.TARGETED_RERUN_PATCH_ID, dl.TARGETED_RERUN_FILE_RADIUS_PATCH_ID)


# ------- t261102-45 (KI-458): the change set is measured against BOTH sides -------
#
# Measured defect: a develop-buffer lane sits on its line AND has synced main, so a
# change set measured against main alone charges the LINE's landed work to the ticket
# (t261102-09: 21 integration paths the line owns, files main does not even have). The
# surface planner then answers mode=full: 784 entries, ~885 s against a 900 s command
# budget, and a measured 776-entry run took 1159 s wall - a full round structurally
# cannot finish. The caliber below is the one the write-set item already uses (261012
# host ruling): a ticket's OWN write is a file that differs from BOTH baselines.

def _two_sided_worktree(tmp_path) -> str:
    """A placeable worktree path: a temp dir carrying a `.git` marker is a repo root."""
    wt = tmp_path / "lane"
    wt.mkdir(parents=True, exist_ok=True)
    (wt / ".git").mkdir(exist_ok=True)
    return str(wt)


class _P:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _one_scope(wt: str):
    """The single-scope shape `_lane_scopes` returns for a plain single-repo lane."""
    return [{"repo": Path(wt), "tree": Path(wt), "branch": "lane-1", "repo_rel": ""}]


def _stub_scope_env(monkeypatch, wt, diff_by_ref, status_out=""):
    """Drive the REAL per-scope collector with a single scope and a fake git.

    The collector resolves the lane branch first (t261031-17's twin logic), so the
    fake answers `rev-parse` with the branch name; `_merge_base_ref` is stubbed by the
    caller. Diff output is keyed by the ref triple's second element prefix.
    """
    def fake_git(args, cwd, timeout=60):
        if args[0] == "rev-parse":
            return _P("lane-1\n")
        if args[0] == "diff":
            ref = args[2]
            for key, out in diff_by_ref.items():
                if ref.startswith(key):
                    return _P(out)
            raise AssertionError(args)
        if args[0] == "status":
            return _P(status_out)
        raise AssertionError(args)

    monkeypatch.setattr(aa, "_git", fake_git)
    monkeypatch.setattr(aa, "_lane_scopes", lambda *a, **k: _one_scope(wt))


def test_changed_files_two_sided_intersection_keeps_only_own_files(tmp_path, monkeypatch):
    wt = _two_sided_worktree(tmp_path)
    _stub_scope_env(monkeypatch, wt, {
        "MAIN...": "integration/own/x.py\nintegration/t261030-35/line_only.mjs\n",
        "LINE...": "integration/own/x.py\nserver/app.py\n",
    })
    monkeypatch.setattr(aa, "_merge_base_ref",
                        lambda branch, repo, other="main": (
                            ("MAIN" if other == "main" else "LINE"), ""))
    r = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t", worktree=wt, branch="lane-1", base_other_ref="develop-buffer")))
    assert r.error == "", r.error
    # the intersection: the line-only file and the main-only file are NOT this ticket's
    assert r.files == ["integration/own/x.py"], r.files
    assert r.basis == "develop-buffer", r.basis


def test_changed_files_default_stays_main_only_and_is_named(tmp_path, monkeypatch):
    wt = _two_sided_worktree(tmp_path)
    _stub_scope_env(monkeypatch, wt, {"BASE...": "a.py\nb.py\n"}, status_out="?? c.py\0")
    monkeypatch.setattr(aa, "_merge_base_ref", lambda branch, repo, other="main": ("BASE", ""))
    r = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t", worktree=wt, branch="lane-1")))
    assert r.error == "", r.error
    # byte-identical caliber: the main diff plus the dirty files, and the receipt says so
    assert r.files == ["a.py", "b.py", "c.py"], r.files
    assert r.basis == "main", r.basis


def test_changed_files_unreadable_line_side_fails_closed_by_name(tmp_path, monkeypatch):
    """An unreadable line side must WIDEN, never narrow: files=[] plus an error naming
    the side (the caller's non-empty error arm runs everything)."""
    wt = _two_sided_worktree(tmp_path)
    _stub_scope_env(monkeypatch, wt, {"MAIN...": "a.py\n"})
    monkeypatch.setattr(aa, "_merge_base_ref",
                        lambda branch, repo, other="main": (
                            ("MAIN", "") if other == "main" else ("", "unknown revision")))
    r = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t", worktree=wt, branch="lane-1", base_other_ref="develop-buffer")))
    assert r.files == [] and "develop-buffer" in r.error and "merge-base" in r.error, r.error


def test_dev_lane_passes_the_line_side_for_buffer_tickets():
    """Source lock: the blast-radius call site must hand the line side down, or the
    whole line keeps being charged to the ticket (the measured defect itself)."""
    src = (_ENGINE / "dev_lane.py").read_text(encoding="utf-8")
    i = src.index("ChangedFilesArgs(")
    block = src[i:i + 1200]
    assert "base_other_ref=self._dev_buffer_write_set_other_side()" in block, block[:600]


# ------- t261103-03: the two-sided base inside the per-scope collector -------
#
# The reconciliation makes ONE collector: the line's per-scope walk
# (t261031-17) with the two-sided base (t261102-45) applied inside EACH scope.
# These cases judge that seam. Each one drives the real `aa.changed_files`; the
# scope list, `_git` and `_merge_base_ref` are the only stubs.


def _multiscope_worktree(tmp_path):
    """`<tmp>/proj/.lane/t1` plus one member tree - the convention shape, so
    `_lane_repo_root` answers the project root."""
    lane = tmp_path / "proj" / ".lane" / "t1"
    (lane / "fpv-parts").mkdir(parents=True)
    (tmp_path / "proj" / ".git").mkdir()
    (tmp_path / "proj" / "fpv-parts").mkdir()
    return lane


def _two_scopes(lane: Path, project: Path):
    return [
        {"name": "root", "tree": lane, "repo": project, "branch": "lane-1-root",
         "repo_rel": "", "base_ref": "", "write_set": []},
        {"name": "fpv-parts", "tree": lane / "fpv-parts",
         "repo": project / "fpv-parts", "branch": "lane-1-fpv-parts",
         "repo_rel": "fpv-parts", "base_ref": "", "write_set": []},
    ]


def _scoped_git(diff_by_key, fail=()):
    def fake_git(args, cwd, timeout=60):
        if args[0] == "rev-parse":
            return _P(args[-1].replace("^{commit}", "") + "\n")
        if args[0] == "diff":
            key = (str(cwd), args[2])
            if key in fail:
                return _P(returncode=2, stderr="fatal: bad revision")
            if key not in diff_by_key:
                raise AssertionError("unexpected diff call: %s" % (key,))
            return _P(diff_by_key[key])
        if args[0] == "status":
            return _P("")
        raise AssertionError(args)
    return fake_git


def test_changed_files_intersects_each_scope_against_the_other_side(tmp_path,
                                                                   monkeypatch):
    """A buffer lane's own write per scope = the intersection of the two diffs.
    The member scope keeps its `repo_rel/` prefix, and the line's files never
    reach the receipt."""
    lane = _multiscope_worktree(tmp_path)
    project = tmp_path / "proj"
    scopes = _two_scopes(lane, project)
    member = project / "fpv-parts"
    monkeypatch.setattr(aa, "_git", _scoped_git({
        (str(project), "MAIN...lane-1-root"):
            "integration/own/x.py\nintegration/t261030-35/line_only.mjs\nserver/app.py\n",
        (str(project), "LINE...lane-1-root"): "integration/own/x.py\nserver/app.py\n",
        (str(member), "MAIN...lane-1-fpv-parts"):
            "integration/own/y.py\ntools/line_only.py\n",
        (str(member), "LINE...lane-1-fpv-parts"): "integration/own/y.py\n",
    }))
    monkeypatch.setattr(aa, "_lane_scopes", lambda *a, **k: scopes)
    monkeypatch.setattr(aa, "_merge_base_ref",
                        lambda branch, repo, other="main": (
                            ("MAIN" if other == "main" else "LINE"), ""))
    r = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t", worktree=str(lane), branch="lane/t1",
        base_other_ref="develop-buffer")))
    assert r.error == "", r.error
    assert r.files == ["integration/own/x.py", "server/app.py",
                       "fpv-parts/integration/own/y.py"], r.files
    assert r.basis == "develop-buffer", r.basis
    assert r.resolved == ["root:lane-1-root", "fpv-parts:lane-1-fpv-parts"], r.resolved


def test_changed_files_other_side_diff_error_names_the_side_and_the_repo(tmp_path,
                                                                       monkeypatch):
    """The t261031-17 caliber stays (`failed in repo <path>`) and the second
    baseline says which side it was, because one scope reads two diffs."""
    lane = _multiscope_worktree(tmp_path)
    project = tmp_path / "proj"
    monkeypatch.setattr(aa, "_git", _scoped_git(
        {(str(project), "MAIN...lane-1-root"): "a.py\n"},
        fail=((str(project), "LINE...lane-1-root"),)))
    monkeypatch.setattr(aa, "_lane_scopes",
                        lambda *a, **k: _two_scopes(lane, project)[:1])
    monkeypatch.setattr(aa, "_merge_base_ref",
                        lambda branch, repo, other="main": (
                            ("MAIN", "") if other == "main" else ("LINE", "")))
    r = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t", worktree=str(lane), branch="lane/t1",
        base_other_ref="develop-buffer")))
    assert r.files == [], r.files
    assert "failed in repo" in r.error, r.error
    assert "develop-buffer" in r.error, r.error


def test_changed_files_unreadable_other_side_names_the_member_scope(tmp_path,
                                                                  monkeypatch):
    """An unreadable line side in ONE scope fails the whole call closed."""
    lane = _multiscope_worktree(tmp_path)
    project = tmp_path / "proj"
    member = project / "fpv-parts"
    monkeypatch.setattr(aa, "_git", _scoped_git({
        (str(project), "MAIN...lane-1-root"): "a.py\n",
        (str(project), "LINE...lane-1-root"): "a.py\n",
        (str(member), "MAIN...lane-1-fpv-parts"): "b.py\n",
    }))
    monkeypatch.setattr(aa, "_lane_scopes", lambda *a, **k: _two_scopes(lane, project))

    def fake_base(branch, repo, other="main"):
        if other != "main" and str(repo).endswith("fpv-parts"):
            return "", "unknown revision develop-buffer"
        return ("MAIN" if other == "main" else "LINE"), ""

    monkeypatch.setattr(aa, "_merge_base_ref", fake_base)
    r = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t", worktree=str(lane), branch="lane/t1",
        base_other_ref="develop-buffer")))
    assert r.files == [], r.files
    assert "[fpv-parts]" in r.error, r.error
    assert "merge-base" in r.error and "develop-buffer" in r.error, r.error


def test_changed_files_other_side_main_is_the_main_only_caliber(tmp_path, monkeypatch):
    """`base_other_ref="main"` reads ONE diff: the historical caliber, byte for
    byte. The fake git has no second-diff answer, so a second read would raise."""
    lane = _multiscope_worktree(tmp_path)
    project = tmp_path / "proj"
    monkeypatch.setattr(aa, "_git", _scoped_git(
        {(str(project), "MAIN...lane-1-root"): "a.py\nb.py\n"}))
    monkeypatch.setattr(aa, "_lane_scopes",
                        lambda *a, **k: _two_scopes(lane, project)[:1])
    monkeypatch.setattr(aa, "_merge_base_ref",
                        lambda branch, repo, other="main": ("MAIN", ""))
    r = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t", worktree=str(lane), branch="lane/t1",
        base_other_ref="main")))
    assert r.error == "", r.error
    assert r.files == ["a.py", "b.py"], r.files
    assert r.basis == "main", r.basis
