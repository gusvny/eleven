#!/usr/bin/env python3
"""sc_t26103128_static_analyzer_read_only - a read-only static analyzer never reds a
stage, and the module exemption never admits an executor (t261031-28).

Grey-box L3: the real stage activity entry, a real zstd session file, the receipt on
disk. Offline, seconds, zero docker, zero Temporal server, zero network, never touches
3099/7233.

Measured fault (upstream integration report, t261031-24): a developer stage that ran
`python3 -m pyflakes integration/sc_*.py` settled RED. The forbidden-integration scanner
matched the FILE argument of a `-m <module>` command because that module was not in its
read-only table, so a read-only check looked like a suite run and the ticket burned a
whole round. The fix admits the static-analyzer family and keeps pytest/unittest
execution red.

intent - the user-perceivable contract at the stage face (no engine internals asserted;
the commands below are what a developer types, never a copy of an internal table):
  A  THE READ-ONLY ANALYZER FAMILY IS LEGAL: the reported command verbatim (glob
     included), `python -m` instead of `python3 -m`, every user-typed analyzer over each
     entry shape (the runner, a scenario script under a ticket dir, a baselines script),
     the joined form `-mpyflakes`, and an analyzer with its own options before the file -
     the developer stage settles green, writes no violation row, and the receipt is
     byte-identical (a green stage never rewrites the result file).
  B  THE RED LINE STAYS: executor modules keep their hits (`-m pytest`, `-m unittest`,
     `-m doctest`, `-m runpy`, `-m timeit`, `-m cProfile`, `-m profile`, `-m pdb`,
     `-m coverage`, `-m trace` over an entry path), an analyzer in the same segment is
     not swept in with them; entry-module and plain execution forms stay red with the
     right entry key; the exemption is segment-local and never retroactive (an analyzer
     before or after a real run leaves exactly one violation naming the run).
  C  MALFORMED ANALYZER ARGV NEVER STOPS A GOOD TICKET: unbalanced quote, dangling `-m`,
     `-m <analyzer>` with no file, empty command, and a tool frame whose arguments are
     not JSON - green stage, zero rows, no crash.
  D  THE EVIDENCE FACE (walkthrough/arbitrate, role=integration): the same analyzer
     command is not a suite invocation (green, no full_suite_violations row, receipt
     untouched), a bare full run still lands one drift row named on the receipt, and a
     targeted run (`--only`) stays green - the classifier keeps its teeth and does not
     wash to always-green.
  E  DECLARATION/GATE PAIRING, new form only: every analyzer name the agent-facing
     discipline clause advertises is accepted by the gate over an entry path, and the
     clause advertises at least one. A prompt that recommends a form the gate rejects is
     the same split this ticket exists to remove.

Declared and NOT asserted: the joined form `-m<analyzer> <entry>` is matcher-green but
the evidence-face classifier still reports a suite invocation for it (agent_activities is
outside this ticket's write set; the module docstring declares that residual). Pinning
today's split would pin a known bug in a test that must not rot, so this scenario leaves
that shape alone.

Intent split (no intent-level duplication): matcher truth tables, the set composition and
the docstring/clause name lists belong to developer L1; the receipt enforcement chain for
read-only inspection (`sed`/`grep`/`ls`, `bash -lc`) belongs to
t260921-04-discipline-receipt-journey and t261009-36-discipline-read-not-run; the
agent-facing clause anchors for the pre-existing forms belong to
t260921-04-discipline-clause-contract. THIS entry uniquely owns the newly admitted
`-m <static analyzer>` family and the execution modules that must stay outside it, at
both stage faces.

Pre-fix tree: A, D1 and E are red (the analyzer family is not admitted), B and D2 are
green - that is the TDD signal of this ticket. Green is required at the integration gate
and at merge.

Three-state: zstd absent, or the engine modules unimportable (temporalio missing with no
venv fallback) = ENV_FAIL exit 2, named on stdout. Assertion failed = FAIL exit 1, each
failure named. All green = `SUMMARY pass=N fail=0`, exit 0.

Run (cwd = repo root):
  sh integration/py_interp.sh integration/t261031-28/sc_t26103128_static_analyzer_read_only.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _ensure_venv_python() -> None:
    """agent_activities imports temporalio at module level - fall back to the engine
    venv (same chain as verify.yaml's test check) when the running interpreter lacks it."""
    if os.environ.get("_T261031_28_REEXEC") == "1":
        return
    for cand in (REPO / "server/engine/.venv/bin/python",
                 REPO / "server/dsh/temporal-poc/.venv/bin/python"):
        if cand.is_file():
            try:
                same = Path(sys.executable).resolve() == cand.resolve()
            except OSError:
                same = False
            if not same:
                env = dict(os.environ)
                env["_T261031_28_REEXEC"] = "1"
                os.execve(str(cand), [str(cand), "-B", os.path.abspath(__file__)], env)
            return


_ensure_venv_python()
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    from shared import AgentStageArgs  # noqa: E402
    import agent_activities  # noqa: E402
    import integration_discipline  # noqa: E402
    from lib_env import clean_narrowing_env  # noqa: E402  (L12: fixture spawn runs a cleaned env)
    import lib_tmp_reclaim  # noqa: E402
except Exception as e:  # pragma: no cover - dependency-free faces only
    print("ENV_FAIL: engine modules unimportable (temporalio missing?): %s: %s"
          % (type(e).__name__, e))
    sys.exit(2)

if not shutil.which("zstd"):
    print("ENV_FAIL: zstd missing (the session-archive fixture needs it)")
    sys.exit(2)

TICKET = "t261031-28-scene"

#: The static analyzers a developer uses on a judgement file. These are USER commands,
#: not a copy of any engine table: if the gate stops accepting one of them, this
#: scenario must go red (that is the promise of the ticket).
ANALYZERS = ("pyflakes", "flake8", "pycodestyle", "pydocstyle", "pylint", "mypy", "ruff")

#: Modules that EXECUTE the file they are given. The ticket admits `-m <module>`, so the
#: adversary is exactly here: one accidental name in the read-only family opens the red
#: line without any visible symptom.
EXECUTOR_MODULES = ("pytest", "unittest", "doctest", "runpy", "timeit",
                    "cProfile", "profile", "pdb", "coverage", "trace")

#: Entry shapes the scan judges by basename, one per entry-table family.
ENTRY_SHAPES = ("integration/run_scenarios.py",
                "integration/t260902-07/tests/sc_x.py",
                "integration/baselines/lane-stages-chain.mjs")

RUNNER = "python3 integration/run_scenarios.py"

passed = 0
failed = 0


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s%s" % (label, ((" :: " + detail[:300]) if detail else "")))
    return cond


def user_frame(text):
    return {"type": "user/message", "data": {"content": [{"type": "text", "text": text}]}}


def tool_frame(seq, cmd):
    return {"type": "tool/call", "seq": seq,
            "data": {"name": "bash", "arguments": json.dumps({"command": cmd})}}


def write_session(role_dir: Path, frames) -> None:
    role_dir.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(f, ensure_ascii=False) for f in frames) + "\n"
    out = role_dir / "session.jsonl.zstd"
    with open(out, "wb") as fh:
        proc = subprocess.run(["zstd", "-z", "-c"], input=payload.encode("utf-8"),
                              stdout=fh, stderr=subprocess.DEVNULL,
                              env=clean_narrowing_env())
    if proc.returncode != 0:
        print("ENV_FAIL: zstd compress failed (rc=%d)" % proc.returncode)
        sys.exit(2)


