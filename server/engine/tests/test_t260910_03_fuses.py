"""t260910-03 双保险丝直调用例（零 Temporal server / 零模型 / 零网络，git 夹具 tmp 自足）。

覆盖（方案 v2 步骤 1/2 的 UT 面）：
  - 保险丝A shared.multirepo_fuse_a_error：成员仓条目×空明细=拒收点名；明细在=放行
    （完备性归保险丝B，不在此重复判）；单仓全归根本体=放行；空写集=放行；
    逃逸/非字符串条目=ValueError fail-closed（不吸收）；
  - 保险丝B agent_activities.multirepo_materialization_error：清单缺失单仓回落
    形态+成员仓写集=红灯点名（缺陷形态）；双仓物化在位=放行；树被普通目录占位
    =红灯点名；空写集=不触发（在途旧票兼容）；逃逸条目=转红灯文案不 raise；
  - merge_check 接线：保险丝项恒插 rehearsal 之前（恒落 checks[:-1] 非冲突类），
    仅保险丝红 → green=False 且 conflict=False（不进自动消解回路，KI-047 同族
    位置风险钉死）；
  - merge 接线：保险丝命中 → MergeResult(ok=False, action="failed")，不进逐仓
    squash 循环（_fetch_ticket_project 打桩，零 Temporal）。

畸形输入用例全走 tmp git 夹具/桩谓词，不靠外部源。
"""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import shared  # noqa: E402
import agent_activities as aa  # noqa: E402
from shared import MergeArgs, MergeCheckArgs  # noqa: E402


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path, fname):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    fpath = path / fname
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)


@pytest.fixture
def multirepo(tmp_path):
    """父目录作根（无 .git）+ 两个真 git 子仓（t260907-06 夹具同款形态）。"""
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root / "repo_a", "src/a.py")
    _init_repo(root / "repo_b", "lib/b.py")
    return root


@pytest.fixture
def singlerepo(tmp_path):
    """根即 git 仓、无子仓（单仓项目，零回归面）。"""
    root = tmp_path / "single"
    _init_repo(root, "f.txt")
    return root


def _make_multirepo_lane(root, ticket="t26091003ut"):
    """在多仓项目里建双仓泳道（worktree + 清单），返回 (lane, scopes)。"""
    lane = root / ".lane" / ticket
    for rel, br in (("repo_a", "lane/%s-repo_a" % ticket),
                    ("repo_b", "lane/%s-repo_b" % ticket)):
        _git("worktree", "add", "-b", br, str(lane / rel), cwd=root / rel)
    manifest = [
        {"repo": "repo_a", "name": "repo_a", "branch": "lane/%s-repo_a" % ticket},
        {"repo": "repo_b", "name": "repo_b", "branch": "lane/%s-repo_b" % ticket},
    ]
    import json
    # 清单路径消费引擎单一真源常量（MULTI_MANIFEST_REL，与 _lane_scopes 同源；
    # 命名闸 t260907-04 纪律：新读点禁落旧 dot 目录名裸字面量）
    mf_path = lane / aa.MULTI_MANIFEST_REL
    mf_path.parent.mkdir(parents=True)
    mf_path.write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
    return lane


# ---------- 保险丝A ----------

def test_fuse_a_member_entries_empty_detail_rejected_named(multirepo):
    err = shared.multirepo_fuse_a_error(
        str(multirepo), ["repo_a/src/a.py", "repo_b/lib/b.py"], [])
    assert err, "成员仓条目×空明细必须拒收"
    assert "repo_a" in err and "repo_b" in err and "src/a.py" in err


def test_fuse_a_detail_present_passes_even_if_not_exhaustive(multirepo):
    # 明细非空=放行（完备性归保险丝B）：少一仓也放行，两道保险丝各守一态
    detail = [{"repo": "repo_a", "name": "repo_a", "branch": "lane/x-repo_a"}]
    assert shared.multirepo_fuse_a_error(
        str(multirepo), ["repo_a/src/a.py", "repo_b/lib/b.py"], detail) == ""


def test_fuse_a_single_repo_all_root_passes(singlerepo):
    assert shared.multirepo_fuse_a_error(
        str(singlerepo), ["f.txt", "g.txt"], []) == ""


def test_fuse_a_empty_write_set_passes(multirepo):
    assert shared.multirepo_fuse_a_error(str(multirepo), [], []) == ""
    assert shared.multirepo_fuse_a_error(str(multirepo), None, []) == ""


@pytest.mark.parametrize("bad", [["../escape.py"], [""], [123], ["repo_a/../x"]])
def test_fuse_a_malformed_entries_fail_closed(multirepo, bad):
    with pytest.raises(ValueError):
        shared.multirepo_fuse_a_error(str(multirepo), bad, [])


def test_fuse_a_no_project_root_member_entries_still_rejected(multirepo):
    # project_root 空=无法判根本体归属 → 全部归属仓都算 offender（fail-closed 不放行）
    err = shared.multirepo_fuse_a_error("", ["repo_a/src/a.py"], [])
    assert err and "repo_a" in err


