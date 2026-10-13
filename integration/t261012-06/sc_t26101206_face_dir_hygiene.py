#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101206_face_dir_hygiene.py — t261012-06 spec 2: a scenario must
not leave entities in the directory a production face owns (static guard,
offline seconds, zero docker/Temporal-server/browser/network, never
touches 3099/7233).

intent (ticket t261012-06 spec 2, user words: the rounds dir held exactly
ten run-<id> directories written by the ticket's own scenarios — fixture
entities landed in the PRODUCTION face dir and the prune's name sort then
ate the real round dirs):
    Any integration scenario or test file that drives the real
    line-round runner must aim its face dir / projects root at a TEMP
    dir (pin SANDBAR_LINE_ROUND_FACE_DIR or SANDBAR_PROJECTS_DIR, or get
    the pin from the shared t261011-26 fixture lib). A file that spawns
    the runner without any such pin is a named polluter: its run-<id>
    entities land wherever resolve_develop_dir points — the production
    face dir — and the retention window then fights live rounds over a
    shared directory.

Guard shape (lint-grade, deliberately textual): for every integration/
*.py (scenarios, tests, ticket dirs) whose text references the real
runner (``line_round_runner``), require the file to mention a face-dir or
projects-root pin, or to import the shared fixture lib that does. Naming
the offender file IS the failure message — the fix is to add the pin at
that file's env assembly point.

Three states: this guard has no environment dependencies (pure file
scan) — PASS / FAIL only; a missing integration tree = FAIL named (it
can never be an environment problem).
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261012-06-face-dir-hygiene"

#: a DRIVER actually resolves/spawns/runs the REAL runner — the only acts
#: that make the runner resolve the face dir from the env seams (or fall
#: through to the real projects root):
#:   - a spawn: the runner's PATH on a line that also builds a command
#:     (python3 / sys.executable / Popen / subprocess), or
#:   - the engine's resolver seam (dc.resolve_runner) or the runner-command
#:     env seam (SANDBAR_LINE_ROUND_RUNNER).
#: NOT drivers (gate red t261012-06 gen1, the t261011-25 false positive):
#: a mere path STRING in an asset-existence table, or an in-process import
#: calling read_header/parse helpers with explicit dirs — those never
#: reach the face-dir resolution.
RUNNER_LINE = re.compile(
    r"line_round_runner\.py")
RUNNER_LINE_EXEC = re.compile(
    r"sys\.executable|python3|Popen|subprocess\.(run|Popen|check_output)")
RUNNER_SEAM = re.compile(
    r"dc\.resolve_runner\(|\[\"SANDBAR_LINE_ROUND_RUNNER\"\]")


def _is_driver(text):
    if RUNNER_SEAM.search(text):
        return True
    return any(RUNNER_LINE.search(ln) and RUNNER_LINE_EXEC.search(ln)
               for ln in text.splitlines())
#: the guard's contract is about scenario/test drivers only — library,
#: lint and suite-table files at the integration root are out of scope
SCOPE = re.compile(r"integration/t[^/]+/.+\.py$|integration/tests/.+\.py$")
#: the pin may be spelled as the env literal or via lib_round_face's
#: FACE_DIR_ENV constant (unit batteries use the constant)
PIN = re.compile(
    r"SANDBAR_LINE_ROUND_FACE_DIR|SANDBAR_PROJECTS_DIR|FACE_DIR_ENV")
SHARED_LIB = re.compile(r"lib_t26101126_fixture")


def main():
    root = REPO / "integration"
    offenders = []
    scanned = 0
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if path.name.startswith("sc_t26101206"):
            continue  # this guard and its sibling drive the runner pinned
        if not SCOPE.search(rel):
            continue  # contract scope: scenario/test drivers only
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not _is_driver(text):
            continue
        scanned += 1
        if PIN.search(text) or SHARED_LIB.search(text):
            continue
        offenders.append(rel)
    chk_ok = root.is_dir() and scanned > 0
    print("  ok scanned=%d runner-driving files, all pinned" % scanned
          if chk_ok and not offenders else
          "  FAIL %d runner-driving file(s) without a temp face-dir pin "
          "(each writes fixture entities into the production face dir): %s"
          % (len(offenders), ", ".join(offenders) or "?"))
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
          % (1 if (chk_ok and not offenders) else 0,
             0 if (chk_ok and not offenders) else 1))
    if not chk_ok:
        print("FAIL [%s] exit=1 | integration tree missing or no "
              "runner-driving file found — coverage problem, not green"
              % NAME)
        return 1
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
