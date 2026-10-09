#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_run_record_drivers.py —— t261009-11 双驱动 run 记录的端到端旅程
（灰盒 L3，真执行器子进程 + 真 git 夹具树，离线秒级零 docker 零 Temporal）。

intent（用户可感知行为；真源=票面「a header written once at the end of a run,
by BOTH drivers」+ ledger-record-models-v1.md §A）：
    A. 执行器顶驱一轮（无 owner env）：每个新行带同一个 `run-` id；
       轮末恰落一份头；头计数 == 对该 id 行的重数；verdict 是计数的机械
       卷积；INTEG_SUMMARY 带加法键 run_id 且与头的 id 相等（消费面可引用）；
       started_at 是整数毫秒、duration_s 是数字。
    B. 闸-owned 轮（SANDBAR_INTEG_LEDGER_OWNER=gate）：执行器一个字都不写——
       行数与头数逐字节不变（单写者纪律按轮收口，绝无两份头）。
    C. 旧行共存：账里预置的无 run 旧行在一轮新写后仍在、仍可按旧键查询——
       legacy 保持可读，新行不重盖章到旧行上。
    D. 闸面（真 verify_lane integ 道）：闸轮自己落头（lane  revision set 一份，
       免基线档恰一份）；头计数 == 该 id 行重数；闸回执带 run 面（id 在场，
       消费者可从回执引用 run）。

分层与 intent 分工（防重复）：
  · 库/CLI 契约（铸造、拒写真值表、legacy、中断态、卷出保留）→ 同票
    sc_run_record_store.py（L2），本条不重测；
  · 台账绿行复用与采信判据 → t260930-01 / t260922-12 家族，本条只锁 run
    身份与头记录面；developer L1 锁纯函数电池。
  夹具手法沿 t260930-01-sc_ledger_reuse_round 的既有共享缝（真 git 树 + 树内
  执行器副本 + 注入注册表），步骤级复用不构成 intent 重复。

安全红线：夹具树与账目录都在本场景私有临时目录（finally+atexit 双路回收 +
git worktree prune——main 树 worktree 注册表零残留）；真账零写入
（SANDBAR_SCENARIO_LEDGER_DIR 投影）；零端口、零控制台（永不接触 3099）。
三态：git 缺失=ENV_FAIL exit 2；被锁的 run 面未落地 = FAIL 点名（TDD 信号），
arbitrate/merge 期必须绿。
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261009-11-run-record-drivers"
SLUG = "t261009-11-run-record-fixture"

sys.path.insert(0, str(REPO / "integration"))
import scenario_ledger as sl  # noqa: E402
from lib_env import clean_narrowing_env  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

_TMP = None
_MAIN = None
_RECLAIMED = False


def _cleanup():
    global _RECLAIMED
    if _RECLAIMED:
        return
    _RECLAIMED = True
    try:
        if _MAIN is not None:
            subprocess.run(["git", "worktree", "prune"], cwd=str(_MAIN),
                           capture_output=True, timeout=30)
    except Exception:  # noqa: BLE001 —— 回收面不抛（残留交清扫器）
        pass
    if _TMP is not None:
        shutil.rmtree(str(_TMP), ignore_errors=True)


atexit.register(_cleanup)


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=str(cwd or _MAIN),
                          capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- 夹具

def _fixture_script(marker: Path, log: Path) -> str:
    return (
        "import json, os, pathlib\n"
        "NAME = %r\n"
        "pathlib.Path(%r).write_text('ran\\n')\n"
        "pathlib.Path(%r).open('a').write('ran\\n')\n"
        "print(json.dumps({'name': NAME,\n"
        "                  'suite': 'main', 'status': 'pass', 'cause': None,\n"
        "                  'reason': None, 'evidence': 'fixture', 'dur_s': 0.01,\n"
        "                  'started': '2026-10-09T00:00:00+00:00', 'git_sha': '',\n"
        "                  'attempt': 1}, ensure_ascii=False))\n"
        % (SLUG, str(marker), str(log)))


