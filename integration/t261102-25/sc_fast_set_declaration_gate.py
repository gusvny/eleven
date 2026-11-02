#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261102-25 scenario: the lane's merge gate catches a fast member that
catches nothing.

Measured on main 9897c555 (integration gatekeeping, 2026-11-02): the new
scenario t261102-12-named-read-state carried the fast marker without a
FAST_SET_CATCH clause, so the registry-wide declaration validator refused and
EVERY face that drives the declaration stopped:
t261011-10-fast-proof-membership ENV_FAIL, t261011-10-proof-degradation-named
ENV_FAIL, t261011-11-fast-set-review-patrol FAIL 3/3,
t261018-01-closing-fast-once FAIL, t260919-02-terminal-face-board FAIL. The
pytest rod that judged the declaration existed and was red, but no merge-gate
check collected integration/tests, so the red sat on main until the next
gatekeeping round.

Intent (grey-box L2/L3, offline, about half a minute, read-only for the tree
under test, zero docker/Temporal-server/browser, never touches 3099/7233; the
gate's stdout and exit code are the public face under test, never an internal
callable):

  A1 the fixture is real - a shared git clone of this tree carries the SAME
     integration/ bytes the lane would land (the working tree's copy, not only
     the last commit), and neither probe member name exists in the shipped
     registry before injection (a real injection, not a fixture that was
     already broken).
  A2 THE INCIDENT REPLAYED - a fast-marked registry entry with NO catch
     clause is appended to the clone's registry; the FULL gate battery (the
     very command verify.yaml's `lint` check runs) exits non-zero, NAMES that
     member, and the naming row carries the declaration/catch concept. This is
     the merge-gate reach the incident proved missing: the lane would stop
     before main, not the fast-set family afterwards.
  A3 THE SHIPPED DECLARATION PASSES - with the clone restored byte-identically,
     the gate rule that caught A2 exits 0: the guard does not false-red the
     declaration it was built to protect.
  A4 THE PLACEHOLDER SHAPE IS CAUGHT TOO - the same member shape with a
     whitespace-only clause (a member that declares nothing, "the same escape
     in a new dress") is refused by name as well, and the missing-clause probe
     of A2 is NOT named in that run (the placeholder is judged on its own
     shape, not as a leftover).
  A5 HYGIENE - the clone registry is back to the exact bytes it started with,
     the tree under test is byte-identical (sha256 of
     integration/run_scenarios.py and integration/lint_tests.py read before
     and after), and the fixture clone is reclaimed on every path.

Intent split (no intent-level duplication): the declaration FACE (members and
clauses printed, gate faces refusing over fixture rosters) belongs to
t261009-16-fast-set-declaration / -gate; the patrol face and its record belong
to t261011-11-fast-set-review-patrol; the wiring of the lint battery into the
code lane belongs to t261004-34-lint-battery-wired-into-code-lane; the
interpreter lint's own vacuity control belongs to
t261026-35-interp-lint-gate; the validator truth tables and the in-process
reader rod belong to developer L1 (integration/tests/test_t26100916_fast_set.py).
THIS entry uniquely owns: a fast member that joined without an honest catch
declaration is stopped BY THE MERGE GATE'S OWN BATTERY, by name, in a
lane-shaped tree, and the shipped declaration passes the same rule.

Failure surfaces this case attacks: a guard that exists only in the pytest rod
(the incident's exact escape); a guard wired into the battery but silent about
the offending member; a placeholder clause accepted because the key exists; a
false red on the shipped declaration; a fixture run that mutates the tree under
test or leaks its clone.

Cost note (declared honestly): one full battery run in the clone (about 30 s,
dominated by the engine test collection) plus two seconds-scale scoped runs.
No real-tree body write, so the 'ro' pool may run this concurrently.

Run: python3 -B integration/t261102-25/sc_fast_set_declaration_gate.py
(cwd = repo root). PASS 0 / FAIL 1 / ENV_FAIL 2.
Pre-implement tree red on A2/A4 = the named TDD signal; arbitrate/merge must
be green.
"""
from __future__ import annotations

import atexit
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
REGISTRY_REL = "integration/run_scenarios.py"
GATE_REL = "integration/lint_tests.py"

#: Probe member names. They never exist in the shipped registry; the clone-only
#: injection creates them. The cmd points at an ALREADY registered scenario
#: script, so the injected entry adds no file and needs no anchor row of its own.
MISSING_PROBE = "t26110225-probe-fast-no-clause"
PLACEHOLDER_PROBE = "t26110225-probe-fast-empty-clause"
PROBE_CMD = "python3 integration/t261009-16/sc_fast_set_declaration.py"

FULL_GATE_TIMEOUT = 600
SCOPED_GATE_TIMEOUT = 180

FAILS: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print("PASS " + name)
    else:
        FAILS.append(name)
        print("FAIL " + name + ((" — " + str(detail)[:600]) if detail else ""),
              flush=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_entry(name: str, note: str, clause: str | None = None) -> str:
    """The injected registry tail: one fast-marked member with no clause, or
    (clause given) with that clause value installed (the placeholder shape)."""
    body = (
        "\n\n# t261102-25 probe (injected in the fixture clone only; the tree\n"
        "# under test is never written): a fast member that catches nothing.\n"
        "SCENARIOS.append((%r,\n"
        "                  %r,\n"
        "                  %r, \"ro\", \"fast\"))\n"
        % (name, note, PROBE_CMD)
    )
    if clause is not None:
        body += "FAST_SET_CATCH[%r] = %r\n" % (name, clause)
    return body


def build_fixture() -> tuple[Path, Path] | None:
    """A shared clone of this tree with the WORKING TREE's integration/ mirrored
    over it (the clone alone carries committed state only; the gate judges the
    lane's landed union). Returns (tmp_root, clone_root) or None."""
    if shutil.which("git") is None:
        print("ENV_FAIL: git unavailable, the fixture clone cannot be built")
        return None
    tmp = Path(tempfile.mkdtemp(prefix="t26110225-gate-"))
    clone = tmp / "clone"
    p = subprocess.run(["git", "clone", "-q", "--shared", str(REPO), str(clone)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       text=True, timeout=300)  # SANCTIONED-WAIT: local clone hang guard, not a state wait
    if p.returncode != 0:
        print("ENV_FAIL: git clone of the tree under test failed: %s"
              % (p.stderr or "")[-300:])
        return None
    exclude = shutil.ignore_patterns("__pycache__", ".sandbox", ".sandbar",
                                     "*.pyc")
    try:
        shutil.copytree(INTEG, clone / "integration", dirs_exist_ok=True,
                        ignore=exclude)
    except OSError as e:                       # noqa: BLE001 — named, not silent
        print("ENV_FAIL: integration/ could not be mirrored over the clone: %s"
              % e)
        return None
    return tmp, clone


def run_gate(root: Path, rules: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-B", GATE_REL]
    if rules:
        cmd.append("--rules=" + rules)
    return subprocess.run(cmd, cwd=str(root), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          timeout=(SCOPED_GATE_TIMEOUT if rules
                                   else FULL_GATE_TIMEOUT))


def rows_naming(out: str, name: str) -> list[str]:
    return [ln for ln in out.splitlines() if name in ln]


def main() -> int:
    if not (REPO / REGISTRY_REL).is_file() or not (REPO / GATE_REL).is_file():
        print("ENV_FAIL: %s or %s missing at the repo root" % (REGISTRY_REL,
                                                               GATE_REL))
        return 2
    shipped_registry = sha(REPO / REGISTRY_REL)
    shipped_gate = sha(REPO / GATE_REL)
    shipped_text = (REPO / REGISTRY_REL).read_text(encoding="utf-8")
    if MISSING_PROBE in shipped_text or PLACEHOLDER_PROBE in shipped_text:
        print("ENV_FAIL: a probe member name already exists in the shipped "
              "registry; this scenario cannot attribute its own injection")
        return 2

    built = build_fixture()
    if built is None:
        return 2
    tmp, clone = built
    atexit.register(shutil.rmtree, str(tmp), True)
    registry = clone / REGISTRY_REL
    clean_bytes: bytes | None = None
    try:
        clean_bytes = registry.read_bytes()
        print("== A1 fixture carries the lane's integration/ bytes")
        check("A1.fixture-mirrors-the-working-tree",
              hashlib.sha256(clean_bytes).hexdigest() == shipped_registry,
              "the clone's registry differs from the tree under test")

        # ---- A2 the incident: a fast member with no catch clause -----------
        print("== A2 a fast member that joined without a declaration is caught")
        registry.write_bytes(clean_bytes + probe_entry(
            MISSING_PROBE,
            "probe: a fast member joined without a fast-catch declaration").encode())
        r = run_gate(clone)
        out = r.stdout or ""
        named = rows_naming(out, MISSING_PROBE)
        check("A2a.gate-red", r.returncode != 0, "rc=%s tail=%r" % (r.returncode,
                                                                   out[-400:]))
        check("A2b.gate-names-the-member", bool(named),
              "no row named %s; tail=%r" % (MISSING_PROBE, out[-400:]))
        check("A2c.naming-row-carries-the-concept",
              any(("declaration" in ln or "catch" in ln) for ln in named),
              "rows naming the member: %r" % (named[:3],))
        rule_ids = sorted({m.group(0) for ln in named
                           for m in re.finditer(r"\bL\d+\b", ln)})

        # ---- A3 the shipped declaration passes the same rule ---------------
        registry.write_bytes(clean_bytes)
        print("== A3 the shipped declaration passes the rule that caught A2")
        check("A3a.clone-restored-byte-identical",
              sha(registry) == shipped_registry,
              "the clone's registry was not restored")
        scoped = rule_ids[0] if len(rule_ids) == 1 else None
        if scoped is None:
            print("NOTE  no single gate rule id could be read from the A2 rows "
                  "(%r); the clean leg runs the full battery instead" % (rule_ids,))
        r3 = run_gate(clone, scoped)
        out3 = r3.stdout or ""
        check("A3b.shipped-declaration-green", r3.returncode == 0
              and not rows_naming(out3, MISSING_PROBE),
              "rc=%s tail=%r" % (r3.returncode, out3[-400:]))

        # ---- A4 the placeholder shape (a clause that says nothing) ---------
        print("== A4 a placeholder clause is refused by name too")
        registry.write_bytes(clean_bytes + probe_entry(
            PLACEHOLDER_PROBE,
            "probe: a fast member declared a clause that says nothing",
            clause="   ").encode())
        r4 = run_gate(clone, scoped)
        out4 = r4.stdout or ""
        check("A4a.gate-red-on-placeholder", r4.returncode != 0,
              "rc=%s tail=%r" % (r4.returncode, out4[-400:]))
        check("A4b.gate-names-the-placeholder-member",
              bool(rows_naming(out4, PLACEHOLDER_PROBE)),
              "no row named %s; tail=%r" % (PLACEHOLDER_PROBE, out4[-400:]))
        check("A4c.judged-on-its-own-shape",
              not rows_naming(out4, MISSING_PROBE),
              "the placeholder run still named the missing-clause probe: %r"
              % (rows_naming(out4, MISSING_PROBE)[:3],))
    finally:
        if clean_bytes is not None and registry.exists():
            registry.write_bytes(clean_bytes)
        shutil.rmtree(str(tmp), ignore_errors=True)

    # ---- A5 hygiene ------------------------------------------------------
    print("== A5 the fixture and the tree under test are left untouched")
    check("A5a.fixture-reclaimed", not tmp.exists(),
          "the fixture root still exists: %s" % tmp)
    check("A5b.tree-under-test-byte-identical",
          sha(REPO / REGISTRY_REL) == shipped_registry
          and sha(REPO / GATE_REL) == shipped_gate,
          "the tree under test changed while the scenario ran")

    print("SUMMARY: pass=%d fail=%d env_fail=0 na=0" % (PASSES, len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
