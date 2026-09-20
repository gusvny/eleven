#!/usr/bin/env python3
"""阶段路径闸·零代码改动段拒绝落盘（t260911-03 验收 a，灰盒 L3，宿主令 260910）。

用户可感知契约：做方案/审方案/验收走查＝零代码改动段，注入产品代码改动后
worker 代落盘（settle）必须拒绝——不 commit、工作区原样保留（agent 产物不丢）、
拒绝回执点名「段 X 不允许改 Y」且带机读原因码 path_gate_reason=unauthorized_path；
仅 .sandbar/ 结果文件则照常落盘（闸不误伤结果文件面）。

契约修订注记（t260916-19 B）：越权件 ??（未跟踪新建）/M（tracked 修改）两态改自动处置
（挪档/回滚留档）后复判，不再产生终态拒绝——拒绝终态只保留在删除型（D）/暂存型/
protected 上。本场景越权子用例相应改用删除型注入（A1/A2 泳道内删除 tracked 产品文件），
「拒绝+0 commit+点名+工作区原样保留」断言面在新旧契约下同形；??/M 处置旅程守卫归
t260916-19 场景（t26091619-unauth-disposal-matrix）。

依据：工单验收 a（走查段改产品代码→拒绝落盘+点名）＋宿主 260910 明令
「凡事不应该有代码变化的阶段，不允许改代码」。与 notes-write-gate（notes 禁写
合并闸面）、ki044 patch 门（merge 面）、t260904-18 背景文件闸（建单面）intent
不同面：本条执法点=settle 落盘时刻的阶段路径白名单。
与 developer L1（judge 纯函数矩阵）intent 分工：本条只锁真实 settle 链路的
终态三件套（0 新 commit+点名+原因码），L1 锁不住接线与回执传播。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260911-03/tests/sc_pathgate_walkthrough_reject.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
实现段落地前闸子用例红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
import inspect
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TICKET = "t260911-03"

_ok = _fail = 0


def ok(cond, label):
    global _ok, _fail
    print(("  ok " if cond else "  FAIL ") + label)
    _ok, _fail = _ok + (1 if cond else 0), _fail + (0 if cond else 1)


def section(t):
    print("\n== " + t)


def sh(*cmd, cwd=None):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None)


def load_engine():
    if shutil.which("git") is None:
        print("ENV_FAIL: git 不可用（本场景全程真 git 仓）")
        sys.exit(2)
    try:
        import temporalio  # noqa: F401
    except Exception:
        print("ENV_FAIL: temporalio 不可导入——用 server/engine/.venv/bin/python 跑"
              "（KI-036 口径：缺环境点名，环境红非产品红）")
        sys.exit(2)
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import agent_activities
    return agent_activities


# 泳道分叉点基线文件（受保护名单/测试面/写集的真实相对路径形态）
BASE = {
    "verify.yaml": "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/engine/\n      - integration/\n    checks: []\n",
    "server/engine/keep.py": "# engine anchor\n",
    # t260916-19 B 起 ??/M 态越权改自动处置（挪档/回滚留档）不再终态拒绝——
    # 本场景越权子用例改用删除型（D 态）注入以保持「拒绝+保留」终态的可测性，
    # 故产品代码越权件先落分叉点基线（tracked），A1/A2 在泳道内删除。
    "server/engine/feature.py": "x = 0\n",
    "server/engine/feature2.py": "y = 0\n",
    "docs/design/contract-v1.md": "# contract v1\n",
    "integration/baselines/sc_battery.py": "# shared battery\n",
    "integration/t260902-07/tests/test_route_table.py": "# shared guard\n",
    "integration/t260911-03/tests/.keep": "",
}


def mk_lane():
    """tmp 主仓（带本地 git 身份）+ 真注册泳道 worktree → (tmp, main, lane, 分叉sha)。"""
    tmp = Path(tempfile.mkdtemp(prefix="pathgate-s1-"))
    main = tmp / "main"
    main.mkdir()
    for rel, content in BASE.items():
        p = main / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    sh("git", "init", "-q", "-b", "main", cwd=main)
    sh("git", "config", "user.email", "t@t", cwd=main)
    sh("git", "config", "user.name", "t", cwd=main)
    sh("git", "add", "-A", cwd=main)
    sh("git", "commit", "-qm", "init", cwd=main)
    fork = head(main)
    lane = tmp / "lane"
    r = sh("git", "-C", main, "worktree", "add", "-q", "-b", "lane/" + TICKET, lane)
    assert r.returncode == 0, "worktree add 失败: %s" % r.stderr
    return tmp, main, lane, fork


def head(repo):
    return sh("git", "-C", repo, "rev-parse", "HEAD").stdout.strip()


def dirty(repo):
    out = sh("git", "-C", repo, "status", "--porcelain").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def main():
    aa = load_engine()
    sig = inspect.signature(aa._settle_worktree_lane)
    has_gate = "path_gate" in sig.parameters
    has_face = "face" in sig.parameters

    def settle(lane, mainrepo, stage, gen=0, gate=True, write_set=None, base=""):
        kwargs = {"repo": mainrepo}
        if gate:
            if not has_gate:
                return None, "settle 未接闸参数（path_gate 不在签名）——闸未接线，契约未兑现"
            kwargs.update(path_gate=True, write_set=list(write_set or []),
                          base_ref=str(base))
            if has_face:
                kwargs.update(face="join")  # t260916-19 D：settle 分层标签（本场景模拟 join 点收口）
        try:
            return aa._settle_worktree_lane(lane, TICKET, stage, gen, **kwargs), None
        except Exception as e:  # noqa: BLE001 — 场景层任何异常都算该子用例红
            return None, "settle 调用异常：%s" % e

    # ---- A1 验收走查段注入产品代码改动 → 拒绝落盘（验收 a 正例）----
    section("A1 acceptance_walkthrough 注入产品代码 → 拒+点名+0 commit")
    tmp, mainrepo, lane, fork = mk_lane()
    inject = "server/engine/feature.py"
    (lane / inject).unlink()  # 删除型注入（D 态）：拒绝终态在新旧契约下都成立（t260916-19 B）
    (lane / ".sandbar").mkdir(exist_ok=True)
    (lane / ".sandbar" / "stage_acceptance_walkthrough_gen0.json").write_text(
        '{"status":"ok"}\n', encoding="utf-8")
    before = head(lane)
    note, err = settle(lane, mainrepo, "acceptance_walkthrough", base=fork)
    if err is None and note is not None:
        ok("path_gate_reason=unauthorized_path" in note,
           "机读原因码 unauthorized_path 在回执")
        ok("acceptance_walkthrough" in note, "点名段 id（段 X 不允许改 Y 口径）")
        ok(inject in note, "点名违规文件 %s" % inject)
        ok(head(lane) == before, "0 新 commit（拒绝落盘）")
        ok(any(inject in ln for ln in dirty(lane)), "工作区原样保留（agent 产物不丢）")
    else:
        ok(False, "A1 驱动失败：%s" % (err or "note 缺失"))

    # ---- A2 审方案段同拒（review_plan 键真实命中，R1 正例面）----
    section("A2 review_plan 注入产品代码 → 拒")
    inject2 = "server/engine/feature2.py"
    (lane / inject2).unlink()  # 同 A1：删除型注入（t260916-19 B 契约修订）
    note, err = settle(lane, mainrepo, "review_plan", gen=1, base=fork)
    if note is not None:
        ok("path_gate_reason=unauthorized_path" in note and "review_plan" in note,
           "review_plan 段拒绝且回执带段 id")
        ok(head(lane) == before, "仍 0 新 commit")
    else:
        ok(False, "A2 驱动失败：%s" % (err or "note 缺失"))

    # ---- A3 对照子用例：仅 .sandbar/ 结果文件 → settle 零动作、零拒绝 ----
    # （结果文件被 SETTLE_PATHSPEC 排除、从不进 commit——「放行」的真实形状=
    #   回执零原因码+结果文件原样保留+历史零扰动，并非产生新 commit。）
    section("A3 仅 .sandbar/ 结果文件 → 零动作不误伤")
    tmp2, main2, lane2, fork2 = mk_lane()
    (lane2 / ".sandbar").mkdir()
    (lane2 / ".sandbar" / "stage_review_plan_gen0.json").write_text(
        '{"status":"ok"}\n', encoding="utf-8")
    before2 = head(lane2)
    note, err = settle(lane2, main2, "review_plan", base=fork2)
    if note is not None:
        ok("path_gate_reason" not in note, "回执零原因码（结果文件面不被拒）")
        ok((lane2 / ".sandbar" / "stage_review_plan_gen0.json").is_file(),
           "结果文件原样保留（agent 产物不丢）")
        ok(head(lane2) == before2, "历史零扰动（结果文件不进 commit=既定口径）")
    else:
        ok(False, "A3 驱动失败：%s" % (err or "note 缺失"))

    print("\nSC sc_pathgate_walkthrough_reject pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
