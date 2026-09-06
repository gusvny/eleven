#!/usr/bin/env python3
"""t260905-03 场景①：KI-051 守卫锚×生产方措辞漂移——静态回放必抓（验收②主证据）。

依据三支：①工单验收②「KI-051 案例回放能抓到（守卫锚生产方在场性核验）」；
②KI-051 未闭合条目（notes/debts/known-issues.md L65，挂本票扫描项）——真实形态=
生产方在位（模板拼接、旧字面搜不到）+守卫断言旧字面，且曾被 env_fail 捂住数日；
③交付扫描器的锚判据四支路（inspection_scan.py 头注①~④）：字面/组合片段在场=零发现；
核心片段全缺（纯重写）=high 确证漂移；部分片段悬置=med 交人审；生产方上下文定位不到
=锚跳过不出发现（防误报满屏）。

本场景纯 stdlib 夹具、零 env 依赖、零真仓接触——环境红永远捂不住本断言面。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
与 developer L1（扫描纯函数真值表）intent 不同层：本条黑盒 CLI 消费扫描器，锁
「KI-051 两形态（纯重写/共享前缀）必报＋健康对照零误报＋定位不到不误伤」四面；
与 t260904-08 模板退役负扫描不同面（彼守退役类名零活引用，本守在役守卫锚×生产方
措辞在场性）。夹具=仓形树（integration/sc_* 守卫 + server/** 生产方），与扫描器
真实收集口径同构。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspection as lib


def anchor_findings(parsed, severity=None):
    fs = lib.scanner_findings(parsed) or []
    out = [f for f in fs if isinstance(f, dict) and f.get("scan") == "guard-anchor"]
    if severity:
        out = [f for f in out if f.get("severity") == severity]
    return out


def main() -> int:
    failures = []

    # ── 腿1：纯重写漂移（核心片段全缺）——必报 high，证据双点名守卫与生产方 ──
    t = lib.ki051_high_tree()
    try:
        t.keep_checksums()
        proc, parsed = lib.run_scanner(t.root)
        highs = anchor_findings(parsed, "high")
        if highs is None or not isinstance(parsed, dict) or parsed.get("ok") is not True:
            failures.append("腿1 扫描器回执异常：%r | stderr=%s"
                            % (str(parsed)[:160], (proc.stderr or "")[:160]))
        elif not highs:
            failures.append("腿1 KI-051 纯重写形态（生产方在位+锚字面与核心片段全缺）"
                            "未报任何 high——验收②失真")
        else:
            ev = "".join(str(h.get("evidence", "")) + str(h.get("subject", ""))
                         for h in highs)
            if "sc_guard_sample" not in ev:
                failures.append("腿1 high 证据未点名守卫文件 sc_guard_sample：%r" % ev[:300])
            if "capture.mjs" not in ev:
                failures.append("腿1 high 证据未点名生产方 capture.mjs：%r" % ev[:300])
        red = t.tree_unchanged()
        if red:
            failures.append("腿1 " + red + "（巡检零直接改码红线）")
    finally:
        t.cleanup()

    # ── 腿2：真实 capture.mjs 案形态（留共享前缀「隔离台」、模板拼接换措辞）——
    #    相似度悬置=med 必报不静默，且不得误判成 high 确证漂移 ──
    t = lib.ki051_med_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            failures.append("腿2 扫描器回执异常：%r" % str(parsed)[:160])
        else:
            meds = anchor_findings(parsed, "med")
            highs = anchor_findings(parsed, "high")
            if not meds:
                failures.append("腿2 真实 KI-051 形态（共享前缀+措辞已换）零 med=静默放行"
                                "（悬置必须交人审）")
            if highs:
                failures.append("腿2 悬置形态被误判 high 确证漂移：%r" % (highs,))
    finally:
        t.cleanup()

    # ── 腿3：健康对照（锚措辞字面在场）——零发现+heartbeat true（防误报满屏逼死守卫） ──
    t = lib.ki051_healthy_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        fs = lib.scanner_findings(parsed)
        res = lib.scanner_result(parsed)
        if fs is None:
            failures.append("腿3 扫描器回执异常：%r" % str(parsed)[:160])
        else:
            if fs != []:
                failures.append("腿3 健康对照（字面在场）非零发现：%r" % (fs,))
            if res.get("heartbeat") is not True:
                failures.append("腿3 健康对照 heartbeat 非 true（全绿期心跳语义破）：%r" % res.get("heartbeat"))
    finally:
        t.cleanup()

    # ── 腿4：生产方上下文定位不到（引用缺席）——锚让位不出锚发现，只出 stale 面 ──
    t = lib.ki051_orphan_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            failures.append("腿4 扫描器回执异常：%r" % str(parsed)[:160])
        elif anchor_findings(parsed):
            failures.append("腿4 定位不到生产方仍出锚发现（防误报满屏口径破）：%r"
                            % (anchor_findings(parsed),))
    finally:
        t.cleanup()

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: KI-051 纯重写形态必报 high 且证据双点名；真实共享前缀形态 med 必报"
          "不误判 high；健康对照零发现心跳 true；定位不到不误伤", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
