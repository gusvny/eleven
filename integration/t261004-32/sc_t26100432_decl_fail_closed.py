#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261004-32 场景①：并发上限声明的 fail-closed 契约 + 只读读出面（灰盒 L3，离线秒级
零 docker 零 Temporal，真引擎公开模块面 + 真 CLI 子进程，隔离项目根零生产写入）。

intent（工单规则 6/7/8/9 的用户可感知面——宿主令「an unreadable limit must not become
an unbounded machine」）：
- D1 缺声明 = 具名拒绝（点名声明文件路径与原因），绝不静默 unlimited，也绝不静默默认 3
  （规则 9 fail-closed；默认 3 属声明模板/CL-2 首存，不是引擎回落——review 意见 4）；
- D2 声明矩阵逐形拒绝并点名：unreadable（权限 000）、malformed JSON、wrong version、
  limit=0 / 11 / "3"（字符串）/ null、缺 limit 键、顶层非对象；
- D3 合法声明读回：1、10、"unlimited"（读成 None=不限）三边界照收；
- D4 状态账文件畸形 = 具名拒绝（畸形账绝不按空账放行，KI-188 泄漏家族的读面）；
- D5 只读读出面（规则 8）：读面载荷带 limit / holders（含 reason、held_s）/
  queue（含 1-based position、waited_s）——面板只读不计算；声明缺席时读面具名拒绝
  （绝不静默当空态）；CLI 出口面（ticket.py concurrency op）在场且拒收缺席声明。

与相邻场景 intent 分界：
- sc_t26100432_slot_ledger：彼锁额度账行为（判/排/销账/下调/改序/对账）；
  declaration 真值表白盒归 developer L1；本条只锁声明读法拒绝矩阵与读出面形状。
- 真 Temporal 两票端到端归 fixture 模板 L1 与后续 engine 池场景，本条零 docker。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t261004-32/sc_t26100432_decl_fail_closed.py（cwd=仓根）
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t26100432 import (  # noqa: E402
    check, env_fail, engine_modules, guard, isolated_root, register_project,
    run_cli, set_projects_root, summary, write_decl, REPO,
)

MOD = "server/engine/concurrency.py"


def decl_refusal(fn, label, key, root):
    """The loader must raise a named refusal that quotes the declaration location."""
    try:
        v = fn(key)
    except Exception as e:
        msg = str(e)
        check(label, str(root) in msg and key in msg,
              "refusal not naming the decl location (%s): %s: %s"
              % (key, type(e).__name__, msg[:200]))
        return
    check(label, False, "no refusal raised (returned %r) — fail-open" % (v,))


