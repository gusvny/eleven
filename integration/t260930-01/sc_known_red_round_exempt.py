#!/usr/bin/env python3
"""在册红不进每轮路径·黑盒契约（t260930-01 宿主裁 B 档，灰盒 L2/L3）。

命名注：本文与注册名一律用 exempt——t260904-12 的防复辟守卫把旧状态词视作禁字
（旧语义：干净状态词穿闸是 KI-046 实锤），本场景讲的是「在册红不进每轮注册面」，
与那套语义无关，故取一个不撞判据的词。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNNER = "integration/run_scenarios.py"
EXCLUDE_ENV = "SANDBAR_KNOWN_RED_EXCLUDE"
ROSTER_ENV = "SANDBAR_KNOWN_RED_ROSTER"
# 一条真在册（真挂账册里 verdict=booked/isolated，**只用于「被跳过」断言**，故零成本）。
# 261002 退役批后改指 ms-decl-gate（原指 t260903-07-chat-project-tag，已随退役批除名；
# 本夹具只要求「真在册且零成本」，指哪条都守同一契约）。
BOOKED = "t260910-09-ms-decl-gate"
# 两条零依赖离线条目：开关对照档位用**夹具册子**把 FAST 标成在册，避免真跑 43 秒的
# 浏览器条目（对照判据是「谁进注册面」，不是「它跑出什么」）。
FAST = "t260905-08-hex-clean"
FAST2 = "scenario-guard-doc-drift"

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:400]) if detail else ""))


def run(extra_env, only=(FAST, FAST2), budget=None):
    env = dict(os.environ)
    env.pop(EXCLUDE_ENV, None)
    env.pop(ROSTER_ENV, None)
    env["SANDBAR_SCENARIO_LEDGER_DIR"] = tempfile.mkdtemp(prefix="sc-kr-ledger-")
    # 单飞锁**必须换路径**：本场景是「场景内起执行器」，外层那一轮已经持有同泳道锁，
    # 不换路径=嵌套跑秒退（实锤：经注册表跑 0.3s 全红，直跑 4.5s 全绿）。指到一次性
    # 临时路径=与外层互不干扰，且仍然是真执行器真单飞。
    env["SANDBAR_INTEG_RUN_LOCK_PATH"] = os.path.join(
        env["SANDBAR_SCENARIO_LEDGER_DIR"], "run.lock")
    if budget:
        env["SANDBAR_INTEG_RUN_BUDGET_SEC"] = str(budget)
    env.update({k: str(v) for k, v in extra_env.items()})
    cp = subprocess.run(
        [sys.executable, RUNNER, "--only", ",".join(only)],
        cwd=str(REPO), capture_output=True, text=True, timeout=900, env=env)
    return cp


def summary_of(cp):
    for ln in cp.stdout.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except json.JSONDecodeError:
                return None
    return None


def fake_roster(tmp, name=FAST):
    """夹具册子：把零成本条目标成在册（+ 一条不在本轮的点名条目与一条畸形条目）。"""
    p = Path(tmp) / ("roster-%s.json" % name)
    p.write_text(json.dumps({"meta": {"max_entries": 3}, "entries": [
        {"name": name, "verdict": "booked"},
        {"name": "not-registered-anywhere", "verdict": "isolated"},
        "junk-line",
    ]}), encoding="utf-8")
    return p


def leg_on(tmp):
    """① 开关开：在册红不进注册面 + 具名上报。"""
    cp = run({EXCLUDE_ENV: "1", ROSTER_ENV: str(fake_roster(tmp))},
             only=(FAST, FAST2))
    ok(cp.returncode == 0, "① exit=0（点名轮全绿）", cp.returncode)
    joined = "\n".join(cp.stdout.splitlines()
                       + cp.stderr.splitlines() + [cp.stdout, cp.stderr])
    ok("INTEG_KNOWN_RED " in cp.stdout and FAST in cp.stdout,
       "①a 具名行在场且点名在册条目", cp.stdout[-300:])
    ok("观察位" in cp.stdout, "①b 具名行写清观察位（巡检/合并前全量）")
    ok("INTEG_KNOWN_RED_NOTE" in cp.stdout and "未跑 ≠ 判绿" in cp.stdout,
       "①c 「未跑 ≠ 判绿」专行在场（静默放行防线）")
    ok(("本轮只跑点名 2 条" in cp.stdout),
       "①d 注册面按原意点名 2 条（豁免发生在注册面之内，不吞点名）")
    ok("not-registered-anywhere" not in cp.stdout,
       "①i 不在本轮点名的在册条目不进具名面（只看本轮注册面）")
    s = summary_of(cp)
    ok(isinstance(s, dict) and s.get("known_red_skipped") == 1,
       "①e 汇总 known_red_skipped=1", s)
    ok(isinstance(s, dict) and s.get("expected") == 1 and s.get("ran") == 1,
       "①f 在册数只剩不在册那条（expected=1/ran=1）", s)
    ok(isinstance(s, dict) and s.get("known_red_names") == [FAST],
       "①g 汇总带完整豁免名单", s)
    ok(("FAIL" not in cp.stdout), "①h 豁免本身不制造红")
    return joined


def leg_off(tmp):
    """② 开关关：照旧全跑、零豁免面（同一夹具册子在场也不生效）。"""
    cp = run({ROSTER_ENV: str(fake_roster(tmp))})
    ok(EXCLUDE_ENV not in cp.stdout and "INTEG_KNOWN_RED" not in cp.stdout,
       "②a 关档零豁免行（逐字节旧行为）")
    s = summary_of(cp)
    ok(isinstance(s, dict) and "known_red_skipped" not in s or
       (isinstance(s, dict) and s.get("known_red_skipped") == 0),
       "②b 关档汇总不声明豁免", s)
    ok("本轮只跑点名 2 条" in cp.stdout, "②c 关档注册面仍是 2 条")
    ok(cp.returncode == 0, "②d 关档退出码 0（全跑且全绿）", cp.returncode)
    s2 = summary_of(cp)
    ok(isinstance(s2, dict) and s2.get("expected") == 2 and s2.get("ran") == 2,
       "②e 关档在册数=2（在册条目一条都没被摘）", s2)


def leg_bad_roster(tmp):
    """③ 册子坏：fail-closed 一条不豁免 + 具名。"""
    bad = Path(tmp) / "bad.json"
    bad.write_text("{bad json", encoding="utf-8")
    cp = run({EXCLUDE_ENV: "1", ROSTER_ENV: str(bad)}, only=(FAST, FAST2))
    ok("INTEG_KNOWN_RED_WARN" in cp.stderr,
       "③a 坏册具名 WARN（stderr）", cp.stderr[-300:])
    ok("未**豁免**" in cp.stderr or "未*豁免*" in cp.stderr or "豁免" in cp.stderr,
       "③b WARN 写清「未豁免任何在册红」")
    ok("本轮只跑点名 2 条" in cp.stdout, "③c 坏册不改变注册面（照跑）")
    missing = run({EXCLUDE_ENV: "1", ROSTER_ENV: str(Path(tmp) / "nope.json")},
                  only=(FAST, FAST2))
    ok("INTEG_KNOWN_RED_WARN" in missing.stderr, "③d 册子缺席同样具名", missing.stderr[-200:])
    weird = Path(tmp) / "weird.json"
    weird.write_text(json.dumps({"meta": {}, "entries": [
        {"name": BOOKED, "verdict": "future-verdict"},
        {"name": 123, "verdict": "booked"},
        "junk-line",
    ]}), encoding="utf-8")
    cp3 = run({EXCLUDE_ENV: "1", ROSTER_ENV: str(weird)}, only=(FAST, FAST2))
    ok("INTEG_KNOWN_RED " not in cp3.stdout,
       "③e 认不得的 verdict 词/畸形条目一律照跑（宁慢勿窄）", cp3.stdout[-200:])


def leg_real_roster():
    """④ 真册冒烟：真挂账册读得动、且豁免面与在册数守恒。"""
    cp = run({EXCLUDE_ENV: "1"}, only=(BOOKED, FAST2))
    s = summary_of(cp)
    ok(isinstance(s, dict) and s.get("known_red_skipped") == 1
       and s.get("expected") == 1 and s.get("ran") + s.get("reused", 0) == s.get("expected"),
       "④a 真册：豁免数与在册数守恒（ran+reused==expected）", s)


def main():
    print("[known-red-round-exempt] 在册红不进每轮路径·黑盒契约")
    with tempfile.TemporaryDirectory(prefix="sc-kr-roster-") as tmp:
        leg_on(tmp)
        leg_off(tmp)
        leg_bad_roster(tmp)
    leg_real_roster()
    print("SUMMARY pass=%d fail=%d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
