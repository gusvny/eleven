#!/usr/bin/env python3
"""t260922-09 场景一：工单 update 写面「被拒审计面」契约（灰盒 L2，离线桩驱动真引擎类）。

用户场景（工单正文，宿主 260922 实案）：ops/宿主清理 blocked 残渣票时对票发
`update status=closed`（带 note + 跨项目记名旗），旧引擎回执 ok:false 说「被拒」，
票面却已被改（status=closed、无留痕、updated 不动）——操作被拒但副作用已发生、
被拒无任何留痕、回执还说成失败，三者互相矛盾；事后审计看不出是谁、为什么动的，
且 status=closed×stage_state=blocked 的票从此常规入口再也清不动（只能 terminate）。

本场景钉「被拒面」的用户可感知契约（票面要求 1/2 的验收口径；受理与重放面归
sc_t26092209_update_accept_replay_face）：
  A. 结构化拒收回执：被拒回执 ok=false 且必带 kind/reason 结构化字段（不再只有一句
     error 字符串——宿主口径原话）；error 键保留（只读 error 的既有消费者零破坏）。
  B. 拒绝=业务字段零副作用：status/stage_state/updated/pending/book_path/
     cross_project_uses 与拒前逐字段全等（快照查询面判，不翻引擎内部）。
  C. 被拒必留痕且可查：快照 refused 面恰增 1 条（who 非空记名位+at 时间位+want=
     update+kind 点名守卫族+why 原因）；票面 log 恰增 1 行且为拒绝行——含原因语义词
     面（A3.5/非法），不含请求 note 原文（请求载荷不因被拒进事件面）。
  D. 今日实案回归形：blocked+closed+全载荷（note/pending_add/book_path）——「关票
     无痕」绝迹的直接验收；第二出集值 verified 同形（防只钉 closed 的窄测）。
  E. 畸形/超长输入三态：非法 status（含 wire 直发形）→ illegal 族拒收+零副作用+
     留痕；10 万字符畸形 status → 留痕有界（数量级上界，原文绝不进快照查询面）。
  F. wire 形状兼容：恰按现行线上四位置实参调用（无 who 位）→ 不炸、留痕 who 位
     非空显式记名（未记名也是名，不是空串更不是缺键）。
  G. 双类 parity：同名 update 服务两个工作流类（client.py 按名分发透明服务）——
     同一拒绝输入下回执形状、refused 条目形状两类一致（漂移即用户可感知不一致）。

依据三支：①工单原始 user_request 与宿主口径（校验前置/被拒留痕/回执与副作用一致，
拒绝=零副作用、留痕含原因+who+时间、回执带结构化字段、A3.5 允许集不动）；②已知问题
清单（notes/debts/known-issues.md）：本票事故即 KI 级实案（260922 四张 utmr 残渣票
terminate 收尾），本场景按事故回归纪律钉 L2 契约面；KI-031（收口票可见性）/approve 侧
留痕缺口均为另票，不混面；③对外契约=update 回执形状与快照查询面键（t260922-09 方案
gen3 §2/§5 承诺），锚承诺不锚实现——契约不变的实现重构不得打破本场景。

分工（防 intent 级重复）：developer L1（server/engine/tests/test_t260922_09_*.py）
白盒真值表钉 handler 逻辑两侧、可随实现重构；本条灰盒钉用户可感知契约面（快照查询面
可见的留痕与零副作用、wire 四参形状、双类 parity）；t260915-12 跨项目闸场景守项目
归属维（update 面本就不盖章），本条只钉「拒绝不触碰 cross_project_uses」的零副作用
半边，不碰闸行为；t260910-06 守 CLI 入口包装/审计面，本条不碰 CLI 层。
纯离线（stub temporalio+真引擎类，无 ENV 子用例）；引擎模块离线加载失败=产品红
（被测对象就是引擎模块本身，不归环境）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B integration/t260922-09/sc_t26092209_update_reject_audit_face.py
"""
import copy
import json
import sys

