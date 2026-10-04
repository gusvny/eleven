#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261004-32 场景②：额度账行为——开跑前判额度 / 四处销账 / 人门占坑 / 暂停不占 /
下调不打断 / 队序可读 / 泄漏对账（灰盒 L3，离线秒级零 docker 零 Temporal，真引擎
公开模块面，隔离项目根零生产写入）。

intent（工单规则 1/2/3/4/5/8 的用户可感知面）：
- S1 判额度在启动前：limit=N 时第 N+1 张票 granted=False、入队报 1-based 位次
  （队头=1）、且不是持有者（不占账）；
- S2 真释放词表恰两个 cause（terminated / paused——段结束/转人门是原子续约点，
  被实现按宿主原话「非终态泳道 ≤ N」判为不开放窗口），stage-end/human-gate 作释放
  cause 具名拒收；release 幂等（空持释放=no-op 回执，不炸不双扣）；
- S3 人门占坑（规则 3）：human-gate 点是原子续约（reason→human-hold）不是放槽——
  持有者仍在账、仍计入在跑数，满额时新票排队（额度被人的关口吃掉是故意的）；
- S4 暂停不占（规则 4）：paused 释放后槽空，队头晋升；
- S5 下调不打断（规则 5）：声明降到低于在跑数，持有者原封不动，只影响下一次
  acquire 的判决；
- S6 unlimited 全收（12 张全持有、队空）；
- S7 队序：默认 FIFO；reorder 只收当前队列的排列（引擎不重算、不丢条目——CL-3 写、
  引擎消费），晋升取重排后的队头；
- S8 读出面每条排队带 since 与 waited_s（单调、机器可读——规则 8）；
- S9 泄漏对账（KI-188 家族：死持有者占坑 ⇒ 上限误拒）：reconcile 清掉不在存活集的
  持有者、点名清了谁（named output）、同锁步晋升队头。

