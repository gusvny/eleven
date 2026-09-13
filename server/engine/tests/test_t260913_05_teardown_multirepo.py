"""t260913-05 拆道逐仓化直调用例（零 Temporal server / 零模型 / 零网络，tmp 真 git 夹具自足）。

被测：
  - `agent_activities.teardown_lane`：逐仓三清（各自仓的 worktree remove + branch -D）、
    逐仓点名 warn 不阻断收口、三态明细取用（盘上清单 / workflow 递来的 meta 明细救源 /
    旧单仓回落）、两态不对称（明细损坏与非法 branch = fail-closed 不动手）；
  - `agent_activities._lane_scopes` 的 `entries` 入参与读盘清单**同一归一化段**（验收 D
    同源判定：拆道与 merge 落账共用，不另造第二套解析）；
  - `shared.MergeArgs.repo_worktrees` payload 兼容字段（缺键回落空列表 + 字段追加在末尾）；
  - dev_lane 接线源码锁定：teardown 调用点带 repo_worktrees；回执 ok=False → _blocked
    分支在「只记 warn」分支之前（防后人把 fail-closed 误读成静默）。

畸形输入用例全走 tmp git 夹具/桩 `_git`，不靠外部源（工单惯例：消费外部输入的实现
必带畸形输入用例）。
"""
import asyncio
import dataclasses
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
from shared import MergeArgs  # noqa: E402


# ---------- 夹具 ----------

def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path: Path, fname: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    fp = path / fname
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)


@pytest.fixture
def mixed(tmp_path):
    """混合形态（dengzhufpv / t260911-04 同款）：根亦 git 仓 + repo_a 子仓。"""
    root = tmp_path / "proj"
    _init_repo(root, "docs/root.md")
    (root / ".gitignore").write_text("repo_a/\n.suyou/\n.sandbar/\n", encoding="utf-8")  # naming-compat：.suyou/=旧名清单镜像目录，fixture 照造（t260911-04 同款）
    _git("add", "-A", cwd=root)
    _git("commit", "-m", "ignore", cwd=root)
    _init_repo(root / "repo_a", "src/a.py")
    return root


def _make_mixed_lane(root: Path, ticket: str, root_first=True):
    """建混合形态泳道（root 树=泳道容器 + repo_a 成员树）+ 清单镜像。

    返回 (lane, manifest 明细)。清单序默认 root 在前（真实 build_repo_worktrees
    对 [docs/root.md, repo_a/...] 写集的产物序），root_first=False 供序不敏感用例。"""
    lane = root / ".lane" / ticket
    br_root = "lane/%s-root" % ticket
    br_a = "lane/%s-repo_a" % ticket
    _git("worktree", "add", "-b", br_root, str(lane), cwd=root)
    _git("worktree", "add", "-b", br_a, str(lane / "repo_a"), cwd=root / "repo_a")
    entries = [{"repo": "", "name": "root", "branch": br_root},
               {"repo": "repo_a", "name": "repo_a", "branch": br_a}]
    if not root_first:
        entries = list(reversed(entries))
    mf = lane / aa.MULTI_MANIFEST_REL
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return lane, entries


@pytest.fixture
def members_only(tmp_path):
    """成员仓形态（父目录非 git 仓）：repo_a / repo_b 两成员仓。"""
    proj = tmp_path / "members"
    proj.mkdir()
    _init_repo(proj / "repo_a", "src/a.py")
    _init_repo(proj / "repo_b", "lib/b.py")
    return proj


def _make_members_lane(proj: Path, ticket: str):
    lane = proj / ".lane" / ticket
    entries = []
    for rel in ("repo_a", "repo_b"):
        br = "lane/%s-%s" % (ticket, rel)
        _git("worktree", "add", "-b", br, str(lane / rel), cwd=proj / rel)
        entries.append({"repo": rel, "name": rel, "branch": br})
    mf = lane / aa.MULTI_MANIFEST_REL
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return lane, entries


