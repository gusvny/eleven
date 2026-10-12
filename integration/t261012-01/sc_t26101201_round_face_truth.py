#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101201_round_face_truth.py — t261012-01, the round face must not
print a green it cannot support (grey-box L3, the REAL
integration/line_round_runner.py as a subprocess over a real git fixture
tree + stub suites, offline seconds, zero docker/Temporal-server/browser,
never touches 3099/7233; the real ledgers are never written).

intent (user words, verbatim: "Found the moment t261011-26 landed and the
face became readable: face.json reads {'state': 'done', 'counts': {'ran':
0, ...}, 'outcome': {'verdict': 'green'}} while the suite.log retained
beside it says INTEG_SUMMARY {'ran': 1, ...}" — the host reads this face):
    A. NO GREEN OVER NOTHING: a round whose header/summary counted
       ran == 0 is never published as green — the face says so (the
       no-proof verdict), mirroring the engine's rule in
       server/engine/develop_certify.run_verdict ("ran == 0 is never a
       proof, a live incident made that rule"). This is the incident
       class, replayed end to end.
    B. TERMINAL FACTS ONLY: 'done' is written only when the suite's own
       INTEG_SUMMARY was seen and parsed; a suite that exits 0 WITHOUT a
       summary line lands state=failed with the runner's named reason —
       never a fabricated done.
    C. COUNTS AGREE, OR ARE NAMED UNREADABLE: for the same round, the
       counts on the terminal face agree with the counts in the retained
       suite.log read back from the READER side (rounds/<run_id>/suite.log);
       a real summary beside per-scenario lines the parser does not know
       never publishes silent zeros — the face carries the summary's own
       numbers (and the unreadable-shape note), never zeros next to a
       summary that counted something.
    D. FOUR-WAY TERMINALS STAY DISTINGUISHABLE: green / red / no-proof /
       failed+named-reason remain four different records read back from
       disk without worker.log — that distinction is the whole point of
       the face.

Layering / intent split (no intent-level duplication):
  - the live face while running, retained-evidence survival, rolling
    retention and overlapping-round safety belong to the t261011-26
    sibling entries (already shipped) — this file reuses their shared
    fixture helpers and does NOT re-prove visibility or retention;
  - parser truth tables, torn JSON rows and idempotent re-parse belong
    to developer L1;
  - the panel's rendering of the verdicts is its own ticket, out of
    scope; the round's scope is out of scope.

Three states: the runner or git missing = ENV_FAIL exit 2; the incident
class replaying (green over ran=0, zeros beside a real summary, a done
without a summary) = FAIL named (the TDD signal, pre-implement tree red);
must be green at the integration gate / merge.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261012-01-round-face-truth"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "integration" / "t261011-26"))
from lib_result import ScenarioCheck  # noqa: E402
from lib_t26101126_fixture import Fixture, RUNNER  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

if not RUNNER.is_file():
    env_fail("line_round_runner missing", str(RUNNER))

# ---- my stub suite: the t261011-26 fixture's stub shapes, plus the
# incident-class modes this ticket exists for. Written OVER the fixture's
# stub inside the fixture tree (shared helpers reused, new behaviour
# local to this ticket; the fixture tree is per-scenario temp).
STUB = '''#!/usr/bin/env python3
"""Stub full suite with t261012-01 incident-class modes."""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration"))
import scenario_ledger as sl

mode = sys.argv[1]
candidates = json.loads(os.environ["SANDBAR_LINE_ROUND_CANDIDATES"])
ledger = Path(os.environ["SANDBAR_SCENARIO_LEDGER_DIR"])
ledger.mkdir(parents=True, exist_ok=True)
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                      capture_output=True, text=True).stdout.strip()
run_id = sl.mint_run_id()

# per-mode scenario blocks the face parser is expected to recognise
scen = {"green": [("sc_alpha", "PASS"), ("sc_beta", "PASS")],
        "red": [("sc_red_one", "FAIL")],
        "empty": [],
        "drift": [("sc_drift_one", "PASS")],
        "nosummary": [("sc_alpha", "PASS")]}[mode]

for name, verdict in scen:
    if mode == "drift":
        # THE INCIDENT SHAPE: a real summary exists below, but the
        # per-scenario lines are in a vocabulary the face parser has
        # never seen (not PASS/FAIL/ENV_FAIL blocks)
        print("ok  %s  0.1s" % name, flush=True)
    elif verdict == "PASS":
        print("PASS [%s] (0.1s)" % name, flush=True)
    else:
        print("FAIL [%s] exit=1 (0.1s)\\n    stub: product red" % name,
              flush=True)

cases = {
    "ran": len(scen),
    "passed": sum(1 for _, v in scen if v == "PASS"),
    "failed": sum(1 for _, v in scen if v == "FAIL"),
    "env_failed": sum(1 for _, v in scen if v == "ENV_FAIL"),
}
env_fp = hashlib.sha256(b"stub-suite").hexdigest()
for name, verdict in scen:
    row = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit": head,
        "env_fp": env_fp,
        "conc_width": 1,
        "pool": "serial",
        "scenario": name,
        "verdict": {"PASS": "pass", "FAIL": "fail",
                    "ENV_FAIL": "env_fail"}[verdict],
        "wall_s": 0.1,
        "source": "lane:stub",
        "ticket": "t261012-01",
        "run": run_id,
    }
    clean, why = sl.validate_row(row)
    if clean is None:
        sys.stderr.write("stub row refused: %s\\n" % why)
        sys.exit(2)
    if sl.append_records([clean])["written"] != 1:
        sys.stderr.write("stub row not written\\n")
        sys.exit(2)
header = {
    "v": sl.RUN_HEADER_V,
    "id": run_id,
    "repos": candidates,
    "suite": "full",
    "source": "lane:stub",
    "env_fp": env_fp,
    "conc_width": 1,
    "pool": "serial",
    "started_at": int(time.time() * 1000),
    "duration_s": 0.1,
    "cases": cases,
    "verdict": sl.run_verdict(cases),
}
if sl.append_run_header(header)["written"] != 1:
    if mode != "empty":
        sys.stderr.write("stub header refused\\n")
        sys.exit(2)
    # THE INCIDENT WRITER, replayed: the ledger's write face (rightly)
    # refuses a ran=0 header as "never a proof", but the runner's face must
    # defend itself anyway — a degraded / pre-guard writer can land a raw
    # zero-count header line directly (read_header reads it back without
    # revalidation). This is the exact shape the live incident produced.
    with open(str(ledger / sl.RUNS_NAME), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\\n")
if mode != "nosummary":
    print("INTEG_SUMMARY " + json.dumps(
        {"ran": cases["ran"], "passed": cases["passed"],
         "failed": cases["failed"], "env_failed": cases["env_failed"],
         "run_id": run_id}), flush=True)
else:
    # exit 0 WITHOUT the completion mark: no terminal fact
    print("stub: done, no summary line", flush=True)
sys.exit(0)
'''


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  an unparseable face is a red, not a crash
        return None


def _terminal(face_dir):
    faces = sorted((face_dir / "rounds").glob("*/face.json")) \
        if (face_dir / "rounds").is_dir() else []
    return (faces[0] if faces else None)


def _log_summary_counts(log_path):
    """Reader-side: the suite's own numbers, parsed from the retained log."""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        if line.startswith("INTEG_SUMMARY "):
            try:
                s = json.loads(line[len("INTEG_SUMMARY "):])
                return {k: s.get(k) for k in
                        ("ran", "passed", "failed", "env_failed")}
            except ValueError:
                return None
    return None


try:
    fx = Fixture()
except Exception as e:  # noqa: BLE001
    env_fail("fixture tree unbuildable",
             "%s: %s" % (type(e).__name__, e))
    sys.exit(2)
(fx.src / "tools" / "stub_suite.py").write_text(STUB, encoding="utf-8")
# the runner CLONES the fixture tree from its committed HEAD, so this
# ticket's stub modes must be IN the commit the round reads
subprocess.run(["git", "add", "-A"], cwd=str(fx.src), check=True,
               capture_output=True,
               # SANCTIONED-WAIT: ceiling on a sanctioned child-process git call
               timeout=120)
subprocess.run(["git", "commit", "-q", "-m", "fixture: t261012-01 "
                "incident-class stub modes"], cwd=str(fx.src), check=True,
               capture_output=True,
               # SANCTIONED-WAIT: ceiling on a sanctioned child-process git call
               timeout=120)
fx.head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(fx.src),
                         capture_output=True, text=True,
                         # SANCTIONED-WAIT: ceiling on a sanctioned child-process git call
                         timeout=120).stdout.strip()

# ---- A: the incident class — a round that ran nothing must not be green
fd_empty = fx.face_dir("empty")
proc_e = fx.run_round("empty", face_dir=fd_empty)
tp = _terminal(fd_empty)
tf = _read_json(tp) if tp else None
out = (tf or {}).get("outcome") or {}
ok(tp is not None and (tf or {}).get("state") == "done",
   "A1 a zero-ran round with a parsed summary still ends state=done "
   "(it completed — the truth is in the verdict, not the state)",
   "rc=%d face=%r stderr=%r"
   % (proc_e.returncode, tf, (proc_e.stderr or "")[-200:]))
ok(out.get("verdict") not in (None, "green"),
   "A2 THE INCIDENT: a round that ran nothing is NEVER published green "
   "(ran=0 is not a proof; the face names the no-proof verdict instead)",
   "outcome=%r face=%r" % (out, tf))
ok((tf or {}).get("counts", {}).get("ran") == 0
   and out.get("verdict") == "no_proof",
   "A3 the no-proof verdict carries the zero counts and a nameable "
   "state (distinguishable from red and from could-not-run)",
   "outcome=%r counts=%r" % (out, (tf or {}).get("counts")))

# ---- B: exit 0 with no INTEG_SUMMARY is a named failure, never done
fd_ns = fx.face_dir("nosummary")
proc_n = fx.run_round("nosummary", face_dir=fd_ns)
tp_n = _terminal(fd_ns)
tf_n = _read_json(tp_n) if tp_n else None
out_n = (tf_n or {}).get("outcome") or {}
ok(proc_n.returncode != 0 and (tf_n or {}).get("state") == "failed"
   and bool(out_n.get("reason")) and "summary" in (out_n.get("reason") or ""),
   "B1 a suite exiting 0 WITHOUT its INTEG_SUMMARY lands state=failed "
   "with a reason NAMING the missing summary — never a done",
   "rc=%d face=%r stderr=%r"
   % (proc_n.returncode, tf_n, (proc_n.stderr or "")[-200:]))

# ---- C1: real summary + unknown per-scenario shape => no silent zeros
fd_dr = fx.face_dir("drift")
proc_d = fx.run_round("drift", face_dir=fd_dr)
tp_d = _terminal(fd_dr)
tf_d = _read_json(tp_d) if tp_d else None
log_counts = _log_summary_counts(tp_d.parent / "suite.log") if tp_d else None
face_counts = (tf_d or {}).get("counts") or {}
ok(tp_d is not None and log_counts is not None and log_counts["ran"] == 1,
   "C0 fixture sanity: the retained log beside the face really counts "
   "ran=1 (the reader-side fact the face must agree with)",
   "face=%r log_counts=%r stderr=%r"
   % (tf_d, log_counts, (proc_d.stderr or "")[-200:]))
ok(face_counts.get("ran") == 1,
   "C1 THE INCIDENT: a real summary beside per-scenario lines the parser "
   "does not know NEVER publishes zeros — the face carries the summary's "
   "own ran (or names the shape unreadable), not {ran: 0}",
   "face_counts=%r log_counts=%r" % (face_counts, log_counts))
same = all(face_counts.get(k) == log_counts.get(
    {"ran": "ran", "passed": "passed", "failed": "failed",
     "env_fail": "env_failed"}.get(k, k))
    for k in ("ran", "passed", "failed")) if log_counts else False
ok(same or bool((tf_d or {}).get("counts_note")),
   "C2 the face's counts agree with the retained log's summary for the "
   "same round, or the face says 'counts unreadable: <why>'",
   "face_counts=%r log_counts=%r counts_note=%r"
   % (face_counts, log_counts, (tf_d or {}).get("counts_note")))

# ---- C3: a fully recognisable round — face counts == log counts,
# read back from the reader side of the SAME round id
fd_g = fx.face_dir("green")
proc_g = fx.run_round("green", face_dir=fd_g)
tp_g = _terminal(fd_g)
tf_g = _read_json(tp_g) if tp_g else None
log_g = _log_summary_counts(tp_g.parent / "suite.log") if tp_g else None
fc_g = (tf_g or {}).get("counts") or {}
agree = bool(log_g) and fc_g.get("ran") == log_g["ran"] \
    and fc_g.get("fail") == log_g["failed"] \
    and fc_g.get("env_fail") == log_g["env_failed"]
ok(proc_g.returncode == 0 and (tf_g or {}).get("state") == "done"
   and ((tf_g or {}).get("outcome") or {}).get("verdict") == "green"
   and agree,
   "C3 a healthy green round: face counts agree with the retained log's "
   "own summary, read back from the reader side",
   "face=%r log=%r" % (fc_g, log_g))

# ---- D: the four terminals stay four different records
fd_r = fx.face_dir("red")
proc_r = fx.run_round("red", face_dir=fd_r)
tp_r = _terminal(fd_r)
tf_r = _read_json(tp_r) if tp_r else None
verdicts = {
    "green": ((tf_g or {}).get("outcome") or {}).get("verdict"),
    "red": ((tf_r or {}).get("outcome") or {}).get("verdict"),
    "no_proof": out.get("verdict"),
    "failed": (tf_n or {}).get("state"),
}
ok(verdicts["red"] == "red",
   "D1 a completed red is still red (a proof, not could-not-run)",
   "red face=%r" % tf_r)
ok(len(set(verdicts.values())) == 4,
   "D2 the four terminals are four distinguishable records: green / red / "
   "no-proof / failed+named-reason — the whole point of the face",
   "verdicts=%r" % verdicts)

finish(NAME)
