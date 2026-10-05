"""t260908-02 单元测试：多仓/混合形态 payload 形状修复（repo_worktrees 一等字段）。

根因（t260907-13 实锤）：derive_lane_workspace 混合形态把 repo_worktrees
(list[dict]) 内嵌进 workspace，而 TicketInput.workspace / WorkspacePrep.workspace
注解是 Optional[Dict[str, str]] → Temporal dataclass payload 解码 TypeError，
workflow 启动失败。t260907-06 族 UT 只夹具直调 prepare_workspace，绕过了 Temporal
编解码缝才漏网（KI-049③ 缝契约同族）——本文件一律走真 DataConverter 编解码往返
做「启动面」代理断言，直调通道只作回落兼容分支。

断言分层（报错必须精确纪律）：
  - 类型毁形（repo_worktrees 含非 dict 条目等）→ Temporal 编解码层拒（roundtrip 抛
    异常，workflow 起不来），不当 gate 拒收断言；
  - 形状合法但语义非法（branch 碰撞/缺 name）→ lane_workspace_gate_error 拒
    （blocked+可读文案），不当编解码层断言。

零 Temporal server / 零模型 / 零网络；git 夹具在 tmp 自足。
"""
import asyncio
import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
import shared  # noqa: E402
from shared import TicketInput, WorkspacePrep  # noqa: E402
from _tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （夹具注册表+atexit 回收）
from temporalio.converter import DataConverter  # noqa: E402


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path, commit=True):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    if commit:
        _git("add", "-A", cwd=path)
        _git("commit", "-m", "base", cwd=path)
    return path


@pytest.fixture
def mixedrepo():
    """混合形态夹具（dengzhufpv 形态，t260907-12 起）：根=git 仓且有子仓。"""
    root = mkdtemp_reclaimed("t260908-02-ut-")
    _init_repo(root)  # 根仓
    a = _init_repo(root / "repo_a")
    (a / "src").mkdir()
    (a / "src" / "a.py").write_text("a\n", encoding="utf-8")
    yield root, a


@pytest.fixture
def singlerepo():
    root = mkdtemp_reclaimed("t260908-02-sg-")
    _init_repo(root)
    yield root


def _derive_split(ticket_id, project_root, write_set):
    """复刻 client.py ticket-start 的 derive→拆分两步，返回 (TicketInput 侧字段)。"""
    lane, ws, worktree, branch = shared.derive_lane_workspace(
        ticket_id, "dev-lane", lane=shared.LANE_WORKTREE,
        project_root=str(project_root), repo_write_set=write_set)
    rws = ws.pop("repo_worktrees", None)
    return lane, ws, worktree, branch, ([dict(e) for e in rws] if rws else [])


def _roundtrip(conv, obj):
    """编解码往返。decode 侧带 type_hints=按 dataclass 注解逐字段校验——正是
    workflow 启动解码的失败点（worker 日志 Failed converting field workspace）。"""
    pc = conv.payload_converter

    async def go():
        payloads = pc.to_payloads([obj])
        values = pc.from_payloads(payloads, type_hints=[type(obj)])
        got = values[0]
        assert got == obj, "往返内容不等: %r vs %r" % (got, obj)
        return got
    return asyncio.run(go())


# ---------- 混合形态：TicketInput 编解码往返（启动面代理） ----------

def test_mixed_ticketinput_payload_roundtrip(mixedrepo):
    root, sub = mixedrepo
    lane, ws, worktree, branch, rws = _derive_split(
        "t26090802mx", root, ["docs/kb.md", "repo_a/src/a.py"])
    assert rws, "混合形态 derive 应产出逐仓明细"
    assert "repo_worktrees" not in ws, "拆分后 workspace 必须归纯 {type, path}"
    inp = TicketInput(ticket_id="t26090802mx", template_id="dev-lane",
                      lane=lane, workspace=ws, repo_worktrees=rws,
                      worktree=worktree, branch=branch,
                      write_set=["docs/kb.md", "repo_a/src/a.py"])
    out = _roundtrip(DataConverter(), inp)
    assert out.repo_worktrees, "混合形态逐仓明细独立字段往返保留"
    assert "repo_worktrees" not in out.workspace


def test_mixed_workspaceprep_payload_roundtrip(mixedrepo):
    """第二跳：workflow→activity 的 WorkspacePrep 同样经编解码，独立字段必须过。"""
    prep = WorkspacePrep(
        ticket_id="t26090802mx",
        workspace={"type": "worktree", "path": "/tmp/x/.lane/t26090802mx"},
        repo_worktrees=[{"repo": "", "name": "root", "branch": "lane/t-root"},
                        {"repo": "repo_a", "name": "repo_a", "branch": "lane/t-repo-a"}],
        branch="lane/t26090802mx")
    out = _roundtrip(DataConverter(), prep)
    assert out.repo_worktrees and "repo_worktrees" not in out.workspace


# ---------- 畸形输入（消费外部输入纪律，桩内复现） ----------

