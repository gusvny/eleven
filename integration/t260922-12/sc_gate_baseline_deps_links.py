#!/usr/bin/env python3
"""基线树依赖软链四态行为面（t260922-12 验收⑤，灰盒 L3）。

intent（登记于 run_scenarios.py SCENARIOS）：真缝+真 worktree，桩在基线执行相
实测四条依赖路径形态（islink/dir/file/absent）。R1（SANDBAR_GATE_BASELINE_DEPS=1
显式置位，不依赖缺省——缺省值由取证 A'/B' 实录裁定，场景不钉）：src 在场→软链
建成（app/node_modules）、dst 已在（仓内已跟踪真目录）→绝不覆盖
（server/engine/.venv 仍是真目录）、src 缺席→跳过不致命
（ui-check playwright-core 与 temporal 两路径 absent）。R2（=0）：一条不建
（旋钮真的关得掉）。两轮基线跑均正常收口、台账写账不受软链影响、worktree 零残留。
软链只读使用语义由「src 指向主仓共享目录」的夹具同构构造保证。

若实现改了旋钮名或没接旋钮，R2 会红点名（旋钮名由方案 C4 钉死）。与 developer
L1（软链四态单测）intent 不同层：彼白盒测建链函数本身，本条锁基线执行相里依赖
真实可见——「回退路线必须真能跑」的物理前提。实现落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿；git 缺席=ENV_FAIL exit 2。

安全红线：夹具全落临时目录零真仓接触；零 docker 零端口；不触 3099/7233。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_ledger_fixture import (call_gate, make_fixture, make_stub,
                                read_ledger, read_log, worktree_count)

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""))


def newest_head_entry(log):
    heads = [e for e in read_log(log) if e.get("ref") == "HEAD"]
    return heads[-1] if heads else {}


def main():
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        print("ENV_FAIL: git 缺失，基线子用例不可验（exit 2）")
        return 2
    td = tempfile.mkdtemp(prefix="t26092212-links-")
    repo = make_fixture(
        make_stub(["case-a", "case-b"], "case-a"),
        tracked_extra={".gitignore": "app/node_modules\n",
                       "server/engine/.venv/KEEPSAFE": "keep\n"},
        ignored_markers={"app/node_modules/marker.txt": "shared-deps\n"})
    ledger_root = Path(td) / "ledgers"
    ledger_root.mkdir()

    print("== R1 旋钮=1：src 在场→建链；dst 已在→不覆盖；src 缺席→跳过不致命")
    led1 = ledger_root / "r1"
    led1.mkdir()
    log1 = Path(td) / "log-r1.jsonl"
    r1 = call_gate(repo, {"SANDBAR_GATE_BASELINE_DEPS": "1",
                          "SANDBAR_SCENARIO_LEDGER_DIR": str(led1),
                          "SANDBAR_INTEG_LEDGER_SOURCE": "lane:t260922-12",
                          "FIXTURE_LOG": str(log1)})
    ok(r1.get("ok") is True, "R1 调闸成功", (r1.get("stderr") or "")[-300:])
    inner1 = r1.get("result") or {}
    ok(inner1.get("green") is True, "R1 软链在场基线照跑（a 同红不拦 green=true）")
    e1 = newest_head_entry(log1)
    ok(bool(e1), "R1 基线相真执行过（桩日志 ref=HEAD）")
    links1 = e1.get("links") or {}
    ok(links1.get("app/node_modules") == "link",
       "R1 src 在场→软链建成（app/node_modules=%s）" % links1.get("app/node_modules"),
       str(links1)[:300])
    ok(links1.get("server/engine/.venv") == "dir",
       "R1 dst 已在→绝不覆盖（.venv 仍为真目录=%s）"
       % links1.get("server/engine/.venv"))
    ok(links1.get("server/ui-check/node_modules/playwright-core") == "absent",
       "R1 src 缺席→跳过（ui-check absent，不致命）")
    ok(links1.get("server/engine/bin/temporal") == "absent",
       "R1 src 缺席→跳过（temporal absent，不致命）")
    rows1, bad1, exists1 = read_ledger(led1 / "scenario-results.jsonl")
    ok(exists1 and rows1 and bad1 == 0,
       "R1 台账写账不受软链影响（行=%d 坏行=%d）" % (len(rows1), bad1))
    ok(worktree_count(repo) == 1, "R1 基线 worktree 终态回收零残留")

    print("== R2 旋钮=0：一条不建（旋钮真的关得掉）")
    led2 = ledger_root / "r2"
    led2.mkdir()
    log2 = Path(td) / "log-r2.jsonl"
    r2 = call_gate(repo, {"SANDBAR_GATE_BASELINE_DEPS": "0",
                          "SANDBAR_SCENARIO_LEDGER_DIR": str(led2),
                          "SANDBAR_INTEG_LEDGER_SOURCE": "lane:t260922-12",
                          "FIXTURE_LOG": str(log2)})
    ok(r2.get("ok") is True, "R2 调闸成功", (r2.get("stderr") or "")[-300:])
    e2 = newest_head_entry(log2)
    ok(bool(e2), "R2 基线相真执行过")
    links2 = e2.get("links") or {}
    ok(links2.get("app/node_modules") != "link",
       "R2 旋钮关闭→软链未建（app/node_modules=%s）" % links2.get("app/node_modules"),
       str(links2)[:300])
    rows2, _, exists2 = read_ledger(led2 / "scenario-results.jsonl")
    ok(exists2 and rows2, "R2 旋钮关闭不影响写账")
    ok(worktree_count(repo) == 1, "R2 基线 worktree 终态回收零残留")

    print("== 结果：%d ok / %d FAIL" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
