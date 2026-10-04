#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261002-10：代码生成物新鲜度豁免（_codegen_fresh_snapshots）UT（gen5 修订）。

四轮同因实案（gen1–gen4）：gen_workflows_doc.py 的 yaml 快照落在写集外
（server/workflows/），path_gate 自动处置每轮回滚 M 态生成物。gen3 加固引入豁免，
但 gen4 仲裁钉出**第二病根**：检查子进程用 sys.executable，settle worker 的解释器
不保证是 engine venv ⇒ `import dev_lane` 处 ModuleNotFoundError: temporalio ⇒
检查假失败、静默 [] ⇒ 豁免隐形 ⇒ 照旧回滚。

本 UT 锁（gen5 三点修复意见逐一对应）：
- A 解释器回落链 `_engine_python_for_codegen`：engine venv 在场=用它；备选 venv
  回落=仅认在役 engine venv（gen6 收窄：旧布局 temporal-poc 路径不硬编码）；都不在=回
  sys.executable 兜底。
- B 检查判定（二元组）：--check 退 0=恰返回快照名单+空诊断；任何失败形态
  （生成器缺席/非 0/超时/异常）=fresh [] + **具名诊断串**（点名解释器与原因，
  绝不静默 [] —— 仲裁意见②）；无快照名单=零动作零诊断。
- C 接线与回执面：豁免判定先于 judge（闸序）；具名诊断进拒绝回执 note 与
  activity 日志；豁免命中写进 settle 回执 notes（仲裁意见③：豁免必须以
  「随段代落盘」收尾，不只是不回滚——回执 notes 即落盘凭证位）。
