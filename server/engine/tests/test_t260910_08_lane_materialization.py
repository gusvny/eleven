"""t260910-08 单元测试：多仓明细贯通到建泳道 + 场景断言上移磁盘终态 + CWD 敏感红收口。

三面（对齐工单三项修复，全部零 Temporal server / 零模型 / 零网络，git 夹具 tmp 自足）：
  - 明细贯通：DevLaneWorkflow._init / TicketWorkflowBase._init 必须把
    TicketInput.repo_worktrees（原样，畸形条目不崩）与 project_root 搬进 meta；
    WorkspacePrep 构造收敛单点 shared.build_workspace_prep（绑定锚=getsource：
    任一 workflow 族回退内联 WorkspacePrep(...) 该 UT 即红——t260910-07 实案的
    「构造点静默缺喂」缺陷形态由结构钉死）；
  - 磁盘终态（进程内快腿）：_init 后的 meta 三环齐全、闸放行；泳道磁盘逐仓物化
    的完整断言（逐仓目录/分支名/清单/meta 非空）在 L3 真开票场景
    integration/t260910-08/sc_t260910_08_lane_materialization.py（真 ticket.py
    create → 真 worker → 磁盘），本文件不重复其 intent；
  - CWD 敏感红收口：shared.multirepo_fuse_a_error 在 project_root 缺失时不再借
    Path("").resolve()=cwd 兜底解析——同一输入在不同运行目录下结果必须逐字节一致
    （t260910-03 票 test_fuse_a_no_project_root_member_entries_still_rejected 的
    环境依赖红根因，本文件钉回归）。

畸形输入用例全走 tmp git 夹具/原样落键，不靠外部源。
"""
import inspect
import subprocess
import sys
import types
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
import shared  # noqa: E402
import dev_lane  # noqa: E402
import base  # noqa: E402
from shared import TicketInput  # noqa: E402


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
    return path


@pytest.fixture
def mixedrepo(tmp_path):
    """混合形态夹具（dengzhufpv 形态）：根=git 仓且有子仓（根树 repo="" 条目）。"""
    root = tmp_path / "proj"
    _init_repo(root, "notes/root.md")            # 根仓
    _init_repo(root / "repo_a", "src/a.py")      # 子仓
    yield root


@pytest.fixture
def singlerepo(tmp_path):
    root = tmp_path / "sg"
    _init_repo(root, "f.txt")
    yield root


class _BaseShell(base.TicketWorkflowBase):
    """base 族最小具体子类（STAGES 是子类职责，基类恒空 tuple）。"""
    PATCH_ID = "t26091008-ut"
    TEMPLATE_LANE = "worktree"
    TEMPLATE_WORKSPACE_DIR = False
    STAGES = (shared.Stage(id="s1", name="一步", role="developer"),)
    engine_version = shared.ENGINE_VERSION_V2


def _derive_split(ticket_id, project_root, write_set):
    """复刻 client.py ticket-start 的 derive→拆分两步（夹具同款，t260908-02 先例）。"""
    lane, ws, worktree, branch = shared.derive_lane_workspace(
        ticket_id, "dev-lane", lane=shared.LANE_WORKTREE,
        project_root=str(project_root), repo_write_set=write_set)
    rws = ws.pop("repo_worktrees", None)
    return lane, ws, worktree, branch, ([dict(e) for e in rws] if rws else [])


def _stub_workflow(monkeypatch, module):
    """免 Temporal 运行时的 workflow 壳（test_t260904_18_gate_pure.py:139 同款手法，
    monkeypatch 版=自动恢复）：patched 门恒 False、now 恒定、logger 静默。"""
    import datetime
    stub = types.SimpleNamespace(
        patched=lambda pid: False,
        now=lambda: datetime.datetime(2026, 9, 10, 12, 0, 0),
        logger=types.SimpleNamespace(info=lambda *a, **k: None))
    monkeypatch.setattr(module, "workflow", stub)
    return stub


# ---------- ① 明细贯通：_init 搬运 ----------

