"""KI-048（t260911-05）合并失败正确分类直调用例（零 Temporal server / 零模型 / 零网络，
git 夹具 tmp 自足，仿 t260910-03 fuses harness）。

覆盖（create_plan gen1 方案步骤 1/3 + review 附条件意见）：
  - _classify_main_dirty 六形态：干净 / 暂存(main_staged) / 重叠未提交(main_dirty·重叠) /
    不重叠未提交(main_dirty·不重叠，保守拦) / 未跟踪相撞(untracked_collision) /
    未跟踪不相撞(干净)；畸形（branch 以 - 开头=diff 失败）不作脏判定降级 clean+note；
  - _dirty_block_note 人话三问（哪个文件/什么原因/怎么处理）+ clean 恒空串 +
    文件封顶 MERGE_FILES_CAP 计数注记；
  - _squash_merge 失败路径分类：staged→dirty/main_staged；重叠→dirty/main_dirty；
    未跟踪相撞→dirty/untracked_collision；真冲突→conflict/conflict；
    非法 branch→failed/merge_fault；干净→merged；
  - 竞态出口（review 附条件①）：读时干净、merge 时变脏→dirty；复判仍干净→
    failed/merge_fault（绝不改判 conflict——reason 非空不变式的兜底出口）；
  - 红线断言（验收 f）：每条失败路径前后 main 工作区 status/HEAD/stash 计数/
    关键文件字节不变（无 auto-stash/auto-commit/checkout），泳道 worktree 不拆不删；
  - merge_check 接线（验收 a）：脏 main → 新脏检查项红+点名文件、rehearsal 恒
    checks[-1]、conflict=False（不冒充冲突、不打回实现段）；干净→该项绿；
  - R3 源码锁：dev_lane merge 段回执重建回填 reason/files；dirty/failed 分流
    blocked、conflict 分支保留 _auto_rework 原形状。

畸形输入用例全走 tmp git 夹具/桩，不靠外部源。
"""
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
from shared import MergeCheckArgs  # noqa: E402


def _git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check:
        assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout


def _init_repo(path, fname="f.txt"):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    # 与真仓同口径：泳道目录 .lane/ 进 gitignore（否则 git add -A 会把 worktree 当
    # gitlink 收进提交，污染脏判定夹具——本测试第一版实证）
    (path / ".gitignore").write_text(".lane/\n", encoding="utf-8")
    fp = path / fname
    fp.write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def _make_lane(root, ticket="t26091105ut"):
    """建泳道 worktree+分支，泳道内改 f.txt 并 commit（领先 main 一个提交）。"""
    br = "lane/%s" % ticket
    lane = root / ".lane" / ticket
    _git("worktree", "add", "-b", br, str(lane), cwd=root)
    (lane / "f.txt").write_text("lane change\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-m", "lane work", cwd=lane)
    return lane, br


def _snapshot(repo):
    """红线断言取面：main 工作区可观测状态 + 关键文件字节。"""
    fp = repo / "f.txt"
    return {
        "status": _git("status", "--porcelain", cwd=repo),
        "head": _git("rev-parse", "HEAD", cwd=repo),
        "stash": _git("stash", "list", cwd=repo),
        "bytes": fp.read_bytes() if fp.exists() else b"",
    }


@pytest.fixture
def repo_lane(tmp_path):
    root = _init_repo(tmp_path / "proj")
    lane, br = _make_lane(root)
    return root, lane, br


# ---------- _classify_main_dirty 六形态 ----------

def test_classify_clean_repo_lane(repo_lane):
    root, lane, br = repo_lane
    v = aa._classify_main_dirty(root, br)
    assert v["kind"] == "" and v["files"] == []