def test_malformed_repo_worktrees_rejected_at_codec_layer():
    """类型毁形在编解码层拒（workflow 起不来）——不与 gate 拒收混断。"""
    conv = DataConverter()
    bad_entries = [[{"repo": "", "name": "root", "branch": "b"}, 42],          # 非 dict 条目
                   [{"repo": "", "name": "root", "branch": 7}]]                # 值非 str
    for rws in bad_entries:
        inp = TicketInput(ticket_id="t", template_id="dev-lane",
                          workspace={"type": "worktree", "path": "/tmp/x"},
                          repo_worktrees=rws)
        with pytest.raises(Exception):
            _roundtrip(conv, inp)


def test_old_embedded_shape_still_fails_at_codec_layer():
    """事故形态复现（t260907-13）：workspace 内嵌 repo_worktrees 旧形状在 decode 层
    必炸（Failed converting field workspace）——守住「不得再把 list 塞回 workspace」。"""
    old = TicketInput(ticket_id="t", template_id="dev-lane",
                      workspace={"type": "worktree", "path": "/tmp/x",
                                 "repo_worktrees": [{"repo": "", "name": "root",
                                                     "branch": "b"}]})
    with pytest.raises(TypeError, match="Failed converting field workspace"):
        _roundtrip(DataConverter(), old)


# ---------- gate：语义非法在新/旧两真源位都拒，空列表/单仓不误伤 ----------

_BASE_WS = {"type": "worktree", "path": "/proj/.lane/tx"}
_GOOD_RWS = [{"repo": "", "name": "root", "branch": "lane/tx-root"},
             {"repo": "repo_a", "name": "repo_a", "branch": "lane/tx-repo-a"}]


def test_gate_semantic_rejects_meta_toplevel():
    bad = [dict(_GOOD_RWS[0]),
           dict(_GOOD_RWS[0], repo="repo_a", name="repo_a")]  # branch 碰撞
    assert "branch name collision" in shared.lane_workspace_gate_error(
        {"lane": "worktree", "workspace": dict(_BASE_WS),
         "worktree": _BASE_WS["path"], "branch": "lane/tx",
         "repo_worktrees": bad})
    missing = [{"repo": ""}]  # 缺 name/branch
    assert shared.lane_workspace_gate_error(
        {"lane": "worktree", "workspace": dict(_BASE_WS),
         "worktree": _BASE_WS["path"], "branch": "lane/tx",
         "repo_worktrees": missing})


def test_gate_fallback_embedded_ws_position():
    """回落 ws 内嵌旧位：兜「未来新入口/手写 payload/夹具直调」绕过创建链的情形
    ——不是兜旧 RUNNING 票（旧形状 payload 第一跳 decode 就起不来，不可能在飞）。"""
    good = {"lane": "worktree", "workspace": dict(_BASE_WS, repo_worktrees=_GOOD_RWS),
            "worktree": _BASE_WS["path"], "branch": "lane/tx"}
    assert shared.lane_workspace_gate_error(good) == ""
    bad = {"lane": "worktree",
           "workspace": dict(_BASE_WS, repo_worktrees=[
               dict(_GOOD_RWS[0]),
               dict(_GOOD_RWS[0], repo="repo_a", name="repo_a")]),
           "worktree": _BASE_WS["path"], "branch": "lane/tx"}
    assert "branch name collision" in shared.lane_workspace_gate_error(bad)


def test_gate_empty_list_and_single_repo_pass():
    # 新字段缺省 []（单仓票）：不得被误判为多仓明细缺失
    assert shared.lane_workspace_gate_error(
        {"lane": "worktree", "workspace": dict(_BASE_WS),
         "worktree": _BASE_WS["path"], "branch": "lane/tx",
         "repo_worktrees": []}) == ""
    assert shared.lane_workspace_gate_error(
        {"lane": "worktree", "workspace": dict(_BASE_WS),
         "worktree": _BASE_WS["path"], "branch": "lane/tx"}) == ""


# ---------- 单仓/纯容器零回归 ----------

def test_single_repo_zero_regression(singlerepo):
    root = singlerepo
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("a\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "-m", "w", cwd=root)
    lane, ws, worktree, branch, rws = _derive_split("t26090802sg", root,
                                                    ["src/a.py"])
    assert rws == [] and "repo_worktrees" not in ws, "单仓 derive 不产明细（回归面）"
    inp = TicketInput(ticket_id="t26090802sg", template_id="dev-lane",
                      lane=lane, workspace=ws, repo_worktrees=rws,
                      worktree=worktree, branch=branch, write_set=["src/a.py"])
    conv = DataConverter()
    out = _roundtrip(conv, inp)
    assert out.repo_worktrees == []


def test_prep_default_field_replay_safe():
    """缺省构造（存量 RUNNING 重放形态）：字段缺键回落 []，不破回放。"""
    prep = WorkspacePrep(ticket_id="t", workspace={"type": "worktree", "path": "/x"})
    assert prep.repo_worktrees == []
    assert TicketInput(ticket_id="t", template_id="dev-lane").repo_worktrees == []
