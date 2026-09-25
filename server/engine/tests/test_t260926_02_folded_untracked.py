"""t260926-02（KI-125）：settle/merge_check 判脏展开 git 折叠未跟踪目录。

事故形态（nusuyou t260925-06）：全新未跟踪目录在缺省 `git status --porcelain -z`
下折叠成一条 `?? dir/`，写集条目写的是文件 `dir/file.py`——
path_gates._within('dir/', ['dir/file.py']) 为 False → unauthorized_path，
合法交付被隔离进 .sandbar/quarantine/，票两轮落不了地；同一形态用目录级条目
则命中「条目+/」前缀分支放行（对照 commit f1ca1a9a）。

修复立场：判定前在数据收集端展开（`--untracked-files=all`），闸保持逐文件
白名单判定、零放宽。本文件锁四件事：
  ① 事故形态 × 修复绿 × 反向对照（写集外文件仍红——派发规格硬性要求）；
  ② 嵌套仓目录 -uall 下仍折叠（gitlink 闸(a) 的尾斜杠形态前提保留，无旁路）；
  ③ merge_check 自愈准入 _dirty_within_write_set 同族根修回归（review_plan 附条件）；
  ④ ast 漂移锁：_settle_worktree_lane 内与 _merge_check_one_scope 的准入 status
    调用必须带 --untracked-files=all（漏改任一处=红）。
畸形输入用例以固定桩串复现（消费 git 输出必配畸形用例，不靠外部真源）。
"""
import ast
import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
from path_gates import judge_stage_paths  # noqa: E402
from agent_activities import (  # noqa: E402
    _dirty_files_from_status_z,
    _dirty_within_write_set,
)

AGENT_ACT = POC / "agent_activities.py"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture()
def scratch_repo(tmp_path: Path) -> Path:
    """干净基线的 scratch 仓（真实 git，只读 status 观测；不碰任何真仓 .git）。"""
    repo = tmp_path / "lane"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init")
    return repo


# ---------- ① KI-125 事故形态 × 修复 × 反向对照 ----------

def test_incident_shape_folded_by_default(scratch_repo: Path):
    """事故形态桩：缺省 status 把新未跟踪目录折叠成 `?? dir/`（KI-125 触发前提）。"""
    d = scratch_repo / "workflows"
    d.mkdir()
    (d / "content_studio.py").write_text("x = 1\n", encoding="utf-8")
    dirty = _dirty_files_from_status_z(
        subprocess.run(["git", "-C", str(scratch_repo), "status", "--porcelain", "-z"],
                       capture_output=True, text=True).stdout)
    assert dirty == ["workflows/"]
    # 折叠形态 × 文件级写集条目 = 误判红（复现 KI-125）
    allowed, violations, reason = judge_stage_paths(
        "implement", dirty, write_set=["workflows/content_studio.py"])
    assert not allowed and reason == "unauthorized_path"


def test_fix_uall_expands_and_gate_passes(scratch_repo: Path):
    """修复面：-uall 展开成文件级条目，写集判定绿；闸语义零改变。"""
    d = scratch_repo / "workflows"
    d.mkdir()
    (d / "content_studio.py").write_text("x = 1\n", encoding="utf-8")
    dirty = _dirty_files_from_status_z(
        subprocess.run(["git", "-C", str(scratch_repo), "status", "--porcelain",
                        "-z", "--untracked-files=all"],
                       capture_output=True, text=True).stdout)
    assert dirty == ["workflows/content_studio.py"]
    allowed, violations, reason = judge_stage_paths(
        "implement", dirty, write_set=["workflows/content_studio.py"])
    assert allowed and violations == [] and reason == ""


def test_reverse_control_out_of_write_set_still_red(scratch_repo: Path):
    """反向对照（防闸放宽）：同目录内写集外文件展开后仍判红、逐文件点名。"""
    d = scratch_repo / "workflows"
    d.mkdir()
    (d / "content_studio.py").write_text("x = 1\n", encoding="utf-8")
    (d / "evil.sh").write_text("rm -rf /\n", encoding="utf-8")
    dirty = _dirty_files_from_status_z(
        subprocess.run(["git", "-C", str(scratch_repo), "status", "--porcelain",
                        "-z", "--untracked-files=all"],
                       capture_output=True, text=True).stdout)
    assert sorted(dirty) == ["workflows/content_studio.py", "workflows/evil.sh"]
    allowed, violations, reason = judge_stage_paths(
        "implement", dirty, write_set=["workflows/content_studio.py"])
    assert not allowed and reason == "unauthorized_path"
    assert violations == ["workflows/evil.sh"]  # 只点名越权文件，不误伤写集内文件


def test_directory_level_entry_control_still_green(scratch_repo: Path):
    """对照组（commit f1ca1a9a 形态）：目录级条目 × 折叠清单照旧绿，不回归。"""
    d = scratch_repo / "workflows"
    d.mkdir()
    (d / "content_studio.py").write_text("x = 1\n", encoding="utf-8")
    dirty = _dirty_files_from_status_z(
        subprocess.run(["git", "-C", str(scratch_repo), "status", "--porcelain", "-z"],
                       capture_output=True, text=True).stdout)
    allowed, _, _ = judge_stage_paths("implement", dirty, write_set=["workflows"])
    assert allowed
    # -uall 清单 × 目录级条目同样绿（展开不破坏目录条目语义）
    uall = ["workflows/content_studio.py"]
    allowed, _, _ = judge_stage_paths("implement", uall, write_set=["workflows"])
    assert allowed


