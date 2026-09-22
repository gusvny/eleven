#!/usr/bin/env python3
"""门先查账后实跑·正例面（t260922-12 验收③正例/⑥正例/①⑦文件面，灰盒 L3）。

intent（登记于 run_scenarios.py SCENARIOS）：真缝 admin.py call verify_lane ×
真 git 临时仓 × 桩执行器。R1：泳道红×活基线同红→既有欠账记录不拦（green=true 且
summary 诚实计数 fail=1），主账落 lane:/baseline 两源行且全部十字段全键（无脏行），
桩日志 ref=HEAD 证明基线相真执行。R2 同输入再跑：台账命中→基线相零执行（桩基线
执行数不增+基线源行零新增）、a 仍由台账判既有欠账、主账字节前缀保持且增长
（append-only）、新增行仍全良构。断言锚=台账文件内容、桩执行日志、green/blockers/
summary 公开回执，不锚闸回执内部新增键（浅绑定）。

与 developer L1（test_t260922_12_gate_ledger 白盒电池：env 形状/回执内部键/写失败
降级）不同层：本条锁真缝组装行为与文件级不变式。实现落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。

安全红线：夹具全落临时目录零真仓接触；零 docker 零端口；不触 3099/7233。
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_ledger_fixture import (LEDGER_KEYS, call_gate, make_fixture,
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


def main():
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        print("ENV_FAIL: git 缺失，基线归属子用例不可验（exit 2）")
        return 2
    td = tempfile.mkdtemp(prefix="t26092212-debt-")
    repo = make_fixture(make_stub(["case-a", "case-b"], "case-a"))
    ledger_dir = Path(td) / "ledger"
    ledger_dir.mkdir()
    log = Path(td) / "fixture-log.jsonl"
    env = {"SANDBAR_SCENARIO_LEDGER_DIR": str(ledger_dir),
           "SANDBAR_INTEG_LEDGER_SOURCE": "lane:t260922-12",
           "FIXTURE_LOG": str(log)}
    lf = ledger_dir / "scenario-results.jsonl"

    print("== R1 活基线权威：同红→既有欠账不拦，两源行落账，行行全键")
    r1 = call_gate(repo, env)
    ok(r1.get("ok") is True, "R1 调闸成功", (r1.get("stderr") or "")[-300:])
    inner = r1.get("result") or {}
    ok(inner.get("err") is None and inner.get("cases") is not None,
       "R1 协议判定真发生（err 空+cases 在场）")
    ok(inner.get("green") is True, "R1 泳道红×基线红→既有欠账不拦（green=true）")
    ok((inner.get("summary") or {}).get("fail") == 1,
       "R1 诚实计数 summary.fail=1（不拦不洗数）")
    aff = inner.get("affiliation") or {}
    ok(aff.get("blockers") == [], "R1 blockers 空（记录面不拦）",
       str(aff.get("blockers"))[:200])
    rows, bad, exists = read_ledger(lf)
    ok(exists and len(rows) > 0, "R1 台账文件已产出且非空")
    ok(bad == 0 and all(all(k in r for k in LEDGER_KEYS) for r in rows),
       "R1 全部行十字段全键（无脏行，bad=%d）" % bad)
    srcs = [str(r.get("source")) for r in rows]
    ok(any(s == "baseline" for s in srcs), "R1 baseline 源行在账", str(srcs)[:260])
    ok(any(s.startswith("lane:") for s in srcs), "R1 lane:<票> 源行在账")
    ok(any(r.get("scenario") == "case-a" and r.get("source") == "baseline"
           and r.get("verdict") == "fail" for r in rows),
       "R1 case-a 基线行=fail 在账")
    b1 = lf.read_bytes()
    log1 = read_log(log)
    head1 = [e for e in log1 if e.get("ref") == "HEAD"]
    ok(len(head1) >= 1, "R1 基线相真执行过（桩日志 ref=HEAD）")

    print("== R2 台账命中：基线跳过+仍判欠账+主账 append-only")
    r2 = call_gate(repo, env)
    ok(r2.get("ok") is True, "R2 调闸成功", (r2.get("stderr") or "")[-300:])
    inner2 = r2.get("result") or {}
    ok(inner2.get("green") is True, "R2 台账命中同红→不拦（green=true）")
    aff2 = inner2.get("affiliation") or {}
    ok(aff2.get("blockers") == [], "R2 blockers 空（台账判欠账）",
       str(aff2.get("blockers"))[:200])
    ok((inner2.get("summary") or {}).get("fail") == 1, "R2 诚实计数 fail=1")
    b2 = lf.read_bytes()
    ok(b2.startswith(b1) and b2 != b1,
       "R2 主账 append-only：旧字节前缀保持且新增行")
    rows2, bad2, _ = read_ledger(lf)
    base1 = sum(1 for r in rows if r.get("source") == "baseline")
    base2 = sum(1 for r in rows2 if r.get("source") == "baseline")
    ok(base2 == base1, "R2 基线源行零新增（基线跳过 %d→%d）" % (base1, base2))
    ok(bad2 == 0, "R2 新增行仍全为良构行（bad=%d）" % bad2)
    log2 = read_log(log)
    head2 = [e for e in log2 if e.get("ref") == "HEAD"]
    ok(len(head2) == len(head1),
       "R2 基线相桩执行零新增（先查账后实跑 %d→%d）" % (len(head1), len(head2)))
    ok(len(log2) > len(log1), "R2 泳道相照常执行（桩日志增长）")
    ok(worktree_count(repo) == 1, "R2 基线 worktree 终态回收零残留")

    print("== 结果：%d ok / %d FAIL" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
