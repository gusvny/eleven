#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101206_rounds_window.py — t261012-06: the retention window must
never delete its own kept evidence (grey-box L3, the REAL
integration/line_round_runner.py as a subprocess over a real git fixture
tree + a stub suite; offline seconds; zero docker/Temporal-server/browser;
never touches 3099/7233; the real ledgers are never written).

intent (ticket t261012-06, user words: the rounds dir held ten run-<id>
fixture dirs, the prune's name sort deleted the round dirs including the
round that is starting, and the delivery-ledger row carried the copy error
instead of the round's real reason):
    A. THE INCIDENT SHAPE (spec 1 + 4): a shared rounds dir already
       crowded with old run-<id> entries (which sort AFTER round-...) and
       foreign non-round entries. A round runs and keeps its retained
       suite.log; the NEXT round starting does not delete it, keeps its
       own evidence, and leaves foreign entries alone. The window keys on
       the round-dir shape and recency, never on a name sort over a
       shared directory.
    B. ROLLING STILL ROLLS: the retention window still keeps only about
       the declared number of round-shaped evidence dirs — the fix may not
       become "delete nothing".
    C. RETENTION-FAILURE HONESTY (spec 3): when the retained-log copy
       fails, the round still completes honestly (exit code, stdout
       header, terminal record all intact), the failure is NAMED (a
       LINE_ROUND_FACE note on stderr and a named note on the terminal
       face), and on a could-not-run round the runner's OWN reason line is
       not masked — the reason line leads and the retention notes trail
       it as the NAMED secondary note.

Layering / intent split (no intent-level duplication):
  - retained-log survival, plain rolling retention and live-pointer
    safety in an UNCROWDED dir belong to t261011-26-round-evidence-kept;
  - prune-policy unit truth tables belong to developer L1;
  - the runner->header contract belongs to t261009-77 / t261011-18.

Three states: the runner or git missing = ENV_FAIL exit 2; the incident
shape re-firing (round evidence deleted / foreign entries touched /
retention failure masking the round) = FAIL named (TDD signal
pre-implement), must be green at the integration gate / merge.
"""
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261012-06-rounds-window"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "integration" / "t261011-26"))

from lib_result import ScenarioCheck  # noqa: E402
from lib_t26101126_fixture import (Fixture, RUNNER,  # noqa: E402
                                   seed_run_dir)

TAG = "LINE_ROUND_FACE"
CROWD = 12  # more run-<id> entries than the declared keep window (10)


def _read_header(proc):
    """The runner's one JSON header on stdout (the round's own identity)."""
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None


def _crowd(face_dir):
    """Seed the exact incident shape: more run-<id> dirs than the window
    holds (they sort after round-), plus foreign non-round entries."""
    rounds = face_dir / "rounds"
    rounds.mkdir(parents=True, exist_ok=True)
    for i in range(CROWD):
        seed_run_dir(face_dir, "run-seed%02d" % i, age_orders=i + 1)
    foreign = []
    for name in ("scratch", "keepme"):
        d = rounds / name
        d.mkdir(exist_ok=True)
        (d / "marker.txt").write_text("not a round\n", encoding="utf-8")
        foreign.append(d)
    return foreign


def _round_shape_names(face_dir):
    rounds = face_dir / "rounds"
    if not rounds.is_dir():
        return []
    return sorted(d.name for d in rounds.iterdir()
                  if d.is_dir() and (d.name.startswith("round-")
                                     or d.name.startswith("run-")))


def main():
    chk = ScenarioCheck()
    if not RUNNER.is_file():
        chk.env_fail(NAME, "ENV_FAIL: line_round_runner.py missing")
        return 2
    fx = Fixture()

    # ---- A. the incident shape: crowded dir, two consecutive rounds ----
    face_a = fx.face_dir("crowded")
    foreign = _crowd(face_a)
    p1 = fx.run_round("green", face_dir=face_a)
    h1 = _read_header(p1)
    ok_a1 = p1.returncode == 0 and isinstance(h1, dict) and h1.get("id")
    log1 = None
    if ok_a1:
        log1 = face_a / "rounds" / str(h1["id"]) / "suite.log"
    chk.ok(ok_a1 and log1 is not None and log1.is_file(),
           "A1 first round in a crowded dir keeps its retained suite.log",
           "rc=%s header=%s log_exists=%s stderr=%s"
           % (p1.returncode, (h1 or {}).get("id"),
              log1 is not None and log1.is_file(), p1.stderr[-200:]))

    p2 = fx.run_round("green", face_dir=face_a)
    h2 = _read_header(p2)
    ok_a2 = p2.returncode == 0 and isinstance(h2, dict) and h2.get("id")
    log2 = (face_a / "rounds" / str(h2["id"]) / "suite.log") \
        if ok_a2 else None
    chk.ok(ok_a2 and log2 is not None and log2.is_file(),
           "A2 the NEXT round starting keeps its own evidence too",
           "rc=%s header=%s stderr=%s"
           % (p2.returncode, (h2 or {}).get("id"), p2.stderr[-200:]))
    chk.ok(ok_a1 and log1 is not None and log1.is_file(),
           "A3 the next round did NOT delete the first round's kept "
           "evidence (the incident: name sort ate every round dir)",
           "first round suite.log exists=%s"
           % (log1 is not None and log1.is_file()))
    f_ok = all(d.is_dir() and (d / "marker.txt").is_file()
               for d in foreign)
    chk.ok(f_ok, "A4 foreign non-round entries in the shared dir are "
           "never deleted by the retention window",
           "foreign intact=%s" % f_ok)

    # ---- B. rolling still rolls on round-shaped dirs ----
    names = _round_shape_names(face_a)
    chk.ok(0 < len(names) <= CROWD + 1,
           "B1 the window still prunes old round-shaped dirs (kept=%d, "
           "seeded=%d) — the fix is a shape-keyed window, not no-op"
           % (len(names), CROWD + 1),
           "round dirs=%s" % names)
    chk.ok(all(n.startswith(("round-", "run-")) for n in names)
           and sorted(d.name for d in (face_a / "rounds").iterdir()
                      if d.is_dir())[-2:] not in ([],),
           "B2 only round-shaped entries remain managed",
           "names=%s" % names)

    # ---- C. a retention-copy failure is named and never masks the round ----
    # C1 green path: the run dir's suite.log slot is occupied by a
    # directory, so the copy fails while every other face write succeeds.
    face_c = fx.face_dir("copyfail")
    bg, _env = fx.run_round_bg("slow", face_dir=face_c)
    planted = False
    deadline = time.time() + 30
    while time.time() < deadline and bg.poll() is None:
        rounds = face_c / "rounds"
        if rounds.is_dir():
            for d in rounds.iterdir():
                if d.is_dir() and d.name.startswith("round-"):
                    (d / "suite.log").mkdir(exist_ok=True)
                    planted = True
                    break
        if planted:
            break
        time.sleep(0.2)
    try:
        rc = bg.wait(timeout=90)
    except BaseException:
        bg.kill()
        rc = "killed"
    out = (bg.stdout.read() if bg.stdout else "") if rc != "killed" else ""
    err = (bg.stderr.read() if bg.stderr else "") if rc != "killed" else ""
    hc = _read_header(type("P", (), {"stdout": out, "returncode": 0})())
    chk.ok(rc == 0 and isinstance(hc, dict),
           "C1 a failed retained-log copy does not fail the round (exit, "
           "stdout header intact)",
           "rc=%s header=%s stderr=%s" % (rc, (hc or {}).get("id"),
                                          err[-200:]))
    face_ok = False
    if isinstance(hc, dict):
        fpath = face_c / "rounds" / str(hc["id"]) / "face.json"
        if fpath.is_file():
            try:
                fobj = json.loads(fpath.read_text(encoding="utf-8"))
                blob = json.dumps(fobj).lower()
                face_ok = ("retention" in blob or "suite log" in blob) \
                    and fobj.get("outcome", {}).get("verdict") == "green"
            except (OSError, ValueError):
                pass
    chk.ok(face_ok,
           "C2 the copy failure is NAMED on the terminal face without "
           "touching the round's verdict (named secondary note)",
           "face carries named retention note=%s" % face_ok)
    chk.ok(TAG in err and "retention" in err.lower(),
           "C3 the copy failure is NAMED on stderr (%s note)" % TAG,
           "stderr=%s" % err[-200:])

    # C2b could-not-run path: the rounds dir is made unwritable so start,
    # copy and finish all fail; the runner's OWN reason must still lead —
    # the retention warns come earlier, never in place of the reason.
    face_d = fx.face_dir("locked")
    (face_d / "rounds").mkdir(parents=True, exist_ok=True)
    os.chmod(str(face_d / "rounds"),
             stat.S_IRUSR | stat.S_IXUSR)  # read-only: writes fail
    try:
        pb = fx.run_round("boom", face_dir=face_d)
    finally:
        os.chmod(str(face_d / "rounds"), stat.S_IRWXU)
    lines = [ln for ln in pb.stderr.splitlines() if ln.strip()]
    reason_idx = [i for i, ln in enumerate(lines)
                  if "could_not_run:" in ln]
    # the CONTRACT is about the copy-failure family (the note that the
    # ledger row's stderr tail would otherwise lead with); "face start
    # failed" necessarily fires before the round even reaches the suite
    copy_warn_idx = [i for i, ln in enumerate(lines) if TAG in ln and
                     ("retention failed" in ln
                      or "terminal face write failed" in ln)]
    chk.ok(pb.returncode == 2 and reason_idx,
           "C4 the could-not-run round still exits 2 with its named "
           "reason despite the retention failure",
           "rc=%s stderr=%s" % (pb.returncode, pb.stderr[-200:]))
    chk.ok(bool(reason_idx) and
           (not copy_warn_idx or min(copy_warn_idx) > max(reason_idx)),
           "C5 every copy-failure warn trails the round's own reason "
           "line — the row's tail leads with the reason, the copy error "
           "is the NAMED secondary note",
           "first copy warn=%s reason line=%s"
           % (min(copy_warn_idx) if copy_warn_idx else None,
              max(reason_idx) if reason_idx else None))

    chk.finish(NAME)  # prints SUMMARY and exits 0/1 by the three-state contract
    return 0


if __name__ == "__main__":
    sys.exit(main())
