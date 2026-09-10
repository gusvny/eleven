#!/usr/bin/env python3
"""阶段路径闸·正常面不误伤（t260911-03 验收 c 反例三连，灰盒 L3）。

用户可感知契约：闸只拦越权，不拦正常干活——实现段改写集内文件、设计集成测试
段只改 integration/、仲裁段只改本票场景（tests/ 测试面）＝全部放行且 commit
落地、回执零原因码；仲裁段碰产品代码（宿主 260910 实证另一半）仍拒。

依据：工单验收 c（反例三连全放行）＋「机械闸门检查」不得把正常流堵死的
误伤面。与 notes-write-gate 的「写集内普通文件不误伤」腿 intent 不同面
（本条是 settle 时刻阶段闸的三段正例+仲裁负例，非合并闸 notes 面）。
与 developer L1（judge 矩阵正反例）intent 分工：本条锁真实 settle 链路上
「放行=真 commit 落地」的终态，L1 锁不住接线。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260911-03/tests/sc_pathgate_normal_faces_land.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
实现段落地前闸腿红属预期（TDD 验收门），arbitrate/merge 期必须绿。
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


def mk_lane():
    """tmp 主仓（带本地 git 身份）+ 真注册泳道 worktree → (tmp, main, lane, 分叉sha)。"""
    tmp = Path(tempfile.mkdtemp(prefix="pathgate-s3-"))
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


def committed(repo):
    out = sh("git", "-C", repo, "show", "--name-only", "--format=", "HEAD").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def inject(lane, rel, content="x = 1\n"):
    p = lane / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def main():
    aa = load_engine()
    has_gate = "path_gate" in inspect.signature(aa._settle_worktree_lane).parameters

    def settle(lane, mainrepo, stage, gen=0, write_set=None, base=""):
        if not has_gate:
            return None, "settle 未接闸参数（path_gate 不在签名）——闸未接线，契约未兑现"
        try:
            return aa._settle_worktree_lane(lane, TICKET, stage, gen, repo=mainrepo,
                                            path_gate=True,
                                            write_set=list(write_set or []),
                                            base_ref=str(base)), None
        except Exception as e:  # noqa: BLE001
            return None, "settle 调用异常：%s" % e

    tmp, mainrepo, lane, fork = mk_lane()

    # ---- C1 实现段：写集内文件 → 放行落地 ----
    section("C1 implement 写集内（server/engine/ + integration/）→ 全落地")
    before = head(lane)
    inject(lane, "server/engine/impl.py")
    inject(lane, "integration/t260911-03/tests/sc_reg_helper.py")
    note, err = settle(lane, mainrepo, "implement",
                       write_set=["server/engine/", "integration/"], base=fork)
    if note is not None:
        ok("path_gate_reason" not in note, "写集内放行、回执零原因码")
        ok(head(lane) != before, "commit 落地")
        c = committed(lane)
        ok("server/engine/impl.py" in c and
           "integration/t260911-03/tests/sc_reg_helper.py" in c, "两文件都在 commit 内")
    else:
        ok(False, "C1 驱动失败：%s" % (err or "note 缺失"))

    # ---- C2 设计集成测试段：只改 integration/ → 放行落地 ----
    section("C2 design_integration_tests 只改 integration/ → 落地")
    before = head(lane)
    inject(lane, "integration/t260911-03/tests/sc_new_case.py")
    note, err = settle(lane, mainrepo, "design_integration_tests", gen=1, base=fork)
    if note is not None:
        ok("path_gate_reason" not in note, "integration/ 面放行")
        ok(head(lane) != before and
           "integration/t260911-03/tests/sc_new_case.py" in committed(lane), "落地")
    else:
        ok(False, "C2 驱动失败：%s" % (err or "note 缺失"))

    # ---- C3 仲裁段正腿：只改本票场景（测试面）→ 放行落地 ----
    section("C3 arbitrate 只改本票 tests/ 测试面 → 落地")
    before = head(lane)
    inject(lane, "integration/t260911-03/tests/sc_own_fix.py")
    note, err = settle(lane, mainrepo, "arbitrate", gen=1, base=fork)
    if note is not None:
        ok("path_gate_reason" not in note,
           "tests/ 测试面放行（tests-fault 修测试属设计内）")
        ok(head(lane) != before and
           "integration/t260911-03/tests/sc_own_fix.py" in committed(lane), "落地")
    else:
        ok(False, "C3 驱动失败：%s" % (err or "note 缺失"))

    # ---- C4 仲裁段负腿：碰产品代码 → 拒（260910 实证另一半回归）----
    section("C4 arbitrate 碰产品代码 → 拒+点名（code-fault 只许打回 implement）")
    before = head(lane)
    inject(lane, "server/engine/arbitral_patch.py")
    note, err = settle(lane, mainrepo, "arbitrate", gen=2, base=fork)
    if note is not None:
        ok("path_gate_reason=unauthorized_path" in note, "仲裁段产品代码被拒")
        ok("server/engine/arbitral_patch.py" in note, "点名违规文件")
        ok(head(lane) == before, "0 新 commit")
    else:
        ok(False, "C4 驱动失败：%s" % (err or "note 缺失"))

    print("\nSC sc_pathgate_normal_faces_land pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