def test_dev_lane_init_carries_detail_and_project_root(mixedrepo, monkeypatch):
    """t260910-07 实案根因回归：dev_lane._init 必须把 repo_worktrees（原样）与
    project_root 搬进 meta（含 workflow_input 镜像），三环随即可用。"""
    _stub_workflow(monkeypatch, dev_lane)
    root = mixedrepo
    write_set = ["notes/root.md", "repo_a/src/a.py"]  # 根树+子仓（dengzhufpv 形态）
    lane, ws, worktree, branch, detail = _derive_split("t26091008dv", root, write_set)
    assert detail, "混合形态 derive 必须产出逐仓明细（含根树条目）"
    inp = TicketInput(ticket_id="t26091008dv", template_id="dev-lane", lane=lane,
                      workspace=ws, repo_worktrees=detail, worktree=worktree,
                      branch=branch, write_set=write_set, project_root=str(root))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.timeline = []
    wf.engine_version = shared.ENGINE_VERSION_V2   # __init__ 内的实例属性，壳对象手工补
    dev_lane.DevLaneWorkflow._init(wf, inp)
    assert wf.meta["repo_worktrees"] == detail, "明细必须原样贯通到 meta（缺陷面）"
    assert wf.meta["project_root"] == str(root), "归属锚必须贯通（兜底环③）"
    assert wf.meta["workflow_input"]["repo_worktrees"] == detail
    assert wf.meta["workflow_input"]["project_root"] == str(root)
    # 三环齐备后的直接后果：闸放行 + 单点构造出的 prep 三环全满
    assert shared.lane_workspace_gate_error(wf.meta) == ""
    prep = shared.build_workspace_prep("t26091008dv", wf.meta)
    assert prep.repo_worktrees == detail and prep.write_set == write_set
    assert prep.project_root == str(root)


def test_dev_lane_init_malformed_detail_lands_raw_not_crash(monkeypatch):
    """畸形条目（旁路 payload）：原样落 meta 不崩 _init（C3），形状裁判交既有闸出
    可读拒收——崩在 workflow 上下文=拿不到可读文案（评审条3 的反面钉死）。"""
    _stub_workflow(monkeypatch, dev_lane)
    inp = TicketInput(ticket_id="tbad1", template_id="dev-lane",
                      lane=shared.LANE_WORKTREE,
                      workspace={"type": "worktree", "path": "/tmp/x/.lane/tbad1"},
                      repo_worktrees=["oops", 7],   # 类型毁形（正常入口不会产出）
                      worktree="/tmp/x/.lane/tbad1", branch="lane/tbad1")
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.timeline = []
    wf.engine_version = shared.ENGINE_VERSION_V2   # __init__ 内的实例属性，壳对象手工补
    dev_lane.DevLaneWorkflow._init(wf, inp)  # 不得 raise
    assert wf.meta["repo_worktrees"] == ["oops", 7]
    gate = shared.lane_workspace_gate_error(wf.meta)
    assert gate, "畸形条目必须被闸拒收（可读文案，非静默放行）"


def test_base_init_carries_project_root(mixedrepo, monkeypatch):
    """C4 同族收口：base 族 meta 有 repo_worktrees、也必须有 project_root（兜底环③
    不许死）；缺键回落=老在途票 replay 安全。"""
    _stub_workflow(monkeypatch, base)
    root = mixedrepo
    write_set = ["notes/root.md", "repo_a/src/a.py"]
    lane, ws, worktree, branch, detail = _derive_split("t26091008bs", root, write_set)
    inp = TicketInput(ticket_id="t26091008bs", template_id="t-chore", lane=lane,
                      workspace=ws, repo_worktrees=detail, worktree=worktree,
                      branch=branch, write_set=write_set, project_root=str(root))
    wf = object.__new__(_BaseShell)
    wf.timeline = []
    _BaseShell._init(wf, inp)
    assert wf.meta["repo_worktrees"] == detail
    assert wf.meta["project_root"] == str(root)


# ---------- ② 绑定锚：WorkspacePrep 构造单点 ----------