"""
from __future__ import annotations

import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402

SRC = (POC / "agent_activities.py").read_text("utf-8")

GEN_STUB = """#!/usr/bin/env python3
import sys
sys.exit(%d)
"""

YAML_F = "server/workflows/dev-lane.yaml"


def _lane(cwd, exit_code=0, with_gen=True):
    eng = cwd / "server" / "engine"
    eng.mkdir(parents=True, exist_ok=True)
    if with_gen:
        g = eng / "gen_workflows_doc.py"
        g.write_text(GEN_STUB % exit_code, encoding="utf-8")
        g.chmod(g.stat().st_mode | 0o755)


# ---------- A：解释器回落链 ----------

def test_engine_python_prefers_lane_engine_venv(tmp_path):
    venv = tmp_path / "server" / "engine" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("", encoding="utf-8")
    assert aa._engine_python_for_codegen(tmp_path) == str(
        tmp_path / "server" / "engine" / ".venv" / "bin" / "python")


def test_engine_python_never_points_at_retired_temporal_poc_layout():
    """gen6（宿主令）：陈旧迁移前引擎路径（旧 temporal-poc venv 布局）不得作为解释器  # t260907-10（反向守卫行：票号锚=扫描器豁免约定）
    回落——t260907-10-engine-layout 同族判据，代码与测试源码双双不硬编码完整路径。"""
    assert "temporal-poc/.venv/bin/python" not in SRC  # 路径字面量不得存在（注释提及不在此列）# t260907-10（反向守卫行）
    fn = SRC[SRC.index("def _engine_python_for_codegen"):]
    fn = fn[:fn.index("\n\n\ndef ")]
    assert "server/engine/.venv/bin/python" in fn
    assert "server/dsh" not in fn  # t260907-10（反向守卫行：断言不指旧布局，非回落链）


def test_engine_python_falls_back_to_sys_executable(tmp_path):
    (tmp_path / "server" / "engine").mkdir(parents=True)
    assert aa._engine_python_for_codegen(tmp_path) == sys.executable


# ---------- B：检查判定（二元组，具名诊断） ----------

def test_fresh_when_check_exits_zero(tmp_path):
    _lane(tmp_path, exit_code=0)
    files = [YAML_F, "server/workflows/light-lane.yaml", "server/engine/dev_lane.py"]
    out, diag = aa._codegen_fresh_snapshots(tmp_path, files)
    assert out == ["server/workflows/dev-lane.yaml", "server/workflows/light-lane.yaml"]
    assert diag == ""
    # 非生成物（不在 server/workflows/ 下或非 .yaml）永不进豁免名单
    out2, _ = aa._codegen_fresh_snapshots(
        tmp_path, ["server/workflows/README.md", "server/workflows/x.yml"])
    assert out2 == []


def test_unfresh_names_interpreter_when_check_exits_nonzero(tmp_path):
    _lane(tmp_path, exit_code=1)
    out, diag = aa._codegen_fresh_snapshots(tmp_path, [YAML_F])
    assert out == []
    assert "未过" in diag and "解释器=" in diag and "exit=1" in diag


def test_fail_closed_with_named_reason_when_generator_missing(tmp_path):
    (tmp_path / "server" / "engine").mkdir(parents=True)
    out, diag = aa._codegen_fresh_snapshots(tmp_path, [YAML_F])
    assert out == [] and "生成器缺席" in diag
    out2, diag2 = aa._codegen_fresh_snapshots(tmp_path / "nope", [YAML_F])
    assert out2 == [] and "生成器缺席" in diag2


def test_malformed_generator_counts_as_unfresh_with_named_reason(tmp_path):
    _lane(tmp_path, with_gen=True)
    g = tmp_path / "server" / "engine" / "gen_workflows_doc.py"
    g.write_text("import sys\nsys.stderr.write('boom')\nsys.exit(3)\n",
                 encoding="utf-8")
    out, diag = aa._codegen_fresh_snapshots(tmp_path, [YAML_F])
    assert out == [] and "exit=3" in diag and "boom" in diag


def test_no_snapshot_paths_means_noop_without_diagnostics(tmp_path):
    assert aa._codegen_fresh_snapshots(tmp_path, ["server/engine/dev_lane.py"]) == ([], "")
    assert aa._codegen_fresh_snapshots(tmp_path, []) == ([], "")


# ---------- C：接线与回执面 ----------

def test_gate_order_exemption_before_judge_and_diag_on_receipt():
    """结构锚：豁免判定先于 judge（先判后 add）；诊断串同时进 activity 日志与
    拒绝回执 note；豁免命中写进 settle 回执 notes（落盘凭证位）。"""
    i_fresh = SRC.index("fresh, fresh_diag = _codegen_fresh_snapshots(cwd, dirty)")
    i_judge = SRC.index("path_gates.judge_stage_paths(", i_fresh)
    assert i_fresh < i_judge
    assert "judged = [f for f in dirty if f not in fresh] if fresh else dirty" in SRC
    # 诊断双出口：日志（settle 即时可见）+ 拒绝 note（票面可见，gen4 缺的就是这句）
    assert 'face, fresh_diag)' in SRC
    i_refusal = SRC.index('note = path_gates.gate_refusal_note(stage_id, violations, reason)')
    tail = SRC[i_refusal:i_refusal + 700]
    assert 'note += "；%s" % fresh_diag' in tail
    # 豁免命中=回执 notes 记名「随本段代落盘」（不只是不回滚）
    assert "代码生成物新鲜度豁免（t261002-10）" in SRC and "随本段代落盘" in SRC


def test_engine_venv_chain_is_the_one_used_by_the_check(tmp_path):
    """回落链真被检查子进程消费（不是摆设）：stub 生成器只在 engine venv 解释器
    下退 0（argv[0]/samefile 点名自证）。"""
    eng = tmp_path / "server" / "engine"
    eng.mkdir(parents=True)
    vbin = eng / ".venv" / "bin"
    vbin.mkdir(parents=True)
    vpy = vbin / "python"
    vpy.symlink_to(sys.executable)  # 真 venv 形态=可执行解释器（空文件会 Exec format error）
    g = eng / "gen_workflows_doc.py"
    g.write_text("import sys, os\nsys.exit(0 if os.path.samefile(sys.executable, %r) else 1)\n"
                 % str(vpy), encoding="utf-8")
    out, diag = aa._codegen_fresh_snapshots(tmp_path, [YAML_F])
    assert out == [YAML_F] and diag == "", diag


def test_forbidden_entries_untouched():
    """红线：developer 段集成禁跑判据面逐字节未放宽（本票加固不碰执法面）。"""
    import integration_discipline
    assert integration_discipline.FORBIDDEN_ENTRIES == (
        ("run_scenarios.py", "integration/run_scenarios.py"),
        ("sc_*", "integration/**/sc_*.py|.mjs"),
        ("baselines", "integration/baselines/*"),
        ("with_stage.sh", "integration/with_stage.sh"),
        ("verify_lane", "verify_lane（含 admin.py call verify_lane）"),
    )


def test_settle_end_to_end_exemption_commits_the_snapshot(tmp_path):
    """仲裁意见③端到端证明（gen5）：真 git 泳道 + 真落盘函数——豁免命中的快照必须
    以 **commit** 收尾（不是仅仅不回滚）。写集只含 server/engine，快照在写集外；
    生成器 stub 把快照重写为 fresh 文本，工作区脏快照与其一致 ⇒ --check 绿 ⇒
    settle 提交携带快照，回执 notes 记名豁免。"""
    import subprocess as sp

    def git(*a):
        p = sp.run(["git"] + list(a), cwd=str(tmp_path if len(a) == 0 else a[-1]),
                   capture_output=True, text=True)
        assert p.returncode == 0, (a, p.stderr)
        return p.stdout.strip()

    repo = tmp_path / "r"
    repo.mkdir()
    for a in (["init", "-b", "main"],):
        p = sp.run(["git"] + a, cwd=str(repo), capture_output=True, text=True)
        assert p.returncode == 0
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        p = sp.run(["git", "config", cfg[0], cfg[1]], cwd=str(repo),
                   capture_output=True, text=True)
        assert p.returncode == 0
    (repo / "server" / "engine").mkdir(parents=True)
    (repo / "server" / "workflows").mkdir(parents=True)
    (repo / "server" / "engine" / "keep.txt").write_text("x\n")
    (repo / "server" / "workflows" / YAML_F.rsplit("/", 1)[1]).write_text("old\n")
    (repo / "server" / "engine" / "gen_workflows_doc.py").write_text(
        "#!/usr/bin/env python3\n"
        "open('../workflows/dev-lane.yaml','w').write('fresh: true\\n')\n"
        "import sys; sys.exit(0)\n")
    p = sp.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, text=True)
    assert p.returncode == 0
    p = sp.run(["git", "commit", "-m", "base"], cwd=str(repo), capture_output=True, text=True)
    assert p.returncode == 0
    p = sp.run(["git", "branch", "lane"], cwd=str(repo), capture_output=True, text=True)
    assert p.returncode == 0
    lane = tmp_path / "lane"
    p = sp.run(["git", "worktree", "add", str(lane), "lane"], cwd=str(repo),
               capture_output=True, text=True)
    assert p.returncode == 0
    snap = lane / "server" / "workflows" / "dev-lane.yaml"
    snap.write_text("fresh: true\n")  # 脏快照=生成器输出（--check 绿）

    note = aa._settle_worktree_lane(
        lane, "t261002-10", "implement", 0, repo=repo,
        write_set=["server/engine"], path_gate=True, face="agent")

    head = sp.run(["git", "show", "--stat", "--format=", "HEAD"], cwd=str(lane),
                  capture_output=True, text=True)
    assert head.returncode == 0
    assert "dev-lane.yaml" in head.stdout, head.stdout
    assert snap.read_text() == "fresh: true\n"
    assert "代码生成物新鲜度豁免（t261002-10）" in note and "随本段代落盘" in note
