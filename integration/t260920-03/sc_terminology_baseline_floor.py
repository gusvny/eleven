#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_terminology_baseline_floor.py — 术语基线帽单调看守（t260920-03 要求②）。

intent（用户可感知契约）：票面要求「基线计数随替换批次下调（值只许降；上调=红）」。
L7 看守（兄弟场景 sc_terminology_l7_gate.py 所守）只判「用量不新增」——对「改基线
本身」全盲：抬帽、扩 allowlist、加新键都能让新增用量合法化，而 L7 恒绿。本场景把
S4 落地时的基线冻结为 floor 快照（terminology-baseline-floor.json），机械化
「上调=红」四规则：
  ① 逐键：基线现值 > floor → 红（帽被抬）；
  ② 键集：基线出现 floor 没有的键 → 红（基线扩面）；
  ③ allowlist 冻结：值 -1 只许落在术语表本体与基线自身两件上，且不得把 floor 里
     的有限帽改成 -1 → 红（免红令面扩）；
  ④ 汇总：total_before_allowlist > floor → 红（汇总字段上调误导人）。

与 t260920-03-terminology-l7-gate 不同面：彼守「用量维」（不新增），本条守「帽维」
（不上移）——同一堵墙的两半，合起来才封死「加用量同时抬帽给自己发免红令」
（t260911-03 改共享守卫期望值给自己发免红令同族事故的术语域形态）。不互替。

自证纪律：比较器是纯函数，红绿电池用合成数据逐规则自证（抬帽红/下调绿/缩键绿/
扩 allowlist 红/扩键红/汇总上调红/畸形红）——守卫自身失明在此现形，防「断言恒真」
（守卫资产在册自证先例：t260905-05-multitab-guard-assets）。

被看守文件（基线/floor/术语表）缺失或畸形=FAIL 点名：它们是仓内受控资产，缺损
属产品红而非环境缺席；本场景纯标准库零子进程，无环境依赖，故无 ENV_FAIL 子用例
（t260919-02-terminal-face-board 纯离线同例）。三态语义不受损：本场景只会
PASS(0)/FAIL(1)，不存在「什么都没验证到」的环境支路。

场景源码自洁：被禁字零残留（需要写出处一律 chr 构词），看守对象自身不入基线、
不欠账；由 T0 子用例自证。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "integration" / "terminology-baseline.json"
FLOOR = REPO / "integration" / "t260920-03" / "terminology-baseline-floor.json"
GLOSSARY = REPO / "docs" / "terminology.md"
TERM = chr(0x817F)  # 被禁字只在常量构词处出现，本文件其余位置零残留
# allowlist 冻结面（票面要求①：允许名单仅术语表本体与基线自身）
ALLOWLIST_FROZEN = {"docs/terminology.md",
                    "integration/terminology-baseline.json"}

_PASSES: list[str] = []
_FAILS: list[str] = []


def ok(msg: str) -> None:
    _PASSES.append(msg)
    print("  ok %s" % msg)


def bad(msg: str) -> None:
    _FAILS.append(msg)
    print("  FAIL %s" % msg)


# ---------- 纯函数比较器（合成数据电池自证的对象） ----------

def floor_violations(baseline: dict, floor: dict) -> list[str]:
    """返回违例清单（空=绿）。入参=两份 JSON 的解析产物。

    只消费 counts 与 total_before_allowlist 两个键；形状畸形按违例点名
    （fail-closed，不猜不吞）。四规则见模块 docstring。
    """
    v: list[str] = []
    bc = baseline.get("counts")
    fc = floor.get("counts")
    if not isinstance(bc, dict) or not isinstance(fc, dict):
        v.append("形状畸形：基线/floor 的 counts 不是对象（fail-closed）")
        return v
    for k in sorted(bc):
        cap = bc[k]
        if k not in fc:
            v.append("%s：基线新键（floor 无此键）——基线扩面；确需扩面走票更新 floor" % k)
            continue
        fcap = fc[k]
        if cap == -1:
            if fcap != -1:
                v.append("%s：有限帽 %d 被改成 allowlist（-1）——免红令面扩" % (k, fcap))
            elif k not in ALLOWLIST_FROZEN:
                v.append("%s：allowlist 键越出冻结面（冻结面=%s）"
                         % (k, sorted(ALLOWLIST_FROZEN)))
            continue
        if fcap == -1:
            continue  # floor 原为 allowlist、现值有限=收紧，恒绿
        if cap > fcap:
            v.append("%s：%d > floor %d——帽被抬" % (k, cap, fcap))
    bt = baseline.get("total_before_allowlist")
    ft = floor.get("total_before_allowlist")
    if isinstance(bt, int) and isinstance(ft, int) and bt > ft:
        v.append("total_before_allowlist：%d > floor %d——汇总字段上调" % (bt, ft))
    return v


# ---------- 合成数据红绿电池（比较器自证） ----------

