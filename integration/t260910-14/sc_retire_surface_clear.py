#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-14 场景④：suggest_next / epic-next 退役面功能引用清零扫（验收 G 的机械腿）。

intent（登记于 run_scenarios.py，本文件为其执行体）：
全票落地后，退役标识在**活功能面**必须清零：
  - 引擎：dev_lane.py / agent_activities.py / shared.py 全文零 suggest_next/epic_next 族
    token（Stage、activity、prompt 构造、precache 帮手、SUGGEST_STUB 注释面全退）；
  - 工作流参考快照：server/workflows/dev-lane.yaml 零 suggest_next 段（gen_workflows_doc 重生成）；
  - workbench 源面（src/**、node.ts）：零 epic-next 文件/导入/路由/janitor/客户端入口 token；
  - 退役文件在位性：epic-next.ts、selfcheck_epic_next.py、t260901-19 t03 两场景、
    t260907-07 建议场景、对应 engine 测试、epic-next 族 tests/smoke —— 均不存在；
  - ui-check 夹具：零 suggest_next 段数据；
  - 场景登记：run_scenarios.py 零指向退役面/退役文件的登记残留。
白名单（历史账与机器产物，不扫）：notes/**、docs/**、server/roles/**（含 integration.yml:67
历史教训行）、.sandbar/**、workbench lib/（构建产物）、各历史票目录、本文件。
三态：纯 stdlib 恒可跑；断言破面=exit 1。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
与 t260907-05 sc_naming_residue_fulltext（suyou 令牌族）intent 不同面：本条锁本票退役 token 族。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def read(rel):
    p = os.path.join(REPO, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def zero_tokens(rel, tokens, label):
    text = read(rel)
    if text is None:
        check(False, "%s：文件缺席（%s）" % (label, rel))
        return
    hits = ["%s(%s:%d)" % (t, rel, text[:text.find(t) + len(t)].count("\n") + 1)
            for t in tokens if t in text]
    check(not hits, "%s：零退役 token（%s）" % (label, ("命中 " + "、".join(hits[:4])) if hits else "clean"))


def absent(rel, label):
    check(not os.path.exists(os.path.join(REPO, rel)), "%s：已退场（%s）" % (label, rel))


# ---- 引擎面 ----
zero_tokens("server/engine/dev_lane.py",
            ["suggest_next", "prepare_epic_next", "build_suggest_next_prompt",
             "EpicNextPrep", "epic_next_precache", "SUGGEST_NEXT_PATCH_ID"],
            "引擎 dev_lane")
zero_tokens("server/engine/agent_activities.py",
            ["suggest_next", "prepare_epic_next", "build_suggest_next_prompt", "epic_next"],
            "引擎 agent_activities")
zero_tokens("server/engine/shared.py",
            ["suggest_next", "epic_next", "EpicNext", "SANDBAR_SUGGEST"],
            "引擎 shared")
zero_tokens("server/workflows/dev-lane.yaml", ["suggest_next"], "工作流参考快照")

# ---- 引擎自检面（acceptance 走查 260910 补强：selfcheck_*.py 同属活功能面——
# selfcheck_ui_acceptance H 段漏退役实锤（仍 import 已删除的 epic-next.ts）暴露
# 本守卫原白名单盲区；token 族按退役面取 epic-next/epic_next/EpicNext/prepare_epic/
# SANDBAR_SUGGEST，不扫裸 "suggest"（selfcheck_scan 的巡检建议字段属同名词不同族））----
import glob
for rel in sorted(glob.glob("server/engine/selfcheck_*.py")):
    zero_tokens(rel,
                ["epic-next", "epic_next", "EpicNext", "prepare_epic", "SANDBAR_SUGGEST",
                 "readPrecacheHint", "dismissPrecache"],
                "引擎自检 %s" % os.path.basename(rel))

# ---- workbench 面 ----
zero_tokens("server/plugins/workbench/node.ts",
            ["Suggest", "epic-next", "EpicNext", "EPIC_NEXT"], "workbench node.ts")
for root in ("server/plugins/workbench/src/host", "server/plugins/workbench/src/client"):
    for name in sorted(os.listdir(os.path.join(REPO, root))):
        full = os.path.join(REPO, root, name)
        if os.path.isdir(full):
            continue  # vendor 等资源目录不是文本文件，跳过（token 扫描面=源文件）
        rel = "%s/%s" % (root, name)
        zero_tokens(rel, ["epic-next", "epic_next", "EpicNext", "startSuggestJob",
                          "pollSuggestJob", "SANDBAR_EPIC_NEXT", "suggest_next"],
                    "workbench %s" % name)

# ---- 退役文件在位性 ----
for rel, label in [
    ("server/plugins/workbench/src/host/epic-next.ts", "workbench epic-next job"),
    ("server/engine/selfcheck_epic_next.py", "引擎 epic-next selfcheck"),
    ("integration/t260901-19/t03_suggest_next_precache.py", "t260901-19 预跑缓存场景"),
    # 注：t260901-19/sc_t04_cache_probe.py 测的是 integration/cache_probe.py（会话
    # 缓存率只读探针，通用工具非预跑建议面）——不属退役面，保留。
    ("integration/t260907-07/sc_epic_next_prepare_project.py", "t260907-07 建议场景"),
    ("server/engine/tests/test_t260901_19_t03_suggest_next_precache.py", "引擎预跑缓存单测"),
    ("server/plugins/workbench/tests/epic-next-lifecycle.mjs", "workbench epic-next 生命周期测试"),
    ("server/plugins/workbench/smoke/epic-next.mjs", "workbench epic-next 冒烟"),
    ("server/plugins/workbench/smoke/epic-precache.mjs", "workbench 预跑缓存冒烟"),
]:
    absent(rel, label)

# ---- ui-check 夹具 ----
for name in ("workflows.json", "tickets-list.json"):
    zero_tokens("server/ui-check/fixtures/%s" % name, ["suggest_next"], "ui-check 夹具 %s" % name)

# ---- 场景登记面（钉退役登记路径与旧断言串；本票新登记文案提及退役名属合法叙述，不扫裸 token）----
zero_tokens("integration/run_scenarios.py",
            ["t03_suggest_next_precache", "sc_epic_next_prepare_project"],
            "run_scenarios 退役登记路径")
zero_tokens("integration/sc_check_auto_rework_trace.py",
            ['target in ("suggest_next", "ui_evidence")'],
            "auto-rework 旧源码锁断言串")

print("t260910-14 retire-surface-clear: failed=%d" % len(FAILS))
sys.exit(1 if FAILS else 0)
