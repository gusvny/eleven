#!/usr/bin/env python3
"""双闸兼容面·老票零破 + 未知段 fail-closed（t260911-03 验收 d＋R1②闭环，灰盒 L3）。

用户可感知契约：
  d 老在途票兼容——不传闸参数（老调用形状=path_gate 缺省 False，等价存量序列化
    事件缺字段）时，任何段的行为与装闸前逐字节一致：产品代码照常落盘（老票按
    patch 门保护，不追溯）；显式 path_gate=False 同样全放行。D1 子用例实现落地前
    即应绿（现状行为基线，兼当本套 fixture 机械证明）。
  R1② 未知段 fail-closed——path_gate=True 而段 id 不在规则表＝拒绝落盘+
    path_gate_reason=unknown_stage+出路文案（合法出路前缀在场），绝不静默放行
    （新段忘配规则=被堵出来，不是自动免检）。

依据：工单验收 d（老票 replay/兼容零破）＋工单规格③（判定走单点、兼容不追溯）
＋review_plan R1②（fallback fail-closed 裁决）。
与 developer L1（judge 未知段/缺省矩阵）intent 分工：本条锁真实 settle 单点上
「参数缺省=闸不存在」的老票承诺与未知段拒绝的回执终态。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260911-03/tests/sc_pathgate_legacy_compat.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
D1 现状即绿；D2/D3 实现段落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
import atexit
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
    tmp = Path(tempfile.mkdtemp(prefix="pathgate-s4-"))
    # 260926 磁盘泄漏修（同类普查）：本夹具此前从不回收——$TMPDIR 实测 `pathgate-*`
    # 攒了 5449 个 / 约 171MB。atexit 覆盖正常/异常/早退所有终态（含断言失败直接 sys.exit）。
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
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


def inject(lane, rel, content="x = 1\n"):
    p = lane / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def main():
    aa = load_engine()
    sig = inspect.signature(aa._settle_worktree_lane).parameters
    has_gate = "path_gate" in sig
    has_face = "face" in sig  # t260916-19 D：face 必填分层标签——新老树两侧可跑

    # ---- D1 老票闸关（老调用形状，缺省不传闸参数）→ 行为零变化 ----
    section("D1 老调用形状（无闸参数）走查段改产品代码 → 照常落盘（现状基线）")
    tmp, mainrepo, lane, _fork = mk_lane()
    before = head(lane)
    inject(lane, "server/engine/legacy_change.py")
    try:
        d1kw = {"repo": mainrepo}
        if has_face:
            d1kw["face"] = "join"  # 「老形状」锁的是闸参数缺省语义，非标签形参
        note = aa._settle_worktree_lane(lane, TICKET, "acceptance_walkthrough", 0,
                                        **d1kw)
    except Exception as e:  # noqa: BLE001
        ok(False, "D1 子用例异常（fixture 机械面破）：%s" % e)
    else:
        ok(note is not None and "path_gate_reason" not in note,
           "老票零干扰、回执零原因码")
        ok(head(lane) != before, "老票照常 commit（patch 门保护，不追溯）")

    # ---- D2 显式 path_gate=False → 同样全放行 ----
    section("D2 显式 path_gate=False → 全放行（开关语义）")
    if has_gate:
        before = head(lane)
        inject(lane, "server/engine/flag_off_change.py")
        try:
            note = aa._settle_worktree_lane(lane, TICKET, "acceptance_walkthrough", 1,
                                            repo=mainrepo, path_gate=False,
                                            write_set=[],
                                            **({"face": "join"} if has_face else {}))
        except Exception as e:  # noqa: BLE001
            note = None
            ok(False, "D2 子用例异常：%s" % e)
        ok(note is not None and "path_gate_reason" not in note and head(lane) != before,
           "开关关=闸不存在，commit 落地")
    else:
        ok(False, "settle 无 path_gate 参数——闸未接线，开关语义不可验（契约未兑现）")

    # ---- D3 未知段 fail-closed：键不在规则表 → 拒+unknown_stage+出路 ----
    section("D3 path_gate=True 未知段 → 拒+unknown_stage（绝不静默放行）")
    if has_gate:
        tmp2, main2, lane2, fork2 = mk_lane()
        before2 = head(lane2)
        inject(lane2, "server/engine/future_feature.py")
        try:
            d3kw = dict(repo=main2, path_gate=True,
                        write_set=["server/engine/"], base_ref=str(fork2))
            if has_face:
                d3kw["face"] = "join"
            note = aa._settle_worktree_lane(lane2, TICKET, "brand_new_stage", 0,
                                            **d3kw)
        except Exception as e:  # noqa: BLE001
            note = None
            ok(False, "D3 子用例异常：%s" % e)
        if note is not None:
            ok("path_gate_reason=unknown_stage" in note, "未知段拒绝+机读原因码")
            ok("sanctioned way out" in note, "出路文案在场（sanctioned way out 前缀）")
            ok(head(lane2) == before2, "0 新 commit")
        else:
            ok(False, "D3 驱动失败：settle 未返回拒绝 note")
    else:
        ok(False, "settle 无 path_gate 参数——未知段 fail-closed 不可验（契约未兑现）")

    print("\nSC sc_pathgate_legacy_compat pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