from lib_t26092209 import (  # noqa: E402  # 夹具先于断言装配（含桩与路径）
    LOG_BOUND,
    WHY_BOUND,
    blocked_meta,
    call_update,
    mk_base,
    mk_devlane,
    set_patched,
    snapshot_of,
)

PASS = 0
FAIL = 0
REQUEST_NOTE = "清理残渣：关票（宿主令 260922）"


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok    %s" % msg)
    else:
        FAIL += 1
        print("FAIL  %s" % msg)


def business_fields_untouched(wf, before_snap):
    """B：业务字段逐字段全等（经快照查询面；log/refused/updated 由各自子用例单判）。"""
    after = snapshot_of(wf)
    keys_ok = all(after.get(k) == before_snap.get(k)
                  for k in ("status", "stage_state", "pending"))
    meta_keys_ok = all(after["meta"].get(k) == before_snap["meta"].get(k)
                       for k in ("updated", "book_path", "cross_project_uses"))
    return keys_ok and meta_keys_ok, after


def leg_today_incident_form():
    """D+A+B+C：今日实案形 blocked→closed 全载荷被拒——零副作用+留痕+结构化回执。"""
    wf = mk_devlane(blocked_meta())
    before = copy.deepcopy(snapshot_of(wf))
    r = call_update(wf, "closed", REQUEST_NOTE, "补一条 pending", "/tmp/book.md")
    ok(r.get("ok") is False, "A 今日实案形被拒：ok=false")
    ok(isinstance(r.get("kind"), str) and r.get("kind") != "",
       "A 回执带结构化 kind（不再只有一句 error）")
    ok(isinstance(r.get("reason"), str) and r.get("reason") != "",
       "A 回执带结构化 reason")
    ok("error" in r, "A error 键保留（旧消费者兼容）")
    untouched, after = business_fields_untouched(wf, before)
    ok(untouched, "B 业务字段零副作用（status/stage_state/pending/updated/"
                  "book_path/cross_project_uses 全等）")
    ok(after["meta"].get("updated") == before["meta"].get("updated"),
       "B updated 未刷新（拒绝不触碰 updated）")
    refused = after.get("refused") or []
    ok(len(refused) == len(before.get("refused") or []) + 1,
       "C 快照 refused 面恰增 1 条（留痕可查）")
    if refused:
        e = refused[-1]
        ok(e.get("want") == "update", "C refused 条目 want=update")
        ok(isinstance(e.get("who"), str) and e.get("who") != "",
           "C refused 条目 who 非空（未记名也是显式名）")
        ok(bool(e.get("at")) and bool(e.get("why")),
           "C refused 条目 at/why 在（时间+原因）")
        ok("A3.5" in str(e.get("why", "")),
           "C why 点名 A3.5 守卫语义")
    log = after["meta"].get("log") or []
    ok(len(log) == len(before["meta"].get("log") or []) + 1,
       "C 票面 log 恰增 1 行（拒绝行）")
    if log:
        note = str(log[-1].get("note", ""))
        ok("A3.5" in note and "被拒" in note,
           "C 拒绝行含原因语义词面（A3.5+被拒）")
        ok(REQUEST_NOTE not in note,
           "C 请求 note 原文不因被拒进事件面")
        ok(str(e.get("who", "")) in note or "未记名" in note,
           "C 拒绝行含操作人记名")


def leg_second_out_of_set_value():
    """D：第二出集值 verified 同形（防窄测）。"""
    wf = mk_devlane(blocked_meta())
    before = copy.deepcopy(snapshot_of(wf))
    r = call_update(wf, "verified", "n", "", None)
    ok(r.get("ok") is False and r.get("kind") != "",
       "D verified 同样被拒且带 kind")
    untouched, after = business_fields_untouched(wf, before)
    ok(untouched, "D verified 拒绝零副作用")
    ok(len(after.get("refused") or []) == len(before.get("refused") or []) + 1,
       "D verified 拒绝同样留痕")