def _build_tree(tmp: Path) -> Path:
    """真 git 树（干净 HEAD）+ 树内执行器/账本副本 + 注入注册表（一条夹具）。"""
    global _TMP, _MAIN
    _TMP = tmp
    main = tmp / "main"
    main.mkdir()
    _MAIN = main
    _git("init", "-q", cwd=main)
    _git("config", "user.email", "scenario@example.invalid", cwd=main)
    _git("config", "user.name", "scenario", cwd=main)
    integ = main / "integration"
    integ.mkdir()
    for name in ("run_scenarios.py", "scenario_ledger.py", "lib_tmp_reclaim.py",
                 "lib_env.py", "lib_result.py", "conftest_result_protocol.py",
                 "conftest.py"):
        p = REPO / "integration" / name
        if p.is_file():
            shutil.copy2(str(p), str(integ / name))
    eng_dst = main / "server" / "engine"
    eng_dst.mkdir(parents=True)
    shutil.copy2(str(REPO / "server" / "engine" / "failure_protocol.py"),
                 str(eng_dst / "failure_protocol.py"))
    fx = tmp / "fixtures"
    fx.mkdir()
    script = fx / "fake_scenario.py"
    script.write_text(_fixture_script(tmp / "ran.marker", tmp / "ran.log"),
                      encoding="utf-8")
    text = (integ / "run_scenarios.py").read_text(encoding="utf-8")
    entry = ('    (%r,\n'
             '     "fixture: minimal round injected by the run-record drivers '
             'scenario (not part of the real registry)",\n'
             '     "python3 %s", "serial"),\n]' % (SLUG, script))
    head, sep, _tail = text.partition("\nSCENARIOS = [")
    if not sep:
        env_fail("run_scenarios registry anchor missing (SCENARIOS = [ moved)")
    text = head + sep + "\n" + entry + \
        text.split("\nSCENARIOS = [", 1)[1].split("\n]", 1)[1]
    (integ / "run_scenarios.py").write_text(text, encoding="utf-8")
    (main / ".gitignore").write_text("out/\n__pycache__/\n", encoding="utf-8")
    (main / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/run_scenarios.py\n",
        encoding="utf-8")
    _git("add", "-A", cwd=main)
    r = _git("commit", "-q", "-m", "fixture", cwd=main)
    if r.returncode != 0:
        env_fail("fixture commit failed: %s" % (r.stderr or r.stdout)[-300:])
    return main


def _run_runner(wt: Path, ledger_dir: Path, extra_env=None):
    env = clean_narrowing_env()
    env["SANDBAR_SCENARIO_LEDGER_DIR"] = str(ledger_dir)
    env["SANDBAR_POOL_CONC"] = "4"
    env["SANDBAR_CONC_POOLS"] = "main:1"
    env["SANDBAR_UNDECLARED_POLICY"] = "record"
    env["SANDBAR_INTEG_RUN_LOCK_PATH"] = str(_TMP / "run.lock")
    # 记账来源：与闸同词表的回落链（engine 通道 env 优先，这里给 ticket 回落）。
    env["SANDBAR_TICKET_ID"] = NAME
    env.update({k: str(v) for k, v in (extra_env or {}).items()})
    try:
        p = subprocess.run(["python3", "integration/run_scenarios.py"],
                           cwd=str(wt), capture_output=True, text=True,
                           timeout=600, env=env)
    except subprocess.TimeoutExpired as e:
        return -9, (e.stdout or ""), (e.stderr or "")
    return p.returncode, p.stdout or "", p.stderr or ""


def _jsonl(path: Path):
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def _summary(out):
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except ValueError:
                return None
    return None


def _recount(rows, run_id):
    got = [r for r in rows if r.get("run") == run_id]
    passed = sum(1 for r in got if r.get("verdict") == "pass")
    failed = sum(1 for r in got if r.get("verdict") == "fail")
    envf = sum(1 for r in got if r.get("verdict") == "env_fail")
    return got, {"ran": len(got), "passed": passed, "failed": failed,
                 "env_failed": envf}