# ---------- ② 嵌套仓折叠保留（gitlink 闸(a) 前提） ----------

def test_nested_repo_stays_folded_under_uall(scratch_repo: Path):
    """-uall 不跨仓下钻：嵌套仓目录仍折叠成尾斜杠条目——gitlink_risk_from_dirty
    闸(a)（尾斜杠 × .git 探测）的形态前提保留，修复不构成旁路。"""
    (scratch_repo / "workflows").mkdir()
    (scratch_repo / "workflows" / "content_studio.py").write_text("x\n", encoding="utf-8")
    sub = scratch_repo / "sub"
    _git(scratch_repo, "init", "-q", str(sub))
    (sub / "a.txt").write_text("y\n", encoding="utf-8")
    dirty = _dirty_files_from_status_z(
        subprocess.run(["git", "-C", str(scratch_repo), "status", "--porcelain",
                        "-z", "--untracked-files=all"],
                       capture_output=True, text=True).stdout)
    assert "sub/" in dirty  # 嵌套仓仍折叠（尾斜杠条目在场）
    assert "workflows/content_studio.py" in dirty  # 普通目录照常展开


# ---------- ③ merge_check 自愈准入同族根修（review_plan 附条件第 5 条） ----------

def test_self_heal_admission_with_uall_file_entries():
    """回归：新目录 × 文件级写集条目 → 自愈准入放行（修复前折叠清单判假拒绝）。"""
    assert _dirty_within_write_set(
        ["workflows/content_studio.py"], ["workflows/content_studio.py"]) is True
    # 目录级条目（既有语义）不回归
    assert _dirty_within_write_set(["workflows/content_studio.py"], ["workflows"]) is True
    # 准入面同款反向对照：写集外文件仍拒（fail-closed 不放宽）
    assert _dirty_within_write_set(
        ["workflows/content_studio.py", "workflows/evil.sh"],
        ["workflows/content_studio.py"]) is False


# ---------- 解析器畸形输入（固定桩串，不靠外部源） ----------

@pytest.mark.parametrize("raw,expected", [
    # -uall 输出形与缺省形同构（XY<空格>path<NUL>）：畸形条目照旧丢弃不猜
    ("?? workflows/content_studio.py\0", ["workflows/content_studio.py"]),
    ("??\0?? workflows/a.py\0", ["workflows/a.py"]),       # 无路径条目丢弃
    ("? workflows/a.py\0", []),                            # XY 形不成立（第2字符非空格）丢弃
    ("?? \0", []),                                          # 空路径丢弃
    ("", []),
    (None, []),
])
def test_parser_malformed_shapes(raw, expected):
    assert _dirty_files_from_status_z(raw) == expected


# ---------- ④ ast 漂移锁：修复点不可回退 ----------

def _status_calls_with_pathspec(source: str) -> dict:
    """收集「带 SETTLE_PATHSPEC 实参的 git status 调用」按顶层函数名分组，
    每处标记是否带 --untracked-files=all（review 意见 6：锁面限定 pathspec 调用，
    不把无 pathspec 的旁路 status 误纳入）。"""
    out: dict = {}

    def visit(fn_node: ast.AST, fname: str) -> None:
        for node in ast.walk(fn_node):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) \
                    or node.func.id != "_git" or not node.args:
                continue
            arg0 = node.args[0]
            # SETTLE_PATHSPEC 以 BinOp（["status",…,"--"] + SETTLE_PATHSPEC）拼接：
            # arg0 可能是 List 也可能整个是 BinOp，先解出字面量列表再判
            lst = arg0
            if isinstance(lst, ast.BinOp):
                lst = lst.left
            if isinstance(lst, (ast.List, ast.Tuple)):
                strs = [e.value for e in lst.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                has_pathspec = any(isinstance(n, ast.Name) and n.id == "SETTLE_PATHSPEC"
                                   for n in ast.walk(arg0))
                if strs and strs[0] == "status" and has_pathspec:
                    out.setdefault(fname, []).append(
                        "--untracked-files=all" in strs)

    for fn in ast.parse(AGENT_ACT.read_text(encoding="utf-8")).body:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(fn, fn.name)
    return out


def test_ast_drift_lock_uall_on_gate_call_sites():
    """锁①：_settle_worktree_lane 内每处 pathspec status 都带 -uall（漏改重拉处=红）。
    锁②：_merge_check_one_scope 的自愈准入 status 带 -uall（附条件第 5 条）。"""
    calls = _status_calls_with_pathspec(AGENT_ACT.read_text(encoding="utf-8"))
    assert calls.get("_settle_worktree_lane") == [True, True], calls
    mc = calls.get("_merge_check_one_scope") or []
    assert True in mc, calls