def test_workspace_prep_construction_is_single_point():
    """「构造点绕开单点回退内联会红」：两族 workflow 的构造点必须走
    build_workspace_prep 且不再内联 WorkspacePrep(（t260910-07 缺陷的结构性钉子）。"""
    for obj, name in ((dev_lane.DevLaneWorkflow.run, "dev_lane.run"),
                      (base.TicketWorkflowBase._prepare_workspace,
                       "base._prepare_workspace")):
        src = inspect.getsource(obj)
        assert "build_workspace_prep(" in src, "%s 必须经单点构造" % name
        assert "WorkspacePrep(" not in src, (
            "%s 回退内联 WorkspacePrep(——t260910-07 缺陷形态复发，改回单点" % name)


def test_build_workspace_prep_feeds_three_rings_and_replay_safe():
    """单点构造的三环喂养 + 缺键回落（老 RUNNING 实例 replay 形态）。"""
    meta = {"workspace": {"type": "worktree", "path": "/r/.lane/t1"},
            "repo_worktrees": [{"repo": "", "name": "root", "branch": "lane/t1-root"}],
            "branch": "lane/t1", "base_ref": "abc",
            "write_set": ["notes/a.md"], "project_root": "/r"}
    p = shared.build_workspace_prep("t1", meta)
    assert p.ticket_id == "t1" and p.workspace == meta["workspace"]
    assert p.repo_worktrees == meta["repo_worktrees"]
    assert p.write_set == ["notes/a.md"] and p.project_root == "/r"
    assert p.branch == "lane/t1" and p.base_ref == "abc"
    # replay 安全：老票 meta 无这些键 → 全部缺省回落，不 raise、不误喂
    p0 = shared.build_workspace_prep("t0", {"workspace": None})
    assert p0.repo_worktrees == [] and p0.write_set == [] and p0.project_root == ""


# ---------- ③ CWD 敏感红收口：fuse A project_root 缺失腿 ----------

def test_fuse_a_empty_project_root_cwd_invariant(tmp_path, monkeypatch):
    """同输入在不同 cwd 下结果逐字节一致（环境依赖即缺陷，t260910-03 票红根因）。"""
    args = ("", ["repo_a/src/a.py"], [])
    with_git = tmp_path / "looks_like_repo"
    (with_git / ".git").mkdir(parents=True)     # cwd 有 .git（旧行为：判 offender）
    naked = tmp_path / "no_repo_at_all"         # cwd 无仓（旧行为：撞豁免放行）
    naked.mkdir()
    results = []
    for d in (with_git, naked, POC.parents[1]):  # 含引擎仓根本身
        monkeypatch.chdir(d)
        results.append(shared.multirepo_fuse_a_error(*args))
    assert results[0] == results[1] == results[2], "cwd 翻转判定=环境依赖缺陷"
    err = results[0]
    assert err, "project_root 缺失=归属锚缺失，fail-closed 拒收"
    assert "repo_a/src/a.py" in err, "拒收必须点名写集条目"


def test_fuse_a_empty_project_root_detail_present_passes():
    # 明细非空=放行（A 守缺失、B 守物化，两道保险丝各守一态）——收窄不波及
    assert shared.multirepo_fuse_a_error(
        "", ["repo_a/src/a.py"],
        [{"repo": "repo_a", "name": "repo_a", "branch": "lane/x-repo_a"}]) == ""


def test_fuse_a_empty_project_root_empty_write_set_passes():
    assert shared.multirepo_fuse_a_error("", [], []) == ""
    assert shared.multirepo_fuse_a_error("", None, []) == ""


def test_fuse_a_real_root_semantics_unchanged(mixedrepo):
    """project_root 在位时既有语义零漂移：根树条目放行、子仓条目缺失拒收点名。"""
    root = str(mixedrepo)
    # 全归根仓 → 放行（单仓/混合形态的根树部分）
    assert shared.multirepo_fuse_a_error(root, ["notes/root.md"], []) == ""
    # 命中子仓且明细缺失 → 拒收点名（owner 归属仍由 resolve 判）
    err = shared.multirepo_fuse_a_error(root, ["repo_a/src/a.py"], [])
    assert err and "repo_a" in err