def battery() -> None:
    j = lambda c, t=0: {"counts": c, "total_before_allowlist": t}  # noqa: E731

    out = floor_violations(j({"a.py": 1}, 1), j({"a.py": 2}, 2))
    expect(not out, "J2 下调恒绿（逐键+汇总双降）",
           "J2 下调应绿，实得 %s" % out)
    out = floor_violations(j({"a.py": 3}, 3), j({"a.py": 2}, 2))
    expect(bool(out) and any("帽被抬" in x for x in out),
           "J1 抬帽即红且点名「帽被抬」",
           "J1 抬帽应红，实得 %s" % out)
    out = floor_violations(j({"a.py": 2}, 2), j({"a.py": 2, "old.md": 7}, 9))
    expect(not out, "J3 键集收缩恒绿（floor 多出的键不算违例）",
           "J3 缩键应绿，实得 %s" % out)
    out = floor_violations(j({"a.py": -1}, 0), j({"a.py": 5}, 5))
    expect(bool(out) and any("免红令面扩" in x for x in out),
           "J4 有限帽改 allowlist 即红（免红令面扩）",
           "J4 扩 allowlist 应红，实得 %s" % out)
    out = floor_violations(j({"a.py": 2, "new.md": 1}, 3), j({"a.py": 2}, 2))
    expect(bool(out) and any("基线新键" in x for x in out),
           "J5 基线扩键即红（floor 无此键）",
           "J5 扩键应红，实得 %s" % out)
    out = floor_violations(j({"a.py": 2}, 4), j({"a.py": 2}, 2))
    expect(bool(out) and any("汇总字段上调" in x for x in out),
           "J6 汇总 total 上调即红",
           "J6 汇总上调应红，实得 %s" % out)
    out = floor_violations({"counts": "不是对象"}, j({"a.py": 2}, 2))
    expect(bool(out) and any("形状畸形" in x for x in out),
           "J7 counts 形状畸形 fail-closed 红",
           "J7 畸形应红，实得 %s" % out)


def expect(cond: bool, ok_msg: str, bad_msg: str) -> None:
    ok(ok_msg) if cond else bad(bad_msg)


# ---------- 主流程 ----------

def main() -> int:
    # T0 场景源码自洁：看守对象自身零被禁字（否则本文件就是新欠账面）
    src = Path(__file__).read_text(encoding="utf-8")
    expect(TERM not in src,
           "T0 场景源码自洁（被禁字零残留，全 chr 构词）",
           "T0 场景源码出现被禁字——自洁破功（须改用 chr 构词）")

    # T1 floor 资产在册且可解析（闸自身资产缺损=产品红点名，不静默绿）
    floor: dict = {}
    if not FLOOR.is_file():
        bad("T1 floor 快照缺失：%s——帽单调看守失去锚点（资产缺损，禁止静默放行）" % FLOOR)
    else:
        try:
            floor = json.loads(FLOOR.read_text(encoding="utf-8"))
            expect(isinstance(floor.get("counts"), dict),
                   "T1 floor 快照在册且 counts 可解析（%d 键）"
                   % len(floor.get("counts") or {}),
                   "T1 floor counts 形状畸形（非对象）")
        except Exception as e:  # noqa: BLE001 —— 畸形=红不猜
            bad("T1 floor 快照畸形（%s: %s）" % (type(e).__name__, e))

    # T2 基线在册且可解析（与 L7 的 fail-closed 互为独立 belt）
    baseline: dict = {}
    if not BASELINE.is_file():
        bad("T2 术语基线缺失：%s——fail-closed" % BASELINE)
    else:
        try:
            baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
            expect(isinstance(baseline.get("counts"), dict),
                   "T2 基线在册且 counts 可解析（%d 键）"
                   % len(baseline.get("counts") or {}),
                   "T2 基线 counts 形状畸形（非对象）")
        except Exception as e:  # noqa: BLE001 —— 畸形=红不猜
            bad("T2 术语基线畸形（%s: %s）" % (type(e).__name__, e))

    # T3 真仓判定面：四规则逐条比对（违例逐条点名）
    if baseline and floor:
        v = floor_violations(baseline, floor)
        if v:
            for x in v:
                bad("T3 基线上调：%s" % x)
        else:
            ok("T3 基线对 floor 单调（逐键不升/键集不扩/allowlist 冻结/汇总不升）")

    # T4 出路可达面：L7 红行承诺「替换词见 docs/terminology.md 禁用对照」——
    # 该真源必须真实在册且真列被禁字（报错不得指向 404 的出路）
    if not GLOSSARY.is_file():
        bad("T4 术语表缺失：%s——L7 红行指向的替换词真源不存在（出路 404）" % GLOSSARY)
    else:
        g = GLOSSARY.read_text(encoding="utf-8", errors="replace")
        expect("禁用对照" in g and TERM in g,
               "T4 术语表「禁用对照」真源在册且真列被禁字",
               "T4 术语表缺「禁用对照」节或未列被禁字——红行出路名不副实")

    battery()

    print("\nSUMMARY pass=%d fail=%d" % (len(_PASSES), len(_FAILS)))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
