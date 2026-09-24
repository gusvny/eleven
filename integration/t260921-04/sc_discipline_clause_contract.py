#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_discipline_clause_contract.py — developer 段验证纪律的派活文案契约（t260921-04）。

intent（守护的用户可感知契约，宿主令 260921 要求①④文案侧）：
dev-lane 两个 developer agent 段（create_plan/implement）的派活契约文本必须同批携带——
  A. 禁跑语义锚（集成禁跑）+ 五类集成入口点名（run_scenarios.py、sc_ 场景脚本、
     integration/baselines 基线、with_stage.sh 包装器、verify_lane 验收脚本）；
  B. 受影响面单测正道（pytest + integration/lint_tests.py）与只读放行语义——
     文案是人话+可执行（含可执行命令形态），不是一句口号；
  C. 集成验证归属段（run_integration_tests 闸）与违规后果（红+票面点名）；
  D. 角色面对称（防单边，宿主要求④）：其余 agent 段（review_plan/
     design_integration_tests/arbitrate/acceptance_walkthrough）的契约文本**不**
     携带禁跑语义与集成执行器点名——执法与文案都只对 developer 段。

锚派活契约文本的语义词/稳定文件名，不锚全句（KI-051 纪律：锚语义优先）。
与 developer L1 口径同步测试（方案 S3，断言文案含入口表渲染产物字面）intent
不同面：本场景守公开派活契约面 + 他段负向对称（「机械判了但文案没说/文案禁了
但机械不判」单边态的文案半边，及越段执法文案的反向误伤）。

Hermetic：零端口零网络零写盘，不触 3099；cwd=仓库根；秒级。
退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0；
引擎模块不可导入（temporalio 缺失且无 venv 回落）= ENV_FAIL exit 2。

**本场景锚定 t260921-04 implement 段落地后的契约——落地前红属预期（TDD 信号），
run_integration_tests 期必须绿。**
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _ensure_venv_python() -> None:
    """dev_lane 模块级 import temporalio——系统 python3 缺依赖时回落引擎 venv
    （verify.yaml test check 同款回落链；已在 venv 内则原样继续）。"""
    if os.environ.get("_T260921_04_REEXEC") == "1":
        return
    for cand in (REPO / "server/engine/.venv/bin/python",
                 REPO / "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat（t260907-10 旧路径一轮回落，摘除票删；与 verify.yaml test check 同款）
        if cand.is_file():
            try:
                same = Path(sys.executable).resolve() == cand.resolve()
            except OSError:
                same = False
            if not same:
                env = dict(os.environ)
                env["_T260921_04_REEXEC"] = "1"
                os.execve(str(cand), [str(cand), "-B", os.path.abspath(__file__)], env)
            return


_ensure_venv_python()
sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    import dev_lane  # noqa: E402  （FLOW_BRIEF=派活契约文本真源）
except Exception as e:  # pragma: no cover - 环境缺依赖路径
    print("ENV_FAIL: 引擎模块不可导入（temporalio 缺失？）：%s: %s" % (type(e).__name__, e))
    sys.exit(2)

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)
    return cond


DEV_STAGES = ("create_plan", "implement")
OTHER_AGENT_STAGES = ("review_plan", "design_integration_tests", "arbitrate",
                      "acceptance_walkthrough")
ENTRY_ANCHORS = ("run_scenarios.py", "sc_", "integration/baselines",
                 "with_stage.sh", "verify_lane")


def main():
    briefs = dev_lane.FLOW_BRIEF

    print("== A developer 两段契约文本携禁跑语义+五类入口点名")
    for stage in DEV_STAGES:
        text = briefs.get(stage) or ""
        check("集成禁跑" in text, "A/%s 禁跑语义锚（集成禁跑）在场" % stage)
        missing = [a for a in ENTRY_ANCHORS if a not in text]
        check(not missing, "A/%s 五类集成入口点名齐（缺=%s）" % (stage, missing or "无"))

    print("== B 单测正道+只读放行+归属段+点名后果（人话+可执行非口号）")
    for stage in DEV_STAGES:
        text = briefs.get(stage) or ""
        for anchor in ("pytest", "lint_tests.py", "只读", "run_integration_tests",
                       "点名", "python3 "):
            check(anchor in text, "B/%s 锚「%s」在场" % (stage, anchor))

    print("== C 其余 agent 段不携执法文案（角色面对称，防越段执法）")
    for stage in OTHER_AGENT_STAGES:
        text = briefs.get(stage) or ""
        # 前提修订（t260924-09 必做①，仲裁段裁定=契约演进非弱化）：走查/仲裁段
        # 派活文案现在**必须**点名集成执行器——但只许「定点复跑取证纪律」形态
        # （--only 定点 / 闸口径 --exclude-pools），不许出现 developer 型「集成禁跑」
        # 执法语义。执法缺席与取证形态齐备两侧都断言，堵「借演进之名整体卸锁」。
        check("集成禁跑" not in text,
              "C/%s 无禁跑执法语义（该段本职含集成取证面，禁跑执法不得越段）" % stage)
        if "run_scenarios.py" in text:
            check("--only" in text,
                  "C/%s 执行器点名=定点复跑纪律形态（--only 在场）" % stage)

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