def test_fuse_a_no_repos_at_all_not_applicable(tmp_path):
    # 仓集合为空（无 .git 注册目录存量面）= 无成员仓可言，保险丝不适用（放行）
    assert shared.multirepo_fuse_a_error(str(tmp_path), ["a.txt"], []) == ""


def test_derive_preserves_repo_worktrees_on_explicit_workspace(multirepo):
    # 正规入口第二跳：ticket.py 预派生 ws 显式转发 → derive 重建 dict 时必须保留
    # repo_worktrees（否则明细在创建链第二跳被丢，保险丝A 误拒正规入口）
    detail = [{"repo": "repo_a", "name": "repo_a", "branch": "lane/x-repo_a"}]
    _l, ws, _w, _b = shared.derive_lane_workspace(
        "t26091003ut", "worktree", project_root=str(multirepo),
        workspace={"type": "worktree", "path": str(multirepo / ".lane" / "x"),
                   "repo_worktrees": detail})
    assert ws.get("repo_worktrees") == detail


def test_derive_preserves_only_list_shaped_repo_worktrees(multirepo):
    # 畸形（非列表）repo_worktrees 不保留（交由闸/保险丝按各自口径拒，不在 derive 放行）
    _l, ws, _w, _b = shared.derive_lane_workspace(
        "t26091003ut", "worktree", project_root=str(multirepo),
        workspace={"type": "worktree", "path": str(multirepo / ".lane" / "x"),
                   "repo_worktrees": "junk"})
    assert "repo_worktrees" not in (ws or {})


# ---------- 保险丝B ----------

def test_fuse_b_manifest_missing_single_fallback_red(multirepo):
    lane = multirepo / ".lane" / "t26091003ut"  # 清单缺失（目录不存在也行）
    scopes = aa._lane_scopes(lane, "lane/t26091003ut")
    assert len(scopes) == 1 and scopes[0]["name"] == ""  # 单仓回落形态=缺陷形态
    err = aa.multirepo_materialization_error(
        lane, ["repo_a/src/a.py", "repo_b/lib/b.py"], scopes)
    assert err and "repo_a" in err and "repo_b" in err
    assert "绝不静默收口" in err


def test_fuse_b_both_materialized_passes(multirepo):
    lane = _make_multirepo_lane(multirepo)
    scopes = aa._lane_scopes(lane, "lane/t26091003ut")
    assert len(scopes) == 2
    assert aa.multirepo_materialization_error(
        lane, ["repo_a/src/a.py", "repo_b/lib/b.py"], scopes) == ""


def test_fuse_b_tree_displaced_by_plain_dir_red_named(multirepo):
    lane = _make_multirepo_lane(multirepo)
    # repo_b 树被普通目录占位（非本仓已注册 worktree）→ 红灯点名该仓
    # （先 rmtree 再 prune：否则 git worktree list 残留注册仍判在位——残留注册
    # 是 git 的语义，不是本保险丝的判定对象）
    import shutil
    shutil.rmtree(lane / "repo_b")
    _git("worktree", "prune", cwd=multirepo / "repo_b")
    (lane / "repo_b").mkdir()
    (lane / "repo_b" / "junk.txt").write_text("x", encoding="utf-8")
    scopes = aa._lane_scopes(lane, "lane/t26091003ut")
    err = aa.multirepo_materialization_error(
        lane, ["repo_a/src/a.py", "repo_b/lib/b.py"], scopes)
    assert err and "repo_b" in err and "repo_a" not in err.split("；")[0]


def test_fuse_b_empty_write_set_no_trigger(multirepo):
    lane = multirepo / ".lane" / "t26091003ut"
    scopes = aa._lane_scopes(lane, "lane/t26091003ut")
    assert aa.multirepo_materialization_error(lane, [], scopes) == ""


def test_fuse_b_no_repos_at_all_not_applicable(tmp_path):
    # 仓集合为空=保险丝不适用（存量无 .git 注册目录面，merge 红灯不追溯）
    scopes = aa._lane_scopes(tmp_path / ".lane" / "x", "lane/x")
    assert aa.multirepo_materialization_error(tmp_path / ".lane" / "x",
                                              ["a.txt"], scopes) == ""


def test_fuse_b_escape_entry_red_not_raise(multirepo):
    lane = multirepo / ".lane" / "t26091003ut"
    scopes = aa._lane_scopes(lane, "lane/t26091003ut")
    err = aa.multirepo_materialization_error(lane, ["../escape.py"], scopes)
    assert err and "fail-closed" in err  # 转红灯文案，不 raise


def test_fuse_b_root_only_write_set_passes(singlerepo):
    # 单仓项目：写集全归根本体 → ""（零回归面）。lane_root 按引擎约定取
    # <repo>/.lane/<id> 形态（parent.parent=仓根），目录不存在不影响判定。
    lane = singlerepo / ".lane" / "x"
    scopes = aa._lane_scopes(lane, "lane/x")
    assert aa.multirepo_materialization_error(singlerepo / ".lane" / "x",
                                              ["f.txt"], scopes) == ""


