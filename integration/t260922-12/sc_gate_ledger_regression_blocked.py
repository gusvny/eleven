#!/usr/bin/env python3
"""门先查账后实跑·拦截面（t260922-12 验收③反例1/反例2+④⑥，灰盒 L3）。

intent（登记于 run_scenarios.py SCENARIOS）：真缝同族。种子轮落台账 a=fail、
b=pass。RB（反例1「台账不变假绿机」的反向锁）：泳道脏改 b 红→b 仍拦（blockers
含 b 不含 a），且基线相零执行（两红都有可信台账答案：a=fail→欠账记录、b=pass→
维持 main 绿方向定拦，不靠重跑）、脏树轮 lane 源行零新增（脏树不写账）——主账
字节逐位不变。RC（反例2+④定点复跑）：泳道再添从没跑过的 z 红→基线必须真跑且
只跑 z（桩基线执行名单恰=[case-z]，不整跑——门侧歧义名单注入的用户可感知形态）、
z=基线绿→拦、a 照旧欠账不拦、z 落 baseline 源行而 a 零新增。

断言锚=台账文件逐字节/分计数、桩执行日志、green/blockers 公开回执。与 developer
L1（test_t260922_12_only_scenarios 执行器 --only 电池：fail-closed/expected 不变式）
intent 不同面：彼锁执行器入口自身，本条锁门侧「歧义名单注入基线」的组装行为。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

安全红线：夹具全落临时目录零真仓接触；零 docker 零端口；不触 3099/7233。
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_ledger_fixture import (call_gate, has_string, make_fixture,
                                make_stub, read_ledger, read_log,
                                worktree_count)

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""))


def blockers_of(inner):
    return list((inner.get("affiliation") or {}).get("blockers") or [])


def main():
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        print("ENV_FAIL: git 缺失，基线归属子用例不可验（exit 2）")
        return 2
    td = tempfile.mkdtemp(prefix="t26092212-block-")
    repo = make_fixture(make_stub(["case-a", "case-b"], "case-a"))
    stub = repo / "stub_exec.py"
    ledger_dir = Path(td) / "ledger"
    ledger_dir.mkdir()
    log = Path(td) / "fixture-log.jsonl"
    env = {"SANDBAR_SCENARIO_LEDGER_DIR": str(ledger_dir),
           "SANDBAR_INTEG_LEDGER_SOURCE": "lane:t260922-12",
           "FIXTURE_LOG": str(log)}
    lf = ledger_dir / "scenario-results.jsonl"

    print("== RA 种子轮：a 同红欠账落账（a=fail，b=pass）")
    ra = call_gate(repo, env)
    ok(ra.get("ok") is True, "RA 调闸成功", (ra.get("stderr") or "")[-300:])
    inner_a = ra.get("result") or {}
    ok(inner_a.get("green") is True, "RA 种子轮 a 既有欠账不拦（green=true）")
    b_a = lf.read_bytes()
    rows_a, _, _ = read_ledger(lf)
    lane_a = sum(1 for r in rows_a if str(r.get("source", "")).startswith("lane:"))
    base_a = sum(1 for r in rows_a if r.get("source") == "baseline")
    base_a_z = sum(1 for r in rows_a
                   if r.get("source") == "baseline" and r.get("scenario") == "case-z")
    head_a = len([e for e in read_log(log) if e.get("ref") == "HEAD"])

    print("== RB 反例1：记账绿×泳道红→仍拦；基线零执行；脏树不写账")
    stub.write_text(make_stub(["case-a", "case-b"], "case-a,case-b"))  # 泳道脏改
    rb = call_gate(repo, env)
    ok(rb.get("ok") is True, "RB 调闸成功", (rb.get("stderr") or "")[-300:])
    inner_b = rb.get("result") or {}
    ok(inner_b.get("green") is False, "RB 记账绿×泳道红→拦（green=false）")
    blks = blockers_of(inner_b)
    ok(any("case-b" == b for b in blks), "RB blockers 点名 case-b", str(blks)[:200])
    ok(all("case-a" != b for b in blks),
       "RB case-a 照旧欠账不拦（不在 blockers）", str(blks)[:200])
    ok(has_string(inner_b, "case-b"), "RB 拦截面可见非静默（回执点名）")
    b_b = lf.read_bytes()
    ok(b_b == b_a, "RB 主账字节逐位不变（脏树 lane 行零新增+基线零执行）")
    rows_b, _, _ = read_ledger(lf)
    lane_b = sum(1 for r in rows_b if str(r.get("source", "")).startswith("lane:"))
    ok(lane_b == lane_a, "RB 脏树轮 lane 源行零新增（脏树不写账 %d→%d）"
       % (lane_a, lane_b))
    head_b = len([e for e in read_log(log) if e.get("ref") == "HEAD"])
    ok(head_b == head_a, "RB 基线相零执行（台账两红皆有可信答案 %d→%d）"
       % (head_a, head_b))

    print("== RC 反例2+④：无记录→回退实跑，且基线只跑歧义那条（定点复跑）")
    stub.write_text(make_stub(["case-a", "case-z"], "case-a,case-z"))
    rc = call_gate(repo, env)
    ok(rc.get("ok") is True, "RC 调闸成功", (rc.get("stderr") or "")[-300:])
    inner_c = rc.get("result") or {}
    ok(inner_c.get("green") is False, "RC 无记录回退实跑后 z 基线绿→拦")
    blks_c = blockers_of(inner_c)
    ok(any("case-z" == b for b in blks_c), "RC blockers 点名 case-z",
       str(blks_c)[:200])
    ok(all("case-a" != b for b in blks_c),
       "RC case-a 照旧欠账不拦（台账命中）", str(blks_c)[:200])
    log_c = read_log(log)
    head_c = [e for e in log_c if e.get("ref") == "HEAD"]
    ok(len(head_c) > head_b, "RC 基线相真执行（无记录→回退实跑，不得当绿 %d→%d）"
       % (head_b, len(head_c)))
    newest = head_c[-1] if head_c else {}
    ok(newest.get("names") == ["case-z"],
       "RC 基线只跑歧义那条 case-z（④定点复跑，实跑名单=%s）"
       % str(newest.get("names")))
    ok(newest.get("only") == ["case-z"],
       "RC 歧义名单注入可见（SANDBAR_SCENARIO_ONLY 传导至基线执行）",
       str(newest.get("only")))
    rows_c, _, _ = read_ledger(lf)
    lane_c = sum(1 for r in rows_c if str(r.get("source", "")).startswith("lane:"))
    ok(lane_c == lane_a, "RC 脏树仍不写 lane 行（%d→%d）" % (lane_a, lane_c))
    base_c_z = sum(1 for r in rows_c
                   if r.get("source") == "baseline" and r.get("scenario") == "case-z")
    ok(base_c_z == base_a_z + 1, "RC z 落 baseline 源行（%d→%d）"
       % (base_a_z, base_c_z))
    base_c_a = sum(1 for r in rows_c
                   if r.get("source") == "baseline" and r.get("scenario") == "case-a")
    base_a_cnt = sum(1 for r in rows_a
                     if r.get("source") == "baseline" and r.get("scenario") == "case-a")
    ok(base_c_a == base_a_cnt, "RC a 无新基线行（定点复跑不整跑）")
    ok(worktree_count(repo) == 1, "RC 基线 worktree 终态回收零残留")

    print("== 结果：%d ok / %d FAIL" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