def test_classify_staged(repo_lane):
    root, lane, br = repo_lane
    (root / "f.txt").write_text("host staged\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    v = aa._classify_main_dirty(root, br)
    assert v["kind"] == "main_staged" and "f.txt" in v["files"]


def test_classify_unstaged_overlapping(repo_lane):
    root, lane, br = repo_lane
    (root / "f.txt").write_text("host overlapping\n", encoding="utf-8")  # 泳道也改了 f.txt
    v = aa._classify_main_dirty(root, br)
    assert v["kind"] == "main_dirty" and "f.txt" in v["files"]
    assert "重叠" in v["note"]


def test_classify_unstaged_non_overlapping_conservative_block(repo_lane):
    root, lane, br = repo_lane
    # tracked 的无关文件改动（先落库成 tracked，再改——未跟踪走相撞形态，另一用例）
    (root / "other.txt").write_text("tracked base\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "-m", "add other", cwd=root)
    (root / "other.txt").write_text("unrelated edit\n", encoding="utf-8")
    v = aa._classify_main_dirty(root, br)
    assert v["kind"] == "main_dirty" and "other.txt" in v["files"]
    assert "不重叠" in v["note"]  # KI-048 保守拦（gen1 review 确认）


def test_classify_untracked_collision(repo_lane):
    root, lane, br = repo_lane
    (root / "f.txt.untracked").unlink(missing_ok=True)
    (root / "f.txt").write_text("base\n", encoding="utf-8")  # 保持 tracked 干净
    # 未跟踪文件落在泳道将写入的路径上：新文件 g.txt（泳道加它）
    (lane / "g.txt").write_text("new from lane\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-m", "add g", cwd=lane)
    (root / "g.txt").write_text("host untracked collision\n", encoding="utf-8")
    v = aa._classify_main_dirty(root, br)
    assert v["kind"] == "untracked_collision" and "g.txt" in v["files"]


def test_classify_untracked_non_collision_is_clean(repo_lane):
    root, lane, br = repo_lane
    (root / "scratch.tmp").write_text("host scratch\n", encoding="utf-8")
    v = aa._classify_main_dirty(root, br)
    assert v["kind"] == ""  # 不在收口路径上的未跟踪文件不拦（git 本来也不拒）


def test_classify_malformed_branch_degrades_clean_with_note(repo_lane):
    root, lane, _br = repo_lane
    v = aa._classify_main_dirty(root, "-bad-branch")  # git 解析为选项 → diff 失败
    assert v["kind"] == "" and v["note"]  # 不作脏判定，fail-safe 交 merge 自身把关


# ---------- _dirty_block_note 人话三问 + 非空不变式 ----------

def test_block_note_answers_three_questions(repo_lane):
    root, lane, br = repo_lane
    (root / "f.txt").write_text("host\n", encoding="utf-8")
    v = aa._classify_main_dirty(root, br)
    note = aa._dirty_block_note(v)
    assert "f.txt" in note and "非冲突" in note and "stash" in note


def test_block_note_clean_is_empty_and_reason_never_blank(repo_lane):
    root, lane, br = repo_lane
    assert aa._dirty_block_note(aa._classify_main_dirty(root, br)) == ""
    # reason 非空不变式：任何 kind 出口必非空（空=clean）
    (root / "f.txt").write_text("host\n", encoding="utf-8")
    v = aa._classify_main_dirty(root, br)
    assert v["kind"]  # failure shape always carries a non-empty code


def test_block_note_caps_files_with_count():
    v = {"kind": "main_dirty", "note": "",
         "files": ["f%02d.txt" % i for i in range(aa.MERGE_FILES_CAP + 5)],
         "extra": 5}
    note = aa._dirty_block_note(v)
    assert "另有 5 个未列" in note and "f%02d.txt" % (aa.MERGE_FILES_CAP - 1) in note


# ---------- _squash_merge 失败路径分类 + 红线断言（验收 f） ----------

def _assert_main_untouched(root, before):
    after = _snapshot(root)
    assert after["status"] == before["status"], "main 工作区状态变了（红线）"
    assert after["head"] == before["head"], "main HEAD 变了（红线：无 auto-commit）"
    assert after["stash"] == before["stash"], "stash 栈变了（红线：无 auto-stash）"
    assert after["bytes"] == before["bytes"], "main 关键文件字节变了（红线）"


def test_squash_staged_is_dirty_main_staged(repo_lane):
    root, lane, br = repo_lane
    (root / "f.txt").write_text("host staged\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    before = _snapshot(root)
    res = aa._squash_merge(root, lane, br, "t26091105ut", defer_teardown=True)
    assert not res.ok and res.action == "dirty" and res.reason == "main_staged"
    assert "f.txt" in res.files and res.reason  # 非空不变式
    _assert_main_untouched(root, before)
    assert lane.is_dir()  # 泳道不拆（trade-off b）


def test_squash_overlapping_dirty(repo_lane):
    root, lane, br = repo_lane
    (root / "f.txt").write_text("host overlapping\n", encoding="utf-8")
    before = _snapshot(root)
    res = aa._squash_merge(root, lane, br, "t26091105ut", defer_teardown=True)
    assert not res.ok and res.action == "dirty" and res.reason == "main_dirty"
    assert "f.txt" in res.files
    _assert_main_untouched(root, before)
    assert lane.is_dir()


def test_squash_untracked_collision_named(repo_lane):
    root, lane, br = repo_lane
    (lane / "g.txt").write_text("new from lane\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-m", "add g", cwd=lane)
    (root / "g.txt").write_text("host untracked\n", encoding="utf-8")
    before = _snapshot(root)
    res = aa._squash_merge(root, lane, br, "t26091105ut", defer_teardown=True)
    assert not res.ok and res.action == "dirty" and res.reason == "untracked_collision"
    assert "g.txt" in res.files  # 验收 c：未跟踪相撞形态点名
    _assert_main_untouched(root, before)


def test_squash_real_conflict_stays_conflict(tmp_path):
    """真冲突（两边改同一行）仍归 conflict/conflict——不因分类收紧误伤消解回路。"""
    root = _init_repo(tmp_path / "proj")
    lane, br = _make_lane(root)
    (root / "f.txt").write_text("main side\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "-m", "main side", cwd=root)
    (lane / "f.txt").write_text("lane side\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-m", "lane side", cwd=lane)
    before = _snapshot(root)
    res = aa._squash_merge(root, lane, br, "t26091105ut", defer_teardown=True)
    assert not res.ok and res.action == "conflict" and res.reason == "conflict"
    _assert_main_untouched(root, before)
    assert lane.is_dir()


def test_squash_bad_branch_is_failed_merge_fault(repo_lane):
    root, lane, _br = repo_lane
    res = aa._squash_merge(root, lane, "-bad", "t26091105ut", defer_teardown=True)
    assert not res.ok and res.action == "failed" and res.reason == "merge_fault"


def test_squash_clean_merges(repo_lane):
    root, lane, br = repo_lane
    res = aa._squash_merge(root, lane, br, "t26091105ut", defer_teardown=True)
    assert res.ok and res.action == "merged" and res.merge_commit


def test_squash_race_outlet_never_coerced_to_conflict(repo_lane, monkeypatch):
    """review 附条件①：读时干净、merge 时变脏=竞态。复判脏→dirty；复判仍干净→
    failed/merge_fault，绝不改判 conflict凑出口。桩面：拦截 merge --squash 令其
    「未开始即被拒」（_merge_started 走真判定=False），分类器按调用序桩。"""

    class _FakeProc:
        returncode = 1
        stdout = "error: The following untracked working tree files would be overwritten by merge:\n\tg.txt"
        stderr = ""

    real_git = aa._git

    def _stub_git(args, repo, timeout=None):
        if args[:2] == ["merge", "--squash"]:
            return _FakeProc()  # merge 被拒且未开始
        return real_git(args, repo, timeout=timeout)

    root, lane, br = repo_lane
    calls = {"n": 0}

    def _fake(rp, b):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"kind": "", "files": [], "extra": 0, "note": ""}  # 预读判干净
        return {"kind": "main_dirty", "files": ["f.txt"], "extra": 0,
                "note": "竞态"}  # merge 被拒后复判变脏
    monkeypatch.setattr(aa, "_git", _stub_git)
    monkeypatch.setattr(aa, "_classify_main_dirty", _fake)
    res = aa._squash_merge(root, lane, br, "t26091105ut", defer_teardown=True)
    assert not res.ok and res.action == "dirty" and res.reason == "main_dirty"

    calls["n"] = 0

    def _fake_always_clean(rp, b):
        return {"kind": "", "files": [], "extra": 0, "note": ""}
    monkeypatch.setattr(aa, "_classify_main_dirty", _fake_always_clean)
    res = aa._squash_merge(root, lane, br, "t26091105ut", defer_teardown=True)
    assert not res.ok and res.action == "failed" and res.reason == "merge_fault"
    assert res.action != "conflict"  # 兜底出口绝不冒充冲突


# ---------- merge_check 接线（验收 a） ----------

def _merge_check_args(lane, br):
    return MergeCheckArgs(ticket_id="t26091105ut", worktree=str(lane), branch=br,
                          write_set=["f.txt"])


def _no_verify_spawn(*a, **k):
    """桩掉 verify_lane 子进程（本票只验脏检查项的接线与分类，不重跑 verify 面）。"""
    raise RuntimeError("verify spawn stubbed")


async def _run_scope(repo, lane, br):
    sc = {"tree": lane, "repo": repo, "branch": br, "base_ref": "main",
          "write_set": ["f.txt"], "name": "", "repo_rel": ""}
    return await aa._merge_check_one_scope(_merge_check_args(lane, br), sc, lane, False)


def test_merge_check_dirty_main_red_not_conflict_class(repo_lane, monkeypatch):
    root, lane, br = repo_lane
    (root / "f.txt").write_text("host dirty\n", encoding="utf-8")
    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _no_verify_spawn)
    core = asyncio.run(_run_scope(root, lane, br))
    checks = core["checks"]
    dirty = [c for c in checks if "合并前脏检查" in c["item"]]
    assert len(dirty) == 1 and not dirty[0]["green"]
    assert "f.txt" in dirty[0]["detail"]  # 点名挡事文件（验收 a 前半）
    # 位置钉死：rehearsal 恒 checks[-1]，脏检查项恒落 checks[:-1] 非冲突类
    assert aa.MERGE_REHEARSAL_ITEM in checks[-1]["item"]
    assert checks.index(dirty[0]) < len(checks) - 1


def test_merge_check_clean_main_item_green(repo_lane, monkeypatch):
    root, lane, br = repo_lane
    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _no_verify_spawn)
    core = asyncio.run(_run_scope(root, lane, br))
    dirty = [c for c in core["checks"] if "合并前脏检查" in c["item"]]
    assert len(dirty) == 1 and dirty[0]["green"]
    assert "clean" in dirty[0]["detail"]


# ---------- R3 源码锁（dev_lane 回执重建/分流形状，守卫同款源码断言） ----------

def test_dev_lane_rebuild_backfills_reason_and_files():
    src = (POC / "dev_lane.py").read_text("utf-8")
    assert 'reason=str(raw.get("reason") or "")' in src, \
        "merge 回执 dict 态重建必须回填 reason（R3）"
    assert '[str(x) for x in (raw.get("files") or [])]' in src, \
        "merge 回执 dict 态重建必须回填 files（R3）"
    # 分流形状：dirty/failed → _blocked；conflict 保留 _auto_rework 原形状
    assert 'mr.action in ("dirty", "failed")' in src
    assert '_auto_rework("merge_check", note, who="workflow",\n                                              fallback="merge")' in src
    assert 'self.meta["blocked_detail"]' in src  # 件②结构化原因在位
    # 件② 票面透传面：_blocked 落 meta.blocked_reason；snapshot 顶层透传两字段
    assert 'self.meta["blocked_reason"] = why' in src, "blocked 文案必须落 meta（票面可达）"
    assert '"blocked_reason": str(self.meta.get("blocked_reason") or "")' in src, \
        "snapshot 顶层必须透传 blocked_reason（验收 d）"
    assert '"blocked_detail": self.meta.get("blocked_detail")' in src, \
        "snapshot 顶层必须透传 blocked_detail（验收 d）"


def test_merge_result_new_fields_default_empty():
    from shared import MergeResult
    r = MergeResult()  # 旧回执/缺字段反序列化兼容：缺省空
    assert r.reason == "" and r.files == [] and r.action == ""