def _worktrees(repo: Path):
    out = _git("worktree", "list", "--porcelain", cwd=repo)
    return [ln[len("worktree "):] for ln in out.splitlines() if ln.startswith("worktree ")]


def _lane_branches(repo: Path):
    out = _git("branch", "--list", "lane/*", cwd=repo)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _run(args: MergeArgs):
    return asyncio.run(aa.teardown_lane(args))


def _failed(stderr: str):
    return subprocess.CompletedProcess(["git"], 1, "", stderr)


# ---------- 多仓逐仓三清（正路） ----------

def test_teardown_mixed_shape_cleans_all_repos_and_container(mixed):
    """混合形态（清单 root 在前）：根仓与成员仓各自三清，容器目录一并消失。"""
    lane, entries = _make_mixed_lane(mixed, "utt05a")
    res = _run(MergeArgs(ticket_id="utt05a", worktree=str(lane),
                         branch="lane/utt05a-root", repo_worktrees=entries))
    assert res.ok and res.action == "teardown"
    assert res.error == "", res.error
    assert all(str(lane) not in p for p in _worktrees(mixed)), _worktrees(mixed)
    assert all(str(lane) not in p for p in _worktrees(mixed / "repo_a")), _worktrees(mixed / "repo_a")
    assert _lane_branches(mixed) == []
    assert _lane_branches(mixed / "repo_a") == []
    assert not lane.exists(), "泳道容器目录应随根树 remove 消失"


def test_teardown_member_first_manifest_order_also_clean(mixed):
    """清单序不敏感：成员条目在前同样全净（实现按 repo_rel 重排，root 恒最后）。"""
    lane, entries = _make_mixed_lane(mixed, "utt05b", root_first=False)
    res = _run(MergeArgs(ticket_id="utt05b", worktree=str(lane),
                         branch="lane/utt05b-root", repo_worktrees=entries))
    assert res.ok and res.error == ""
    assert all(str(lane) not in p for p in _worktrees(mixed))
    assert all(str(lane) not in p for p in _worktrees(mixed / "repo_a"))
    assert _lane_branches(mixed) == [] and _lane_branches(mixed / "repo_a") == []
    assert not lane.exists()


def test_teardown_manifest_gone_entries_rescue_names_members(mixed):
    """部分拆除重试态（容器/清单已灭、成员注册悬空）：workflow 递来的 meta 明细仍逐仓清。"""
    lane, entries = _make_mixed_lane(mixed, "utt05c")
    _git("worktree", "remove", "--force", str(lane), cwd=mixed)   # 模拟上一次跑掉一半
    assert not lane.exists()
    res = _run(MergeArgs(ticket_id="utt05c", worktree=str(lane),
                         branch="lane/utt05c-root", repo_worktrees=entries))
    assert res.ok and res.action == "teardown"
    assert all("utt05c" not in p for p in _worktrees(mixed / "repo_a")), _worktrees(mixed / "repo_a")
    assert _lane_branches(mixed / "repo_a") == []
    assert _lane_branches(mixed) == []


def test_teardown_member_repo_dir_missing_named_warn_not_blocking(members_only):
    """成员仓目录已不在盘上：逐仓点名 warn、ok=True 不阻断，其余仓照清（review 硬条件 3）。"""
    lane, entries = _make_members_lane(members_only, "utt05d")
    shutil.rmtree(members_only / "repo_b")          # 仓目录整个消失（裸 _git 会 FileNotFoundError）
    res = _run(MergeArgs(ticket_id="utt05d", worktree=str(lane),
                         branch="lane/utt05d-repo_a", repo_worktrees=entries))
    assert res.ok and res.action == "teardown"
    assert "[repo_b] 仓目录不存在" in res.error, res.error
    assert all("utt05d" not in p for p in _worktrees(members_only / "repo_a")), _worktrees(members_only / "repo_a")
    assert _lane_branches(members_only / "repo_a") == []