与相邻场景 intent 分界：
- sc_t26100432_decl_fail_closed：彼锁声明读法拒绝矩阵与读出面形状；
- developer L1（acquire/release 真值表、flock 原子性）白盒随实现；
- workflow 接线（门真的挡住首段、道内四处销账）归道内 L1 与后续 engine 池场景。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t261004-32/sc_t26100432_slot_ledger.py（cwd=仓根）
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。
"""
import sys
import time

from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t26100432 import (  # noqa: E402
    check, env_fail, engine_modules, guard, isolated_root, register_project,
    set_projects_root, summary, write_decl,
)

MOD = "server/engine/concurrency.py"


def main():
    shared, conc, why = engine_modules()
    if shared is None:
        env_fail("engine base unavailable (%s); no stdlib substitute case" % why)
    if conc is None:
        check("t261004-32 engine face landed (%s)" % MOD, False, why)
        summary()

    def proj(root, key, limit):
        register_project(root, key)
        write_decl(root, key, {"version": 1, "limit": limit})
        return key

    def st(key):
        return conc.read_state(key)

    def holds(key, t):
        return any(h.get("ticket") == t for h in st(key)["holders"])

    def hreason(key, t):
        return next((h.get("reason") for h in st(key)["holders"] if h.get("ticket") == t), None)

    def pos(key, t):
        q = st(key)["queue"]
        return next((e.get("position") for e in q if e.get("ticket") == t), None)

    def nh(key):
        return len(st(key)["holders"])

    # ---------------- S1 judge before start ----------------
    print("\n== S1 judge before start: N-th runs, N+1-th queues at position 1")
    root = isolated_root("t26100432-s1-")
    set_projects_root(root)
    k = proj(root, "s1", 2)
    r1, r2 = conc.acquire(k, "tA"), conc.acquire(k, "tB")
    check("S1a first two tickets granted",
          r1.get("granted") and r2.get("granted")
          and holds(k, "tA") and holds(k, "tB"),
          "r1=%s r2=%s" % (r1, r2))
    r3 = conc.acquire(k, "tC")
    check("S1b third ticket NOT granted", r3.get("granted") is False, "r3=%s" % r3)
    check("S1c third ticket queued at 1-based position 1", pos(k, "tC") == 1,
          "state=%s" % str(st(k))[:200])
    check("S1d queued ticket is NOT a holder", not holds(k, "tC"))
    conc.acquire(k, "tC")
    check("S1e re-acquire while queued does not duplicate the queue entry",
          len(st(k)["queue"]) == 1 and pos(k, "tC") == 1,
          "state=%s" % str(st(k))[:200])

    # ---------------- S2 real-release vocabulary + idempotence ----------------
    # Contract resolution (documented in concurrency.py's header, accepted at plan
    # review comment 2, and matching the host order's original wording 非终态泳道 ≤ N):
    # a slot is HELD for the lane's whole lifetime; the REAL release points are
    # paused | terminated. stage-end / human-gate are atomic RENEWALS (reason
    # running <-> human-hold) — they must be refused as freeing causes, by name.
    print("\n== S2 real-release vocabulary = terminated|paused; renew points refused; idempotent")
    root = isolated_root("t26100432-s2-")
    set_projects_root(root)
    k = proj(root, "s2", 2)
    conc.acquire(k, "x0")
    conc.acquire(k, "x1")
    for label, bad in [("S2a an off-vocabulary cause is refused by name", "whenever"),
                       ("S2a2 stage-end is refused as a freeing cause (it is a renew point)", "stage-end"),
                       ("S2a3 human-gate is refused as a freeing cause (rule 3: the gate holds)", "human-gate")]:
        try:
            conc.release(k, "x0", bad)
            check(label, False, "no refusal")
        except Exception as e:
            check(label, "cause" in str(e) or "vocabulary" in str(e), "%s" % str(e)[:160])
    r = conc.release(k, "x0", "terminated")
    check("S2b release receipts name released/cause", r.get("released") is True
          and r.get("cause") == "terminated", "r=%s" % r)
    r2 = conc.release(k, "x0", "terminated")
    check("S2c double release is a no-op receipt (idempotent, not an error)",
          r2.get("released") is False, "r2=%s" % r2)
    r3 = conc.release(k, "nobody", "terminated")
    check("S2d releasing a non-holder is a no-op, not an error",
          r3.get("released") is False, "r3=%s" % r3)

    # ---------------- S3 human-gate hold occupies ----------------
    print("\n== S3 human gate: atomic renew to human-hold, still counted (rule 3)")
    root = isolated_root("t26100432-s3-")
    set_projects_root(root)
    k = proj(root, "s3", 1)
    conc.acquire(k, "tH")
    rn0 = conc.renew(k, "tH", "human-hold")
    check("S3a human-gate point renews the holder, does not free the slot",
          rn0.get("renewed") and holds(k, "tH"), "rn0=%s" % rn0)
    check("S3b holder reason is human-hold", hreason(k, "tH") == "human-hold",
          "state=%s" % str(st(k))[:150])
    r3 = conc.acquire(k, "tX")
    check("S3c over-limit ticket queues while a human is awaited",
          r3.get("granted") is False and pos(k, "tX") == 1, "r3=%s" % r3)
    # back to running on the resume side (same atomic renew, opposite direction)
    rn = conc.renew(k, "tH", "running")
    check("S3d renew back to running after the signature (tH keeps its slot, never re-queues)",
          rn.get("renewed") and hreason(k, "tH") == "running" and holds(k, "tH")
          and not any(e.get("ticket") == "tH" for e in st(k)["queue"]), "rn=%s" % rn)
    check("S3g the still-over-limit waiter stays queued after the signature",
          pos(k, "tX") == 1 and not holds(k, "tX"), "state=%s" % str(st(k))[:150])
    # renew of a non-holder must not fabricate a slot
    rn2 = conc.renew(k, "tGHOST", "running")
    check("S3e renew of a non-holder grants nothing", not rn2.get("holding"),
          "rn2=%s" % rn2)
    # Contract pin (was a defect probe at design stage; implement resolved it by
    # refusing human-gate as a freeing cause): the release face must never accept
    # the human-gate point — the hold face is renew(reason="human-hold").
    k2 = proj(root, "s3b", 1)
    conc.acquire(k2, "tG")
    try:
        rg = conc.release(k2, "tG", "human-gate")
        check("S3f release(cause=human-gate) must NOT free the slot (rule 3)",
              not rg.get("released") and holds(k2, "tG"),
              "DEFECT: released=%s — the hold face and the release cause contradict" % rg)
    except Exception as e:
        check("S3f release(cause=human-gate) must NOT free the slot (rule 3)",
              holds(k2, "tG") and ("human-gate" in str(e) or "vocabulary" in str(e)),
              "refused but holder lost or refusal not named: %s" % str(e)[:160])

    # ---------------- S4 pause does not hold ----------------
    print("\n== S4 pause releases and the queue head promotes (rule 4)")
    root = isolated_root("t26100432-s4-")
    set_projects_root(root)
    k = proj(root, "s4", 1)
    conc.acquire(k, "tP")
    conc.acquire(k, "tQ")
    r = conc.release(k, "tP", "paused")
    check("S4a paused ticket is not a holder", not holds(k, "tP"), "r=%s" % r)
    check("S4b queue head promoted after the pause",
          r.get("promoted") == "tQ" and holds(k, "tQ") and not st(k)["queue"],
          "r=%s" % r)

    # ---------------- S5 lowering never interrupts ----------------
    print("\n== S5 lower limit below holders: holders untouched, next start only")
    root = isolated_root("t26100432-s5-")
    set_projects_root(root)
    k = proj(root, "s5", 3)
    for t in ("t1", "t2", "t3"):
        conc.acquire(k, t)
    write_decl(root, k, {"version": 1, "limit": 2})  # the knob is CL-2; the decl is the truth
    n = nh(k)
    check("S5a running holders untouched after lowering", n == 3, "holders=%d" % n)
    r5 = conc.acquire(k, "t4")
    check("S5b next acquire judged against the lower limit (queued, not granted)",
          r5.get("granted") is False and pos(k, "t4") == 1, "r5=%s" % r5)
    # lowering must not break release+promote: free down to the lowered limit
    conc.release(k, "t1", "terminated")
    conc.release(k, "t2", "terminated")
    check("S5c after releases free a slot under the lowered limit, the head promotes",
          holds(k, "t4") and not st(k)["queue"], "state=%s" % str(st(k))[:200])

    # ---------------- S6 unlimited ----------------
    print("\n== S6 unlimited admits all")
    root = isolated_root("t26100432-s6-")
    set_projects_root(root)
    k = proj(root, "s6", "unlimited")
    for i in range(12):
        conc.acquire(k, "u%d" % i)
    s = st(k)
    check("S6a 12 tickets all hold under unlimited, queue empty",
          len(s["holders"]) == 12 and not s["queue"]
          and conc.load_limit(k) is None, "limit=%r" % s.get("limit"))

    # ---------------- S7 order: FIFO default, reorder consumed ----------------
    print("\n== S7 queue order: FIFO; reorder consumes the panel's permutation")
    root = isolated_root("t26100432-s7-")
    set_projects_root(root)
    k = proj(root, "s7", 1)
    conc.acquire(k, "w0")
    for t in ("w1", "w2", "w3"):
        conc.acquire(k, t)
    check("S7a FIFO enqueue order",
          [pos(k, t) for t in ("w1", "w2", "w3")] == [1, 2, 3],
          "state=%s" % str(st(k))[:200])
    try:
        conc.reorder(k, ["w3", "w2"])
        check("S7b a non-permutation is refused by name", False, "no refusal")
    except Exception:
        check("S7b a non-permutation is refused by name", True)
    conc.reorder(k, ["w3", "w1", "w2"])
    check("S7c reordered order is consumed as-is",
          [pos(k, t) for t in ("w3", "w1", "w2")] == [1, 2, 3],
          "state=%s" % str(st(k))[:200])
    r = conc.release(k, "w0", "terminated")
    check("S7d promotion takes the reordered head",
          r.get("promoted") == "w3" and holds(k, "w3"), "r=%s" % r)

    # ---------------- S8 waited time machine-readable ----------------
    print("\n== S8 read face: per-queue-entry waited time, monotonic in order")
    root = isolated_root("t26100432-s8-")
    set_projects_root(root)
    k = proj(root, "s8", 1)
    conc.acquire(k, "m0")
    conc.acquire(k, "m1")
    time.sleep(1.1)
    conc.acquire(k, "m2")
    s = st(k)
    q = s["queue"]
    check("S8a both queued entries carry position + since + waited_s",
          [e.get("position") for e in q] == [1, 2]
          and all("waited_s" in e and "since" in e for e in q),
          "queue=%s" % str(q)[:200])
    if len(q) == 2:
        check("S8b waited time grows with real time and is ordered",
              q[0]["waited_s"] > q[1]["waited_s"],
              "w0=%r w1=%r" % (q[0]["waited_s"], q[1]["waited_s"]))

    # ---------------- S9 leak reconcile (KI-188 family) ----------------
    print("\n== S9 reconcile drops dead holders, names them, promotes the head")
    root = isolated_root("t26100432-s9-")
    set_projects_root(root)
    k = proj(root, "s9", 1)
    conc.acquire(k, "ghost")
    conc.acquire(k, "waiter")
    out = conc.reconcile(k, [])  # nothing alive: the ghost is stale by definition
    check("S9a reconcile names what it dropped", out.get("dropped") == ["ghost"],
          "out=%s" % out)
    check("S9b the waiter is promoted in the same locked step",
          out.get("promoted") == "waiter" and holds(k, "waiter"), "out=%s" % out)
    out2 = conc.reconcile(k, ["waiter"])
    check("S9c a live holder survives reconcile", holds(k, "waiter")
          and out2.get("dropped") == [], "out2=%s" % out2)

    summary()


if __name__ == "__main__":
    guard(main)
