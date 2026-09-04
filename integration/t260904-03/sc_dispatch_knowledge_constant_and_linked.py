#!/usr/bin/env python3
"""sc_dispatch_knowledge_constant_and_linked.py — 派活头知识段恒定 + 死链归零（t260904-03）。

intent（守护的用户可感知契约，KI-035 宿主拍板=索引化）：任何工单、任何标题、
任何 workflow、任何段形态（含打回重派/段专项条款/分工实例/畸形输入）下，
两条派活组装路径（v1 dispatch 头 / v2 dispatch-next）的知识段——
  A. 恰有一行（无缺失、无双写）；
  B. 全电池逐字节同一（不随票面相关性膨胀——「60-80k token/票、与票面相关性
     无关的重复消耗」的根除面）；
  C. 含目录锚 docs/README.md（「知识库目录=docs/README.md」的落地形态）；
  D. prompt 内提及的一切 docs/*.md|json 路径落盘存在——旧表「掌握→掌握模型设计.md、
     content-pipeline→平台架构设计.md」留守 suyou 断链形态的根除守护。
扫描器自证红绿（合成样本注入即红——guard the guard）。

锚公开渲染契约不锚实现：文案重构/前缀编号演进不改契约则本场景不红。
Hermetic：零端口零网络零写盘，不触 3099；cwd=仓库根；秒级。
退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0。

**本场景锚定索引化落地后的契约——t260904-03 implement 段落地前红属预期
（TDD 信号），arbitrate/merge 期必须绿。**
"""
from __future__ import annotations

import os
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


def main():
    v1 = lib.v1_battery()
    v2 = lib.v2_battery()

    print("== A 知识段恰一行（两条路径全电池，缺失/双写都算红）")
    bad = []
    for label, p in v1 + v2:
        kn = lib.knowledge_lines(p)
        if len(kn) != 1:
            bad.append("%s（知识段行数=%d）" % (label, len(kn)))
    check(not bad, "全电池 %d 例知识段恰一行%s" % (len(v1) + len(v2),
                                        ("；异常：" + "; ".join(bad[:4])) if bad else ""))

    print("== B 知识段逐字节恒定（不随票面/workflow/段形态变化）")
    v1_kn = {lib.knowledge_lines(p)[0] for _, p in v1 if lib.knowledge_lines(p)}
    v2_kn = {lib.knowledge_lines(p)[0] for _, p in v2 if lib.knowledge_lines(p)}
    check(len(v1_kn) == 1, "v1 全电池知识段唯一（实得 %d 种）" % len(v1_kn))
    check(len(v2_kn) == 1, "v2 全电池知识段唯一（实得 %d 种）" % len(v2_kn))

    print("== C 目录锚在位（docs/README.md）")
    for name, kns in (("v1", v1_kn), ("v2", v2_kn)):
        check(all("docs/README.md" in k for k in kns) and bool(kns),
              "%s 知识段含目录锚 docs/README.md" % name)

    print("== D 死链归零（prompt 内提及的一切 docs 路径落盘存在）")
    missing = []
    for label, p in v1 + v2:
        for dp in lib.docs_paths(p):
            if not (lib.REPO / dp).exists():
                missing.append("%s → %s" % (label, dp))
    check(not missing, "全电池零死链%s" % (("；死链：" + "; ".join(missing[:6])) if missing else ""))

    print("== E 扫描器自证红绿（合成样本注入即红）")
    check(len(lib.knowledge_lines("   ③ 知识库：甲\n   ② 知识库：乙")) == 2,
          "知识段抽取器对双写样本报 2 行（守卫自身有效）")
    check(not (lib.REPO / "docs/design/并不存在档.md").exists(),
          "死链探针对虚构路径判缺失（守卫自身有效）")

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
