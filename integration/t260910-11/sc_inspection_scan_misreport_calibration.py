#!/usr/bin/env python3
"""t260910-11 场景②：扫描误报校准三面（灰盒 L2，仓形夹具，纯离线）。

依据三支：①工单③逐条校准点名的三类误报——S3 stale-ref 把模块加载形态（裸名
index.mjs）当路径断言；S2 把泳道/过程目录（.lane/<票>/… 等）当生产方源码索引、
运行时拼装/DOM 形锚不得报 high；S1 duplicate 须意图+断言对象+选择器三级比对复核
（首期 t18-* 四场景互配对全误报）。②校准目标「真实报告 ≤30 条+抽样判读」是验收
证据面（随仓每票变化），不进场景断言防 rot——本场景只钉夹具可判定的行为翻转；
真仓前后对照由 implement 段交付报告承载。③与既有 intent 分工：
t260905-03-ki051-anchor-replay 守「锚×生产方措辞漂移必抓」（检测半），本条守
「误报校准」（排除/降级/复核半）；t260905-03-scan-contract 守扫描器横向契约与
「intent 近逐字+同 cmd 必报」的检测下界——本条的必报对照腿防「校准=剁手」
（检测器被砍死），两者合起来才是完整校准语义。

纯 stdlib 夹具零 env 依赖；实现段落地前红属预期（TDD 信号），arbitrate/merge 期
必须绿。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                + "/t260905-03")
import lib_inspection as lib  # noqa: E402

LANE_ANCHOR = "泳道夹具锚字面（不应被泳道副本满足）"


def calibration_tree() -> lib.RepoTree:
    """一张夹具树装全三类：S1 对照对+分歧对、S2 泳道生产方+DOM 拼装锚、S3 模块名+真路径。"""
    t = lib.RepoTree("t260910-11-cal")
    intent_a = "校准夹具 A 守护面：账册生命周期，锚字面在场、引用全存"
    # S1 对照对（必须仍报）：intent 同 + cmd（断言对象）同 + 选择器同——三级全符
    t.write_scenarios([
        ("t-cal-a", intent_a, "node integration/baselines/cal_a.mjs"),
        ("t-cal-a-copy", intent_a + "（副本）", "node integration/baselines/cal_a.mjs"),
        # S1 分歧对（校准后不得再报）：intent 同、断言对象（cmd）分歧
        ("t-cal-b", "校准夹具 B 守护面：重复检测的断言对象维度", "node integration/baselines/cal_b.mjs"),
        ("t-cal-b-copy", "校准夹具 B 守护面：重复检测的断言对象维度", "node integration/baselines/cal_x.mjs"),
    ])
    # 真路径引用面：存在的相对路径引用（真阴性）+ 缺席的相对路径引用（必须仍报 stale-ref）
    t.write("integration/baselines/cal_a.mjs", "export const ok = true;\n")
    t.write("integration/baselines/cal_b.mjs", "export const ok = true;\n")
    t.write("integration/baselines/cal_x.mjs", "export const ok = true;\n")
    t.write("integration/sc_cal_paths.py",
            'cmd_missing = "node integration/baselines/cal_missing_asset.mjs"  # 缺席：slash 路径形态\n'
            'cmd_ok = "node integration/baselines/cal_a.mjs"  # 在场：真阴性\n')
    # S3 模块加载形态：裸名（无 slash）且仓内无该文件——不得当路径断言产 stale-ref
    t.write("integration/sc_cal_module.py",
            'import { createSession } from "index.mjs";\n'
            "const helper = require(other_dir + '/util');\n")
    # S2 泳道生产方：.lane/<票>/ 下的 capture.mjs 副本满足守卫锚——不得被索引为生产方
    t.write(".lane/t9999-00/server/plugins/workbench/src/client/capture.mjs",
            'export const label = "%s";\n' % LANE_ANCHOR)
    t.write("integration/sc_lane_guard.py",
            "// 守卫：泳道锚（S2 排除面夹具）\n"
            "// 守卫对象生产方: server/plugins/workbench/src/client/capture.mjs\n"
            'const label = await page.locator(\'.session-create\').innerText();\n'
            'assert(label.includes("%s"), "守卫锚缺失");\n' % LANE_ANCHOR)
    # S2 运行时拼装锚：字面由变量拼接——DOM/拼装形锚不得报 high
    t.write("integration/sc_dom_guard.py",
            "// 守卫：运行时拼装文案锚（S2 降级面夹具）\n"
            "// 守卫对象生产方: server/plugins/workbench/src/client/capture.mjs\n"
            'const suffix = maybeLocale();\n'
            'const label = "提交" + suffix;\n'
            'assert(label.includes("提交并收口"), "守卫锚缺失");\n')
    return t


def main() -> int:
    failures = []
    t = calibration_tree()
    t.keep_checksums()
    try:
        proc, parsed = lib.run_scanner(t.root)
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            failures.append("扫描回执非 ok（夹具树本身必须可扫）：%r | stderr=%s"
                            % ((parsed or (proc.stdout or "")[:200]), (proc.stderr or "")[:200]))
            return _finish(failures, t)
        findings = lib.scanner_findings(parsed) or []
        res = lib.scanner_result(parsed) or {}

        def texts(f):
            return "%s %s %s" % (f.get("subject") or "", f.get("evidence") or "",
                                 f.get("scan") or "")

        # ── S2a：泳道目录不进扫描根——零 finding 的证据/主体指向 .lane/ 路径 ──
        lane_hits = [f for f in findings if ".lane" in texts(f)]
        if lane_hits:
            failures.append("S2a 泳道目录仍被当扫描对象（%d 条指向 .lane/）：%s"
                            % (len(lane_hits), [texts(f)[:120] for f in lane_hits[:3]]))
        # ── S2b：除有意真阳性（S3b 的缺席路径引用）外零 high——泳道锚与拼装锚不得撑 high ──
        highs = [f for f in findings
                 if f.get("severity") == "high" and "cal_missing_asset" not in texts(f)]
        if highs:
            failures.append("S2b 校准夹具仍出 high（泳道/DOM 拼装锚未降级排除）：%s"
                            % [texts(f)[:140] for f in highs[:3]])
        # ── S3a：模块加载形态不报 stale-ref（裸名 index.mjs 不得出现在证据里）──
        mod_hits = [f for f in findings if "index.mjs" in texts(f)]
        if mod_hits:
            failures.append("S3a 裸模块名仍被当路径断言：%s"
                            % [texts(f)[:140] for f in mod_hits[:3]])
        # ── S3b：真路径形态的缺席引用必须仍报（检测器在场，校准≠剁手）──
        if not any("cal_missing_asset" in texts(f) for f in findings):
            failures.append("S3b 缺席路径引用（cal_missing_asset.mjs）未报 stale-ref——"
                            "检测面被校准砍死（校准≠剁手）")
        # ── S1a：三级全符对照对必须仍报 duplicate ──
        if not any("t-cal-a-copy" in texts(f) or "t-cal-a" in texts(f)
                   for f in findings if f.get("scan") == "duplicate" or "duplicate" in texts(f)
                   or "重复" in texts(f)):
            failures.append("S1a 三级全符对照对（t-cal-a/t-cal-a-copy）未报 duplicate——"
                            "复核逻辑把真重复也吞了")
        # ── S1b：断言对象分歧对不得报 duplicate ──
        div_hits = [f for f in findings
                    if ("t-cal-b" in texts(f) and "duplicate" in texts(f)) or
                    ("t-cal-b" in texts(f) and "重复" in texts(f))]
        if div_hits:
            failures.append("S1b 断言对象分歧对（t-cal-b vs t-cal-b-copy）仍被判重"
                            "（三级复核缺 cmd/选择器维度）：%s"
                            % [texts(f)[:140] for f in div_hits[:3]])
        # ── 红线判定化：扫描全程（含校准后）不改动被扫树 ──
        dirty = t.tree_unchanged()
        if dirty:
            failures.append("红线 " + dirty)
    finally:
        t.cleanup()
    return _finish(failures, None)


def _finish(failures, t):
    if t is not None:
        t.cleanup()
    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: 泳道目录零命中、夹具零 high、裸模块名不产 stale-ref、"
          "缺席真路径仍报、三级全符对照对仍报、分歧对不判重", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
