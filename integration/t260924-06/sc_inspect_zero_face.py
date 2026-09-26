#!/usr/bin/env python3
"""t260924-06 场景②：inspect 缩面「零发现显式」+预算记账+decl 上限键（灰盒 L2，纯离线桩缝）。

用户场景（工单病象直击）：连续三期 inspect 段跑满预算、台账恒空壳 findings=0——用户
从此可感知的行为承诺：①无新病灶时**显式声明**「本期无新病灶」并附证据面（审查范围
N 文件、输入面点名），空壳 findings=0 不复存在；②预算记账在册（used_sec 进 inspect
meta，workflow 侧 >90% 预算票面点名「先报实测再谈预算」）；③分片上限 decl 键
（inspect_max_shards/inspect_max_files_per_shard）被声明解析器接受且缺省 4/40。

子用例面分工：sc①（scope_input）守输入面/截断/四路畸形；本条守**产出面**——零发现
显式（build_ticket_face 渲染缝）、预算记账、decl 键；t260916-22-inspect-contract 守
零发现心跳/复核/去重（彼 heartbeat 面仍有效，本条不复写 heartbeat，只守「零发现必带
证据面」新契约）；developer L1 守纯函数真值表。预算记账离线面：桩路径无模型耗时，
used_sec 实测值归真 spawn 链（生产路径已记，离线不可驱动）——本条在桩链断 meta.scope
证据结构+票面渲染缝（U7 口径），used_sec>90% 点名分支只核记账缝在册（真值表归
developer L1），不在离线桩链钉实测值。

依据：工单要点③（零发现显式）④（预算护栏）②（上限键）+验收 U6/U7/U8；KI-049
（空壳=不可归因的假绿形态）；三期零产出实录=本条存在的直接理由。
环境语义：temporalio 桩缺席=ENV_FAIL exit 2；实现未落地=FAIL（TDD 信号），
arbitrate/merge 期必须绿。
跑法：python3 -B integration/t260924-06/sc_inspect_zero_face.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_scope as lib  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []
MARK_ZERO = ["No new defects this period", "review scope"]   # 260927 报告英文面（宿主令）


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        FAILURES.append(msg)
        print("  FAIL", msg)


def _engine_path(name):
    import lib_inspection  # noqa: PLC0415
    return os.path.join(lib_inspection.TP_DIR, name)


def main() -> int:
    print("== t260924-06 场景②：零发现显式+预算记账+decl 上限键（离线桩缝）")
    try:
        drv = lib.InspectDriver()
    except ImportError as e:
        print("ENV_FAIL: temporalio 桩/引擎模块缺席：%r" % (e,))
        return 2
    except AttributeError as e:
        ok(False, "引擎缝缺失（实现未落地，TDD 信号）：%r" % (e,))
        print("汇总 pass=%d fail=%d" % (PASS, FAIL))
        return 1
    try:
        inst = "it-zero"
        repo, prev, this = lib.make_base_repo(drv._tmp, n_changed=2)
        drv.seed_prev(inst, "20260923", base_ref=prev)
        suite = lib.write_suite_receipt(drv._tmp)
        lib.write_ki_under(repo)

        # --- ① 空桩 findings → ok + meta.scope 证据结构 + 票面「本期无新病灶」渲染 ---
        args = lib.scope_args(inst, "20260924", repo, this, suite_path=suite)
        pay = drv.run(args, stub_findings=[])
        ok(drv.result_ok(pay), "①空 findings 活动 ok=true")
        findings = ((pay.get("result") or {}).get("findings")
                    if isinstance(pay, dict) else None)
        ok(findings == [], "①findings==[]（零发现桩）")
        m = drv.meta(pay)
        ok(isinstance(m.get("scope"), dict) and m["scope"].get("scope_files") == 2,
           "①meta.scope 证据结构在册（scope_files==2，零发现也带证据面）")
        from inspection_flow import build_ticket_face
        face = build_ticket_face("t-zero", inst, "20260924",
                                 {"findings": [], "meta": {"scope": m["scope"]}})
        note = str(face.get("zero_findings_note") or "")
        ok(all(mk in note for mk in MARK_ZERO),
           "①票面渲染「本期无新病灶（审查范围 N 文件…）」——不再空壳 findings=0")

        # --- ② 预算记账缝在册：生产链记 used_sec、flow 侧 >90% 预算渲染 budget_note
        #     （实测值归真 spawn 链，离线桩零模型调用无实测面——不在桩链钉值） ---
        act_src = open(_engine_path("agent_activities.py"), encoding="utf-8").read()
        flow_src = open(_engine_path("inspection_flow.py"), encoding="utf-8").read()
        ok("used_sec" in act_src, "②生产链 meta 记 used_sec（预算实测面）")
        ok("budget_note" in flow_src and "0.9" in flow_src,
           "②flow 侧 used_sec>90% 预算渲染 budget_note（先报实测再谈调预算）")

        # --- ③ decl 上限键：解析器接受 inspect_max_shards / inspect_max_files_per_shard ---
        try:
            import inspection_decl as decl_engine
            fn = (getattr(decl_engine, "decl_from_mapping", None)
                  or getattr(decl_engine, "decl_from_file"))
            base_inst = {"id": "it-zero", "enabled": "true", "project_key": "sandbar",
                         "workflow": "InspectionPeriodicWorkflow",
                         "template": "inspection-lite",
                         "schedule": {"kind": "cron", "cron": "0 6 * * 1"}}
            spec = fn({"schema": "v1", "instances": [dict(base_inst,
                                                          inspect_max_shards="2",
                                                          inspect_max_files_per_shard="7")]})
            got = (spec.instances or [spec])[0]
            ok(getattr(got, "inspect_max_shards", None) == 2
               and getattr(got, "inspect_max_files_per_shard", None) == 7,
               "③decl 解析器接受两上限键并落 InstanceSpec")
            spec2 = fn({"schema": "v1", "instances": [dict(base_inst, id="it-zero2")]})
            got2 = (spec2.instances or [spec2])[0]
            ok(getattr(got2, "inspect_max_shards", None) == 4
               and getattr(got2, "inspect_max_files_per_shard", None) == 40,
               "③缺省 4/40 在册")
        except Exception as e:  # noqa: BLE001  拒收/形状两不沾=FAIL 点名，不炸场景
            ok(False, "③decl 上限键解析失败：%r" % (e,))

        # --- ④ 桩夹具缺失：既有 _err 短路语义不静默空过（U8 回归面） ---
        pay4 = drv.run(lib.scope_args(inst, "20260924", repo, this), stub_missing=True)
        ok((isinstance(pay4, dict) and pay4.get("ok") is not True)
           or "夹具缺失" in drv.payload_text(pay4),
           "④桩夹具缺失=点名失败，不静默空过（既有 _err 语义维持）")

        print("汇总 pass=%d fail=%d" % (PASS, FAIL))
        return 0 if FAIL == 0 else 1
    except Exception as e:  # noqa: BLE001  场景自身崩=FAIL 点名，不假绿不静默
        ok(False, "场景异常（点名）：%r" % (e,))
        print("汇总 pass=%d fail=%d" % (PASS, FAIL))
        return 1
    finally:
        drv.close()


if __name__ == "__main__":
    sys.exit(main())