# ---------------------------------------------------------------- 主程序

def main():
    if shutil.which("git") is None:
        env_fail("git missing: this scenario's judgement face (clean HEAD "
                 "fixture tree) is entirely on git")
    tmp = Path(tempfile.mkdtemp(prefix="t261009-11-drivers-"))
    wt = _build_tree(tmp)
    led = tmp / "ledger"
    led.mkdir()
    rows_path = led / "scenario-results.jsonl"
    runs_path = led / sl.RUNS_NAME

    # ---------------- C（前置）：账里预置旧行（无 run） ----------------
    legacy = {"ts": "2026-10-01T00:00:00+00:00", "commit": "a" * 40,
              "env_fp": "b" * 64, "conc_width": 1, "pool": "main",
              "scenario": SLUG + "-legacy", "verdict": "pass",
              "wall_s": 0.01,
              "source": "baseline", "ticket": ""}
    with open(str(rows_path), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(legacy, ensure_ascii=False,
                            separators=(",", ":")) + "\n")

    # ---------------- A 执行器顶驱一轮 ----------------
    rcA, outA, errA = _run_runner(wt, led)
    sA = _summary(outA)
    rowsA = _jsonl(rows_path)
    headsA = _jsonl(runs_path)
    new_rows = [r for r in rowsA if r.get("scenario") == SLUG
                and r is not legacy]
    run_ids = {r.get("run") for r in new_rows}
    ok(rcA == 0 and len(new_rows) >= 1,
       "A1 顶驱轮绿且夹具行落账", "rc=%s stderr=%s" % (rcA, errA[-200:]))
    ok(len(run_ids) == 1 and all(
        isinstance(x, str) and x.startswith("run-") for x in run_ids),
       "A2 每个新行带同一个 run- 前缀 id", "run_ids=%s" % run_ids)
    ok(len(headsA) == 1, "A3 轮末恰一份头记录（written once at the end）",
       "headers=%s" % [h.get("id") for h in headsA])
    if headsA and run_ids:
        h = headsA[0]
        rid = next(iter(run_ids))
        got, counts = _recount(rowsA, rid)
        ok(h.get("id") == rid, "A4 头 id == 行上的 run id", "")
        ok(h.get("cases") == counts,
           "A5 头计数 == 对该 id 行的重数（counts derivable from rows）",
           "hdr=%s recount=%s" % (h.get("cases"), counts))
        ok(h.get("verdict") == ("green" if counts["ran"] > 0
                                and counts["failed"] == 0
                                and counts["env_failed"] == 0 else "red"),
           "A6 verdict 是计数的机械卷积", "verdict=%s" % h.get("verdict"))
        ok(isinstance(h.get("started_at"), int)
           and isinstance(h.get("duration_s"), (int, float)),
           "A7 started_at 整数毫秒、duration_s 数字",
           "started_at=%r duration_s=%r" % (h.get("started_at"),
                                            h.get("duration_s")))
        ok(isinstance(sA, dict) and sA.get("run_id") == rid,
           "A8 INTEG_SUMMARY.run_id 加法键在场且与头 id 相等",
           "summary=%s" % json.dumps(sA)[:200])
    else:
        ok(False, "A4..A8 头/行缺席（TDD 红预期）", "")

    # ---------------- B 闸-owned 轮：执行器零写 ----------------
    rows_before = rows_path.read_bytes()
    runs_before = runs_path.read_bytes() if runs_path.is_file() else b""
    rcB, outB, errB = _run_runner(
        wt, led, extra_env={"SANDBAR_INTEG_LEDGER_OWNER": "gate"})
    ok(rcB == 0, "B1 闸-owned 轮本身照常绿（夹具照跑）",
       "rc=%s stderr=%s" % (rcB, errB[-200:]))
    ok(rows_path.read_bytes() == rows_before,
       "B2 执行器零写行（写者=闸，单写者纪律按轮收口）", "")
    ok((runs_path.read_bytes() if runs_path.is_file() else b"") == runs_before,
       "B3 执行器零写头（一轮绝不落两份头）", "")

    # ---------------- C 旧行共存 ----------------
    rowsC = _jsonl(rows_path)
    ok(any("run" not in r for r in rowsC),
       "C1 无 run 的旧行仍在账里（legacy stays readable）", "")
    hits, bad = sl.query_rows("a" * 40, SLUG + "-legacy",
                              path=rows_path)
    ok(len(hits) >= 1 and not bad, "C2 旧行按旧键查询照常命中",
       "hits=%d bad=%s" % (len(hits), bad))

    # ---------------- D 闸面：闸轮自己落头、回执带 run 面 ----------------
    sys.path.insert(0, str(REPO / "server" / "tools"))
    import verify_lane as vl
    heads_before = {h.get("id") for h in _jsonl(runs_path)}
    keys = ("SANDBAR_SCENARIO_LEDGER_DIR", "SANDBAR_INTEG_LEDGER_SOURCE",
            "SANDBAR_GATE_BASELINE", "SANDBAR_LEDGER_REUSE",
            "SANDBAR_INTEG_RUN_BUDGET_SEC", "SANDBAR_SCENARIO_ONLY",
            "SANDBAR_SCENARIO_EXCLUDE_POOLS", "SANDBAR_POOL_CONC",
            "SANDBAR_CONC_POOLS", "SANDBAR_INTEG_LEDGER_OWNER")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        os.environ["SANDBAR_SCENARIO_LEDGER_DIR"] = str(led)
        os.environ["SANDBAR_INTEG_LEDGER_SOURCE"] = "lane:" + NAME
        os.environ["SANDBAR_GATE_BASELINE"] = "0"
        os.environ["SANDBAR_POOL_CONC"] = "4"
        os.environ["SANDBAR_CONC_POOLS"] = "main:1"
        # 复用关（D 段要闸真实执行并落自己的行+头；复用轮什么也不跑=无头可落），
        # kill switch 与 t260930-01 的 D 子用例同一具名 env。
        os.environ["SANDBAR_LEDGER_REUSE"] = "0"
        for k in ("SANDBAR_INTEG_RUN_BUDGET_SEC",
                  "SANDBAR_SCENARIO_ONLY", "SANDBAR_SCENARIO_EXCLUDE_POOLS",
                  "SANDBAR_INTEG_LEDGER_OWNER"):
            os.environ.pop(k, None)
        receipt = vl._integ({"lane": "integ", "path": str(wt),
                             "base": subprocess.run(
                                 ["git", "rev-parse", "HEAD"], cwd=str(wt),
                                 capture_output=True, text=True).stdout.strip()})
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    rowsD = _jsonl(rows_path)
    headsD = _jsonl(runs_path)
    new_heads = [h for h in headsD if h.get("id") not in heads_before]
    run_face = (receipt or {}).get("run") or {}
    gate_rid = (run_face.get("lane_run_id") or run_face.get("baseline_run_id")
                or run_face.get("id") or run_face.get("ids"))
    ok(bool(new_heads), "D1 闸轮落了自己的头（gate 是双驱动之一）",
       "new_heads=%s" % [h.get("id") for h in new_heads])
    gate_ok = False
    for h in new_heads:
        got, counts = _recount(rowsD, h.get("id"))
        if got and h.get("cases") == counts:
            gate_ok = True
    ok(gate_ok, "D2 闸头计数 == 对该 id 行的重数",
       "new_heads=%s" % [(h.get("id"), h.get("cases")) for h in new_heads])
    ok(bool(gate_rid), "D3 闸回执带 run 面（id 可被消费面引用）",
       "receipt.run=%s" % json.dumps((receipt or {}).get("run"))[:200])

    finish(NAME)


if __name__ == "__main__":
    main()