# ---------- 单仓零回归 ----------

def test_teardown_single_repo_fallback_command_stream_unchanged(tmp_path, monkeypatch):
    """旧单仓回落：git 命令流与旧代码同形（守卫锚 REPO_ROOT、清理锚泳道所属仓），
    warn 文案无 tag 前缀；引擎仓泳道下 _lane_repo_root(wt)==REPO_ROOT 逐字节等价。"""
    engine = tmp_path / "engine"
    _init_repo(engine, "f.txt")
    lane = engine / ".lane" / "utt05e"
    br = "lane/utt05e"
    _git("worktree", "add", "-b", br, str(lane), cwd=engine)
    calls = []
    real = aa._git

    def spy(args, cwd, timeout=60):
        calls.append((list(args), str(cwd)))
        return real(args, cwd, timeout=timeout)

    monkeypatch.setattr(aa, "_git", spy)
    res = _run(MergeArgs(ticket_id="utt05e", worktree=str(lane), branch=br))
    assert res.ok and res.action == "teardown" and res.error == ""
    assert calls == [(["check-ref-format", "--branch", br], str(aa.REPO_ROOT)),
                     (["worktree", "remove", "--force", str(lane)], str(engine)),
                     (["branch", "-D", br], str(engine))], calls
    assert not lane.exists() and _lane_branches(engine) == []
    # 引擎仓泳道（<engine>/.lane/<id>）→ 旧硬编码 REPO_ROOT 与新判定同仓 = 零回归
    assert aa._lane_repo_root(Path(aa.REPO_ROOT) / ".lane" / "x") == Path(aa.REPO_ROOT)


# ---------- 明细畸形 / 损坏 / 非法 branch = fail-closed 不动手 ----------

def test_teardown_malformed_entries_fail_closed_nothing_touched(mixed):
    """条目畸形（缺 branch）：走 entries 源（清单已灭的救源态）→ 整体 failed 且一个仓都不碰。"""
    lane, _ = _make_mixed_lane(mixed, "utt05f")
    (lane / aa.MULTI_MANIFEST_REL).unlink()           # 清单不在=entries 才是当次判定源
    bad = [{"repo": "repo_a", "name": "repo_a"}]      # 缺 branch
    res = _run(MergeArgs(ticket_id="utt05f", worktree=str(lane),
                         branch="lane/utt05f-root", repo_worktrees=bad))
    assert not res.ok and res.action == "failed"
    assert "branch 字段缺失" in res.error and "meta.repo_worktrees" in res.error, res.error
    assert lane.exists()
    assert any(str(lane) in p for p in _worktrees(mixed / "repo_a")), _worktrees(mixed / "repo_a")
    assert _lane_branches(mixed / "repo_a") == ["+ lane/utt05f-repo_a"]


def test_teardown_manifest_is_the_authority_over_meta_entries(mixed):
    """清单镜像在=判定源（与 merge 同输入）；此时 meta 明细不参与判定（救源不是并列真源）。"""
    lane, entries = _make_mixed_lane(mixed, "utt05l")
    res = _run(MergeArgs(ticket_id="utt05l", worktree=str(lane),
                         branch="lane/utt05l-root",
                         repo_worktrees=[{"repo": "repo_a", "name": "repo_a"}]))  # 畸形但被忽略
    assert res.ok and res.error == "", res.error
    assert entries  # 清单自身合法
    assert not lane.exists() and _lane_branches(mixed / "repo_a") == []


def test_teardown_corrupt_manifest_fail_closed_nothing_touched(mixed):
    lane, _ = _make_mixed_lane(mixed, "utt05g")
    (lane / aa.MULTI_MANIFEST_REL).write_text("{ not json", encoding="utf-8")
    res = _run(MergeArgs(ticket_id="utt05g", worktree=str(lane), branch="lane/utt05g-root"))
    assert not res.ok and res.action == "failed"
    assert "清单损坏" in res.error, res.error
    assert lane.exists()
    assert any(str(lane) in p for p in _worktrees(mixed)), _worktrees(mixed)
    assert any(str(lane) in p for p in _worktrees(mixed / "repo_a"))


