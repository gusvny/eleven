#!/usr/bin/env python3
"""受保护路径闸·真源与期望值文件（t260911-03 验收 b，灰盒 L3，260910 两实证回归）。

用户可感知契约：任何泳道任何段改「真源与期望值文件」（共享守卫脚本、共享电池、
配置真源、契约文档、闸自身）＝settle 拒绝落盘，回执带机读原因码
path_gate_reason=protected_path 与点名文件——即使该文件在**阶段面内**
（设计集成测试段的 integration/、仲裁段的测试面），双闸独立执法。
「存在才拦」语义钉死（分叉点 base）：闸自身出生轮放行、本票同泳道 rework 轮
放行（防每轮人审死锁）、落地 main 后新分叉泳道改它＝拦（改共享守卫须 main 侧走票）。

依据：工单验收 b＋宿主 260910 实证①（t260910-06/08 仲裁段改共享守卫
test_route_table 期望值＝各自给自己发免红令）。与 notes-write-gate（notes 面）、
ki044 写集 patch 门（merge 面）intent 不同面：本条执法点=settle 时刻的受保护
名单，事故两半（仲裁改守卫/共享电池改动）在此回归。
与 developer L1（judge 纯函数名单正反例）intent 分工：本条锁真实链路+
分叉点语义的终态，L1 锁不住 base 取值与出生悖论。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260911-03/tests/sc_pathgate_protected_reject.py（cwd=仓根）
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


BASE = {
    "verify.yaml": "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/engine/\n      - integration/\n    checks: []\n",
    "server/engine/keep.py": "# engine anchor\n",
    "docs/design/contract-v1.md": "# contract v1\n",
    "integration/baselines/sc_battery.py": "# shared battery\n",
    "integration/t260902-07/tests/test_route_table.py": "# shared guard\n",
    "integration/t260911-03/tests/.keep": "",
}


def mk_lane(tmp_prefix):
    """tmp 主仓（带本地 git 身份）+ 真注册泳道 worktree → (tmp, main, lane, 分叉sha)。"""
    tmp = Path(tempfile.mkdtemp(prefix=tmp_prefix))
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


def main():
    aa = load_engine()
    sig = inspect.signature(aa._settle_worktree_lane).parameters
    has_gate = "path_gate" in sig
    has_face = "face" in sig  # t260916-19 D：face 必填分层标签（新树）——新老树两侧可跑

    def settle(lane, mainrepo, stage, gen=0, write_set=None, base=""):
        if not has_gate:
            return None, "settle 未接闸参数（path_gate 不在签名）——闸未接线，契约未兑现"
        try:
            kw = dict(repo=mainrepo, path_gate=True,
                      write_set=list(write_set or []), base_ref=str(base))
            if has_face:
                kw["face"] = "join"  # 本场景模拟 join 点收口
            return aa._settle_worktree_lane(lane, TICKET, stage, gen, **kw), None
        except Exception as e:  # noqa: BLE001
            return None, "settle 调用异常：%s" % e

    # ---- B1 共享电池（阶段面内！设计集成测试段允许 integration/）→ 受保护闸拦 ----
    section("B1 design_integration_tests 改共享电池 → protected_path（双闸独立性）")
    tmp, mainrepo, lane, fork = mk_lane("pathgate-s2a-")
    battery = "integration/baselines/sc_battery.py"
    (lane / battery).write_text("# tampered expectation\n", encoding="utf-8")
    before = head(lane)
    note, err = settle(lane, mainrepo, "design_integration_tests", base=fork)
    if note is not None:
        ok("path_gate_reason=protected_path" in note, "受保护原因码在回执")
        ok("unauthorized_path" not in note, "阶段面内→非越权码（双闸独立执法的证明）")
        ok(battery in note, "点名文件 %s" % battery)
        ok(head(lane) == before, "0 新 commit")
    else:
        ok(False, "B1 驱动失败：%s" % (err or "note 缺失"))

    # ---- B2 事故重放：仲裁段改共享守卫期望值（260910 实证①）----
    # 干净泳道单脏文件（B1 的 battery 编辑会以 unauthorized_path 先拒、屏蔽受保护
    # 闸的裁定——两闸串行 surface，本子用例只验受保护闸，故独立 fixture）。
    section("B2 arbitrate 改共享守卫 test_route_table → 拒（测试面内，受保护闸拦）")
    tmpB, mainB, laneB, forkB = mk_lane("pathgate-s2c-")
    guard = "integration/t260902-07/tests/test_route_table.py"
    (laneB / guard).write_text("EXPECT = 'my own green'\n", encoding="utf-8")
    beforeB = head(laneB)
    note, err = settle(laneB, mainB, "arbitrate", gen=1, base=forkB)
    if note is not None:
        ok("path_gate_reason=protected_path" in note, "仲裁段改共享守卫被拒")
        ok(guard in note, "点名共享守卫文件")
        ok(head(laneB) == beforeB, "0 新 commit（免红令作废）")
    else:
        ok(False, "B2 驱动失败：%s" % (err or "note 缺失"))

    # ---- B3a 出生语义：implement 新建 path_gates.py → 放行 ----
    section("B3a implement 新建闸自身 → 出生放行")
    tmp2, main2, lane2, fork2 = mk_lane("pathgate-s2b-")
    gatefile = "server/engine/path_gates.py"
    before2 = head(lane2)
    (lane2 / gatefile).write_text("# the gate itself\n", encoding="utf-8")
    note, err = settle(lane2, main2, "implement", write_set=["server/engine/"],
                       base=fork2)
    if note is not None:
        ok("path_gate_reason" not in note, "新建（base 不存在）放行")
        ok(head(lane2) != before2, "出生 commit 落地")
    else:
        ok(False, "B3a 驱动失败：%s" % (err or "note 缺失"))

    # ---- B3b 分叉点语义：本票同泳道 rework 轮再改 → 放行（防每轮人审死锁）----
    section("B3b 同泳道 rework 再改闸自身 → 放行（base=分叉点，非 HEAD）")
    (lane2 / gatefile).write_text("# the gate itself v2\n", encoding="utf-8")
    mid = head(lane2)
    note, err = settle(lane2, main2, "implement", gen=1,
                       write_set=["server/engine/"], base=fork2)
    if note is not None:
        ok("path_gate_reason" not in note, "同泳道再改放行（base_ref 语义）")
        ok(head(lane2) != mid, "rework 轮提交推进")
        r = sh("git", "-C", lane2, "show", "--name-only", "--format=", "HEAD")
        ok(gatefile in r.stdout.splitlines(), "第二次改动已落盘")
    else:
        ok(False, "B3b 驱动失败：%s" % (err or "note 缺失"))

    # ---- B3c 落地 main 后新分叉泳道改闸自身 → 拦（自保护生效）----
    section("B3c 落地后新泳道改闸自身 → protected_path（改共享守卫须 main 侧走票）")
    sh("git", "-C", main2, "merge", "-q", "--no-edit", "lane/" + TICKET)
    fork3 = head(main2)
    lane3 = tmp2 / "lane3"
    r = sh("git", "-C", main2, "worktree", "add", "-q", "-b", "lane/" + TICKET + "-b", lane3)
    assert r.returncode == 0, "第二个 worktree 失败: %s" % r.stderr
    (lane3 / gatefile).write_text("# tampered rule table\n", encoding="utf-8")
    before3 = head(lane3)
    note, err = settle(lane3, main2, "implement", write_set=["server/engine/"],
                       base=fork3)
    if note is not None:
        ok("path_gate_reason=protected_path" in note, "落地后受保护，改它被拒")
        ok(head(lane3) == before3, "0 新 commit")
    else:
        ok(False, "B3c 驱动失败：%s" % (err or "note 缺失"))

    print("\nSC sc_pathgate_protected_reject pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
