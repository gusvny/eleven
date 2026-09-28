#!/usr/bin/env python3
"""t260921-08 场景：巡检引文超长软提醒（宿主令 260921「软提醒不判红」，灰盒 L2 离线桩缝）。

用户场景（工单验收 1~5 + L2 要求）：t260922-01 实案——agent 输出里一条证据引文
227 字 > 上限 200，旧实现把「一处擦边超限」判成整份畸形：inspect 段失败 → 票
blocked → 当日报告 findings=0、suggested_fix_tickets=[]（六条已写出的发现陪葬
=巡检零产出）。本场景用同形态夹具（227 字引文锚真实文件行）驱动 inspect 解析
入口，断言事故形态被复现且不再报废：段不失败、发现全部在册、超长引文截断保
前缀+标注+人话点名、报告计数位在场、建议生成路径仍只看 verified；同入口硬红
形态（空 quote / 围栏缺失 / 围栏内坏 JSON）fail-closed 不放松（新旧边界配对，
防「放松防幻觉面」的回归）。

intent 分工（防 intent 级重复）：
- t260916-22-inspect-contract（L2）：解析八态/复核八态/预算矩阵/去重压制/id 铸造
  的活动缝横向契约全矩阵——本条不复写；
- t260916-22-inspect-journey（L3）：真台真票全链旅程（真 spawn/超时/人门/落账）——
  本条不起台不 spawn；
- 本条只守「引文超长软提醒」差异面 + 事故回归（新旧行为对照留痕：旧=227 字→
  整份拒收 findings=0；新=227 字→在册+截断标注+点名+计数位）。

三态纪律（t260904-12）：exit 0=PASS / 1=FAIL（产品红点名）/ 2=ENV_FAIL（环境缺供点名）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
跑法：python3 -B integration/t260921-08/sc_inspect_quote_overlong_soft_warn.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import lib_overlong as fx  # noqa: E402

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
    inst = "inspect-overlong-%05d" % (os.getpid() % 100000)
    period = "20260922"
    base = fx.build_evidence_tree(tempfile.mkdtemp(prefix="sandbar-overlong-base-"))
    ledger_dir = tempfile.mkdtemp(prefix="sandbar-overlong-ledger-")

    # 夹具自检（夹具失真=FAIL 点名，不假绿）：实案字数 227 必须真是样本行的前缀
    ok(len(fx.LONG_QUOTE) == 227, "夹具引文 227 字（实案字数，> 上限 200）")
    ok(fx.LONG_LINE.startswith(fx.LONG_QUOTE) and len(fx.LONG_LINE) >= 227,
       "夹具引文是 238 字样本行的真实前缀（复核可校验面）")

    try:
        activities, agent_activities, _inspect, flow = fx.load_engine_modules()
    except (ImportError, OSError) as e:
        print("ENV_FAIL: 引擎模块离线加载失败（%s：%s）——环境缺供点名，不判产品红" % (type(e).__name__, e))
        return 2
    try:
        run_inspect = agent_activities.run_inspection_inspect
        verify_findings = activities.verify_inspection_findings
        build_face = flow.build_ticket_face
    except AttributeError as e:
        print("FAIL_REASON: 巡检活动/票面函数未交付（%s）——红属预期（实现段落地前 TDD 信号）" % e)
        return 1

    saved = {k: os.environ.get(k) for k in fx.STUB_ENV_NAMES}
    try:
        def drive_inspect(message_text):
            """桩缝驱动解析入口（方案缝名：SANDBAR_INSPECT_STUB=1 + STUB_FILE）。"""
            stub = fx.write_stub_file(ledger_dir, "stub-%s.json" % inst, message_text)
            os.environ.update(fx.stub_env(stub))
            os.environ["SANDBAR_INSPECTION_DIR"] = ledger_dir
            return fx.run_coro(run_inspect(
                fx.inspect_args(inst, period, base, ledger_dir)))

        # ---- S1 事故形态主道：227 字引文 → 段不失败、在册、截断+标注+人话点名 ----
        payload = drive_inspect(fx.fenced_message(fx.incident_findings()))
        ok(isinstance(payload, dict) and payload.get("ok") is True,
           "S1 事故形态：227 字引文 → inspect 段不失败"
           "（旧码此处整份拒收=当日 findings=0 事故复现位）")
        result = (payload or {}).get("result") or {}
        findings = result.get("findings")
        usable = isinstance(findings, list) and len(findings) == 3
        ok(usable, "S1 三条发现全部在册（不陪葬，findings 非空）")
        if usable:
            f0, f1, f2 = findings
            ev0 = (f0.get("evidence") or [{}])[0]
            ok(ev0.get("quote") == fx.LONG_LINE[:200],
               "S1 超长引文截到上限 200 且是原行前缀（report 段复核仍可校验）")
            ok(ev0.get("quote_truncated") is True
               and ev0.get("quote_original_chars") == 227,
               "S1 截断标注在证据项（quote_truncated / quote_original_chars=227）")
            blob = str(f0)
            ok("227" in blob and "200" in blob and "截断" in blob,
               "S1 人话点名在发现上（含 227>200 与「截断」可读字样，响亮不静默）")
            warns = f0.get("quote_warns")
            ok(isinstance(warns, list) and len(warns) == 1,
               "S1 逐项点名列表明细在场（quote_warns 恰 1 条）")
            ev1 = (f1.get("evidence") or [{}])[0]
            ev2 = (f2.get("evidence") or [{}])[0]
            ok("quote_truncated" not in ev1 and "quote_truncated" not in ev2,
               "S1 未超长证据零新键（一处超限只影响那一条）")
        else:
            ok(False, "S1 发现清单不可用（旧形态：超长判红整份拒收）——复核/票面无从断言")

        # ---- S2 硬红对照（同入口新旧边界配对：不可定位形态仍 fail-closed） ----
        p_noquote = drive_inspect(
            fx.fenced_message(fx.incident_findings(empty_quote=True)))
        ok(isinstance(p_noquote, dict) and p_noquote.get("ok") is False
           and "quote" in str(p_noquote.get("error")),
           "S2 空 quote → 仍 fail-closed 且报错点名 quote 检查（报错精确）")
        p_nofence = drive_inspect(
            fx.fenced_message([], n_blocks=0, preamble="没有围栏块的消息"))
        ok(isinstance(p_nofence, dict) and p_nofence.get("ok") is False,
           "S2 围栏块缺失 → 仍 fail-closed")
        p_badjson = drive_inspect(fx.fenced_message([], outer_json_valid=False))
        ok(isinstance(p_badjson, dict) and p_badjson.get("ok") is False,
           "S2 围栏内坏 JSON → 仍 fail-closed")

        # ---- S3 复核段：计数位、复核语义不变、对账 ----
        if usable:
            vres = fx.run_coro(verify_findings(
                fx.verify_args(inst, period, base, findings, ledger_dir)))
            ok(isinstance(vres, dict) and vres.get("ok") is True, "S3 复核段不失败")
            vpayload = (vres or {}).get("result") or {}
            vmeta = vpayload.get("meta") or {}
            ok(vmeta.get("quote_overlong_warn") == 1,
               "S3 报告计数位 quote_overlong_warn==1（verify meta 面）")
            ok(vmeta.get("truncated") == 0, "S3 预算未截断（40 条上限内）")
            vfs = vpayload.get("findings") or []
            v0 = vfs[0] if len(vfs) > 0 else {}
            v2 = vfs[2] if len(vfs) > 2 else {}
            ok(v0.get("verified") == "verified",
               "S3 截断引文=原行前缀 → 复核仍 verified（复核语义不变，防幻觉面保住）")
            ok(v2.get("verified") == "unverified"
               and bool(v2.get("unverified_reasons")),
               "S3 引文不符 → unverified 且 reason 点名（降级不静默丢）")
            ok(vmeta.get("quote_overlong_warn") == sum(
                len(f.get("quote_warns") or []) for f in vfs if isinstance(f, dict)),
               "S3 计数位与逐项点名可对账（1==1）")
        else:
            vpayload, vmeta, vfs = {}, {}, []
            ok(False, "S3 无法驱动（S1 未产出在册发现）")

        # ---- S4 票面/报告面：计数位在场、建议门只看 verified、发现不静默丢 ----
        if usable and vfs:
            face = build_face("t-sc-overlong", inst, period,
                              {"findings": vfs, "summary": vpayload.get("summary"),
                               "heartbeat": vpayload.get("heartbeat"),
                               "meta": vmeta})
            ok((face.get("scan_meta") or {}).get("quote_overlong_warn") == 1,
               "S4 报告计数位落在票面 scan_meta（报告形状看守：键必在场）")
            titles = [str(s.get("title", ""))
                      for s in face.get("suggested_fix_tickets") or []]
            # 260928 修：夹具叙述字段改英文（语言闸口径，见 lib_overlong.incident_findings
            # 注），按名取的判据随之一并改绑英文条名——判据语义（截断条照常开票、
            # 正常条开票、不符条不开票）逐字未变。
            ok(any("overlong" in t for t in titles),
               "S4 截断但复核过 → 照常进建议面（生成路径只看 verified）")
            ok(any("normal" in t for t in titles)
               and not any("mismatch" in t for t in titles),
               "S4 建议门对照：verified 进、unverified 不进")
            ok(len(face.get("findings") or []) == 3,
               "S4 三条发现全在票面（不静默丢，点名随行）")
        else:
            ok(False, "S4 无法驱动（前置面未产出）")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    if FAILURES:
        print("失败面：")
        for m in FAILURES:
            print(" -", m)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