def main():
    shared, conc, why = engine_modules()
    if shared is None:
        env_fail("engine base unavailable (%s); no stdlib substitute case" % why)
    if conc is None:
        check("t261004-32 engine face landed (%s)" % MOD, False, why)
        summary()

    # ---------------- D1 absent declaration ----------------
    print("\n== D1 absent declaration = named refusal, never unlimited, never default 3")
    root = isolated_root("t26100432-d1-")
    set_projects_root(root)
    register_project(root, "pa")
    decl_refusal(conc.load_limit, "D1a absent decl refused naming the path", "pa", root)
    try:
        conc.load_limit("pa")
        check("D1b absent decl never returns a limit silently", False, "returned")
    except Exception:
        check("D1b absent decl never returns a limit silently", True)

    # ---------------- D2 refusal matrix ----------------
    print("\n== D2 malformed/misversioned declaration matrix (each names the path)")
    root = isolated_root("t26100432-d2-")
    set_projects_root(root)
    cases = [
        ("pb", "D2a malformed JSON", "{\"version\": 1, \"limit\": "),
        ("pc", "D2b wrong version", {"version": 2, "limit": 3}),
        ("pd", "D2c limit below range (0)", {"version": 1, "limit": 0}),
        ("pe", "D2d limit above range (11)", {"version": 1, "limit": 11}),
        ("pf", "D2e limit as string ('3')", {"version": 1, "limit": "3"}),
        ("pg", "D2f limit null", {"version": 1, "limit": None}),
        ("ph", "D2g limit key missing", {"version": 1}),
        ("pi", "D2h decl is a JSON array", "[1,2,3]"),
    ]
    for key, label, payload in cases:
        register_project(root, key)
        write_decl(root, key, payload)
        decl_refusal(conc.load_limit, label, key, root)
    # unreadable file (permission 000)
    register_project(root, "pu")
    f = write_decl(root, "pu", {"version": 1, "limit": 3})
    os.chmod(f, 0)
    try:
        conc.load_limit("pu")
        check("D2i unreadable (chmod 000) refused naming the path", False, "no refusal")
    except Exception as e:
        check("D2i unreadable (chmod 000) refused naming the path", str(f) in str(e),
              "not naming path: %s" % str(e)[:200])
    finally:
        os.chmod(f, 0o644)

    # ---------------- D3 lawful boundaries ----------------
    print("\n== D3 lawful boundaries accepted (1 / 10 / 'unlimited')")
    root = isolated_root("t26100432-d3-")
    set_projects_root(root)
    for key, limit, want in [("p-1", 1, 1), ("p-10", 10, 10), ("p-unl", "unlimited", None)]:
        register_project(root, key)
        write_decl(root, key, {"version": 1, "limit": limit})
        try:
            v = conc.load_limit(key)
            check("D3 %s accepted and read back" % key, v == want,
                  "loader returned %r, want %r" % (v, want))
        except Exception as e:
            check("D3 %s accepted and read back" % key, False, "refused: %s" % str(e)[:200])

    # ---------------- D4 malformed state ledger ----------------
    print("\n== D4 malformed state file = named refusal (never treated as empty)")
    root = isolated_root("t26100432-d4-")
    set_projects_root(root)
    register_project(root, "ps")
    write_decl(root, "ps", {"version": 1, "limit": 2})
    state = Path(root) / "ps" / "concurrency-state.json"
    state.write_text("{\"version\": 1, \"holders\": [ oops", encoding="utf-8")
    try:
        conc.read_state("ps")
        check("D4a malformed state refused and named", False, "no refusal")
    except Exception as e:
        check("D4a malformed state refused and named", str(state) in str(e),
              "not naming the state path: %s" % str(e)[:200])

    # ---------------- D5 read-only face ----------------
    print("\n== D5 read-only read face (rule 8: panel reads, never computes)")
    root = isolated_root("t26100432-d5-")
    set_projects_root(root)
    register_project(root, "pk")
    write_decl(root, "pk", {"version": 1, "limit": 3})
    st = conc.read_state("pk")
    check("D5a face carries limit / holders / queue",
          all(k in st for k in ("limit", "holders", "queue")),
          "keys=%s" % sorted(st.keys()))
    conc.acquire("pk", "tA")
    conc.acquire("pk", "tB")
    conc.acquire("pk", "tC")
    conc.acquire("pk", "tD")  # limit=3: the 4th must queue
    st = conc.read_state("pk")
    h, q = st["holders"], st["queue"]
    check("D5b holder rows carry reason + held time",
          bool(h) and all(("reason" in r and "held_s" in r) for r in h),
          "holders=%s" % str(h)[:200])
    check("D5c queued rows carry 1-based position + waited seconds",
          bool(q) and q[0].get("position") == 1 and "waited_s" in q[0],
          "queue=%s" % str(q)[:200])
    # absent declaration propagates through the read face (never a silent empty state)
    register_project(root, "pz")
    try:
        conc.read_state("pz")
        check("D5d read face refuses an absent declaration (named)", False, "no refusal")
    except Exception as e:
        check("D5d read face refuses an absent declaration (named)",
              str(root) in str(e) and "pz" in str(e), "%s" % str(e)[:200])
    # CLI op face (module header contract: ticket.py {"op":"concurrency"}) — accept
    # either the JSON-op shape or a `concurrency --project` subcommand; a missing
    # face = FAIL named (TDD-phase red, plan step 4).
    rc, out = run_cli(["concurrency", "--project", "pk"], root)
    if rc != 0 or "limit" not in out:
        rc2, out2 = run_cli(['{"op":"concurrency","project":"pk"}'], root)
        check("D5e CLI concurrency read face present and parseable",
              rc2 == 0 and "limit" in out2,
              "subcommand rc=%d out=%s | json-op rc=%d out=%s"
              % (rc, out[:120], rc2, out2[:200]))
        rcm, outm = run_cli(['{"op":"concurrency","project":"pz"}'], root)
        check("D5f CLI refuses an absent declaration: nonzero + named",
              rcm != 0 and ("pz" in outm or "concurrency-limit" in outm),
              "rc=%d out=%s" % (rcm, outm[:200]))
    else:
        check("D5e CLI concurrency read face present and parseable", True)
        rcm, outm = run_cli(["concurrency", "--project", "pz"], root)
        check("D5f CLI refuses an absent declaration: nonzero + named",
              rcm != 0 and ("pz" in outm or "concurrency-limit" in outm),
              "rc=%d out=%s" % (rcm, outm[:200]))

    summary()


if __name__ == "__main__":
    guard(main)