def write_receipt(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"status": "ok", "summary": "[stub] fixture receipt", "report": "fixture",
            "deliverables": [], "files_changed": [], "evidence": "fixture",
            "prompt": "fixture prompt"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return path.read_bytes()


def run_stage(role, stage, cmds, malformed_frames=()):
    """Drive the REAL activity entry (idempotent-cache seam: preset receipt, zero spawn)
    over a REAL zstd session file. Returns (result, receipt_path, receipt_bytes_before)."""
    root = lib_tmp_reclaim.mkdtemp_reclaimed("t26103128-")
    role_dir = root / ".dsh" / "sessions" / "fixture-slug" / ("%s-%s" % (TICKET, role))
    frames = [user_frame("fixture turn")]
    frames += [tool_frame(i + 1, c) for i, c in enumerate(cmds)]
    frames += list(malformed_frames)
    write_session(role_dir, frames)
    rfile = root / "results" / ("%s_gen0.json" % stage)
    before = write_receipt(rfile)
    args = AgentStageArgs(
        ticket_id=TICKET, stage_id=stage, role=role,
        prompt="scenario fixture prompt",
        workspace={"type": "dir", "path": str(root)},
        result_file=str(rfile), log_file="", gen=0,
        workflow_id="dev-lane", skip_settle=True)
    res = asyncio.run(agent_activities._run_agent_stage_impl(args))
    return res, rfile, before


def disk_rows(rfile: Path, key: str):
    try:
        raw = json.loads(rfile.read_text("utf-8"))
    except Exception:
        return None
    rows = raw.get(key)
    return rows if isinstance(rows, list) else []


def main():
    lib_tmp_reclaim.install_signal_reclaim()
    try:
        # ---------------- A: the read-only analyzer family is legal ----------------
        print("== A read-only static analyzers never red a developer stage")
        cmds = ["python3 -m pyflakes integration/sc_*.py",   # the reported command, verbatim
                "python -m pyflakes integration/sc_*.py"]    # `python`, not `python3`
        cmds += ["python3 -m %s %s" % (a, shape)
                 for a in ANALYZERS for shape in ENTRY_SHAPES]
        cmds += ["python3 -mpyflakes integration/sc_*.py",            # joined form
                 "python3 -m flake8 --select=E9,F63 integration/sc_x.py"]  # options first
        res, rfile, before = run_stage("developer", "implement", cmds)
        rows = disk_rows(rfile, "integration_violations")
        check(res.status == "ok",
              "A1 the incident command and the whole analyzer family settle the stage green",
              "status=%s summary=%s" % (res.status, (res.summary or "")[:200]))
        check(rows == [],
              "A2 no violation row is written for a read-only analyzer command",
              "rows=%s" % json.dumps(rows, ensure_ascii=False)[:300])
        check(rfile.read_bytes() == before,
              "A3 a green stage never rewrites the receipt (reader-side, on disk)")

        # ---------------- B1: executor modules keep their hits ----------------------
        print("== B1 execution modules stay outside the read-only family")
        cmds = ["python3 -m %s integration/t260902-07/tests/sc_x.py" % e
                for e in EXECUTOR_MODULES]
        cmds.append("python3 -m pyflakes integration/sc_x.py")   # control: not swept in
        res, rfile, _ = run_stage("developer", "implement", cmds)
        rows = disk_rows(rfile, "integration_violations") or []
        got = [str(r.get("cmd", "")) for r in rows]
        want = ["python3 -m %s integration/t260902-07/tests/sc_x.py" % e
                for e in EXECUTOR_MODULES]
        check(res.status == "failed",
              "B1 every executor module still reds the stage", "status=%s" % res.status)
        check(len(rows) == len(want),
              "B2 exactly one row per executor module (no analyzer, no duplicate)",
              "rows=%d want=%d got=%s" % (len(rows), len(want), got[:12]))
        check(sorted(got) == sorted(want),
              "B3 the rows name the executor commands and only those",
              "got=%s" % got[:12])
        check(all(str(r.get("entry")) == "sc_*" for r in rows),
              "B4 each row keeps the scenario-script entry key",
              "entries=%s" % [r.get("entry") for r in rows][:12])

        # ---------------- B2: entry-module and plain execution forms ----------------
        print("== B2 entry-module and plain execution forms stay red")
        cmds = ["python3 -m run_scenarios", "python3 -m integration.run_scenarios",
                "python3 -m sc_x", RUNNER,
                "node integration/baselines/ticket-validate.mjs",
                "sh integration/with_stage.sh t260901-13",
                "bash -c 'python3 integration/run_scenarios.py'"]
        want_entries = ["run_scenarios.py", "run_scenarios.py", "sc_*",
                        "run_scenarios.py", "baselines", "with_stage.sh",
                        "run_scenarios.py"]
        res, rfile, _ = run_stage("developer", "implement", cmds)
        rows = disk_rows(rfile, "integration_violations") or []
        check(res.status == "failed", "B5 plain execution forms still red the stage",
              "status=%s" % res.status)
        check([r.get("entry") for r in rows] == want_entries,
              "B6 each execution form keeps its entry key",
              "entries=%s" % [r.get("entry") for r in rows])

        # ---------------- B3: exemption locality and non-retroactivity --------------
        print("== B3 the exemption is segment-local and never retroactive")
        mixed = "python3 -m pyflakes integration/sc_x.py && " + RUNNER
        res, rfile, _ = run_stage("developer", "implement", [mixed])
        rows = disk_rows(rfile, "integration_violations") or []
        check(res.status == "failed" and len(rows) == 1
              and rows[0].get("entry") == "run_scenarios.py",
              "B7 analyzer && real run leaves exactly one violation naming the run",
              "status=%s rows=%s" % (res.status, json.dumps(rows, ensure_ascii=False)[:300]))
        wash = RUNNER + " -m pyflakes"
        res, rfile, _ = run_stage("developer", "implement", [wash])
        rows = disk_rows(rfile, "integration_violations") or []
        check(res.status == "failed" and len(rows) == 1
              and rows[0].get("entry") == "run_scenarios.py",
              "B8 a trailing static module never washes an earlier run in the same segment",
              "status=%s rows=%s" % (res.status, json.dumps(rows, ensure_ascii=False)[:300]))

        # ---------------- C: malformed analyzer argv --------------------------------
        print("== C malformed analyzer argv never stops a good ticket")
        cmds = ['python3 -m pyflakes "unclosed integration/sc_x.py',
                "python3 -m", "python3 -m pyflakes", ""]
        bad_frames = [{"type": "tool/call", "seq": 99,
                       "data": {"name": "bash", "arguments": "{not json"}}]
        res, rfile, before = run_stage("developer", "implement", cmds,
                                       malformed_frames=bad_frames)
        rows = disk_rows(rfile, "integration_violations")
        check(res.status == "ok",
              "C1 malformed analyzer argv settles green (no crash, no false red)",
              "status=%s summary=%s" % (res.status, (res.summary or "")[:200]))
        check(rows == [], "C2 malformed analyzer argv writes no violation row",
              "rows=%s" % json.dumps(rows, ensure_ascii=False)[:300])
        check(rfile.read_bytes() == before,
              "C3 a green stage never rewrites the receipt on malformed input")

        # ---------------- D: the walkthrough/arbitrate evidence face ----------------
        print("== D the evidence face classifies the analyzer as a read, a run as a run")
        res, rfile, before = run_stage(
            "integration", "arbitrate",
            ["python3 -m pyflakes integration/run_scenarios.py",
             "python3 -m mypy integration/sc_x.py"])
        rows = disk_rows(rfile, "full_suite_violations")
        check(res.status == "ok",
              "D1 an analyzer command is not a suite invocation on the evidence face",
              "status=%s summary=%s" % (res.status, (res.summary or "")[:200]))
        check(rows == [], "D2 no full_suite_violations row for a read-only analyzer",
              "rows=%s" % json.dumps(rows, ensure_ascii=False)[:300])
        check(rfile.read_bytes() == before,
              "D3 the evidence face does not rewrite a clean receipt")

        res, rfile, _ = run_stage("integration", "arbitrate", [RUNNER])
        rows = disk_rows(rfile, "full_suite_violations") or []
        check(res.status == "failed" and len(rows) == 1,
              "D4 a bare full run is still caught by the evidence face",
              "status=%s rows=%s" % (res.status, json.dumps(rows, ensure_ascii=False)[:300]))
        check(bool(rows) and rows[0].get("kind") == "drift"
              and RUNNER in str(rows[0].get("cmd", "")),
              "D5 the row is a drift row and names the full-run command",
              "row=%s" % json.dumps(rows[:1], ensure_ascii=False)[:300])
        check(RUNNER in (res.summary or ""),
              "D6 the stage summary names the offending command (locatable on the face)",
              "summary=%s" % (res.summary or "")[:240])

        res, rfile, before = run_stage(
            "integration", "arbitrate",
            [RUNNER + " --only scene_x"])
        rows = disk_rows(rfile, "full_suite_violations")
        check(res.status == "ok" and rows == [],
              "D7 a targeted run stays green (the face is not washed to always-red)",
              "status=%s rows=%s" % (res.status, json.dumps(rows, ensure_ascii=False)[:300]))

        # ---------------- E: declaration and gate agree on the new form -------------
        print("== E the clause never advertises a form the gate rejects")
        clause = integration_discipline.prompt_clause()
        mentioned = [a for a in ANALYZERS if a in clause]
        check(bool(mentioned),
              "E1 the agent-facing clause advertises at least one static analyzer",
              "clause=%s" % clause[:240])
        bad = []
        for name in mentioned:
            for shape in ENTRY_SHAPES:
                hits = integration_discipline.scan_bash_command(
                    "python3 -m %s %s" % (name, shape))
                if hits:
                    bad.append("%s -> %s" % (name, shape))
        check(not bad,
              "E2 every advertised analyzer is accepted by the gate over each entry shape",
              "rejected=%s" % bad[:6])
    finally:
        lib_tmp_reclaim.reclaim_registered()

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
