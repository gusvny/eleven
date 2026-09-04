#!/usr/bin/env python3
"""sc_dispatch_composition_integrity.py — 恒定知识行×派活契约组合完整性（t260904-03）。

intent（用户旅程视角）：被打回重派的 agent 收到的**完整**指令仍自洽——恒定
知识行与派活契约的既有组合特征（previous_context 注入、前段交接含多行
report、多行 user_request+spec、段专项条款、分工实例、写集在否）正交共存时：
  A. v2 顶层编号合法：从 1 起、无重号、严格递增（**允许跳号**——块 5「前段交接」
     条件渲染而后续编号硬编码占位是引擎既有契约，非本票改动面，不得锚）；
  B. 知识段恰一行且缩进于块 1 内（不占顶层编号位）；
  C. v1 的段专项条款/分工实例/写集在否——不扰动知识段文本（与朴素例逐字节同）。
防的故障面：恒定行插错列表位抢占编号、某分支双写知识行、条款行与知识行
互相吞噬、打回重派路径漏掉新行。
编号合法性守卫自证红绿（重号/乱序样本即红）。

Hermetic：零端口零网络零写盘，不触 3099；cwd=仓库根；秒级。
退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0。

**本场景锚定索引化落地后的契约——t260904-03 implement 段落地前红属预期
（TDD 信号），arbitrate/merge 期必须绿。**
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_dispatch_prompt as lib  # noqa: E402

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


def top_numbers(prompt):
    return [int(n) for n in re.findall(r"^(\d+)\. ", prompt, re.M)]


def numbering_ok(prompt):
    """顶层编号合法性：从 1 起、无重号、严格递增。跳号合法（条件块的既有占位契约）。"""
    nums = top_numbers(prompt)
    if not nums or nums[0] != 1:
        return False, nums
    if len(set(nums)) != len(nums):
        return False, nums
    return nums == sorted(nums), nums


def main():
    print("== A v2 顶层编号合法（从 1 起、无重号、严格递增；跳号=既有占位契约合法）+ 知识段缩进")
    cases = [
        ("v2 打回重派（注入 previous_context）",
         lib.v2_prompt("工单引擎 temporal dispatch 派活重构",
                       prev_ctx="【方案审读打回（第 1 轮）】review comments：\n1. 输入必须检查"),
         True),
        ("v2 前段交接（多行 report）",
         lib.v2_prompt("朴素标题变体",
                       handoffs=[{"stage": "review_plan", "report": "## 做了什么\n审了方案。"},
                                 {"stage": "create_plan", "summary": "方案落定"}]),
         False),
        ("v2 朴素首跑", lib.v2_prompt("朴素标题变体"), False),
    ]
    for label, p, injected in cases:
        okc, nums = numbering_ok(p)
        check(okc, "%s：顶层编号合法（1 起/无重号/递增，实得 %s）" % (label, nums))
        kn = lib.knowledge_lines(p)
        check(len(kn) == 1, "%s：知识段恰一行" % label)
        check(bool(kn) and kn[0][:1] in (" ", "\u3000"),
              "%s：知识段缩进于块 1（不占顶层编号位）" % label)
        check("2. 工单正文" in p, "%s：正文块编号未被扰动" % label)
        if injected:
            check("上次运行上下文" in p, "%s：注入节在位" % label)

    print("== B v1 段专项条款/分工实例/写集变体不扰动知识段")
    plain = lib.knowledge_lines(lib.v1_prompt("朴素标题基线")[0])
    for label, p in [
        ("v1 content-pipeline/ai-review（段专项条款+审校分工）",
         lib.v1_prompt("知识库 review 审校口径", workflow_id="content-pipeline",
                       stage="ai-review", role="proofreader")[0]),
        ("v1 dev-lane/integration_review（验证分工）",
         lib.v1_prompt("工单引擎 temporal dispatch 派活重构", workflow_id="dev-lane",
                       stage="integration_review", role="integration")[0]),
        ("v1 无写集", lib.v1_prompt("朴素标题基线", write_set=[])[0]),
        ("v1 多项写集", lib.v1_prompt("朴素标题基线",
                                  write_set=["a.py", "b.py", "docs/README.md"])[0]),
    ]:
        check(lib.knowledge_lines(p) == plain, "%s：知识段与朴素基线逐字节同" % label)
    p_clause = lib.v1_prompt("知识库 review 审校口径", workflow_id="content-pipeline",
                             stage="ai-review", role="proofread")[0]
    check("段专项条款" in p_clause, "v1 ai-review：段专项条款仍在位（未被知识行吞噬）")

    print("== C 编号合法性守卫自证红绿（重号/乱序样本即红；跳号样本合法）")
    dup_ok, dup_nums = numbering_ok("1. 甲\n1. 乙\n3. 丙")
    check(not dup_ok and dup_nums == [1, 1, 3], "重号样本被守卫捕获（守卫自身有效）")
    dis_ok, dis_nums = numbering_ok("2. 甲\n1. 乙")
    check(not dis_ok and dis_nums == [2, 1], "乱序样本被守卫捕获（守卫自身有效）")
    gap_ok, gap_nums = numbering_ok("1. 甲\n3. 丙\n4. 丁")
    check(gap_ok and gap_nums == [1, 3, 4], "跳号样本不误报（条件块占位=既有契约）")

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
