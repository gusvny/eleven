#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-19 场景②：dengzhufpv t260916-11 实案形态重演（灰盒 L2，真 git 夹具，无 docker 无 Temporal）。

intent（守护的用户可感知行为/契约，工单修向 C＝声明=执法 + B/M 态解除）：
- **实案工作区同批形态一次收口**：仲裁段（arbitrate，join 点 settle_lane，实案同一入口）工作区
  同时含——顶层 integration/sc_*.py 新建（agent 自救场景）＋ integration/README.md 修改（登记表）
  ＋ integration/lint_tests.py tracked 修改（共享工具，实案第二轮「自救」件）。修复后断言：
  顶层场景与登记表合法落盘（C 的用户可感知面：仲裁改顶层场景/登记不再被拦），
  lint_tests.py 回基线且修改以 diff 留档可还原（B/M 态：分支零删除、agent 修改零丢失），
  代落盘内容恰为两个合法件；
- **C 的边界不外溢**：integration/lint_tests.py 是共享工具不是测试面——删除型（D 态）触碰仍拒
  （合法出路=rework 打回 design_integration_tests 或建票写集列名，修向 C③ 的边界钉死）。

与相邻场景 intent 分界（防 intent 级重复）：
- sc_t26091619_disposal_matrix（本票场景①）：彼分态逐态锁处置矩阵终态（含 judged_files
  证据面），本条锁**实案混合形态的一次收口闭环与 C 合法化旅程**，混合形态本身（三件同批、
  两合法一越权）不在彼断言面；
- t260911-03-normal-faces-land：彼守「正常面放行=commit 落地」的反例三连（实现段/设计段/本票
  tests 面），本条守修复后**实案特定形态**（顶层 sc+README+共享工具 M 态），彼反用例=产品代码
  面已随 t260916-19 改删除型，与本条 lint_tests.py 面（C 边界反用例）不同路径不同因；
- sc_check_auto_rework_trace（顶层源码锁）：彼锁 PHASE_MAIN_CHAIN 常量形状（A 的词表纪律），
  本条零源码解析、全行为面。

与 developer L1（声明=执法枚举矩阵 UT）分工：L1 逐路径点判 judge 函数与 note 措辞，本条锁
**真实 settle 链路**上「合法化=真落盘、边界=真拒绝」的终态——L1 锁不住接线与 commit 内容。

故障面清单（覆盖对应用例）：
① 混合形态一次收口（实案死结的解除面：不再 blocked 空转）→ I1-I7；
② 顶层场景/登记表合法化不误伤共享工具（C 的面边界）→ I4/I5 vs II；
③ M 态共享工具回滚后分支零删除（防「隔离变删除」外漏险）→ I5；
④ 留档可还原（agent 自救产物零丢失，闸与 agent 不再「互相激发」）→ I6；
⑤ 代落盘内容恰为合法清单（越权件零入库）→ I7。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260916-19/sc_t26091619_incident_replay.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST），
# 本场景全程零 Temporal 连接。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t260916_19 import (  # noqa: E402
    check, env_fail, summary, mk_lane, rmtree, head_sha, head_count,
    committed_names, read_file, apply_check, engine_modules, settle,
    quarantine_root,
)

TID = "t26091619b"
LINT = "integration/lint_tests.py"


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——直调 activity 无 stdlib 替代子用例" % why)
    shared, aa = mods

    # ---- I 实案形态：顶层 sc 新建＋README 修改（C 后合法）＋lint_tests.py 修改（M 态越权）----
    print("\n== I 实案形态一次收口：合法化两件落盘、共享工具回基线留档")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-i1-")
    lint_baseline = read_file(mainrepo, LINT)
    (lane / "integration" / "sc_selfrescue.py").write_text(
        "# agent self-rescue scenario\nprint('sc')\n", encoding="utf-8")
    (lane / "integration" / "README.md").write_text(
        "# scenario registry baseline\n(t26091619) new entry\n", encoding="utf-8")
    (lane / LINT).write_text("# shared lint tool baseline\n# agent hotfix\n",
                             encoding="utf-8")
    n0 = head_count(lane)
    r1 = settle(shared, aa, lane, TID, "arbitrate", 3, fork)
    note1 = r1.note or ""
    qroot = quarantine_root(lane, shared)
    lint_diffs = [p for p in qroot.rglob("*.diff") if p.is_file()
                  and LINT in p.read_text(encoding="utf-8", errors="replace")] \
        if qroot.is_dir() else []
    check("I1 一次收口无终态拒绝（死结解除：不再 blocked 空转）",
          "path_gate_reason=" not in note1, "note=%r" % note1[:200])
    check("I2 顶层自救场景合法落盘（C：仲裁改顶层 sc_*.py 不再被拦）",
          (lane / "integration" / "sc_selfrescue.py").is_file(),
          "missing after settle")
    check("I3 登记表修改合法落盘（C：仲裁修 README 登记是本职）",
          (lane / "integration" / "README.md").read_text(encoding="utf-8").endswith(
              "(t26091619) new entry\n"), "content drifted")
    check("I4 共享工具回基线（B/M 态回滚：分支零删除、越权修改不落盘）",
          read_file(lane, LINT) == lint_baseline,
          "now=%r" % read_file(lane, LINT))
    check("I5 留档 diff 在档且可 git apply 还原（agent 自救产物零丢失）",
          bool(lint_diffs) and apply_check(lane, lint_diffs[0].read_text(
              encoding="utf-8"))[0],
          "diffs=%r" % [p.name for p in lint_diffs])
    check("I6 代落盘内容恰为两个合法件（越权件与其留档件零入库）",
          head_count(lane) == n0 + 1
          and committed_names(lane) == ["integration/README.md",
                                        "integration/sc_selfrescue.py"],
          "committed=%r" % committed_names(lane))
    check("I7 回执点名共享工具处置（去向可追溯，闸与 agent 不再互相激发）",
          LINT in note1, "note=%r" % note1[:200])
    after_i = head_count(lane)

    # ---- II C 边界反用例：共享工具删除型（D 态）仍拒（C 有意不放行 lint_tests.py）----
    print("\n== II C 边界：共享工具删除型仍拒（合法出路在打回/写集，不在仲裁段）")
    (lane / LINT).unlink()
    r2 = settle(shared, aa, lane, TID, "arbitrate", 4, fork)
    note2 = r2.note or ""
    gref2 = r2.gate_refusal if isinstance(r2.gate_refusal, dict) else {}
    check("II1 删除型共享工具仍拒（C 边界：lint_tests.py 不因顶层放宽被连带放行）",
          "path_gate_reason=" in note2, "note=%r" % note2[:200])
    check("II2 点名违规路径", LINT in note2 and (gref2.get("files") == [LINT]),
          "note=%r files=%r" % (note2[:160], gref2.get("files")))
    check("II3 零新 commit 且删除态原样保留（人处前提）",
          head_count(lane) == after_i and read_file(lane, LINT) is None,
          "count=%s exists=%r" % (head_count(lane), read_file(lane, LINT) is not None))
    rmtree(tmp)

    return summary()


if __name__ == "__main__":
    sys.exit(main())
