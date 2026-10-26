#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261026-25 guard: the docker-carveout disposition is REAL and the family is still green on docker.

Ticket t261026-25 (host order 261026, batch 2) planned to migrate the three
t260905-02 worker-lifecycle cases to the process bench, but the order's own
carve-out applied: each case also asserts ITS OWN docker stage's teardown
(`stage_down(...).residue == []` + `wait_port_released(port)`), and "container
residue" is named verbatim in the do-not-migrate list. Disposition (review round
2, conditional pass): do NOT migrate; correct the exception rows; surface the
a/b fork to the user (integration/NOTES-bench-migration-t26090502-261026.md).

This scenario is the ticket's green-run face and its regression net:

- A DECISION PINNED (offline): integration/batch_stage_exceptions.json still
  carries the three t260905-02-* rows, and each reason names the
  teardown-residue face it actually tests. A later batch that removes a row or
  migrates a case without the user's fork ruling fails here BY NAME — the
  decision may only be lifted deliberately, never by drift. (sc_batch_manifest_
  contract owns the table's generic schema/classification invariant; THIS entry
  owns this ticket's specific disposition rows.)
- B NOT-MIGRATED CONSISTENT (offline): each of the three scenario files still
  carries its own-stage teardown assertions (residue + port release). If a case
  is migrated under ruling (b), legs A+B fail together and the batch that lifts
  the ruling must rewrite this guard in the same ticket — by design.
- C FAMILY STILL GREEN ON DOCKER (live, the zero-drift evidence face): each of
  the three cases runs as a subprocess exactly as its registry cmd runs it, and
  its verdict must match what the docker stage produced before this ticket:
  exit 0 with a final "PASS  <title>" verdict line (the lib_gate family verdict
  format) and no "FAIL" verdict lines. exit 2 maps to env_fail (docker absent
  is an environment fact, never a silent skip); anything else is a named
  FAIL carrying the child's tail output. No verdict line at all is itself a
  named failure (malformed producer output, never guessed green).
  The child env is scrubbed of SANDBAR_STAGE_BATCH: that injection is the
  runner's consumer-seam knob, and under it these cases assert a fact that does
  not exist (the 261001 measured form: residue None, stage port still held).
  This guard pins the OWN-STAGE disposition, so its children must run own-stage
  regardless of how the gate classified the guard itself. The gate machine runs
  parallel lanes against the same docker daemon, so a child can lose a stage-up
  race through no fault of the case (conflict exit 3, or a contention-shaped
  rc=1): such a child is retried ONCE and the retry's verdict is final. A
  failure verdict always carries the child's OWN FAIL lines, never a stderr
  tail — the tail fills with other lanes' stage-sweep noise and cannot be
  attributed (261026 gate red: unattributable, undiagnosable).

Intent split: the three t260905-02-* entries own the worker/console behaviour
faces; sc_batch_manifest_contract owns the table's schema invariant; THIS entry
uniquely owns "the carve-out disposition holds and the family still runs green
on its lawful docker target". Docker/temporal absent = ENV_FAIL exit 2, named
per child.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INTEG = REPO / "integration"
MANIFEST = INTEG / "batch_stage_exceptions.json"
FAMILY = [
    ("t260905-02-worker-lifecycle", "integration/t260905-02/sc_worker_lifecycle.py"),
    ("t260905-02-ticket-worker-watch-exit", "integration/t260905-02/sc_ticket_worker_watch_exit.py"),
    ("t260905-02-console-duplicate-guard", "integration/t260905-02/sc_console_duplicate_guard.py"),
]
SUMMARY_RE = re.compile(r"^PASS  ", re.M)   # lib_gate family verdict line ("PASS  <title>")
FAIL_RE = re.compile(r"^FAIL( |  )", re.M)  # lib_gate per-assertion / family failure lines
BATCH_ENV = "SANDBAR_STAGE_BATCH"           # runner consumer-seam injection (lib_gate batch mode)
#: Hard ceiling per child run. The children own their own injectable, seconds-scale
#: bounds (lib_gate/lib_t26090502); this is only a run-away kill, not waited evidence.
CHILD_TIMEOUT_S = 900  # SANCTIONED-WAIT: subprocess hard ceiling (run-away kill) over three self-timing children, not a slept bound
#: Contention shapes: stage-up lost to a parallel lane. lib_gate maps stage
#: conflict to exit 3; a docker/port fight can also surface as rc=1 with these
#: markers before any subject assertion ran. One bounded retry, verdict = retry.
CONTENTION_RE = re.compile(
    r"up 失败|conflict|端口段耗尽|端口.*占用|Timeout|timeout|deadline|RESOURCE_BUSY",
    re.I)


def child_fail_lines(blob):
    return [ln.strip() for ln in blob.splitlines() if FAIL_RE.match(ln)]


def run_child(py, path, env):
    proc = subprocess.run([py, "-B", path], cwd=str(REPO), capture_output=True,
                          text=True, timeout=CHILD_TIMEOUT_S, env=env)
    return proc, (proc.stdout or "") + "\n" + (proc.stderr or "")


def main():
    fails = []
    env_fails = []
    passed = []

    def check(name, cond, detail=""):
        print("%s %s%s" % ("ok   " if cond else "FAIL ", name,
                           ("" if cond else " —— %s" % str(detail)[:600])), flush=True)
        if not cond:
            fails.append(name)

    # ---- A. decision pinned in the exception table ----
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        rows = {r.get("entry"): r for r in manifest if isinstance(r, dict)}
    except Exception as e:
        manifest, rows = None, {}
        check("例外清单可解析", False, str(e)[:200])
    for entry, _ in FAMILY:
        row = rows.get(entry)
        check("例外行在册且理由点名拆台残留面（%s）" % entry,
              row is not None and ("残留" in str(row.get("reason", ""))
                                   or "residue" in str(row.get("reason", ""))),
              "missing" if row is None else str(row.get("reason", ""))[:160])

    # ---- B. the three cases are still the not-migrated docker shape ----
    for _, path in FAMILY:
        try:
            text = (REPO / path).read_text(encoding="utf-8")
        except OSError as e:
            check("场景文件在册（%s）" % path, False, str(e)[:160])
            continue
        check("场景仍持自有台拆台断言（%s）" % path,
              "residue" in text and "wait_port_released" in text,
              "residue=%s wait_port_released=%s" % ("residue" in text, "wait_port_released" in text))

    # ---- C. the family still runs green on docker (its lawful target) ----
    py = sys.executable or "python3"
    child_env = dict(os.environ)
    child_env.pop(BATCH_ENV, None)  # own-stage semantics pinned; batch injection would assert a non-existent fact
    for entry, path in FAMILY:
        full = str(REPO / path)
        proc, blob = run_child(py, full, child_env)
        retried = False
        # Contention tolerance: a lost stage-up race against a parallel lane is
        # not the case's verdict. One bounded retry; the retry's result is final
        # (a real regression fails the retry too — this never waits a red away).
        if proc.returncode not in (0, 2) and (
                proc.returncode == 3 or CONTENTION_RE.search(blob)):
            print("note %s —— 疑似并行泳道争用（rc=%s），有界重试一次" % (entry, proc.returncode),
                  flush=True)
            proc, blob = run_child(py, full, child_env)
            retried = True
        has_pass = bool(SUMMARY_RE.search(blob))
        fail_lines = child_fail_lines(blob)
        if proc.returncode == 0:
            if has_pass and not fail_lines:
                passed.append(entry)
                print("ok   docker 上照旧绿（%s：%s%s）" % (
                    entry, SUMMARY_RE.search(blob).group(0).strip(),
                    "，争用重试后" if retried else ""), flush=True)
            else:
                check("docker 绿且判定行形状合规（%s）" % entry, False,
                      "rc=0 但 PASS 行=%s FAIL 行=%r" % (bool(has_pass), fail_lines[:3]))
        elif proc.returncode == 2:
            env_fails.append("%s（docker 台缺席类环境事实，exit 2）" % entry)
            print("ENV_FAIL %s —— docker 台缺席=环境红具名，不算场景红" % entry, flush=True)
        else:
            check("docker 绿（%s）" % entry, False,
                  "rc=%s%s 子用例 FAIL 行=%r" % (
                      proc.returncode, "（重试后）" if retried else "",
                      fail_lines[:5] or ["<no FAIL lines; producer malformed>"]))

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (len(passed), len(fails), len(env_fails)),
          flush=True)
    sys.exit(1 if fails else 2 if env_fails else 0)


if __name__ == "__main__":
    main()
