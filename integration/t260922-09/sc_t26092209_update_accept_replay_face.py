#!/usr/bin/env python3
"""t260922-09 场景二：工单 update 写面「受理真落与旧历史重放」契约（灰盒 L2，离线桩驱动真引擎类）。

用户场景（工单正文 + t260922-09 方案 gen3 §2.6 重放纪律）：①宿主口径「回执与副作用
必须一致」——ok:true 必须意味着真的落了（status 变、updated 刷、请求 note 进票面
log）；②blocked 票的合法清出口必须保住（今日四张 utmr 僵态票最后只能 terminate
收尾——修复只修「先写后校验」，绝不收窄合法恢复路径）；③update 是 Temporal
@workflow.update：返回值作为完成载荷记入事件历史、重放时 handler 重新执行且载荷
比对，回执形状变更（2 键→4 键）对含旧拒收回执历史的存活票是 Nondeterminism 风险
（票僵死只能 terminate——恰是本票要治的病），故新旧两分支由 patched 版本化承载：
旧历史重放逐字复刻旧两键回执且零留痕，新历史走四键+留痕。

本场景钉「受理与重放面」的用户可感知契约（被拒审计面归
sc_t26092209_update_reject_audit_face）：
  A. 受理真落（正侧）：blocked 票合法 update → ok:true 且副作用真的落了
     （status 落、updated 刷新到当前时刻、请求 note 原文进票面 log、回执带
     status/log_len 可判定键）——回执与副作用一致的正半边。
  B. 僵态恢复路径原样：status=closed×stage_state=blocked 的僵态票（今日实案后遗形）
     update dispatched → ok:true——允许集合三分支的清出口一个不动（要求 4）。
  C. 旧历史重放兼容：patched=False（旧语义）下同一拒绝输入 → 回执恰为 {'ok','error'}
     两键（keys 相等断言，多一键=旧存活票重放即 Nondeterminism=产品红）、error 文案
     与新分支等值、refused/log/业务字段零变化（重放逐字节对上，旧拒绝不追溯补落）。
  D. 受理面与重放旗无关：合法 update 在 patched 两旗下回执键集一致且 ok:true
     （accept 路径零重放面承诺的可感知兑现）。
  E. 双类 parity：受理正例在两个工作流类上回执形状一致（同名 update 透明服务）。

依据三支：①工单原始 user_request（要求 3 回执与副作用一致、要求 4 A3.5 语义不变/
允许集一个不动；宿主令「校验须在写之前」的受理半边）；②已知问题清单：本票事故的
僵态半边（blocked×closed 常规入口清不动→terminate）即 KI 级实案，B 为其直接回归
锁；temporalio 1.18.2 源码实证（vendored：worker/_workflow_instance.py do_update
job 重执行 + update_state_machine.rs 完成载荷匹配/Nondeterminism）支撑 C 的存在
理由；③对外契约=update 回执形状与 patched 版本化承诺（t260922-09 方案 gen3 §2.6/
§5-9），锚承诺不锚实现。

分工（防 intent 级重复）：被拒审计面（零副作用/留痕可查/结构化回执/超长有界）归
sc_t26092209_update_reject_audit_face，本条不重复；developer L1 真值表白盒钉
handler 两侧与 patched 常数推导断言，本条灰盒只钉用户可感知终态（两键回执恰好、
accept 两旗同形、僵态恢复、双类 parity）；t260908-01/t260914-04 守 pause/rework
旅程（signal 面），t260912-03/t260913-01 守授权/信号送达（sign 面），均不同写面
不互替。纯离线（stub temporalio+真引擎类，无 ENV 子用例）；引擎模块离线加载失败=
产品红（被测对象就是引擎模块本身）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B integration/t260922-09/sc_t26092209_update_accept_replay_face.py
"""
import copy
import sys

from lib_t26092209 import (  # noqa: E402  # 夹具先于断言装配（含桩与路径）
    blocked_meta,
    call_update,
    mk_base,
    mk_devlane,
    set_patched,
    snapshot_of,
)

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok    %s" % msg)
    else:
        FAIL += 1
        print("FAIL  %s" % msg)


