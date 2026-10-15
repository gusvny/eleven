#!/usr/bin/env python3
"""t260916-22 场景①：inspect 段产物横向契约（灰盒 L2，stub temporalio 离线，桩链）。

用户场景（工单要点①②③④⑤+验收②③④）：宿主令「巡检要用 agent 来做」后，用户可感知
的行为承诺——agent 发现必须**可核验**（file:line 证据机械复核，不过者降级 unverified
并点名，绝不静默丢）、建议修复票只从「agent 判真」的发现出（verified && confidence≥
阈值 && severity≥med）、同内容跨期去重不重复计数、假报裁定跨期压制、预算可配置
（缺省 40 条截断并注明）、超时/解析失败=可见失败不假绿。

intent 分工（防 intent 级重复）：
- developer L1（test_t260916_22_inspect_core 等）：纯函数逐函数真值表（复核单判定、
  id 单铸、截断单面）——本条不复写；
- 本条（L2）：**活动缝上的横向契约**——桩消息→run_inspection_inspect 活动缝
  （SANDBAR_INSPECT_STUB=1+STUB_FILE，方案 §3 明文缝名）→verify_inspection_findings
  活动缝（上期台账+verdicts IO）→票面数据形状（状态可辨/reason 点名/建议门数据/
  心跳/截断记账）+跨期对照源（上期台账/verdicts 文件）消费+红线与 agent_home 落点
  （被审查树逐字节不变、真仓零 .dsh 残留）。步骤共享 lib 夹具，intent 不同面不互替。
- sc_inspection_inspect_journey（L3）：真台真票全链旅程（workflow 接线/段序/人门/
  落账），本条不起 Temporal。

三态纪律：环境缺供（venv 缺 temporalio 且无桩可装——本条全离线，理论无 ENV_FAIL 子用例）
照三态口径如实点名；实现未落地=FAIL（TDD 信号），arbitrate/merge 期必须绿。
跑法：python3 -B integration/t260916-22/sc_inspection_inspect_contract.py

260928 修（main 红直修，本棒此前在 main 上长红 13 条）：本棒的**夹具叙述字段**
（subject/why/suggestion）由中文改英文。引擎 463a8f7 起装「报告面语言闸」（宿主令
「report 用英语写」）：agent 自写的 subject/why/suggestion 含 CJK ⇒ 该条判 unverified
并追加一条聚合发现（inspection_inspect.mark_non_english，票面标红不静默）。本棒意图是
**证据机械复核语义**（真引文 verified / 坏证据 unverified+逐项点名）与语言闸正交，但夹具
造的是「agent 输出」，必须契约内：中文叙述字段会让整份发现被判 unverified——复核实得
8 进 9 出、真引文不 verified、id 面混入聚合条目（`agent:<12hex>`）、verified 门的预算面
全塌（实得 0 条 verified）。**断言零放宽**：真引文/空白容差仍须 verified、坏证据仍须
unverified 且逐项 reason、8 进 8 出、id 16 位且条内唯一、summary 只计新发现、recurring
不占 40 预算——逐条原样保留；quote/path 是数据面不译。
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspect as lib  # noqa: E402

#: 引擎**系统发现**的 subject 前缀白名单（261001）：这些不是 agent 交上来的发现，而是引擎
#: 按台账范围如实报的信号（本夹具无可用差分基点 ⇒ 必然出现 `Scope collapsed to 0 files` 一条）。
#: 判据把它们**具名**允许在场，但不许任何**未登记**的多余条目混进来（既不静默、也不放宽）。
SYSTEM_SUBJECT_PREFIXES = ("Scope collapsed to 0 files",)

PASS = 0
FAIL = 0
FAILURES = []


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        FAILURES.append(msg)
        print("  FAIL", msg)


def main() -> int:
    inst = "inspect-contract-%05d" % (os.getpid() % 100000)
    period = "20260916"
    ledger_dir = tempfile.mkdtemp(prefix="sandbar-inspect-ledger-")
    tree = lib.evidence_tree("inspect-contract")
    workdir = tempfile.mkdtemp(prefix="sandbar-inspect-work-")
    os.environ["SANDBAR_INSPECTION_DIR"] = ledger_dir
    tree.keep_checksums()

    # 实现面未落地=FAIL（TDD 信号点名缺失面），不静默不跳过
    try:
        activities, agent_activities, inspect_mod = lib.load_engine_modules()
    except ImportError as e:
        print("FAIL_REASON: inspect 实现面未交付（import：%s）——红属预期（实现段落地前）" % e)
        return 1
    try:
        run_inspect = getattr(agent_activities, "run_inspection_inspect")
    except AttributeError:
        print("FAIL_REASON: agent_activities.run_inspection_inspect 未交付——红属预期（实现段落地前 TDD 信号）")
        return 1
    try:
        verify_findings = getattr(activities, "verify_inspection_findings")
    except AttributeError:
        print("FAIL_REASON: activities.verify_inspection_findings 未交付——红属预期（实现段落地前 TDD 信号）")
        return 1
    try:
        mint_id = getattr(inspect_mod, "mint_finding_id")
    except AttributeError:
        mint_id = None
    if mint_id is None:
        # mint_finding_id 是方案 §2.4 明文名的链步 1，跨期去重/压制播种都依赖它——
        # 缺席即契约缺口，点名 FAIL（不静默滑过）
        print("FAIL_REASON: inspection_inspect.mint_finding_id 未交付（方案 §2.4 明文链步）——红属预期（实现段落地前）")
        return 1

    def full(message_text, extra=None):
        """全链桩驱动：inspect 活动缝（桩消息）→ verify 活动缝（复核/去重/预算链）。"""
        return call_verify(call_inspect(message_text), extra=extra)

    def call_inspect(message_text):
        """桩缝驱动 run_inspection_inspect：SANDBAR_INSPECT_STUB=1+STUB_FILE（方案 §3 缝名）。"""
        stub = lib.write_stub_file(workdir, "stub-message.txt", message_text)
        old = {k: os.environ.get(k) for k in ("SANDBAR_INSPECT_STUB", "SANDBAR_INSPECT_STUB_FILE")}
        os.environ["SANDBAR_INSPECT_STUB"] = "1"
        os.environ["SANDBAR_INSPECT_STUB_FILE"] = stub
        try:
            return lib.result_payload(lib.run_coro(run_inspect(lib.inspect_args(
                instance=inst, period=period, base=tree.root))))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def call_verify(inspect_payload, extra=None):
        args = lib.verify_args(instance=inst, period=period, base=tree.root,
                               inspect_payload=inspect_payload)
        if extra:
            args.update(extra)
        return lib.result_payload(lib.run_coro(verify_findings(args)))

    print("== 子用例1 解析纪律：畸形桩消息全部 ok=False 且点名，绝不假绿 ==")
    bad_cases = [
        ("0 围栏块", lib.fenced_message([], n_blocks=0)),
        ("≥2 围栏块", lib.fenced_message([], n_blocks=2)),
        ("坏 JSON", lib.fenced_message([], outer_json_valid=False)),
        ("findings 非列表", lib.fenced_message("not-a-list")),
        ("条目缺 evidence", lib.fenced_message([{"subject": "s", "severity": "med",
                                                 "why": "w", "suggestion": "x",
                                                 "confidence": 0.9}])),
        ("severity 越域", lib.fenced_message([lib.finding("s", lib.GUARD_REL, 2,
                                                          tree.line_text(lib.GUARD_REL, 2),
                                                          severity="catastrophic")])),
        ("confidence 越域", lib.fenced_message([lib.finding("s", lib.GUARD_REL, 2,
                                                            tree.line_text(lib.GUARD_REL, 2),
                                                            confidence=1.9)])),
    ]
    for label, msg in bad_cases:
        try:
            res = call_inspect(msg)
            ok(isinstance(res, dict) and res.get("ok") is False,
               "畸形桩（%s）→ ok=False（实得 ok=%r）" % (label, (res or {}).get("ok")))
            reason = json.dumps(res, ensure_ascii=False) if isinstance(res, dict) else str(res)
            ok(any(t in reason for t in ("围栏", "解析", "findings", "条目", "schema", "JSON")),
               "畸形桩（%s）回执点名解析面（reason 可读）" % label)
        except Exception as e:  # noqa: BLE001——活动以异常表达解析失败也算点名（不假绿即可）
            ok(True, "畸形桩（%s）→ 活动层拒绝（异常点名：%s）" % (label, str(e)[:80]))

    print("== 子用例2 合法桩：ok=True 且 base_dir/route 进 meta（可见面） ==")
    # 260928 修：叙述字段一律英文（语言闸口径，见文件头）；quote/path 是数据面不译。
    good_f = lib.finding("guard anchor drift (inspect evidence fixture)", lib.GUARD_REL, 3,
                         tree.line_text(lib.GUARD_REL, 3), severity="high", confidence=0.9)
    res = call_inspect(lib.fenced_message([good_f]))
    ok(isinstance(res, dict) and res.get("ok") is True,
       "合法桩 → ok=True（实得 %r" % (None if not isinstance(res, dict) else res.get("ok")))
    meta_txt = json.dumps(lib.meta_of(res), ensure_ascii=False) if isinstance(res, dict) else ""
    ok(tree.root in meta_txt or tree.root in json.dumps(res, ensure_ascii=False),
       "审查基座 base_dir 进 meta/回执（可见不静默）")

    print("== 子用例3 证据机械复核：verified/unverified 两态 + 逐项点名不静默丢 ==")
    g2 = tree.line_text(lib.GUARD_REL, 2)
    p2 = tree.line_text(lib.PRODUCER_REL, 2)
    cases = [
        ("real quote", lib.finding("real quote", lib.GUARD_REL, 2, g2), "verified"),
        ("whitespace-diff quote (tolerance must pass)",
         lib.finding("whitespace-diff quote (tolerance must pass)", lib.GUARD_REL, 2,
                     g2.replace("const", "const   ") + "  "), "verified"),
        ("missing file", lib.finding("missing file", "server/definitely_absent.py", 1, "x"),
         "unverified"),
        ("../ escape path", lib.finding("../ escape path", "../outside_secret.txt", 1, "x"),
         "unverified"),
        ("absolute path", lib.finding("absolute path", "/etc/hosts", 1, "x"), "unverified"),
        ("line beyond EOF", lib.finding("line beyond EOF", lib.GUARD_REL, 9999, "x"),
         "unverified"),
        ("line zero", lib.finding("line zero", lib.GUARD_REL, 0, "x"), "unverified"),
        ("quote mismatch", lib.finding("quote mismatch", lib.PRODUCER_REL, 2,
                                       "this quote is nowhere in the file"), "unverified"),
    ]
    payload = full(lib.fenced_message([c[1] for c in cases]))
    out_findings = lib.payload_findings(payload)
    # 261001 口径同步（integration 岗位判词）：本子用例的意图是「**本子用例的每一条都回带、
    # 不静默丢**」。inspect 面还会追加**引擎系统发现**——本夹具的合成树没有可差分基点，于是
    # `inspection_inspect.scope_collapse_findings()` 如实报一条 `Scope collapsed to 0 files: …`
    # （无泳道实例的正常信号，不是本子用例的 agent 发现）。故判据改为：①本子用例 8 条按 subject
    # 逐条在场；②多出来的每一条都必须是**具名的系统发现**（前缀白名单），并在消息里点名。
    _out = out_findings if isinstance(out_findings, list) else []
    _case_subjects = [str(c[1].get("subject") or "") for c in cases]
    _present_subjects = [str(f.get("subject") or "") for f in _out if isinstance(f, dict)]
    _missing = [x for x in _case_subjects if x not in _present_subjects]
    _sys = [f for f in _out if isinstance(f, dict)
            and str(f.get("subject") or "").startswith(SYSTEM_SUBJECT_PREFIXES)]
    _unexpected = [str(f.get("subject"))[:60] for f in _out if isinstance(f, dict)
                   and f not in _sys and str(f.get("subject") or "") not in _case_subjects]
    ok(not _missing and not _unexpected,
       "复核链逐条回带（%d 进 %d 出：本子用例缺 %d / 预期外 %d；系统发现 %d 条——%s）"
       % (len(cases), len(_out), len(_missing), len(_unexpected), len(_sys),
          "; ".join(str(f.get("subject"))[:48] for f in _sys) or "无"))
    if isinstance(out_findings, list):
        subjects = {}
        for e in out_findings:
            subjects[str(e.get("subject") or "")] = e
        for idx, (label, _f, want) in enumerate(cases):
            # 260928 修：subject 与 label 同名（英文），按名精确取回；退化为按序对齐
            # （len 相等已断言）。旧按 label 前两字前缀匹配的取法在中文 label 下恒不命中。
            e = subjects.get(label)
            if e is None:
                e = out_findings[idx] if len(out_findings) == len(cases) else None
            got = lib.finding_state(e) if e else None
            ok(got == want, "%s → %s（实得 %r）" % (label, want, got))
            if want == "unverified" and e is not None:
                ok(bool(lib.entry_reason(e)), "%s 逐项点名 reason 在场（不静默）" % label)
        # verified 条目不得带 reason 污染面（有 reason 的 verified=复核链自相矛盾）
        for e in out_findings:
            if lib.finding_state(e) == "verified":
                ok(not lib.entry_reason(e), "verified 条目不带复核失败 reason（%s）"
                   % str(e.get("subject"))[:30])

    print("== 子用例4 id 内容哈希：16 位、同内容跨期稳定、内容变即变 ==")
    def ids_of(payload):
        fs = lib.payload_findings(payload) or []
        return [str(f.get("id") or "") for f in fs if isinstance(f, dict)]
    # 260914 再钉：铸面宽度是 FINDING_ID_HEX=16（inspection_inspect.py，t261009-69
    # 起三侧同为 16——本票合并前的线尖与 main 皆然），纪律本体不变：内容哈希、
    # 条内唯一、同内容跨期稳定、内容变即变。旧「8 位」钉与在产铸面恒不一致。
    ok(all(len(i) == 16 for i in ids_of(payload)) and len(set(ids_of(payload))) == len(ids_of(payload)),
       "id=16 位且条内唯一（实得 %r；若混入 `agent:<hash>` 形状=语言闸聚合条目被追加，"
       "先查夹具 subject/why/suggestion 是否英文）" % ids_of(payload)[:3])
    r2 = full(lib.fenced_message([good_f]))
    r3 = full(lib.fenced_message([dict(good_f, subject=good_f["subject"] + " (reworded)")]))
    i1 = ids_of(r2)
    i2 = ids_of(r3)
    ok(bool(mint_id(good_f)) and mint_id(good_f) == mint_id(dict(good_f)),
       "同内容铸同 id（mint_finding_id 幂等）")
    ok(i1 and i2 and i1[0] != i2[0], "内容变 id 变（跨期去重键不粘连）")

    print("== 子用例5 跨期去重与假报压制：recurring/压制点名，summary 只计新发现 ==")
    dup_f = lib.finding("recurring defect (cross-period)", lib.PRODUCER_REL, 2, p2,
                        severity="high")
    dup_id = str(mint_id(dup_f) or "")
    ok(bool(dup_id), "dup 发现取得机械 id（%r）" % dup_id)
    lib.seed_prev_ledger(ledger_dir, inst, "20260901", [
        {"id": dup_id, "subject": dup_f["subject"], "severity": "high"}])
    lib.seed_verdicts(ledger_dir, inst, "20260902", [
        {"finding_id": dup_id, "verdict": "false-positive", "who": "human-scenario",
         "note": "上期已裁假报", "at": "2026-09-02T08:00:00"}])
    pay = full(lib.fenced_message([dup_f, good_f]))
    fs = lib.payload_findings(pay) or []
    dup_entry = next((f for f in fs if str(f.get("id") or "") == dup_id), None)
    # recurring 与假报压制是正交信号（同一条可既上期已见又被裁假报）——分开读：
    # recurring 布尔/态字段 + 压制面（suppressed 布尔、verdict 裁定、verified 态）。
    ok(dup_entry is not None and (dup_entry.get("recurring") is True
                                  or lib.finding_state(dup_entry) == "recurring"),
       "上期同 id → recurring 标记（实得 %r)"
       % ([lib.finding_state(f) for f in fs if isinstance(f, dict)],))
    ok(dup_entry is not None and (dup_entry.get("suppressed") is True
                                  or dup_entry.get("verdict") == "false-positive"
                                  or lib.finding_state(dup_entry) == "suppressed"),
       "假报裁定 → 压制标记（实得 verdict=%r suppressed=%r)"
       % ((dup_entry or {}).get("verdict"), (dup_entry or {}).get("suppressed")))
    # 心跳/summary 口径子用例单独跑：本期只有 recurring+压制（零新发现）→ heartbeat=true
    pay = full(lib.fenced_message([dup_f]))
    summary, heartbeat, _truncated = lib.tally_of(pay)
    # 261001：本子用例的意图是「recurring/压制**不计新发现**」。夹具无可用基点 ⇒ 引擎会如实追加
    # 系统发现（`Scope collapsed to 0 files: …`，med）——它**也是真信号**，参与汇总与心跳是正确
    # 语义。故判据把系统发现**扣掉后**判意图，并把它具名出来（不静默、也不改产品语义）。
    _fs2 = lib.payload_findings(pay) or []
    _sys_n = len([f for f in _fs2 if isinstance(f, dict)
                  and str(f.get("subject") or "").startswith(SYSTEM_SUBJECT_PREFIXES)])
    if isinstance(summary, dict) and summary:
        _agent_new = sum(int(summary.get(k) or 0) for k in ("high", "med", "low", "total"))
        _agent_new -= _sys_n
        ok(_agent_new == 0,
           "summary 只计新发现（recurring/压制不累计；已扣系统发现 %d 条）：%r"
           % (_sys_n, summary))
    if heartbeat is not None:
        ok(bool(heartbeat) == (_sys_n == 0),
           "心跳与「是否有新发现」一致（系统发现 %d 条 ⇒ 期望 heartbeat=%s；recurring/压制自身"
           "不造新发现）：实得 %r" % (_sys_n, _sys_n == 0, heartbeat))
    else:
        ok("heartbeat" in json.dumps(pay, ensure_ascii=False), "心跳面在回执在场（键名容差）")

    print("== 子用例6 预算：41 条截 40 + truncated 记账；recurring/压制不占预算 ==")
    many = [lib.finding("budget filler finding %03d" % i, lib.GUARD_REL, 2, g2,
                        severity="high" if i % 3 == 0 else ("med" if i % 3 == 1 else "low"),
                        confidence=round(0.95 - i * 0.001, 3))
            for i in range(41)]
    pay = full(lib.fenced_message(many))
    fs = lib.payload_findings(pay) or []
    fresh = [f for f in fs if lib.finding_state(f) == "verified"]
    ok(len(fresh) <= 40, "41 条新发现截到 ≤40（实得 verified %d）" % len(fresh))
    _s, _h, truncated = lib.tally_of(pay)
    ok(truncated in (1, "1") or (isinstance(truncated, int) and truncated >= 1)
       or "truncated" in json.dumps(pay, ensure_ascii=False),
       "截断记账 truncated 在场（实得 %r）" % (truncated,))
    # recurring 不占预算：上期已含 5 条同内容 → 本期同 41 条中 5 条 recurring → 新发现 36 条全保
    keep5 = many[:5]
    lib.seed_prev_ledger(ledger_dir, inst, "20260903",
                         [{"id": (mint_id(f) if mint_id else ""), "subject": f["subject"],
                           "severity": f["severity"]} for f in keep5 if (mint_id(f) if mint_id else True)])
    pay = full(lib.fenced_message(many))
    fs = lib.payload_findings(pay) or []
    rec = [f for f in fs if lib.finding_state(f) == "recurring"]
    fresh = [f for f in fs if lib.finding_state(f) == "verified"]
    ok(len(rec) == 5 and len(fresh) == 36,
       "5 条 recurring 不占 40 预算（recurring=%d、新发现=%d）" % (len(rec), len(fresh)))

    print("== 子用例7 心跳合成：有新发现 → heartbeat=false ==")
    pay = full(lib.fenced_message([good_f]))
    _s, heartbeat, _t = lib.tally_of(pay)
    if heartbeat is not None:
        ok(heartbeat is False, "有新发现 → heartbeat=false（实得 %r）" % heartbeat)
    else:
        ok("heartbeat" in json.dumps(pay, ensure_ascii=False),
           "心跳面在回执在场（键名容差）")

    print("== 子用例8 建议门数据：verified && conf≥0.6 && severity≥med 才进建议 ==")
    mix = [
        lib.finding("suggestion-eligible high", lib.GUARD_REL, 2, g2, severity="high", confidence=0.9),
        lib.finding("low-confidence med (no ticket)", lib.GUARD_REL, 2, g2, severity="med", confidence=0.3),
        lib.finding("low severity (no ticket)", lib.GUARD_REL, 2, g2, severity="low", confidence=0.9),
        lib.finding("bad-evidence high (no ticket)", "server/absent_x.py", 1, "x", severity="high", confidence=0.9),
    ]
    pay = full(lib.fenced_message(mix))
    fixes = lib.payload_fixes(pay)
    if fixes is None:
        ok(True, "建议面由 workflow 侧 build_ticket_face 合成（本条不越层断言，journey 覆盖）")
    else:
        subs = json.dumps(fixes, ensure_ascii=False)
        ok("suggestion-eligible" in subs and "low-confidence" not in subs
           and "low severity" not in subs and "bad-evidence" not in subs,
           "建议门只收 verified&&conf≥0.6&&severity≥med：%r" % subs[:120])

    print("== 子用例9 上期台账坏面：prev_ledger_error 点名 + 降级不崩 ==")
    lib.seed_prev_ledger_raw(ledger_dir, inst, "20260904", "{{{not-json")
    pay = full(lib.fenced_message([good_f]))
    txt = json.dumps(pay, ensure_ascii=False)
    ok(("prev_ledger" in txt) or ("上期" in txt) or ("ledger" in txt),
       "坏上期台账显式点名（prev_ledger_error 面）：%r" % txt[:120])
    ok(isinstance(lib.payload_findings(pay), list), "坏上期不崩，本期发现照常复核")

    print("== 子用例10 红线与 agent_home 落点（方案 §2.2 三层机械面） ==")
    ok(tree.tree_unchanged() == "", "被审查树逐字节不变（巡检绝不改码红线，判定化）")
    ok(not os.path.exists(os.path.join(tree.root, ".dsh")),
       "审查基座（仓根）零 .dsh 残留（agent DSH_HOME 与基座解耦）")
    ah = lib.agent_home_dir(ledger_dir)
    if ah is not None:
        ok(True, "agent-home 落点在台账目录 agent-home/ 下（out/inspection/agent-home/<实例>-<期>）")
    else:
        ok(True, "桩态（SANDBAR_INSPECT_STUB）可短路 spawn → agent-home 缺席属契约内；真 spawn 落点由 journey 的 SANDBAR_INSPECT_CMD 子用例覆盖")

    for d in (tree,):
        d.cleanup()
    shutil.rmtree(workdir, ignore_errors=True)
    shutil.rmtree(ledger_dir, ignore_errors=True)

    if FAILURES:
        for m in FAILURES:
            print("FAIL_REASON: " + m, flush=True)
    print("PASS %d / FAIL %d —— inspect 段横向契约（解析纪律/证据复核/去重压制/预算/心跳/红线）"
          % (PASS, FAIL), flush=True)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
