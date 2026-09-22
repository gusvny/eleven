#!/usr/bin/env python3
"""台账查询 CLI 的无假绿契约（t260922-12 验收②对抗面，灰盒 L2/L3）。

intent（登记于 run_scenarios.py SCENARIOS）：一条命令可答「commit X 上场景 Y 红
不红」，且在四条对抗边上绝不假绿——命中→显式判定面；无记录→显式「无记录」且输出
绝不携带 pass 字样（「查不到当绿」是票据红线①的机械化身）；主账不可读→响亮非零
退出（不可读≠无记录）；主账半行/坏 JSON 畸形行在场→好行照常可读、坏行绝不捏造
判定（畸形行不可回 pass）。commit 属键：同场景异 commit 必须「无记录」。

与 developer L1（test_t260922_12_scenario_ledger：格式/拒写/保留/并发的模块电池）
intent 不同面：彼锁模块级行为与 CLI 词表对账，本条锁黑盒 CLI 的消费端无假绿语义
（「台账变假绿机」的主防线）。实现落地前红属预期（TDD 信号），arbitrate/merge 期
必须绿。

安全红线：全落临时目录零真仓接触；零 docker 零端口；不触 3099/7233。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "integration" / "scenario_ledger.py"
LEDGER_ENV = "SANDBAR_SCENARIO_LEDGER_DIR"

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""))


def cli(args, ledger_dir):
    env = dict(os.environ)
    env[LEDGER_ENV] = str(ledger_dir)
    return subprocess.run(
        [sys.executable, "integration/scenario_ledger.py"] + list(args),
        cwd=str(REPO), capture_output=True, text=True, timeout=60, env=env)


def row(commit, scenario, verdict, source):
    return {"ts": "2026-09-22T01:00:00+00:00", "commit": commit,
            "env_fp": "fp-a1", "conc_width": 1, "pool": "main",
            "scenario": scenario, "verdict": verdict, "wall_s": 1.5,
            "source": source, "ticket": "t260922-12"}


def main():
    if not CLI.is_file():
        print("FAIL integration/scenario_ledger.py 缺席（实现未落地——TDD 信号，"
              "arbitrate/merge 期必须绿）")
        return 1
    td = tempfile.mkdtemp(prefix="t26092212-query-")
    led = Path(td) / "scenario-results.jsonl"
    c_a = "1" * 40
    c_b = "2" * 40
    good_a = json.dumps(row(c_a, "case-a", "fail", "baseline"),
                        ensure_ascii=False)
    good_b = json.dumps(row(c_b, "case-b", "pass", "lane:t260922-12"),
                        ensure_ascii=False)
    led.write_text(good_a + "\n" + good_b + "\n", encoding="utf-8")

    print("== S1 命中面：判定/来源/指纹/时间要素可见，不误报无记录")
    p = cli(["query", "--commit", c_a, "--scenario", "case-a"], str(led.parent))
    ok(p.returncode == 0, "S1 命中退出 0（rc=%s）" % p.returncode,
       (p.stderr or "")[-200:])
    ok("fail" in p.stdout and "baseline" in p.stdout and "fp-a1" in p.stdout,
       "S1 判定/来源/指纹要素在输出", p.stdout[:200])
    ok("2026" in p.stdout, "S1 时间要素在输出（ts 年份在场）", p.stdout[:200])
    ok("无记录" not in p.stdout, "S1 命中不误报「无记录」")

    print("== S2 无记录面：显式回「无记录」，绝不静默回绿")
    p = cli(["query", "--commit", c_a, "--scenario", "case-zzz"], str(led.parent))
    ok(p.returncode == 0, "S2 无记录退出 0（rc=%s）" % p.returncode)
    ok("无记录" in p.stdout, "S2 显式「无记录」文案", p.stdout[:200])
    ok("pass" not in p.stdout, "S2 无记录输出绝不携带 pass 字样（不静默回绿）",
       p.stdout[:200])

    print("== S3 键语义：commit 属键——同场景异 commit 必须「无记录」")
    p = cli(["query", "--commit", c_b, "--scenario", "case-a"], str(led.parent))
    ok(p.returncode == 0 and "无记录" in p.stdout,
       "S3 异 commit 查同场景→无记录（键语义不放宽）", p.stdout[:200])

    print("== S4 主账不可读：不静默——stderr 点名 + 绝不凭空给判定")
    led.unlink()
    led.mkdir()  # 路径被占成目录 = 读必败形态
    p = cli(["query", "--commit", c_a, "--scenario", "case-a"], str(led.parent))
    ok("无记录" in p.stdout and "verdict=" not in p.stdout,
       "S4a 不可读绝不凭空给判定（out=%s）" % p.stdout[:120])
    ok((p.stderr or "").strip() != "", "S4b 不可读必须响亮（stderr 点名在场）",
       (p.stderr or "")[:200])
    led.rmdir()

    print("== S5 畸形行对抗：好行照读，坏行绝不捏造判定")
    corrupt_c = '{"scenario": "case-c", "verdict": "pass"'  # 半行坏 JSON
    led.write_text("\n".join([good_a, good_b, "{corrupt-half", "{not json}",
                              corrupt_c]) + "\n", encoding="utf-8")
    p = cli(["query", "--commit", c_a, "--scenario", "case-a"], str(led.parent))
    ok(p.returncode == 0 and "fail" in p.stdout,
       "S5a 畸形行在场，好行照常可读（rc=%s）" % p.returncode, p.stdout[:200])
    p = cli(["query", "--commit", c_a, "--scenario", "case-c"], str(led.parent))
    ok(not (p.returncode == 0 and "pass" in p.stdout),
       "S5b 坏行绝不捏造 pass 判定（rc=%s out=%s）" % (p.returncode,
                                                       p.stdout[:120]))

    print("== S6 --ledger 直连 + 任意 cwd（CLI 声称 cwd 无关，维护面同缝）")
    led2dir = Path(tempfile.mkdtemp(prefix="t26092212-query-led-"))
    led2 = led2dir / "scenario-results.jsonl"
    led2.write_text(good_a + "\n", encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(CLI), "query", "--commit", c_a,
         "--scenario", "case-a", "--ledger", str(led2)],
        cwd=str(led2dir), capture_output=True, text=True, timeout=60)
    ok(p.returncode == 0 and "verdict=fail" in p.stdout and "无记录" not in p.stdout,
       "S6 异 cwd+--ledger 直连命中（rc=%s）" % p.returncode,
       (p.stdout + (p.stderr or ""))[:200])
    led2.unlink()

    print("== 结果：%d ok / %d FAIL" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
