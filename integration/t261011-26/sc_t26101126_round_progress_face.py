#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101126_round_progress_face.py — t261011-26, the running line round
is VISIBLE while it runs and its outcome stays readable after it ends
(grey-box L3, the REAL integration/line_round_runner.py as a subprocess over
a real git fixture tree + a stub suite, offline seconds, zero docker/
Temporal-server/browser, never touches 3099/7233; the real ledgers are never
written).

intent (user words: "is there really nowhere to see how the line run is
going?" — today the round is only readable from a system temp dir that is
rmtree'd the moment it ends):
    A. LIVE FACE: while the round runs, a face EXISTS at the stable,
       predictable path under the declared face dir (rounds/current.json),
       parseable on every poll, carrying state=running, a run_id,
       started_at/updated_at, the counts so far that GROW as the suite
       judges scenarios, and the last judged scenario's name + verdict.
       Read back from the file face (reader side), not from any writer
       receipt.
    B. TERMINAL OUTCOMES DISTINGUISHABLE WITHOUT worker.log — three rounds,
       three different terminal faces read back from disk: green (state
       done, outcome green), red (completed but failed>0 — outcome red,
       NOT could-not-run), and could-not-run (stub exits nonzero with no
       summary — state failed carrying the runner's named reason). The
       four verdicts (green/red/could-not-run/timeout) are no longer one
       indistinguishable silence.
    C. ABSENCE = IDLE: after every finished round current.json is GONE
       (the rule certification-model's roundState input already declares),
       while a terminal record survives in the round's own directory.
    D. ROUND CONTRACT UNCHANGED: the face is a pure observer — the runner
       still writes EXACTLY ONE JSON header on stdout, exit semantics
       (0 on a completed red, nonzero could-not-run) untouched, and a
       round whose face dir cannot be resolved still completes honestly
       with a NAMED stderr note and no face written anywhere.

Layering / intent split (no intent-level duplication):
  - parser truth tables (log vocabulary, torn JSON rows, idempotent
    re-parse), atomic-write injection, and per-field shape validation
    belong to developer L1 (the in-ticket unit battery);
  - the runner->header contract, red-is-a-proof, malformed candidates,
    timeout, SIGTERM reclaim belong to t261009-77-line-round-runner and
    the t261011-18 asset family;
  - the panel's rendering of the face (roundState consumption by the
    certification adapter) is its own ticket, out of scope here;
  - retained evidence, rolling retention and the overlapping-round
    safety belong to the sibling t261011-26-round-evidence-kept entry.

Three states: the runner or git missing = ENV_FAIL exit 2; the declared
face seams missing (no live face, no terminal record) = FAIL named (TDD
signal pre-implement), must be green at the integration gate / merge.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261011-26-round-progress-face"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "integration"))
from lib_result import ScenarioCheck  # noqa: E402
from lib_t26101126_fixture import (Fixture, CURRENT,  # noqa: E402
                                   FACE_DIR_ENV, RUNNER)

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

if not RUNNER.is_file():
    env_fail("line_round_runner missing", str(RUNNER))
try:
    fx = Fixture()
except Exception as e:  # noqa: BLE001
    env_fail("fixture tree unbuildable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  (a face that cannot be parsed is a red, not a crash)
        return None


def _poll_live(face_dir, want_checks, window_s=25):
    """Poll the stable live path while the round runs; run the wanted
    predicates against the freshest parseable face seen."""
    path = face_dir / CURRENT
    deadline = time.time() + window_s
    seen = []
    while time.time() < deadline and not path.exists():
        time.sleep(0.2)
    while time.time() < deadline and path.exists():
        face = _read_json(path)
        if face is not None:
            seen.append(face)
        time.sleep(0.5)
    return seen


def _wait_gone(path, window_s=60):
    deadline = time.time() + window_s
    while time.time() < deadline and path.exists():
        time.sleep(0.2)
    return not path.exists()


# ---- A + C(green half): the live face during a slow green round ----
fd_green = fx.face_dir("green")
proc_g, env_g = fx.run_round_bg("slow", face_dir=fd_green)
live = _poll_live(fd_green, None)
# bound on a seconds-scale stub round; leak guard, not a wait under test
# SANCTIONED-WAIT: ceiling on the background stub runner reclamation
proc_g.wait(timeout=120)
_g_out, _g_err = proc_g.communicate()
_g_err = _g_err or ""
ok(bool(live),
   "A1 live face exists at the stable path while the round runs",
   "no rounds/current.json ever appeared under %s; stderr tail %r"
   % (fd_green, _g_err[-200:]))
if live:
    growing = any(b["counts"]["ran"] > a["counts"]["ran"]
                  for a, b in zip(live, live[1:]))
    ok(growing,
       "A2 the face's counts grow while the suite judges (ran climbs)",
       "counts seen: %r" % [f.get("counts") for f in live[:6]])
    last = live[-1]
    ok(last.get("state") == "running"
       and bool(last.get("run_id"))
       and bool(last.get("started_at")) and bool(last.get("updated_at")),
       "A3 the live face names state=running with run_id and timestamps",
       "face: %r" % {k: last.get(k) for k in
                     ("state", "run_id", "started_at", "updated_at")})
    named = [f.get("last_scenario") for f in live if f.get("last_scenario")]
    ok(bool(named) and all(n.get("name") and n.get("verdict")
                           for n in named),
       "A4 the last judged scenario's name and verdict are on the face",
       "last_scenario seen: %r" % named[:4])
else:
    ok(False, "A2-A4 live face legs (skipped: no face ever appeared)",
       "live-poll window expired")

# C green half + terminal face (the round may still be writing its terminal
# record when the live face disappears — bounded wait, then judge)
term_dirs = []
deadline = time.time() + 30
while time.time() < deadline and not term_dirs:
    term_dirs = list((fd_green / "rounds").glob("*/face.json")) \
        if (fd_green / "rounds").is_dir() else []
    time.sleep(0.2)
ok(not (fd_green / CURRENT).exists(),
   "C1 after the round ends current.json is GONE (absence = idle)",
   "current.json still present after round end")
ok(proc_g.returncode == 0 and len(term_dirs) == 1,
   "B-green the green round ends exit 0 with exactly one terminal record",
   "rc=%d stderr=%r terminal faces=%d"
   % (proc_g.returncode, _g_err[-160:], len(term_dirs)))
if term_dirs:
    tf = _read_json(term_dirs[0])
    out = (tf or {}).get("outcome") or {}
    ok((tf or {}).get("state") == "done" and out.get("verdict") == "green",
       "B-green the terminal record says done/green, readable without "
       "worker.log", "face: %r" % tf)
else:
    ok(False, "B-green terminal record legs (skipped: none landed)",
       "no rounds/*/face.json")

# ---- B red + could-not-run, each in its own face dir ----
fd_red = fx.face_dir("red")
proc_r = fx.run_round("red", face_dir=fd_red)
red_faces = list((fd_red / "rounds").glob("*/face.json")) \
    if (fd_red / "rounds").is_dir() else []
ok(proc_r.returncode == 0 and red_faces,
   "B-red a completed-but-red round still exits 0 and leaves a terminal "
   "record", "rc=%d faces=%d" % (proc_r.returncode, len(red_faces)))
if red_faces:
    tf = _read_json(red_faces[0])
    out = (tf or {}).get("outcome") or {}
    ok(out.get("verdict") == "red",
       "B-red the terminal outcome says RED (a red is a proof, never "
       "could-not-run)", "outcome: %r" % out)
else:
    ok(False, "B-red outcome leg (skipped: no terminal record)",
       "no face.json under %s" % fd_red)

fd_cnr = fx.face_dir("cnr")
proc_c = fx.run_round("boom", face_dir=fd_cnr)
cnr_faces = list((fd_cnr / "rounds").glob("*/face.json")) \
    if (fd_cnr / "rounds").is_dir() else []
ok(proc_c.returncode != 0,
   "B-cnr a could-not-run round exits nonzero (the engine's contract, "
   "unchanged by the face)", "rc=%d stderr=%r"
   % (proc_c.returncode, (proc_c.stderr or "")[-160:]))
ok(cnr_faces and _read_json(cnr_faces[0]) is not None
   and (_read_json(cnr_faces[0]).get("state") == "failed")
   and bool((_read_json(cnr_faces[0]).get("outcome") or {}).get("reason")),
   "B-cnr the could-not-run is VISIBLE as failed + named reason on the "
   "terminal record (not silence, not a fabricated red)",
   "faces=%d stderr tail=%r" % (len(cnr_faces), (proc_c.stderr or "")[-200:]))
ok(not (fd_cnr / CURRENT).exists(),
   "C2 a failed round also leaves absence = idle (no stale running face)",
   "current.json survived a failed round")

# ---- D honest degrade: unresolvable face dir, round still runs ----
empty_projects = fx.tmp / "empty-projects"
empty_projects.mkdir(exist_ok=True)
proc_d = fx.run_round("green", projects_dir=empty_projects)
no_face = not (fx.tmp / "rounds").exists()
ok(proc_d.returncode == 0 and "face" in (proc_d.stderr or "").lower()
   and no_face,
   "D an unresolvable face dir degrades NAMED on stderr, writes NO face, "
   "and the round still completes honestly",
   "rc=%d stderr tail=%r stray face tree=%s"
   % (proc_d.returncode, (proc_d.stderr or "")[-200:], no_face))

finish(NAME)
