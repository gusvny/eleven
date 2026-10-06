#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-18 场景：左栏工单顺序的引擎消费面——人设的顺序=引擎开跑的顺序
（灰盒 L3，离线秒级零 docker 零 Temporal 零浏览器，真引擎公开模块面，
隔离项目根零生产写入；复用 t261004-32 夹具，KI-161）。

intent（工单 CL-3 规格 3/4/5 的用户可感知面）：
- W1 队列面只含排队票：在跑（running holder）与等你签字（human-hold holder）
  不在 queue 里——它们不参与排序，读面上就没有它们的位次；
- W2 人经引擎入口（concurrency.reorder，即左栏 POST 最终落到的写脸）写入新
  顺序后，**同一条读脸**（read_state）原样吐回该顺序——顺序不落地两次、
  不在别处另记一份；
- W3 下一个开跑跟随人设的顺序：额度一释放，晋升的正是重排后的队头
  （票面验收证据 2 的引擎半边；UI 半边归浏览器场景）；
- W4 非排列一概具名拒收：少一个/多一个/重复/把在跑或暂停票塞进 order/空单
  对非空队——都拒绝且账面原封不动（引擎不丢条目、不发明条目）；
- W5 空队接受空单（合法 no-op，不炸）。

intent 分界（防 intent 级重复，核对全局用例清单后落界）：
- sc_t26100432_slot_ledger S7 已锁「reorder 只收排列、晋升取重排队头」的引擎
  语义真值表——本条不复断其 S1-S6/S8/S9 任何一面，本条独占的是**人设顺序的
  全旅程消费面**：holder 类票的排序排除（W1）、写脸→同脸读回一致性（W2）、
  面向工单验收的 next-start 证据组合（W3）、以及排序拒绝矩阵的账面不变性
  （W4，S7 只断「非排列拒收」单点，本条逐故障面点名+断账面不动）；
- 左栏 DOM 面（位次号/把手/箭头/绿点/琥珀点/两计数/进度点）归浏览器场景
  sc_t26100618_left_column_order.mjs，本条零浏览器。

KI 对齐：KI-072（负载敏感假红）——本条零墙钟断言（waited_s 只断在场不断
数值），串行自跑无并发争抢；KI-161（隔离根，零生产写入）；KI-188 族（拒绝
路径绝不半写）。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t261006-18/sc_t26100618_order_to_next_start.py（cwd=仓根）
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。
"""
import sys

from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "t261004-32"))
from lib_t26100432 import (  # noqa: E402
    check, env_fail, engine_modules, guard, isolated_root, register_project,
    set_projects_root, summary, write_decl,
)


def main():
    shared, conc, why = engine_modules()
    if shared is None:
        env_fail("engine base unavailable (%s)" % why)
    if conc is None:
        check("t261004-32 engine face landed", False, why)
        summary()

    root = isolated_root("t26100618-")
    set_projects_root(root)
    k = "fixorder"
    register_project(root, k)
    write_decl(root, k, {"version": 1, "limit": 2})

    def q(key=k):
        return [e.get("ticket") for e in conc.read_state(key)["queue"]]

    # 布景：t0 与 tH 先拿到槽（limit=2），tH 走人门转 human-hold（仍持槽不排）；
    # t1/t2/t3 排队。排队票 acquire 只入队（额度满、非队首），不会成 holder。
    conc.acquire(k, "t0")
    conc.acquire(k, "tH")
    conc.renew(k, "tH", "human-hold")
    conc.acquire(k, "t1")
    conc.acquire(k, "t2")
    conc.acquire(k, "t3")

    # W1 排序参与面排除：queue 只含排队票，FIFO 缺省序。
    check("W1 queue holds only queued tickets, FIFO default",
          q() == ["t1", "t2", "t3"],
          "queue=%s (t0 running and tH human-hold must stay in holders, not queue)"
          % q())
    face = conc.read_state(k)
    holders = {h.get("ticket"): h.get("reason") for h in face["holders"]}
    check("W1b holders carry running + human-hold, none queued",
          holders.get("t0") == "running" and holders.get("tH") == "human-hold"
          and not ({"t0", "tH"} & set(q())),
          "holders=%s" % holders)

    # W2 人设顺序：经引擎入口写 reorder → 同一条读脸吐回同一顺序。
    r = conc.reorder(k, ["t3", "t1", "t2"])
    check("W2 reorder write accepted with permutation receipt",
          r.get("queue") == ["t3", "t1", "t2"], "receipt=%s" % r)
    check("W2b same read face returns the person-set order",
          q() == ["t3", "t1", "t2"], "queue=%s" % q())
    pos = {e.get("ticket"): e.get("position") for e in conc.read_state(k)["queue"]}
    check("W2c read face positions renumber 1-based after reorder",
          pos == {"t3": 1, "t1": 2, "t2": 3}, "positions=%s" % pos)

    # W3 下一个开跑跟随人设顺序：额度释放 → 晋升的是重排后的队头 t3。
    conc.release(k, "t0", "terminated")
    check("W3 next start follows the person-set order (t3 promoted, not t1)",
          any(h.get("ticket") == "t3" for h in conc.read_state(k)["holders"])
          and q() == ["t1", "t2"],
          "queue=%s holders=%s" % (q(), [h.get("ticket") for h in conc.read_state(k)["holders"]]))

    # W6 暂停的票两本账都不在：released(paused) 后不在 holders 也不在 queue
    # ——读面上没有它，左栏自然无从给它排序控件（规格 4 的引擎半边）。
    conc.release(k, "t3", "paused")
    st = conc.read_state(k)
    check("W6 a paused ticket is on neither ledger face (nothing to order)",
          not any(h.get("ticket") == "t3" for h in st["holders"]) and "t3" not in q(),
          "queue=%s holders=%s" % (q(), [h.get("ticket") for h in st["holders"]]))

    # W4 非排列拒绝矩阵：逐故障面点名拒收，且每次拒绝后账面原封不动。
    before = q()
    refusals = [
        ("W4a missing member", ["t3", "t1"]),
        ("W4b extra unknown id", ["t3", "t1", "t2", "tGHOST"]),
        ("W4c duplicate id", ["t3", "t3", "t1", "t2"]),
        ("W4d at-work holder smuggled in", ["t0", "t3", "t1", "t2"]),
        ("W4e human-hold holder smuggled in", ["tH", "t3", "t1", "t2"]),
        ("W4f empty order vs non-empty queue", []),
        ("W4g non-list order", "t3,t1,t2"),
    ]
    for name, bad in refusals:
        refused = False
        detail = ""
        try:
            out = conc.reorder(k, bad)
            detail = "accepted with %r" % (out,)
        except Exception as e:  # noqa: BLE001——拒收即本意，异常类型不锚定
            refused = True
            detail = "%s: %s" % (type(e).__name__, str(e)[:120])
        unchanged = q() == before
        check("%s refused AND ledger untouched" % name, refused and unchanged,
              "%s; queue after=%s (before=%s)" % (detail, q(), before))

    # W5 空队收空单：合法 no-op。
    k2 = "fixorder-empty"
    register_project(root, k2)
    write_decl(root, k2, {"version": 1, "limit": 3})
    ok_empty = False
    detail = ""
    try:
        out = conc.reorder(k2, [])
        ok_empty = out.get("queue") == []
        detail = "receipt=%s" % (out,)
    except Exception as e:  # noqa: BLE001
        detail = "refused: %s: %s" % (type(e).__name__, str(e)[:120])
    check("W5 empty order on empty queue is a lawful no-op", ok_empty, detail)

    summary()


if __name__ == "__main__":
    guard(main)
