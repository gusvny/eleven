"""260929 单测（KI-162）：重开同期搭不起泳道 —— 判据纯函数 + 定向清扫原语。

病根（260926-27 实案）：巡检泳道路径/分支按 **(实例, 期)** 复用（inspection_lane_name
= `inspection-<实例>-<期>` / `inspection/<实例>/<期>`），而 setup 前置的 sweep 用
`keep_period=本期`（**刻意不碰本期**——那是本票自己要用的路径）。于是「具名重开同期」
（inspection_trigger.py trigger --reopen-reason，260926 宿主令新加的能力）**结构性
搭不起泳道**：旧票（判决 blocked、执行已 COMPLETED）的残留仍在原位 →
`git worktree add` 必败 → setup blocked（t260927-02：09-26 10:10 首次真跑 reopen 即
blocked）；该期此后两张票都 blocked，09-27 的自动班再以「同期已服务票出现多张」硬失败。

本单测锁三件事：
  ①判据＝纯函数 `lane_residue_repair_plan`：只认「worktree add 失败」这一形态
    （清残留解得了的只有它）；git 身份缺失/多仓/权限等别的失败一律不修（判不准不动）；
  ②原语＝`sweep_inspection_lanes_impl` 的**定向模式**（remove_period=本期）在真 git
    仓上真拆：本期 worktree + 本期分支 + 本期裸目录壳三形全收，**别的期/别的实例一律
    不碰**；内嵌真仓的壳拒拆并点名（t260916-20 守卫不许被本条绕开）；
  ③接线＝setup 段的修复分支在 patch 门内（老 history 重放零新命令）、且送的是定向
    参数（keep 空 + remove_period 本期），不是水位模式。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_inspection_lane_residue_repair.py -q
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_activities as aa  # noqa: E402
import inspection_flow as flow  # noqa: E402

INST = "integration-tests"
P = "20260927"          # 被重开的期（旧票残留占位）
P_NEXT = "20260928"     # 次日（定向模式不许碰）

#: 真形失败文案（逐字取自 agent_activities._prepare_worktree_lane 的返回值 +
#: 260927-02 票面 blocked_reason 的 stderr 尾）。
REAL_OCCUPIED = (
    "git worktree add /Users/user/Documents/sandbar/.lane/inspection-integration-tests-20260927 "
    "-b inspection/integration-tests/20260927 失败（目录已存在但非本仓库 worktree？请人工处置）:\n"
    "Preparing worktree (new branch 'inspection/integration-tests/20260927')\n"
    "fatal: a branch named 'inspection/integration-tests/20260927' already exists")
REAL_IDENTITY = ("commit identity missing: user.email is not set (git identity guard, "
                 "t260905-10) — set it in the repo or the global config")


# ---------------- ①判据（纯函数） ----------------

def test_occupied_lane_plans_a_targeted_sweep():
    plan = flow.lane_residue_repair_plan(
        {"ok": False, "action": "failed", "error": REAL_OCCUPIED}, INST, P, "/repo")
    assert plan is not None, "「worktree add 失败」＝本期残留占位，必须给修复计划"
    assert plan["sweep_args"] == {"instance_id": INST, "repo_root": "/repo",
                                  "keep_period": "", "remove_period": P}, \
        "修复必须走定向模式（remove_period=本期），水位模式正是漏掉本期残留的原因"
    assert P in plan["reason"] and "prepare retry" in plan["reason"]
    assert " " not in plan["reason"].rstrip() or " " in plan["reason"]  # 人话（英文，上票面）


@pytest.mark.parametrize("prep", [
    {"ok": True, "action": "created", "error": ""},                       # 搭成了：不修
    {"ok": False, "action": "failed", "error": REAL_IDENTITY},            # 别种失败：不修
    {"ok": False, "action": "reused", "error": ""},                       # 形态不对：不修
    {"ok": False, "action": "failed", "error": ""},                       # 无事由：不修
    {}, None, "boom", 42,                                                  # 畸形：不修不炸
])
def test_non_occupied_failures_are_not_repaired(prep):
    assert flow.lane_residue_repair_plan(prep, INST, P, "/repo") is None, \
        "判不准不动：清残留解不了别的失败，乱清=拆掉别人（或自己）的泳道"


def test_repair_plan_never_targets_another_period():
    plan = flow.lane_residue_repair_plan(
        {"ok": False, "action": "failed", "error": REAL_OCCUPIED}, INST, P, "/repo")
    assert plan["sweep_args"]["remove_period"] == P
    assert plan["sweep_args"]["remove_period"] != P_NEXT


# ---------------- ②原语（真 git 仓上的定向清扫） ----------------

def _git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败：%s" % (" ".join(args), (p.stderr or "").strip()[-300:])
    return p.stdout


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "f.txt").write_text("x", encoding="utf-8")
    _git(r, "add", "f.txt")
    _git(r, "commit", "-m", "init")
    return r


def _make_worktree(repo, instance, period):
    name = flow.inspection_lane_name(instance, period)
    branch = "%s%s/%s" % (flow.LANE_BRANCH_NS, instance, period)
    path = repo / ".lane" / name
    path.parent.mkdir(exist_ok=True)
    _git(repo, "worktree", "add", "-b", branch, str(path))
    return path, branch


def _sweep(repo, target):
    return aa.sweep_inspection_lanes_impl(
        {"instance_id": INST, "repo_root": str(repo), "keep_period": "", "remove_period": target})


def test_targeted_sweep_clears_the_periods_own_worktree_branch_and_shell(repo):
    wt, br = _make_worktree(repo, INST, P)
    other_shell = repo / ".lane" / flow.inspection_lane_name(INST, P_NEXT)
    other_shell.mkdir(parents=True)
    (other_shell / "keep.txt").write_text("keep", encoding="utf-8")
    other_inst = repo / ".lane" / flow.inspection_lane_name("docs-sync", P)
    other_inst.mkdir(parents=True)

    # 造真正的「当期裸目录壳」：拆掉 worktree 登记但同名目录复活（KI-115 实案形态，
    # 也正是重开实案 t260927-02 撞的那种残留——目录在、git 登记不在）
    _git(repo, "worktree", "remove", "--force", str(wt))
    shell = repo / ".lane" / flow.inspection_lane_name(INST, P)
    shell.mkdir()
    (shell / "leftover.txt").write_text("leftover", encoding="utf-8")

    res = _sweep(repo, P)
    assert res["ok"] is True, res.get("error")
    assert res["result"]["remove_period"] == P
    assert str(shell) in res["result"]["removed_dir_stubs"], "当期裸目录壳必须被收掉"
    assert not shell.exists()
    assert other_shell.is_dir() and (other_shell / "keep.txt").is_file(), \
        "定向模式只清本期：别的期的目录一律不碰"
    assert other_inst.is_dir(), "别的实例的命名空间一律不碰"
    assert br not in _git(repo, "branch", "--list", "--format=%(refname:short)")


def test_targeted_sweep_clears_the_periods_registered_worktree_and_branch(repo):
    wt, br = _make_worktree(repo, INST, P)
    _make_worktree(repo, INST, P_NEXT)          # 次日：不许被本期定向清扫带走
    res = _sweep(repo, P)
    assert str(wt) in res["result"]["removed_worktrees"], "本期登记的 worktree 必须拆掉"
    assert not wt.exists()
    assert br not in _git(repo, "branch", "--list", "--format=%(refname:short)")
    nxt = repo / ".lane" / flow.inspection_lane_name(INST, P_NEXT)
    assert nxt.is_dir(), "别的期的 worktree 不许被本期清扫带走"


def test_targeted_sweep_refuses_a_shell_with_an_embedded_repo(repo):
    """内嵌真仓痕迹（未注册嵌套仓，t260916-20）→ 拒拆点名，绝不静默销毁对象库。"""
    shell = repo / ".lane" / flow.inspection_lane_name(INST, P)
    shell.mkdir(parents=True)
    (shell / ".git").mkdir()
    res = _sweep(repo, P)
    assert shell.is_dir(), "内嵌 .git 目录＝独立仓根，绝不能拆"
    assert any("handle manually" in e for e in res["result"]["errors"]), res["result"]["errors"]
    assert res["ok"] is False, "拒拆必须如实报错（不许假成功）"


def test_sweep_rejects_a_malformed_instance():
    res = aa.sweep_inspection_lanes_impl(
        {"instance_id": "BAD INSTANCE", "repo_root": "/tmp", "keep_period": "",
         "remove_period": P})
    assert res["ok"] is False and "invalid instance id" in res["error"]


# ---------------- ③接线（setup 段的修复分支） ----------------

def test_setup_repair_branch_is_patch_gated_and_uses_target_mode():
    """两条链（报告链/产出链）都要修——同类面全量排查纪律：泳道坐标同一套命名，
    残留形态相同，只修点名的那一条＝另一条照旧结构性搭不起泳道。"""
    src = Path(flow.__file__).read_text("utf-8")
    assert flow.LANE_REPAIR_PATCH_ID in src
    # 修复分支必须在 patch 门内（老 history 重放零新命令——否则 replay 非确定，老票卡死）
    gated = re.findall(r'if not prep\.get\("ok"\) and workflow\.patched\(LANE_REPAIR_PATCH_ID\)',
                       src)
    assert len(gated) == 2, "报告链与产出链各一处修复分支（实得 %d）" % len(gated)
    # 送进活动的必须是纯函数给的定向参数（keep 空 + remove_period=本期），不是水位
    assert 'args=[plan["sweep_args"]]' in src
    assert src.count("lane_residue_repair_plan(prep, inp.instance_id, period, repo_root)") == 2
    # prepare 调用收敛到同一形状的壳（首次 + 修复后重试，history 逐字同形）
    assert src.count("await _prepare_lane_activity(") == 3, \
        "两链各一次首次 prepare + 修复壳内一次重试；直调 prepare_workspace 必须被收敛掉"
    assert "prep_raw: Any = await workflow.execute_activity(\n            prepare_workspace," not in src, \
        "旧的直调形状必须被收敛掉"


# ---------------- ④版本门补门（replay 安全，KI-164） ----------------

def test_suite_teardown_grace_sleep_is_patch_gated():
    """260927 直修（49b157a）加的 120s 宽限等待**当时漏了版本门** ⇒ 走该分支的老
    history 重放非确定（t260927-01 实证：代码要定时器、history 是活动 → 该票任何
    重放面全红；改前 HEAD 同样红）。补门后：老 history 无标记 → 跳过等待（逐字一致），
    新 run 记录标记后照旧等。本锁防退化（谁把门拆了，这条必红）。"""
    src = Path(flow.__file__).read_text("utf-8")
    assert flow.SUITE_TEARDOWN_GRACE_PATCH_ID
    # 唯一一处 sleep(SUITE_TIMEOUT_TEARDOWN_GRACE) 必须在 patched 门内
    uses = re.findall(r"\n(\s*)await workflow\.sleep\(SUITE_TIMEOUT_TEARDOWN_GRACE\)", src)
    assert len(uses) == 1, "宽限等待只应有一处（实得 %d）" % len(uses)
    guarded = re.search(
        r'if workflow\.patched\(SUITE_TEARDOWN_GRACE_PATCH_ID\):\n'
        r'(\s*)await workflow\.sleep\(SUITE_TIMEOUT_TEARDOWN_GRACE\)', src)
    assert guarded, "宽限等待必须在 SUITE_TEARDOWN_GRACE_PATCH_ID 门内"
    # 门两侧都要留痕（「等了/没等」都要能读出来，不许静默）
    assert "without the 120s grace" in src
