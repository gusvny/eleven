#!/usr/bin/env python3
"""t260910-09 场景①：机制/简化面扫描器对外契约（L2 灰盒，仓形夹具，零 env 依赖）。

依据三支：①工单规格——dead-man 泛化（日志引用零命中+场景零引用+代码路径零调用的
全史零命中机制，KI-049 源头案例）+影子代码；补丁退役判定带「删了会怎样」风险注+过长/
过深点名，每条发现带证据（文件:行/命中统计）；②红线「巡检只出报告与开票建议绝不直接
改码」判定化=扫描前后被扫树逐字节不变；③方案 D1-D7 承诺的交付契约：CLI 单行 JSON
同票①、severity 分级（dead-man/影子/补丁/重复防御层=med，过长过深=low）、零发现
heartbeat=true、face 分派缝（缺省 test 零变化、未知 face fail-closed 点名）。

纯 stdlib 夹具零 env 依赖（真仓 smoke 腿只读；face 分派缝腿需 temporalio=venv 重入，
缺席=ENV_FAIL 点名，沿票① decl-gate 三态分级先例）。实现段落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。
intent 分工：与 t260905-03-scan-contract（测试面 S1/S2/S3 契约）不同面——本条守新两面的
扫描契约与分派缝；与本票场景②不同面——彼守声明位与门数据面，本守扫描行为本身；
与 developer L1（纯函数真值表/阈值精确边界）不同层——本条锁 CLI 回执契约、正反例
判定与跨面组合行为，阈值边界只用显著超阈/显著低于两档（精确 80/81 真值表归 L1）。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspection_ms as lib  # noqa: E402
import lib_inspection as base  # noqa: E402

SEV_OK = {"high", "med", "low"}


def _reenter_venv_for_temporalio_once() -> None:
    """腿13 前置（main 最初调用，保证重入后全场景只跑一遍）：当前解释器缺 temporalio
    且仓内 venv 可用 → execv 重入（env 标记防环）。真 venv 解释器即使 realpath 与系统
    python 相同（macOS 符链形），sys.prefix 也会指向 venv 的 site-packages。"""
    try:
        import temporalio  # noqa: F401
        return
    except Exception:
        pass
    venv_py = base.VENV_PY
    if os.path.exists(venv_py) and os.environ.get("SANDBAR_MS_SCENARIO_VENV") != "1":
        os.environ["SANDBAR_MS_SCENARIO_VENV"] = "1"
        os.execv(venv_py, [venv_py, os.path.abspath(sys.argv[0])])
    base.die_env("temporalio 缺席且 server/engine/.venv 不可用——腿13 分派缝腿需 "
                 "temporalio 环境（ENV_FAIL 点名，不假红不假绿）")


def main() -> int:
    failures = []
    _reenter_venv_for_temporalio_once()

    # ── 腿1：findings/result 形状契约——六键齐、severity 值域、id 唯一、证据/主体非空 ──
    collected = []
    for tree, face in ((lib.dead_hit_tree("shape-m"), "mechanism"),
                       (lib.patch_tree("shape-s"), "simplify")):
        try:
            proc, parsed = lib.run_ms_scanner(tree.root, face)
            res = lib.ms_result(parsed)
            if res is None:
                failures.append("腿1 face=%s 回执异常：%r | stderr=%s"
                                % (face, str(parsed)[:160], (proc.stderr or "")[:160]))
                continue
            missing = lib.RESULT_KEYS - set(res)
            if missing:
                failures.append("腿1 face=%s result 缺键 %s" % (face, sorted(missing)))
            if res.get("face") != face:
                failures.append("腿1 result.face 未回写声明面：%r" % res.get("face"))
            fs = res.get("findings")
            if not isinstance(fs, list):
                failures.append("腿1 findings 非列表：%r" % (fs,))
                continue
            collected.extend(fs)
        finally:
            tree.cleanup()
    ids = set()
    for f in collected:
        if not isinstance(f, dict):
            failures.append("腿1 finding 非 dict：%r" % (f,))
            continue
        miss = lib.FINDING_KEYS - set(f)
        if miss:
            failures.append("腿1 finding 缺键 %s：%r" % (sorted(miss), f))
        if f.get("severity") not in SEV_OK:
            failures.append("腿1 severity 越域 %r" % (f.get("severity"),))
        if not str(f.get("evidence") or "").strip() or not str(f.get("subject") or "").strip():
            failures.append("腿1 finding 证据/主体为空（发现必须可定位）：%r" % (f,))
        if not str(f.get("scan") or "").strip():
            failures.append("腿1 finding scan 字段为空（面内分类必须可辨）：%r" % (f,))
        fid = f.get("id")
        if fid in ids:
            failures.append("腿1 finding id 重复：%r" % (fid,))
        ids.add(fid)

    # ── 腿2：dead-man 正例——三重零命中 ghost → med；证据含 文件:行+带分母零计数； ──
    #     zombie（零日志字面=日志面空集）仍判 med（空集不得当「查过零」）；meta 记录
    #     「全史」口径局限（方案 D2 承诺，不静默）。
    t = lib.dead_hit_tree()
    try:
        proc, parsed = lib.run_ms_scanner(t.root, "mechanism")
        fs = base.scanner_findings(parsed) or []
        ghost = [f for f in fs if isinstance(f, dict)
                 and "ghost_mechanism" in lib.finding_text(f)]
        if not ghost:
            failures.append("腿2 三重零命中 ghost_mechanism 未报（dead-man 失明）：%r" % (fs,))
        else:
            g = ghost[0]
            if g.get("severity") != "med":
                failures.append("腿2 dead-man 判级非 med（静态面不确证不冤枉口径破）：%r" % (g,))
            ev = "%s %s" % (g.get("subject", ""), g.get("evidence", ""))
            if "mod_ghost.py" not in ev:
                failures.append("腿2 证据未点名定义文件 mod_ghost.py（证据必须可点开）：%r" % (ev,))
            if not lib._ZERO_COUNT_RE.search(g.get("evidence", "")):
                failures.append("腿2 证据零计数不带分母（0/N 形，空集≠查过零，review C2）：%r"
                                % (g.get("evidence", ""),))
        zombie = [f for f in fs if isinstance(f, dict) and "zombie_fn" in lib.finding_text(f)]
        if not zombie:
            failures.append("腿2 零日志字面 zombie_fn 未报（日志面空集被当豁免）：%r" % (fs,))
        res = lib.ms_result(parsed) or {}
        meta_txt = str(res.get("meta") or {})
        if "全史" not in meta_txt:
            failures.append("腿2 meta 未记录「全史」口径局限（方案 D2 承诺）：%s" % meta_txt[:200])
    finally:
        t.cleanup()

    # ── 腿3：dead-man 反例三连——场景引用/被调用/注册表豁免任一命中即不报（并集破零）； ──
    #     在役 live_mechanism 任何情况下不得报。
    for tag, tree in (("场景引用", lib.referenced_tree()),
                      ("被调用", lib.called_tree()),
                      ("注册表豁免", lib.exempt_tree())):
        try:
            proc, parsed = lib.run_ms_scanner(tree.root, "mechanism")
            fs = base.scanner_findings(parsed)
            if fs is None:
                failures.append("腿3(%s) 回执异常：%r" % (tag, str(parsed)[:160]))
                continue
            if any("ghost_mechanism" in lib.finding_text(f) for f in fs if isinstance(f, dict)):
                failures.append("腿3(%s) ghost_mechanism 被误报（反例不当报）：%r" % (tag, fs))
            if any("live_mechanism" in lib.finding_text(f) for f in fs if isinstance(f, dict)):
                failures.append("腿3(%s) 在役 live_mechanism 被误报：%r" % (tag, fs))
        finally:
            tree.cleanup()

    # ── 腿4：影子代码——legacy 零调用+新旧命名对 → med；在役 v2 不报 ──
    t = lib.shadow_tree()
    try:
        proc, parsed = lib.run_ms_scanner(t.root, "mechanism")
        fs = base.scanner_findings(parsed) or []
        legacy = [f for f in fs if isinstance(f, dict)
                  and "fetch_payload_legacy" in lib.finding_text(f)]
        if not legacy:
            failures.append("腿4 影子路径 fetch_payload_legacy 未报：%r" % (fs,))
        elif legacy[0].get("severity") != "med":
            failures.append("腿4 影子路径判级非 med：%r" % (legacy[0],))
        if any(isinstance(f, dict) and "fetch_payload_v2" in lib.finding_text(f) for f in fs):
            failures.append("腿4 在役 fetch_payload_v2 被误报：%r" % (fs,))
    finally:
        t.cleanup()

    # ── 腿5：补丁退役——*_patch 宿主被 v2 取代 → med 且 suggestion 含「删了会怎样」风险注 ──
    t = lib.patch_tree()
    try:
        proc, parsed = lib.run_ms_scanner(t.root, "simplify")
        fs = base.scanner_findings(parsed) or []
        patch = [f for f in fs if isinstance(f, dict)
                 and "upsert_ticket_patch" in lib.finding_text(f)]
        if not patch:
            failures.append("腿5 补丁层 upsert_ticket_patch 未报：%r" % (fs,))
        else:
            p = patch[0]
            if p.get("severity") != "med":
                failures.append("腿5 补丁退役（带取代证据）判级非 med：%r" % (p,))
            if "删了会怎样" not in str(p.get("suggestion", "")):
                failures.append("腿5 suggestion 缺「删了会怎样」风险注（本票硬性口径）：%r" % (p,))
    finally:
        t.cleanup()

    # ── 腿6：重复防御层——同一 sanitize 在调用链两层 → med ──
    t = lib.dupdef_tree()
    try:
        proc, parsed = lib.run_ms_scanner(t.root, "simplify")
        fs = base.scanner_findings(parsed) or []
        hit = [f for f in fs if isinstance(f, dict)
               and "sanitize_name" in lib.finding_text(f) and f.get("severity") == "med"]
        if not hit:
            failures.append("腿6 重复防御层 sanitize_name 未报 med：%r" % (fs,))
    finally:
        t.cleanup()

    # ── 腿7：过长/过深点名——显著超阈（120 行/深 8）low；显著低于（40 行/深 2）不报 ──
    t = lib.longfn_tree()
    try:
        proc, parsed = lib.run_ms_scanner(t.root, "simplify")
        fs = base.scanner_findings(parsed) or []
        for name in ("long_fn", "deep_fn"):
            hit = [f for f in fs if isinstance(f, dict) and name in lib.finding_text(f)]
            if not hit:
                failures.append("腿7 %s 未被点名：%r" % (name, fs))
            elif hit[0].get("severity") != "low":
                failures.append("腿7 %s 点名判级非 low（点名不判高口径破）：%r" % (name, hit[0]))
        # 低于阈值者不得被点名（shallow 模块经同一生成器生成，函数名同为 deep_fn，按文件区分）
        shallow_hits = [f for f in fs if isinstance(f, dict) and "mod_shallow" in lib.finding_text(f)]
        short_hits = [f for f in fs if isinstance(f, dict) and "short_fn" in lib.finding_text(f)]
        if shallow_hits or short_hits:
            failures.append("腿7 低于阈值者被误点名（short_fn/mod_shallow）：%r"
                            % (short_hits + shallow_hits,))
    finally:
        t.cleanup()

    # ── 腿8：零发现=空清单+heartbeat true（两 face；全绿期心跳票的数据面，非静默） ──
    for face in ("mechanism", "simplify"):
        t = lib.clean_ms_tree("clean-%s" % face)
        try:
            proc, parsed = lib.run_ms_scanner(t.root, face)
            res = lib.ms_result(parsed)
            if res is None:
                failures.append("腿8(%s) 干净树回执异常：%r" % (face, str(parsed)[:160]))
                continue
            if res.get("findings") != []:
                failures.append("腿8(%s) 干净树非空清单：%r" % (face, res.get("findings")))
            if res.get("heartbeat") is not True:
                failures.append("腿8(%s) 干净树 heartbeat 非 true：%r" % (face, res.get("heartbeat")))
        finally:
            t.cleanup()

    # ── 腿9：红线判定化——两 face 扫描全程被扫树逐字节不变（巡检绝不直接改码） ──
    t = lib.dead_hit_tree("redline")
    try:
        t.keep_checksums()
        lib.run_ms_scanner(t.root, "mechanism")
        lib.run_ms_scanner(t.root, "simplify")
        red = t.tree_unchanged()
        if red:
            failures.append("腿9 " + red)
    finally:
        t.cleanup()

    # ── 腿10：畸形被扫输入不崩——NUL 乱码模块也结构化回执（逐项降级，不株连不静默） ──
    t = lib.garbage_tree()
    try:
        proc, parsed = lib.run_ms_scanner(t.root, "mechanism")
        res = lib.ms_result(parsed)
        if res is None:
            failures.append("腿10 畸形被扫输入致崩坏/回执非 JSON：%r | stderr=%s"
                            % (str(parsed)[:160], (proc.stderr or "")[:160]))
        else:
            meta_txt = str(res.get("meta") or "")
            if "mod_nul" not in meta_txt:
                failures.append("腿10 乱码模块未在 meta 降级点名（静默吞）：meta=%s" % meta_txt[:200])
    finally:
        t.cleanup()

    # ── 腿11：仓根缺失 fail-closed——ok:false + 非零退出 + error 点名路径（不静默空返） ──
    _probe = base.RepoTree("absent-probe")
    absent_root = os.path.join(_probe.root, "definitely_absent_dir")
    _probe.cleanup()  # 只借路径形，不留夹具
    proc, parsed = lib.run_ms_scanner(absent_root, "mechanism")
    if not isinstance(parsed, dict) or parsed.get("ok") is not False:
        failures.append("腿11 仓根缺失未 fail-closed：%r" % (parsed,))
    else:
        if "definitely_absent_dir" not in str(parsed.get("error") or ""):
            failures.append("腿11 错误未点名缺失路径（报错必须精确）：%r" % (parsed.get("error"),))
    if proc.returncode == 0:
        failures.append("腿11 仓根缺失退出码为 0（与 ok:false 矛盾）")

    # ── 腿12：真仓 smoke（ro）——两 face 真仓可跑、形状齐；发现量级不 pin ──
    for face in ("mechanism", "simplify"):
        proc, parsed = lib.run_ms_scanner(lib.REPO, face)
        res = lib.ms_result(parsed)
        if res is None:
            failures.append("腿12(%s) 真仓扫描回执异常：%r | stderr=%s"
                            % (face, str(parsed)[:160], (proc.stderr or "")[:160]))
            continue
        if not isinstance(res.get("findings"), list):
            failures.append("腿12(%s) 真仓回执缺 findings 列表" % face)
        if not isinstance(res.get("heartbeat"), bool):
            failures.append("腿12(%s) 真仓回执 heartbeat 非布尔" % face)

    # ── 腿13：face 分派缝（activities.run_inspection_scan，需 temporalio=venv 重入，
    #     缺席=ENV_FAIL 点名不假红；沿票① decl-gate 三态分级先例）——缺省 face=test
    #     既有语义零变化（回执 face=test、形状同票①）；face=mechanism 走新面；
    #     未知 face ok:false 且 error 点名已知面清单（fail-closed 不静默）。 ──
    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("离线腿 1-12 全过（契约/正反例/阈值/心跳/红线/畸形/真仓 smoke）", flush=True)
    sys.path.insert(0, base.TP_DIR)
    try:
        import activities  # noqa: E402
    except Exception as e:  # noqa: BLE001
        base.die_env("activities 不可导入（%s: %s）——前 12 腿已过；分派缝腿需 temporalio 环境"
                     % (type(e).__name__, e))
    # ── 腿13：face 分派缝（rework r2 语义，arbitrate code-fault 260910 修订；
    #     t260911-02 arbitrate 再修订：doc 面已接线——「声明驱动、面在项目声明」
    #     拍板②兑现后 face=doc 不再回落 test，改为真分派 docs 面扫描器；对无 docs/
    #     的仓 fail-closed 点名（ok:false + error 点名 docs 目录缺失）。未接线面的
    #     回落契约（ok:true + meta.face_fallback 点名请求面与已接线清单、绝不静默）
    #     以 bogus-face 继续钉住，覆盖不收缩。缺省（无 face 键）=test 既有语义零变
    #     化；face=mechanism 走新面。 ──
    t = lib.dead_hit_tree("dispatch")
    try:
        r_default = asyncio.run(activities.run_inspection_scan({"repo_root": t.root}))
        r_mech = asyncio.run(activities.run_inspection_scan(
            {"repo_root": t.root, "face": "mechanism"}))
        r_doc = asyncio.run(activities.run_inspection_scan(
            {"repo_root": t.root, "face": "doc"}))
        r_bogus = asyncio.run(activities.run_inspection_scan(
            {"repo_root": t.root, "face": "bogus-face"}))
        if not (isinstance(r_default, dict) and r_default.get("ok") is True):
            failures.append("腿13 缺省（无 face 键）未走旧路径 ok:true：%r" % (r_default,))
        elif (r_default.get("result") or {}).get("face") != "test":
            failures.append("腿13 缺省回执 face 非 test（既有语义零变化破）：%r"
                            % (r_default.get("result"),))
        elif "face_fallback" in ((r_default.get("result") or {}).get("meta") or {}):
            failures.append("腿13 缺省路径不应带 face_fallback 标注：%r"
                            % ((r_default.get("result") or {}).get("meta"),))
        if not (isinstance(r_mech, dict) and r_mech.get("ok") is True):
            failures.append("腿13 face=mechanism 分派未走新面 ok:true：%r" % (r_mech,))
        elif (r_mech.get("result") or {}).get("face") != "mechanism":
            failures.append("腿13 mechanism 回执 face 未回写：%r" % (r_mech.get("result"),))
        # face=doc（t260911-02 起已接线）：真分派 docs 面扫描器——对无 docs/ 的仓
        # fail-closed 点名（ok:false + error 点名 docs 目录缺失），不回落不静默
        if not (isinstance(r_doc, dict) and r_doc.get("ok") is False):
            failures.append("腿13 face=doc 已接线却未走 docs 面 fail-closed（回落/假绿均破）：%r"
                            % (r_doc,))
        else:
            err_doc = str(r_doc.get("error") or "")
            if "docs" not in err_doc:
                failures.append("腿13 face=doc fail-closed 未点名 docs 目录（报错精确纪律）：%r"
                                % err_doc[:200])
        for tag, r_un, req in (("未接线面 bogus-face", r_bogus, "bogus-face"),):
            if not (isinstance(r_un, dict) and r_un.get("ok") is True):
                failures.append("腿13(%s) 未回落 ok:true（未接线面回落契约破）：%r"
                                % (tag, r_un))
                continue
            res = r_un.get("result") or {}
            if res.get("face") != "test":
                failures.append("腿13(%s) 回落未走 test 面：%r" % (tag, res.get("face")))
            note = str((res.get("meta") or {}).get("face_fallback") or "")
            if req not in note or "mechanism" not in note or "simplify" not in note:
                failures.append("腿13(%s) face_fallback 未点名请求面与已接线清单（不静默破）：%r"
                                % (tag, note))
    finally:
        t.cleanup()

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: 新两面 CLI 契约与形状齐；dead-man 正例（证据 文件:行+带分母零计数，"
          "空集日志面仍判）与反例三连（引用/调用/豁免任一即不报）；影子路径 med；"
          "补丁退役 med 带「删了会怎样」；重复防御层 med；过长过深 low 点名；"
          "零发现心跳 true；被扫树逐字节未动；乱码/缺根 fail-closed；真仓只读可跑；"
          "face 分派缝缺省 test 零变化+doc 面已接线（fail-closed 点名缺 docs 目录）"
          "+未接线面回落 test 带 face_fallback 标注（t260911-02 起的接线后契约）",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