def leg_accept_really_lands():
    """A：受理真落——ok:true ⟺ 副作用已落（正侧一致性）。"""
    wf = mk_devlane(blocked_meta())
    before = copy.deepcopy(snapshot_of(wf))
    r = call_update(wf, "dispatched", "继续推进（宿主令解除 blocked）", "", None)
    ok(r.get("ok") is True, "A 合法 update 受理 ok=true")
    after = snapshot_of(wf)
    ok(after.get("status") == "dispatched", "A status 真落（快照面可查）")
    ok(after["meta"].get("updated") != before["meta"].get("updated"),
       "A updated 已刷新（受理必须触 updated）")
    log = after["meta"].get("log") or []
    ok(len(log) == len(before["meta"].get("log") or []) + 1
       and log[-1].get("note") == "继续推进（宿主令解除 blocked）",
       "A 请求 note 原文进票面 log")
    ok(r.get("status") == "dispatched" and "log_len" in r,
       "A 回执带可判定键（status/log_len）")


def leg_stuck_ticket_recovery():
    """B：僵态恢复——closed×blocked 票 update dispatched 走得通（允许集清出口原样）。"""
    wf = mk_devlane(blocked_meta(status="closed"))
    r = call_update(wf, "dispatched", "僵态恢复", "", None)
    ok(r.get("ok") is True, "B 僵态票合法清出口 ok=true")
    ok(snapshot_of(wf).get("status") == "dispatched",
       "B 僵态票 status 真落（恢复路径语义不变）")


def leg_legacy_replay_two_key_receipt():
    """C：旧历史重放兼容——patched=False 拒收回执恰两键、零留痕、文案等值。"""
    wf = mk_devlane(blocked_meta())
    # 新分支（旗=True）拿基准文案
    set_patched(True)
    r_new = call_update(wf, "closed", "n", "", None)
    ok(r_new.get("ok") is False and r_new.get("kind") == "blocked_status_guard",
       "C 前置：新分支四键拒收在位（kind=blocked_status_guard）")
    # 旧语义（旗=False）：重放兼容面
    wf_old = mk_devlane(blocked_meta())
    before = copy.deepcopy(snapshot_of(wf_old))
    set_patched(False)
    r_old = call_update(wf_old, "closed", "n", "", None)
    set_patched(True)
    ok(set(r_old.keys()) == {"ok", "error"},
       "C 旧语义回执恰 {'ok','error'} 两键（多一键=旧存活票重放 Nondeterminism）")
    ok(r_old.get("error") == r_new.get("error"),
       "C 旧语义 error 文案与新分支等值（短回显下逐字一致）")
    after = snapshot_of(wf_old)
    ok(after.get("refused") == before.get("refused"),
       "C 旧语义零 refused 留痕（重放不造幽灵条目）")
    ok(after["meta"].get("log") == before["meta"].get("log"),
       "C 旧语义零 log 增行")
    ok(all(after["meta"].get(k) == before["meta"].get(k)
           for k in ("status", "stage_state", "updated")),
       "C 旧语义业务字段零变化（重放逐字节对上）")


def leg_accept_flag_independent():
    """D：受理面与重放旗无关——合法 update 在两旗下回执键集一致且 ok:true。"""
    receipts = []
    for flag in (True, False):
        set_patched(flag)
        wf = mk_devlane(blocked_meta())
        receipts.append(call_update(wf, "dispatched", "n", "", None))
    set_patched(True)
    ok(set(receipts[0].keys()) == set(receipts[1].keys()),
       "D accept 回执键集与 patched 旗无关（零重放面承诺）")
    ok(all(r.get("ok") is True for r in receipts),
       "D 两旗下受理均 ok:true（旧票重放中跑合法 update 同样安全）")


def leg_cross_class_accept_parity():
    """E：受理正例双类 parity（同名 update 透明服务两工作流类）。"""
    shapes = []
    for mk in (mk_devlane, mk_base):
        wf = mk(blocked_meta())
        r = call_update(wf, "dispatched", "n", "", None)
        shapes.append((set(r.keys()), r.get("ok"), snapshot_of(wf).get("status")))
    ok(shapes[0][0] == shapes[1][0], "E 两类 accept 回执键集一致")
    ok(shapes[0][1] == shapes[1][1] is True, "E 两类 accept 均 ok:true")
    ok(shapes[0][2] == shapes[1][2] == "dispatched",
       "E 两类 status 真落一致")


def main():
    legs = [
        leg_accept_really_lands,
        leg_stuck_ticket_recovery,
        leg_legacy_replay_two_key_receipt,
        leg_accept_flag_independent,
        leg_cross_class_accept_parity,
    ]
    for leg in legs:
        set_patched(True)  # 每条子用例复位新语义；C 子用例内部自管旗
        try:
            leg()
        except Exception as exc:  # 子用例炸=该子用例 FAIL（不静默、不连坐）
            global FAIL
            FAIL += 1
            print("FAIL  %s 异常：%r" % (leg.__name__, exc))
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