def test_teardown_invalid_member_branch_rejected_before_any_removal(mixed):
    """盘上清单里成员 branch 非法（前导 "-"）：逐仓守卫在动手前拒，一个仓都不碰。"""
    lane, entries = _make_mixed_lane(mixed, "utt05h")
    entries[1]["branch"] = "-evil"                    # 前导 "-"：check-ref-format 拒
    (lane / aa.MULTI_MANIFEST_REL).write_text(json.dumps(entries), encoding="utf-8")
    res = _run(MergeArgs(ticket_id="utt05h", worktree=str(lane), branch="lane/utt05h-root"))
    assert not res.ok and res.action == "failed"
    assert "[repo_a]" in res.error and "check-ref-format" in res.error, res.error
    assert lane.exists()
    assert any(str(lane) in p for p in _worktrees(mixed / "repo_a"))
    assert _lane_branches(mixed / "repo_a") == ["+ lane/utt05h-repo_a"]
    assert _lane_branches(mixed) == ["+ lane/utt05h-root"]


def test_teardown_invalid_member_branch_via_entries_also_rejected(mixed):
    """同一守卫在 entries 救源态（清单已灭）同样生效：命令流不带病进破坏性段。"""
    lane, entries = _make_mixed_lane(mixed, "utt05m")
    (lane / aa.MULTI_MANIFEST_REL).unlink()
    entries[1]["branch"] = "a..b"                     # 含 ".."：check-ref-format 拒
    res = _run(MergeArgs(ticket_id="utt05m", worktree=str(lane),
                         branch="lane/utt05m-root", repo_worktrees=entries))
    assert not res.ok and res.action == "failed"
    assert "[repo_a]" in res.error and "check-ref-format" in res.error, res.error
    assert any(str(lane) in p for p in _worktrees(mixed / "repo_a"))


# ---------- 残留可见性负锁（验收 C） ----------

def test_teardown_member_remove_failure_named_per_repo_not_silent(mixed, monkeypatch):
    """注入成员仓 worktree remove 失败：回执 ok=True（不阻断收口）但逐仓点名，
    且不短路（branch -D 照跑）、根仓照清——不得静默成功。"""
    lane, entries = _make_mixed_lane(mixed, "utt05i")
    real = aa._git

    def spy(args, cwd, timeout=60):
        if list(args)[:2] == ["worktree", "remove"] and Path(str(cwd)).name == "repo_a":
            return _failed("simulated member remove failure")
        return real(args, cwd, timeout=timeout)

    monkeypatch.setattr(aa, "_git", spy)
    res = _run(MergeArgs(ticket_id="utt05i", worktree=str(lane),
                         branch="lane/utt05i-root", repo_worktrees=entries))
    assert res.ok and res.action == "teardown"          # 既有取舍：残留不阻断收口
    assert "[repo_a] worktree remove 失败" in res.error, res.error
    assert "simulated member remove failure" in res.error
    # 不短路：该仓 branch -D 照样执行（remove 失败后 worktree 仍在，branch 被占用→
    # 删除被 git 拒，故两条 warn 都逐仓点名）；真残留如实留在盘上，可被巡检消费
    assert "[repo_a] branch -D 失败" in res.error, res.error
    assert _lane_branches(mixed / "repo_a") == ["+ lane/utt05i-repo_a"]
    assert any(str(lane) in p for p in _worktrees(mixed / "repo_a"))
    assert all(str(lane) not in p for p in _worktrees(mixed))   # 根仓照清
    assert not lane.exists()