def leg_illegal_status():
    """E：非法 status（wire 直发形）→ illegal 族拒收+零副作用+留痕。"""
    wf = mk_devlane(blocked_meta(stage_state="running"))
    before = copy.deepcopy(snapshot_of(wf))
    r = call_update(wf, "nope", "n", "", None)
    ok(r.get("ok") is False, "E 非法 status 被拒")
    ok(r.get("kind") == "illegal_status", "E kind=illegal_status（守卫族可辨）")
    untouched, after = business_fields_untouched(wf, before)
    ok(untouched, "E 非法 status 零副作用")
    ok(len(after.get("refused") or []) == len(before.get("refused") or []) + 1,
       "E 非法 status 留痕可查")


def leg_oversized_echo_bounded():
    """E：10 万字符畸形 status → 留痕有界，原文绝不进快照查询面。"""
    wf = mk_devlane(blocked_meta(stage_state="running"))
    before = copy.deepcopy(snapshot_of(wf))
    r = call_update(wf, "X" * 100000, "n", "", None)
    ok(r.get("ok") is False, "E 超长畸形 status 被拒不炸")
    untouched, after = business_fields_untouched(wf, before)
    ok(untouched, "E 超长畸形零副作用")
    refused = after.get("refused") or []
    ok(len(refused) == len(before.get("refused") or []) + 1,
       "E 超长畸形同样留痕")
    if refused:
        ok(len(str(refused[-1].get("why", ""))) <= WHY_BOUND,
           "E 留痕 why 有界（≤%d，畸形载荷数量级不进事件面）" % WHY_BOUND)
    dump = json.dumps(after, ensure_ascii=False)
    ok("X" * 500 not in dump,
       "E 快照查询面全文无畸形载荷原文（无界回显绝迹）")
    if after["meta"].get("log"):
        ok(len(str(after["meta"]["log"][-1].get("note", ""))) <= LOG_BOUND,
           "E log 拒绝行有界（≤%d）" % LOG_BOUND)


def leg_wire_four_positional_args():
    """F：恰按线上 wire 形状（四位置实参、无 who 位）调用 → 不炸且留痕有记名位。"""
    wf = mk_devlane(blocked_meta())
    # client.py 现行实参形状：str(status)/str(note)/str(pending_add)/book_path（无 who）
    r = call_update(wf, "closed", REQUEST_NOTE, "", None)
    ok(r.get("ok") is False, "F 四位置实参调用不炸（wire 形状兼容）")
    refused = snapshot_of(wf).get("refused") or []
    ok(bool(refused) and isinstance(refused[-1].get("who"), str)
       and refused[-1].get("who") != "",
       "F 留痕 who 位非空显式记名（未记名也是名）")


def leg_cross_class_parity():
    """G：同一拒绝输入在两个工作流类上回执/留痕形状一致（client 按名分发透明服务）。"""
    shapes = []
    for mk in (mk_devlane, mk_base):
        wf = mk(blocked_meta())
        r = call_update(wf, "closed", REQUEST_NOTE, "", None)
        snap = snapshot_of(wf)
        refused = snap.get("refused") or []
        shapes.append({
            "receipt_keys": set(r.keys()),
            "ok": r.get("ok"),
            "kind": r.get("kind"),
            "refused_entry_keys": set(refused[-1].keys()) if refused else set(),
        })
    ok(shapes[0]["receipt_keys"] == shapes[1]["receipt_keys"],
       "G 两类回执键集一致（%r）" % sorted(shapes[0]["receipt_keys"]))
    ok(shapes[0]["ok"] == shapes[1]["ok"] and shapes[0]["kind"] == shapes[1]["kind"],
       "G 两类回执 ok/kind 值一致")
    ok(shapes[0]["refused_entry_keys"] == shapes[1]["refused_entry_keys"],
       "G 两类 refused 条目键集一致")


def main():
    legs = [
        leg_today_incident_form,
        leg_second_out_of_set_value,
        leg_illegal_status,
        leg_oversized_echo_bounded,
        leg_wire_four_positional_args,
        leg_cross_class_parity,
    ]
    for leg in legs:
        set_patched(True)  # 本场景全走新历史语义分支（重放面归场景二）
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
