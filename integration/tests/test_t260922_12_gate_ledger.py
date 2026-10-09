#!/usr/bin/env python3
"""t260922-12 闸侧台账接线助手段机械自证（server/tools/verify_lane.py）。

只测 verify_lane 的公开助手（不执行 verify_lane 入口/不跑任何集成场景——集成
验证归机械段）：软链四态、同仓守卫、记账来源、行构造、查账/写账包装、git 面
（head/dirty/rev-parse/祖先）。真 git 仓 fixture（tmp 内 init+commit+worktree，
离线秒级）；真主账零接触（临时目录 env）。

覆盖（review 条件 A/B/C 的实现半边）：
- _baseline_dep_links：旋钮关=不挂+点名；happy=四条全挂；src 缺席跳过；dst 已在
  跳过（绝不覆盖）；跨仓守卫（基线树与泳道根非同仓 → 一条不挂+点名）；
- _ledger_source：注入 env > SANDBAR_TICKET_ID 回落 > 空（不写账）；
- _ledger_rows_from_cases：三态映射 not-checked→env_fail、ticket 仅 lane: 携带、
  pool=suite、width 整型；
- _ledger_module：缺席/坏模块 → (None, 响亮 reason)；
- _ledger_consult：可信最新优先、不可信/过期歧义面、读账失败零账可查不炸；
- _ledger_write：写失败折 error 回执（记账面≠判定面）；
- _git_head/_git_rev_parse/_worktree_dirty/_is_ancestor：真 git 面。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "vl_t92212_under_test", REPO / "server" / "tools" / "verify_lane.py")
vl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vl)

_spec_fp = importlib.util.spec_from_file_location(
    "fp_t92212_gate_under_test", REPO / "server" / "engine" / "failure_protocol.py")
fp_mod = importlib.util.module_from_spec(_spec_fp)
_spec_fp.loader.exec_module(fp_mod)

FP = "ab" * 32
SHA = "cd" * 20


def _git(args, cwd, timeout=60):
    return subprocess.run(["git", "-C", str(cwd)] + args, capture_output=True,
                          text=True, timeout=timeout)


def _commit_all(repo, msg):
    _git(["add", "-A"], repo)
    r = _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", msg],
             repo)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def repo(tmp_path):
    """主仓 fixture：带四条依赖目录的真实 git 仓。依赖目录保持 **untracked**
    （真实形态=gitignored：worktree checkout 不带依赖目录，软链才有挂点）——
    只 commit .gitignore+code。"""
    root = tmp_path / "mainrepo"
    root.mkdir()
    _git(["init", "-q", "-b", "main"], root)
    (root / ".gitignore").write_text(
        "".join("/%s\n" % rel for rel in vl.BASELINE_DEP_LINKS), encoding="utf-8")
    for rel in vl.BASELINE_DEP_LINKS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("dep-of-%s\n" % rel, encoding="utf-8")
    (root / "code.py").write_text("print('v1')\n", encoding="utf-8")
    _commit_all(root, "init")
    return root


def _worktree_of(repo, name):
    wt = repo.parent / name
    r = _git(["worktree", "add", "--detach", str(wt), "HEAD"], repo)
    assert r.returncode == 0, r.stderr
    return wt


# ---------------- _baseline_dep_links（review 条件 A：含跨仓守卫） ----------------

def test_dep_links_off_by_knob(repo, tmp_path, monkeypatch):
    wt = _worktree_of(repo, "wt-off")
    monkeypatch.setenv("SANDBAR_GATE_BASELINE_DEPS", "0")
    note = vl._baseline_dep_links(wt, repo)
    assert "显式关闭" in note
    assert not any((wt / rel).is_symlink() for rel in vl.BASELINE_DEP_LINKS)


def test_dep_links_happy_four_links(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_GATE_BASELINE_DEPS", "1")
    wt = _worktree_of(repo, "wt-happy")
    note = vl._baseline_dep_links(wt, repo)
    assert "4 条挂上" in note, note
    for rel in vl.BASELINE_DEP_LINKS:
        link = wt / rel
        assert link.is_symlink() and link.resolve() == (repo / rel).resolve(), rel


def test_dep_links_skip_when_src_absent(repo, tmp_path, monkeypatch):
    """新 clone/布局不同：src 缺席 → 跳过不致命（基线维持裸态方向）。"""
    monkeypatch.setenv("SANDBAR_GATE_BASELINE_DEPS", "1")
    # fixture 造的依赖位是文件（write_text）；unlink 同时兼容文件/符号链接形态，
    # rmtree 只吃目录（NotADirectoryError 实证）。
    (repo / "app" / "node_modules").unlink(missing_ok=True)
    wt = _worktree_of(repo, "wt-srcmiss")
    note = vl._baseline_dep_links(wt, repo)
    assert "3 条挂上" in note and "跳过 1 条" in note, note
    assert not (wt / "app" / "node_modules").is_symlink()


def test_dep_links_never_overwrite_existing_dst(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_GATE_BASELINE_DEPS", "1")
    wt = _worktree_of(repo, "wt-existing")
    dst = wt / "server" / "engine" / ".venv"
    dst.mkdir(parents=True)   # worktree 无依赖（untracked），手工造「dst 已在」
    (dst / "keep.txt").write_text("do-not-touch\n", encoding="utf-8")
    note = vl._baseline_dep_links(wt, repo)
    assert "跳过" in note, note
    assert dst.is_dir() and (dst / "keep.txt").exists(), "dst 已在绝不覆盖"


def test_dep_links_cross_repo_guard(repo, tmp_path, monkeypatch):
    """review 条件 A：基线树与泳道根非同仓 → 一条不挂+响亮点名（t260903-10 同族）。"""
    monkeypatch.setenv("SANDBAR_GATE_BASELINE_DEPS", "1")
    other = tmp_path / "otherrepo"
    other.mkdir()
    _git(["init", "-q", "-b", "main"], other)
    (other / "x.txt").write_text("other\n", encoding="utf-8")
    _commit_all(other, "init")
    wt_other = _worktree_of(other, "wt-cross")
    note = vl._baseline_dep_links(wt_other, repo)   # 基线树属他仓、泳道根=本仓
    assert "跨仓守卫" in note and "基线维持裸态" in note, note
    assert not any((wt_other / rel).is_symlink() for rel in vl.BASELINE_DEP_LINKS)


def test_dep_links_unresolvable_common_dir(tmp_path, monkeypatch):
    """git common dir 解析失败（非仓目录）→ 跳过不致命。"""
    monkeypatch.setenv("SANDBAR_GATE_BASELINE_DEPS", "1")
    plain = tmp_path / "plain"
    plain.mkdir()
    note = vl._baseline_dep_links(plain, plain)
    assert "跳过" in note


# ---------------- 记账来源 / 行构造 ----------------

def test_ledger_source_precedence(monkeypatch):
    monkeypatch.delenv(vl.LEDGER_SOURCE_ENV, raising=False)
    monkeypatch.delenv("SANDBAR_TICKET_ID", raising=False)
    assert vl._ledger_source() == ""
    monkeypatch.setenv("SANDBAR_TICKET_ID", "t-1")
    assert vl._ledger_source() == "lane:t-1"
    monkeypatch.setenv(vl.LEDGER_SOURCE_ENV, "inspection")
    assert vl._ledger_source() == "inspection"
    monkeypatch.setenv(vl.LEDGER_SOURCE_ENV, "lane:t-2")
    assert vl._ledger_source() == "lane:t-2"


def test_rows_from_cases_mapping():
    cases = [
        {"name": "s1", "suite": "main", "status": "pass", "dur_s": 1.5},
        {"name": "s2", "suite": "ro", "status": "fail", "dur_s": 2.0},
        {"name": "s3", "suite": "engine", "status": "not-checked", "dur_s": None},
    ]
    rows = vl._ledger_rows_from_cases(cases, SHA, FP, 4, "lane:t-9")
    assert [r["verdict"] for r in rows] == ["pass", "fail", "env_fail"]
    assert all(r["commit"] == SHA and r["env_fp"] == FP and r["conc_width"] == 4
               for r in rows)
    assert all(r["ticket"] == "t-9" for r in rows)
    assert [r["pool"] for r in rows] == ["main", "ro", "engine"]
    insp = vl._ledger_rows_from_cases(cases[:1], SHA, FP, 1, "inspection")
    assert insp[0]["ticket"] == "" and insp[0]["source"] == "inspection"


# ---------------- 台账模块装载 ----------------

def test_ledger_module_missing(tmp_path):
    mod, why = vl._ledger_module(tmp_path)
    assert mod is None and "缺席" in why


def test_ledger_module_broken(tmp_path):
    (tmp_path / "integration").mkdir()
    (tmp_path / "integration" / "scenario_ledger.py").write_text(
        "def broken(:\n", encoding="utf-8")
    mod, why = vl._ledger_module(tmp_path)
    assert mod is None and "装载失败" in why


def test_ledger_module_loads_real_one(tmp_path):
    (tmp_path / "integration").mkdir()
    (tmp_path / "integration" / "scenario_ledger.py").write_bytes(
        (REPO / "integration" / "scenario_ledger.py").read_bytes())
    mod, why = vl._ledger_module(tmp_path)
    assert mod is not None and why is None
    assert hasattr(mod, "append_records") and hasattr(mod, "read_rows")


# ---------------- 查账 / 写账包装 ----------------

class _FakeLedger:
    def __init__(self, rows, err=None):
        self._rows, self._err = rows, err

    def read_rows(self):
        return list(self._rows), []

    def append_records(self, rows):
        if self._err:
            raise OSError(self._err)
        return {"written": len(rows), "rejected": []}


def _row(verdict="fail", scenario="s1", ts=None, **over):
    # t261009-01 incidental fix: the default ts was a fixed 2026-09-21 stamp;
    # the ≤7-day trust bound (failure_protocol.ledger_trust rule 3) expired it
    # on 2026-09-28+ and the whole consult face started failing as a time bomb.
    # Default to NOW (fresh row) so the fixture tests trust ordering, not the
    # calendar; fixed stamps remain available for expiry tests via ts=...
    if ts is None:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    r = {"ts": ts, "commit": "ef" * 20, "env_fp": FP, "conc_width": 4,
         "pool": "main", "scenario": scenario, "verdict": verdict,
         "wall_s": 1.0, "source": "inspection", "ticket": ""}
    r.update(over)
    return r


def test_consult_trusted_latest_wins(repo, monkeypatch):
    monkeypatch.setattr(vl, "_is_ancestor", lambda *a, **k: True)
    # Both lanes fixed the same calendar time bomb (t261009-01 incidental fix
    # via the _row default ts=None -> NOW; main's t261009-11 via explicit
    # days-ago args). Kept explicit stamps so the fail/pass ORDERING is
    # deterministic regardless of clock resolution; both sit inside the
    # 7-day trust window, so the case tests ordering, not the calendar.
    from datetime import datetime, timedelta, timezone
    _now = datetime.now(timezone.utc)
    _iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    rows = [_row(verdict="fail", ts=_iso(_now - timedelta(days=1))),
            _row(verdict="pass", ts=_iso(_now))]
    answers, red, green, amb = vl._ledger_consult(
        fp_mod, _FakeLedger(rows), ["s1"], FP, 4, SHA, repo)
    assert answers["s1"]["verdict"] == "pass", "同键多行取最新可信"
    assert red == [] and green == ["s1"] and amb == []


def test_consult_untrusted_goes_ambiguous(repo, monkeypatch):
    # 祖先 mock 按提交判（默认行 commit=ef*20 → 祖先；s5 显式换 00*20 → 非祖先）
    monkeypatch.setattr(vl, "_is_ancestor",
                        lambda root, commit, base: commit == "ef" * 20)
    rows = [
        _row("fail", "s1", env_fp="00" * 32),                     # 指纹不等
        _row("fail", "s2", ts="2020-01-01T00:00:00+00:00"),       # 过期
        _row("fail", "s3", conc_width=1),                         # 宽度不等
        _row("env_fail", "s4"),                                   # 没检验到
        _row("fail", "s5", commit="00" * 20),                     # 非祖先
    ]
    answers, red, green, amb = vl._ledger_consult(
        fp_mod, _FakeLedger(rows), ["s1", "s2", "s3", "s4", "s5"], FP, 4, SHA, repo)
    assert answers == {} and red == [] and green == []
    assert amb == ["s1", "s2", "s3", "s4", "s5"], "全歧义=照旧回退实跑"


def test_consult_read_failure_is_loud_not_fatal(repo, tmp_path, monkeypatch):
    class _Boom:
        def read_rows(self):
            raise RuntimeError("disk gone")
    monkeypatch.setattr(vl, "_is_ancestor", lambda *a, **k: True)
    answers, red, green, amb = vl._ledger_consult(
        fp_mod, _Boom(), ["s1"], FP, 4, SHA, repo)
    assert answers == {} and amb == ["s1"], "读账失败=无账可查，回退实跑不炸"


def test_consult_no_module_or_no_reds(repo):
    assert vl._ledger_consult(fp_mod, None, ["s1"], FP, 4, SHA, repo) == ({}, [], [], [])
    assert vl._ledger_consult(fp_mod, _FakeLedger([_row()]), [], FP, 4, SHA, repo) \
        == ({}, [], [], [])


def test_write_wraps_failure_as_error_receipt():
    rcpt = vl._ledger_write(_FakeLedger([], err="boom"),
                            [{"any": "row"}])
    assert rcpt["written"] == 0 and "台账写失败" in rcpt["error"]
    assert "OSError" in rcpt["error"], "异常类型可观测"


# ---------------- git 面（head/rev-parse/dirty/祖先） ----------------

def test_git_head_rev_parse_dirty_ancestor(repo, tmp_path):
    head = vl._git_head(repo)
    assert len(head) == 40
    assert vl._git_rev_parse(repo, "main") == head
    assert vl._worktree_dirty(repo) is False
    (repo / "untracked.txt").write_text("x\n", encoding="utf-8")
    assert vl._worktree_dirty(repo) is True
    # 祖先：前一版是 HEAD 的祖先；反向不成立。fixture 仓单 commit（根提交=自己
    # 是自己的祖先，rev-list --max-parents=0 即 HEAD 本身）——「反向不成立」在
    # 单 commit 仓不可表达（夹具缺陷，P0 修复前该断言从未被执行到）。补第 2 个
    # commit 造「真前一版」：断言变准非变松。
    (repo / "code.py").write_text("print('v2')\n", encoding="utf-8")
    _commit_all(repo, "second")
    head2 = vl._git_head(repo)
    root_sha = _git(["rev-list", "--max-parents=0", "HEAD"], repo).stdout.strip()
    assert head2 != head and root_sha == head, "根提交=init 版，HEAD=v2 版"
    assert vl._is_ancestor(repo, root_sha, head2) is True
    assert vl._is_ancestor(repo, head2, root_sha) is False
    assert vl._is_ancestor(repo, head2, head2) is True, "相同 commit 视为祖先"
    assert vl._is_ancestor(repo, "", head2) is False
    assert vl._git_rev_parse(repo, "no-such-ref") == ""
    assert vl._worktree_dirty(tmp_path / "not-a-repo") is True, "判不了=按脏处理"
