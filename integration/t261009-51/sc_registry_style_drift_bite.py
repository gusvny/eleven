#!/usr/bin/env python3
"""t261009-51 scenario 1: the registry lint BITES on serialization style drift,
names the drifting file and the first differing line, and NEVER rewrites.

Incident (KI-01M4HD396VNTTAY20CH0681N0Q): t261009-48 re-serialized
integration/test_anchors.json with 2-space indent, t261009-49 flipped it back
to 1-space; both diffs carried zero semantic change (9082 / ~9100 lines for
three real lines). The user-visible contract this entry pins:

- C1 on the clean tree the lint is GREEN with every declared registry on the
  canonical serialization (post-normalization state);
- C2 re-serializing a declared registry in a different style (1-space indent,
  content parsed-identical, proven in-scenario) turns the lint RED and the
  output NAMES the file and reports a first differing LINE — the reader sees
  the style drift, never a generic mismatch;
- C3 the lint does NOT rewrite: the file's bytes after the red run are
  identical to before (sha256) — a red is fixed by a human/ticket running the
  canonical writer, never by the gate silently reformatting;
- C4 restore hygiene: after byte-rollback the lint output no longer names the
  file (zero residue — the guard keeps its own hygiene).

Grey-box L3: real `python3 integration/lint_tests.py` subprocess on the real
tree, byte-backed transient rewrite of one declared registry, restored in
finally. Shape-anchored assertions only (filename present, a line-number
token present) — never the check's internal wording. The check must never
judge content: C2's rewrite is proven parsed-identical first, so any red it
produces can only be about serialization.

Run: python3 integration/t261009-51/sc_registry_style_drift_bite.py
(cwd = repo root). PASS 0 / FAIL 1 / ENV_FAIL 2.
Pre-normalization the clean-tree leg is red — expected TDD signal;
arbitrate/merge must be green.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TARGET = os.path.join(REPO, "integration", "test_anchors.json")

FAILURES = []
PLANTED = False
BEFORE_BYTES = None
RC1 = None


def check(name, cond, detail=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                       ("" if cond else " | " + detail)))
    if not cond:
        FAILURES.append(name)


def run_lint():
    p = subprocess.run(
        [sys.executable, os.path.join(REPO, "integration", "lint_tests.py")],
        cwd=REPO, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def main():
    global PLANTED, BEFORE_BYTES, RC1
    if not os.path.isfile(TARGET):
        print("ENV_FAIL: integration/test_anchors.json missing at %s" % TARGET)
        return 2
    try:
        BEFORE_BYTES = open(TARGET, "rb").read()
    except OSError as e:
        print("ENV_FAIL: registry unreadable: %s" % e)
        return 2
    obj = json.loads(BEFORE_BYTES.decode("utf-8"))

    # C1 clean tree: canonical everywhere -> lint green.
    rc1, out1 = run_lint()
    RC1 = rc1
    check("C1.clean-tree-lint-green", rc1 == 0,
          "rc=%s" % rc1)

    # Plant style drift: same content, 1-space indentation (the -49 style).
    drift = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if json.loads(drift.decode("utf-8")) != obj:
        print("FAIL C2.plant-parsed-identical | self-check: the planted "
              "rewrite changed content — aborting, this scenario only ever "
              "injects style drift")
        return 1
    with open(TARGET, "wb") as f:
        f.write(drift)
    PLANTED = True

    rc2, out2 = run_lint()
    named = "test_anchors.json" in out2
    # Line-level report: some line-number token must appear near the drift
    # report (shape anchor, not wording).
    line_reported = re.search(r"line\s*#?\s*\d+", out2, re.IGNORECASE) is not None
    check("C2.drift-lint-red", rc2 != 0, "rc=%s" % rc2)
    check("C2.drift-names-file", named, "output did not name test_anchors.json")
    check("C2.drift-reports-first-differing-line", line_reported,
          "no line-number token in lint output")

    # C3 the lint never rewrites: bytes unchanged after the red run.
    after = open(TARGET, "rb").read()
    check("C3.lint-never-rewrites",
          hashlib.sha256(after).hexdigest() ==
          hashlib.sha256(drift).hexdigest(),
          "file bytes changed by the lint run")

    return 0


def restore():
    global PLANTED, RC1
    if PLANTED and BEFORE_BYTES is not None:
        with open(TARGET, "wb") as f:
            f.write(BEFORE_BYTES)
        PLANTED = False
        # C4 restore hygiene: post-rollback the lint no longer names the file
        # for serialization drift and returns to the clean-tree verdict.
        rc4, out4 = run_lint()
        check("C4.post-restore-no-drift-named",
              "test_anchors.json" not in out4,
              "rc=%s, file still named after byte-rollback" % rc4)
        check("C4.post-restore-green-like-clean-tree", rc4 == RC1,
              "rc=%s vs clean rc=%s" % (rc4, RC1))


if __name__ == "__main__":
    code = 2
    try:
        code = main()
    finally:
        try:
            restore()
        except OSError as e:
            check("C4.restore", False, "rollback failed: %s" % e)
    print("SUMMARY %s: %d failure(s)" %
          ("PASS" if not FAILURES else "FAIL", len(FAILURES)))
    sys.exit(0 if not FAILURES else 1)