def test_fuse_b_stub_predicate_injected(multirepo):
    # 谓词注入面：桩恒 False → 全部成员仓判未物化（UT 免 git 子进程依赖的约定面）
    lane = _make_multirepo_lane(multirepo)
    scopes = aa._lane_scopes(lane, "lane/t26091003ut")
    err = aa.multirepo_materialization_error(
        lane, ["repo_a/src/a.py"], scopes, is_worktree_of=lambda t, r: False)
    assert err and "repo_a" in err


# ---------- merge_check 接线：位置钉死 + conflict 分类 ----------

async def _stub_scope_core(args, sc, lane_root, multi):
    """全绿桩：标准项绿 + rehearsal 绿且在最后（与真实 _merge_check_one_scope 同形）。"""
    return {"checks": [{"item": "标准项（桩）", "green": True, "detail": ""},
                       {"item": aa.MERGE_REHEARSAL_ITEM + "（桩）", "green": True,
                        "detail": "无冲突"}],
            "rehearsal_green": True, "conflict_files": [], "merge_tree_excerpt": ""}


def test_merge_check_fuse_only_red_is_not_conflict_class(multirepo, monkeypatch):
    lane = multirepo / ".lane" / "t26091003ut"  # 清单缺失=保险丝B 红，标准项（桩）全绿
    monkeypatch.setattr(aa, "_merge_check_one_scope", _stub_scope_core)
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="t26091003ut", worktree=str(lane), branch="lane/t26091003ut",
        write_set=["repo_a/src/a.py", "repo_b/lib/b.py"])))
    assert not res.green
    assert res.conflict is False  # 仅保险丝红 → 非冲突类，blocked 直达不进消解回路
    fuse = [c for c in res.checks if "保险丝B" in c["item"]]
    assert len(fuse) == 1 and not fuse[0]["green"]
    # 位置钉死：rehearsal 恒为 checks[-1]，保险丝项在其之前（恒落 checks[:-1]）
    assert aa.MERGE_REHEARSAL_ITEM in res.checks[-1]["item"]
    assert res.checks.index(fuse[0]) < len(res.checks) - 1


def test_merge_check_all_green_stays_green(multirepo, monkeypatch):
    lane = _make_multirepo_lane(multirepo)
    monkeypatch.setattr(aa, "_merge_check_one_scope", _stub_scope_core)
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="t26091003ut", worktree=str(lane), branch="lane/t26091003ut",
        write_set=["repo_a/src/a.py", "repo_b/lib/b.py"])))
    assert res.green and not res.conflict
    # 全绿也出绿色物化项（可见闸记录，不静默），且在 rehearsal 之前
    fuse = [c for c in res.checks if "保险丝B" in c["item"]]
    assert len(fuse) == 1 and fuse[0]["green"] is True
    assert res.checks.index(fuse[0]) < len(res.checks) - 1


def test_merge_check_empty_write_set_no_fuse_item(multirepo, monkeypatch):
    lane = multirepo / ".lane" / "t26091003ut"
    monkeypatch.setattr(aa, "_merge_check_one_scope", _stub_scope_core)
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="t26091003ut", worktree=str(lane), branch="lane/t26091003ut",
        write_set=[])))
    assert res.green  # 空=在途旧票兼容，保险丝不触发


# ---------- merge 接线：保险丝命中=failed，不进 squash ----------

def test_merge_fuse_hit_returns_failed_without_squash(multirepo, monkeypatch):
    async def _fake_project(ticket_id):
        return "utproj"
    monkeypatch.setattr(aa, "_fetch_ticket_project", _fake_project)
    lane = multirepo / ".lane" / "t26091003ut"  # 清单缺失=保险丝B 红
    res = asyncio.run(aa.merge(MergeArgs(
        ticket_id="t26091003ut", worktree=str(lane), branch="lane/t26091003ut",
        write_set=["repo_a/src/a.py"])))
    assert not res.ok and res.action == "failed"
    assert "保险丝B" in res.error and "repo_a" in res.error


def test_merge_empty_write_set_legacy_semantics(multirepo, monkeypatch):
    # 空 write_set=在途旧票兼容：保险丝不触发（走到逐仓 squash 才会碰真 git，
    # 这里桩掉 _squash_merge 只验「过了保险丝」这一段）
    async def _fake_project(ticket_id):
        return "utproj"
    called = {"n": 0}

    def _fake_squash(repo, tree, branch, ticket_id, defer_teardown, project_key):
        called["n"] += 1

        class R:
            ok = True
            action = "merged"
            merge_commit = "abc1234"
            error = ""
        return R()
    monkeypatch.setattr(aa, "_fetch_ticket_project", _fake_project)
    monkeypatch.setattr(aa, "_squash_merge", _fake_squash)
    lane = _make_multirepo_lane(multirepo)
    res = asyncio.run(aa.merge(MergeArgs(
        ticket_id="t26091003ut", worktree=str(lane), branch="lane/t26091003ut",
        write_set=[])))
    assert res.ok and called["n"] == 2  # 双仓各落一次=旧语义放行