def test_teardown_rerun_idempotent_named_warns_no_raise(mixed):
    """幂等重跑（Temporal 重试形态）：第二次不抛异常、ok=True、逐仓点名。"""
    lane, entries = _make_mixed_lane(mixed, "utt05j")
    first = _run(MergeArgs(ticket_id="utt05j", worktree=str(lane),
                           branch="lane/utt05j-root", repo_worktrees=entries))
    assert first.ok and first.error == ""
    second = _run(MergeArgs(ticket_id="utt05j", worktree=str(lane),
                            branch="lane/utt05j-root", repo_worktrees=entries))
    assert second.ok and second.action == "teardown"
    assert "[repo_a]" in second.error and "[root]" in second.error, second.error


# ---------- 同源判定（验收 D）+ payload 兼容 ----------

def test_lane_scopes_entries_param_same_source_as_manifest(mixed):
    """entries 入参走同一归一化段：与读盘清单产出逐字段一致（拆道/merge 不漂移）。"""
    lane, entries = _make_mixed_lane(mixed, "utt05k")
    from_file = aa._lane_scopes(lane, "lane/utt05k-root")
    from_entries = aa._lane_scopes(lane, "lane/utt05k-root", entries=entries)
    assert from_file == from_entries
    assert [s["repo_rel"] for s in from_file] == ["", "repo_a"]


def test_merge_args_repo_worktrees_payload_compat():
    """缺键回落空列表（在途旧票）+ 字段追加在末尾（位置实参兼容）。"""
    assert MergeArgs(ticket_id="x").repo_worktrees == []
    assert [f.name for f in dataclasses.fields(MergeArgs)][-1] == "repo_worktrees"


# ---------- dev_lane 接线源码锁定 ----------

def _src(name: str) -> str:
    return (POC / name).read_text(encoding="utf-8")


def test_source_lock_dev_lane_teardown_carries_repo_worktrees():
    src = _src("dev_lane.py")
    # 找调用点（import 清单里也有 "teardown_lane,"：取其后紧跟 MergeArgs( 的那处）
    at, call = -1, ""
    idx = 0
    while True:
        idx = src.find("teardown_lane,\n", idx + 1)
        if idx < 0:
            break
        tail = src[idx:idx + 400]
        if "MergeArgs(" in tail:
            at, call = idx, src[idx:src.find("start_to_close_timeout", idx)]
            break
    assert at > 0, "dev_lane 里 teardown_lane 调用点找不到"
    assert "repo_worktrees=" in call and 'meta.get("repo_worktrees")' in call, call


def test_source_lock_teardown_receipt_failclosed_branch_precedes_warn_branch():
    """回执 ok=False → _blocked 必须排在「只记 warn」之前：删/改序=静默化风险。"""
    src = _src("dev_lane.py")
    at = src.find("泳道拆除回执异常")
    warn_at = src.find("泳道拆除告警")
    assert 0 < at < warn_at, (at, warn_at)
    assert "_blocked" in src[max(0, at - 200):at], src[max(0, at - 200):at]


def test_source_lock_timeline_row_carries_receipt_error_verbatim():
    """时间线「泳道拆除告警」行必须原样透传回执 error——逐仓点名才能到巡检读面
    （验收 C 的时间线面；改成笼统文案=点名丢失）。"""
    src = _src("dev_lane.py")
    at = src.find("泳道拆除告警")
    assert at > 0, "时间线告警行找不到"
    seg = src[at:at + 200]
    assert "tr.error" in seg, seg


def test_source_lock_teardown_uses_lane_scopes_single_source():
    """拆道判定必须走 _lane_scopes（验收 D 的源码面钉子：不得另造第二套判定）。"""
    src = _src("agent_activities.py")
    at = src.find("async def teardown_lane(")
    assert at > 0
    body = src[at:src.find("\n# ---------- dev-lane:", at)]
    assert "_lane_scopes(" in body, body[:400]
    assert "repo = REPO_ROOT" not in body, "单仓硬编码不得回潮"
