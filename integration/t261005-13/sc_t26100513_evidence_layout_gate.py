#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-13 场景②：UI 证据顶层布局规则两面在文（灰盒 L2 契约锚，integration 岗
design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS）——工单 REQUIRED OUTCOME 3 + 宿主裁定
261005-B 的「规则必须写在生产者与读者都看得见的地方」：ui_evidence 证据闸对
`.sandbar/screenshots/` 的 `*.png` 只扫**顶层、非递归**（嵌套 before/、after/ 计为
缺证据——t261005-04/05 实锤，13/18 张靠人手拍平解卡）。这个选择必须**具名**而非
隐含：闸拒绝文案（merge_check 侧 + worker 代跑侧两处红脸）与生产者文案
（server/ui-check/README.md + capture-lane.mjs 用法说明）都要把「顶层拍平输出 /
非递归扫描」说出来，四面同语不可漂移。

断言落在**契约文字**上（浅绑定：措辞按关键词组匹配，不锁整句字面），落点：
- G（gate 侧，两处红脸）：agent_activities.py 中每个 `glob("*.png")` 消费点
  邻窗必须出现「顶层 + 非递归/嵌套计缺」的说明词——有几处消费点就查几处，
  漏一处=读者那侧看不见规则。
- P（producer 侧）：README.md 与 capture-lane.mjs 用法说明必须写明输出落
  `--out` 顶层拍平（不建子目录）。
- N（具名面）：若闸改成递归扫描则规则变更须留痕——本场景锚定现行选择
  （非递归），改为递归=本场景红=被迫写明理由（工单二选一口径的机械化）。

intent 分工：证据闸的 diff 判定/声明制面归 t260904-13（KI-044 族）与
t260904-18（声明制门③）；capture 工具的功能面归 capture 族场景；本条只锁
「布局规则写在四面 + 扫描选择具名」这一张纸。零 docker、零网络、零 3099、
只读生产树。源文件缺席=FAIL 点名（产品面坏了），工具缺席=ENV_FAIL exit 2。
实现前红属预期（TDD 信号）；arbitrate/merge 必须绿。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))

try:
    from lib_result import emit_case
except Exception as e:
    print("ENV_FAIL: integration/lib_result.py import failed: %r" % (e,))
    sys.exit(2)

SUITE = "t261005-13-evidence-layout-named"
_FAILS = []

# wording keys: the rule must be stated, not implied (loose word families,
# both languages tolerated — new copy per writing standard is English)
TOP = re.compile(r"top[- ]?level|顶层", re.I)
NONRECUR = re.compile(r"non[- ]recursive|非递归|不递归|仅扫|只扫|拍平|flat\b", re.I)
GLOB = 'glob("*.png")'


def check(name, ok, reason="", evidence=""):
    emit_case(name=name, suite=SUITE,
              status="pass" if ok else "fail", cause="self",
              reason=reason, evidence=str(evidence)[:400])
    if not ok:
        _FAILS.append(name)


def window_has_rule(text, idx, span=900):
    lo = max(0, idx - span)
    hi = min(len(text), idx + span)
    seg = text[lo:hi]
    return bool(TOP.search(seg) and NONRECUR.search(seg))


def main():
    # G: every top-level png glob consumer in the engine faces carries the rule
    act = os.path.join(REPO, "server", "engine", "agent_activities.py")
    if not os.path.isfile(act):
        check("G-gate-faces-state-rule", False,
              "engine agent_activities.py missing — reader face gone", act)
    else:
        text = open(act, encoding="utf-8", errors="replace").read()
        # scope to the evidence faces: a png glob whose FOLLOWING window emits a
        # missing-evidence REFUSAL (the user-visible contract face). Binding is on
        # the refusal behaviour, not on a variable token: gen1 lesson — the rework
        # rewrote the red copy to a longer English sentence and the old ±400
        # "window mentions UI_EVIDENCE_DIR" heuristic silently dropped two faces
        # out of scope (a contract-precise rewording must never shrink the net).
        # The archive collector (a silent reader that moves shots into the
        # main-tree evidence drawer, emits no missing-evidence refusal) stays out
        # of scope: no refusal text follows its glob.
        REFUSAL = re.compile(r"no TOP-LEVEL png|无 png|lacks screenshot evidence"
                             r"|count as missing", re.I)
        hits = [m.start() for m in re.finditer(re.escape(GLOB), text)
                if REFUSAL.search(text[m.start():m.start() + 900])]
        if len(hits) < 2:
            check("G-gate-faces-state-rule", False,
                  "expected >=2 top-level png glob faces (merge_check gate + "
                  "worker-side check); found %d — faces renamed/merged without "
                  "keeping the rule visible" % len(hits),
                  "glob hits at %s" % hits)
        else:
            bad = [i for i in hits if not window_has_rule(text, i)]
            check("G-gate-faces-state-rule", not bad,
                  "every png-glob consumer face must state the top-level "
                  "non-recursive rule nearby (t261005-04/05: nested before/ "
                  "after/ shots graded red as missing)",
                  "faces=%d, faces-without-rule=%s" % (len(hits), bad))

    # P: producer copy states flat top-level output
    readme = os.path.join(REPO, "server", "ui-check", "README.md")
    if not os.path.isfile(readme):
        check("P1-producer-readme-states-flat", False,
              "server/ui-check/README.md missing — producer face gone", readme)
    else:
        rtxt = open(readme, encoding="utf-8", errors="replace").read()
        check("P1-producer-readme-states-flat",
              bool(TOP.search(rtxt) and NONRECUR.search(rtxt)),
              "README must state: output lands FLAT at the top level of --out "
              "(the gate scans top-level only, non-recursively)",
              rtxt[-300:])

    lane = os.path.join(REPO, "server", "ui-check", "capture-lane.mjs")
    if not os.path.isfile(lane):
        check("P2-capture-lane-usage-states-flat", False,
              "server/ui-check/capture-lane.mjs missing — the automated entry "
              "the engine invokes is gone", lane)
    else:
        ltxt = open(lane, encoding="utf-8", errors="replace").read()
        check("P2-capture-lane-usage-states-flat",
              bool(TOP.search(ltxt) and NONRECUR.search(ltxt)),
              "capture-lane usage/help must state the same flat top-level "
              "output contract as the gate refusal",
              ltxt[:400])

    # N: the choice itself is named somewhere machine-findable on the engine side
    ok_all = not _FAILS
    print("SUMMARY %s: %s" % (SUITE, "all green" if ok_all
                              else "FAIL: %s" % ",".join(_FAILS)))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
