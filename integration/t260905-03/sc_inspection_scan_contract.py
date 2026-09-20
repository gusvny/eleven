#!/usr/bin/env python3
"""t260905-03 场景②：测试面扫描器对外契约（L2 灰盒，仓形夹具，不靠真仓全量）。

依据三支：①工单正文③「重复场景检测（锚点/断言重叠度）+守卫 vs 文档现实漂移+过时断言
（引用行号/文件已挪）」+「全绿期=零发现票作心跳证明」；②红线「巡检只出报告与开票建议
绝不直接改码」——本场景把它判定化：扫描前后被扫树逐字节校验和不变；③交付扫描器契约
（inspection_scan.py）：result.findings 六键 {id,scan,severity,subject,evidence,suggestion}、
severity∈{high,med,low}、heartbeat 布尔、畸形逐条降级不崩（fail-closed：畸形≠缺省≠静默）。

纯 stdlib 夹具零 env 依赖（真仓 smoke 子用例只读）；实现段落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。与场景① intent 分工：①守 KI-051 事故四面（验收②），本条守
扫描器横向契约（形状/阈值边界/过时断言/零发现/红线/韧性/真仓可跑）——步骤共享 lib
夹具构造器，intent 不同面不互替。与 developer L1 不同层：本条黑盒锁 CLI 回执契约与
跨扫描项组合行为。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspection as lib

SEV_OK = {"high", "med", "low"}


def main() -> int:
    failures = []

    # ── 子用例1：findings 形状契约——六键齐、severity 三值域、id 唯一、证据/主体非空 ──
    collected = []
    for tree in (lib.duplicate_tree(), lib.stale_tree(), lib.ki051_med_tree()):
        try:
            proc, parsed = lib.run_scanner(tree.root)
            fs = lib.scanner_findings(parsed)
            if fs is None:
                failures.append("子用例1 夹具 %s 回执异常：%r" % (tree.label, str(parsed)[:160]))
                continue
            collected.extend(fs)
        finally:
            tree.cleanup()
    if not collected:
        failures.append("子用例1 三夹具合计零发现，形状契约无从验起")
    ids = set()
    for f in collected:
        if not isinstance(f, dict):
            failures.append("子用例1 finding 非 dict：%r" % (f,))
            continue
        missing = lib.FINDING_KEYS - set(f)
        if missing:
            failures.append("子用例1 finding 缺键 %s：%r" % (sorted(missing), f))
        if f.get("severity") not in SEV_OK:
            failures.append("子用例1 severity 越域 %r" % (f.get("severity"),))
        if not str(f.get("evidence") or "").strip() or not str(f.get("subject") or "").strip():
            failures.append("子用例1 finding 证据/主体为空（发现必须可定位）：%r" % (f,))
        fid = f.get("id")
        if fid in ids:
            failures.append("子用例1 finding id 重复：%r" % (fid,))
        ids.add(fid)

    # ── 子用例2：重复场景检测阈值边界——高重叠对必报 med 且双点名，独立条目不误报 ──
    t = lib.duplicate_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        fs = lib.scanner_findings(parsed) or []
        dups = [f for f in fs if isinstance(f, dict) and f.get("scan") == "duplicate"
                and f.get("severity") == "med"]
        pair = [f for f in dups if "t-fix-alpha" in str(f.get("subject", ""))
                and "t-fix-alpha-copy" in str(f.get("subject", ""))]
        if not pair:
            failures.append("子用例2 高重叠对（intent 近逐字）未报重 med：%r" % (fs,))
        for f in dups:
            if f.get("severity") == "high":
                failures.append("子用例2 重复场景混入 high（重复=med 口径破）：%r" % (f,))
        if any("t-fix-gamma" in str(f.get("subject", "")) for f in dups):
            failures.append("子用例2 独立守护面条目被误报重复：%r" % (dups,))
    finally:
        t.cleanup()

    # ── 子用例3：过时断言——引用资产缺席与行号越界两类各自必报，证据点名缺什么 ──
    t = lib.stale_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        fs = lib.scanner_findings(parsed) or []
        stale = [f for f in fs if isinstance(f, dict) and f.get("scan") == "stale-ref"]
        ev_all = "".join(str(f.get("evidence", "")) + str(f.get("subject", "")) for f in stale)
        if "definitely_missing_asset" not in ev_all:
            failures.append("子用例3 引用资产缺席（文件已挪）零发现：%r" % (fs,))
        if "999" not in ev_all:
            failures.append("子用例3 行号越界零发现：%r" % (fs,))
        if not all(f.get("severity") == "high" for f in stale) or len(stale) < 2:
            failures.append("子用例3 过时断言两类未齐/未按 high 定级：%r" % (stale,))
    finally:
        t.cleanup()

    # ── 子用例4：零发现=空清单+heartbeat true（全绿期零发现心跳的数据面，非静默） ──
    t = lib.clean_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        fs = lib.scanner_findings(parsed)
        res = lib.scanner_result(parsed)
        if fs is None or res is None:
            failures.append("子用例4 干净树回执异常：%r" % str(parsed)[:160])
        else:
            if fs != []:
                failures.append("子用例4 干净树非空清单：%r" % (fs,))
            if res.get("heartbeat") is not True:
                failures.append("子用例4 干净树 heartbeat 非 true：%r" % res.get("heartbeat"))
    finally:
        t.cleanup()

    # ── 子用例5：红线判定化——扫描全程被扫树逐字节不变（巡检绝不直接改码） ──
    t = lib.ki051_high_tree("redline")
    try:
        t.keep_checksums()
        lib.run_scanner(t.root)
        red = t.tree_unchanged()
        if red:
            failures.append("子用例5 " + red)
    finally:
        t.cleanup()

    # ── 子用例6：畸形被扫输入不崩——二进制乱码守卫文件也结构化回执 ──
    t = lib.malformed_guard_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            failures.append("子用例6 畸形被扫输入致崩坏/回执非 JSON：%r" % str(parsed)[:160])
    finally:
        t.cleanup()

    # ── 子用例7：清单畸形逐条降级——残缺元组出 med 点名，不崩不静默 ──
    t = lib.malformed_manifest_tree()
    try:
        proc, parsed = lib.run_scanner(t.root)
        fs = lib.scanner_findings(parsed) or []
        hit = [f for f in fs if isinstance(f, dict)
               and "SCENARIOS[1]" in str(f.get("subject", ""))
               and f.get("severity") == "med"]
        if not hit:
            failures.append("子用例7 清单残缺元组未降级 med 点名：%r" % (fs,))
    finally:
        t.cleanup()

    # ── 子用例8：真仓 smoke（只读）——真仓可跑、回执形状齐；发现量级不 pin
    #     （发现随工单演化，可行动性归人审；真仓量级异常已另报缺陷单） ──
    proc, parsed = lib.run_scanner(lib.REPO)
    res = lib.scanner_result(parsed)
    if res is None:
        failures.append("子用例8 真仓扫描回执异常：%r | stderr=%s"
                        % (str(parsed)[:160], (proc.stderr or "")[:160]))
    else:
        if not isinstance(res.get("findings"), list):
            failures.append("子用例8 真仓回执缺 findings 列表")
        if not isinstance(res.get("heartbeat"), bool):
            failures.append("子用例8 真仓回执 heartbeat 非布尔")
        meta = res.get("meta") or {}
        if not str(meta.get("red_line") or "").strip():
            failures.append("子用例8 真仓回执 meta 缺红线声明（红线必须随结果可读）")

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: findings 六键/值域/id 唯一；重复阈值两边界；过时断言两类点名精确；"
          "零发现=空清单心跳 true；被扫树逐字节未动；畸形守卫/清单不崩；真仓只读可跑",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
