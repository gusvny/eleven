#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26102615_failed_detail_evidence.py — t261026-15: a red round leaves its evidence.

Intent (user-visible behaviour; sources = the ticket acceptance verbatim:
"a run with a planted red case carries, in its persisted record, the failing
assertion line and the observed value verbatim; a record for a green round
carries no per-case tails; the size bound is enforced", and the incident that
motivated the ticket: two reds in one night could only be answered "flaky,
evidence: none" because the run record carried the failing case NAME and nothing
else — the assertion text and the observed value were discarded with the temp
tree):

  A. THE INCIDENT CHAIN, POSITIVE. A round whose single case FAILS with a planted
     assertion line and an observed value must persist a header that carries, per
     failing case, a bounded evidence tail containing that line and that value
     VERBATIM, readable back from the ledger FILE (reader side, never the
     writer's return value), accepted by the real header validator and by the
     real runner read-back (the relay keeps the key).
  B. THE GREEN CONTROL. The same round with a passing case persists a header with
     NO per-case tails at all — absence of the detail, never an empty map.
  C. THE SIZE BOUND. A failing case that prints megabytes contributes a bounded
     tail: the end marker present, the head marker ABSENT, length at the bound —
     a tail, not the whole log.

Layering and intent split (no intent-level duplication):
  * the builder/validator truth tables (malformed shapes, oversized evidence,
    bad dur_s, bool exclusion, >20-case truncation, malformed-input battery)
    belong to developer L1 (test_t261026_15_*);
  * the round-shape chain (run id minting, relay acceptance, narrowed-round
    honesty) belongs to t261013-04-line-round-run-record and its family — the
    fixture technique is shared with that entry; shared steps are not shared
    intent;
  * THIS entry uniquely owns the operator-facing promise: the persisted record
    answers "why was it red" for a planted red, stays silent for green, and
    stays bounded for a loud red.

Safety: the fixture tree and every ledger live in this scenario's private temp
directory (finally plus atexit reclaim). The real ledger is never written
(`SANDBAR_SCENARIO_LEDGER_DIR` projection). No port, no console (never 3099), no
docker, no Temporal server.

Three states: a missing `git`, `python3`, or suite module = ENV_FAIL exit 2. A
missing evidence tail = FAIL with a named leg (the TDD signal before the
landing; green is required at the integration gate).
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
NAME = "t261026-15-failed-detail-evidence"
EXCLUDE_POOL = "exclusive"
SOURCE = "lane:line-round"

ASSERTION = "FAIL t261026-15: planted assertion line (expected 42)"
OBSERVED = "observed=42 at t261026-15-observed-marker"
HEAD_MARK = "t26102615-HEAD-MARKER-"
END_MARK = "t26102615-END-MARKER " + OBSERVED
# The executor names the case by its REGISTRY entry name (arbitrated 261026);
# the fixture's own JSON "name" field never reaches the case rows.
CASE = NAME
BOUND = 1200  # the tail bound the timings face already uses

sys.path.insert(0, str(REPO / "integration"))
from lib_env import clean_narrowing_env  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

LIB_FILES = ("run_scenarios.py", "scenario_ledger.py", "lib_tmp_reclaim.py",
             "lib_env.py", "lib_result.py", "conftest_result_protocol.py",
             "conftest.py")
RUNS_NAME = "scenario-runs.jsonl"
ROWS_NAME = "scenario-results.jsonl"

_TMP = None
_RECLAIMED = False


def _cleanup():
    global _RECLAIMED
    if _RECLAIMED:
        return
    _RECLAIMED = True
    if _TMP is not None:
        shutil.rmtree(str(_TMP), ignore_errors=True)


atexit.register(_cleanup)


# ---------------------------------------------------------------- fixture

def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)  # SANCTIONED-WAIT: fixture-local git command on a private tree, hard 120 s ceiling, never a poll


def _fixture_script() -> str:
    """The fixture round's one scenario: pass, planted red, or loud red.

    The mode comes from SC_T26102615_MODE in the child environment:
      pass — one green case;
      fail — one failing case whose evidence/stdout carry the planted assertion
             line and the observed value;
      mega — one failing case that prints megabytes of head-marked filler and
             ENDS on the end marker (the bound leg's input).
    """
    return r'''
import json, os, sys
mode = os.environ.get("SC_T26102615_MODE", "pass")
assertion = %r
observed = %r
head_mark = %r
end_mark = %r
if mode == "pass":
    status, evidence, tail = "pass", "fixture", ""
elif mode == "fail":
    status = "fail"
    evidence = assertion + "\n" + observed
    tail = "noise before the failure\n" + evidence
else:
    status = "fail"
    # > 1 MB: the head marker printed ONCE at the very start, then anonymous
    # filler — so a bounded tail can hold the end without the head.
    filler = head_mark + "\n" + ("x" * 79 + "\n") * 14000
    evidence = assertion + "\n" + observed
    tail = filler + assertion + "\n" + observed + "\n" + end_mark
sys.stdout.write(tail + "\n")
print(json.dumps({"name": %r, "suite": "main", "status": status,
                  "cause": None if status == "pass" else "fail",
                  "reason": None if status == "pass" else "planted failure",
                  "evidence": evidence, "dur_s": 0.02,
                  "started": "2026-10-26T00:00:00+00:00", "git_sha": "",
                  "attempt": 1}, ensure_ascii=False))
# A case is red by EXIT CODE in this suite (run_scenarios counts exit_code == 0
# as pass — arbitrated 261026): the printed fail row alone never plants a red.
sys.exit(0 if status == "pass" else 1)
''' % (ASSERTION, OBSERVED, HEAD_MARK, END_MARK, CASE)


def _build_tree(root: Path) -> Path:
    """A private tree: the REAL suite with an injected one-entry registry."""
    tree = root / "tree-git"
    integ = tree / "integration"
    integ.mkdir(parents=True)
    missing = []
    for name in LIB_FILES:
        src = REPO / "integration" / name
        if src.is_file():
            shutil.copy2(str(src), str(integ / name))
        else:
            missing.append(name)
    if "run_scenarios.py" in missing or "scenario_ledger.py" in missing:
        env_fail(NAME, "suite modules missing from the tree under test: %s"
                 % ", ".join(missing))
    eng = tree / "server" / "engine"
    eng.mkdir(parents=True)
    fp = REPO / "server" / "engine" / "failure_protocol.py"
    if fp.is_file():
        shutil.copy2(str(fp), str(eng / "failure_protocol.py"))
    fixtures = root / "fixtures"
    fixtures.mkdir(exist_ok=True)
    script = fixtures / "case_t26102615.py"
    script.write_text(_fixture_script(), encoding="utf-8")
    # Registry injection: byte-identical except for the injected registry body
    # (the seam the run-record scenarios share).
    text = (integ / "run_scenarios.py").read_text(encoding="utf-8")
    entry = ('    (%r,\n'
             '     "fixture: one mode-switchable round injected by the '
             't261026-15 failed-detail evidence scenario (not part of the real '
             'registry)",\n'
             '     "python3 %s", "ro"),\n]' % (NAME, script))
    head, sep, _tail = text.partition("\nSCENARIOS = [")
    if not sep:
        env_fail(NAME, "run_scenarios registry anchor missing (SCENARIOS = [ moved)")
    text = head + sep + "\n" + entry + \
        text.split("\nSCENARIOS = [", 1)[1].split("\n]", 1)[1]
    (integ / "run_scenarios.py").write_text(text, encoding="utf-8")
    (tree / ".gitignore").write_text("out/\n__pycache__/\n", encoding="utf-8")
    (tree / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/run_scenarios.py\n",
        encoding="utf-8")
    for args in (["init", "-q"],
                 ["config", "user.email", "scenario@example.invalid"],
                 ["config", "user.name", "scenario"],
                 ["add", "-A"],
                 ["commit", "-q", "-m", "fixture"]):
        r = _git(*args, cwd=tree)
        if r.returncode != 0:
            env_fail(NAME, "fixture git %s failed: %s"
                     % (args[0], (r.stderr or r.stdout)[-300:]))
    return tree


# ---------------------------------------------------------------- round driving

def _round_env(ledger: Path, extra: dict) -> dict:
    """The round's environment, built the way the line round builds it."""
    declared = {
        "SANDBAR_SCENARIO_LEDGER_DIR": str(ledger),
        "SANDBAR_POOL_CONC": "4",
        "SANDBAR_CONC_POOLS": "main:1",
        "SANDBAR_UNDECLARED_POLICY": "record",
        "SANDBAR_INTEG_RUN_LOCK_PATH": str(Path(str(_TMP)) / "run.lock"),
        "SANDBAR_INTEG_LEDGER_SOURCE": SOURCE,
        "SANDBAR_LEDGER_REUSE": "0",
    }
    declared.update(extra or {})
    return clean_narrowing_env(declared)


def _run_round(tree: Path, ledger: Path, env_extra=None):
    argv = ["python3", "integration/run_scenarios.py",
            "--exclude-pools", EXCLUDE_POOL]
    try:
        p = subprocess.run(argv, cwd=str(tree), capture_output=True, text=True,
                           env=_round_env(ledger, env_extra or {}),
                           timeout=300)  # SANCTIONED-WAIT: drives the real suite over a private fixture tree; a hard 300 s outer deadline, expiry returns the named -9, never a poll
    except subprocess.TimeoutExpired as e:
        return -9, (e.stdout or ""), (e.stderr or "")
    return p.returncode, p.stdout or "", p.stderr or ""


def _summary(stdout: str):
    found = None
    for line in stdout.splitlines():
        if line.startswith("INTEG_SUMMARY "):
            try:
                found = json.loads(line[len("INTEG_SUMMARY "):])
            except ValueError:
                found = None
    return found


def _jsonl(path: Path):
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def _header(ledger: Path):
    headers = _jsonl(ledger / RUNS_NAME)
    return (headers[0] if len(headers) == 1 else None), headers


def _validate(hdr):
    """The header through the REAL validator, in a clean child process."""
    code = (
        "import json,sys;sys.path.insert(0,sys.argv[1]);"
        "import scenario_ledger as sl;"
        "h,why=sl.validate_run_header(json.loads(sys.argv[2]));"
        "print(json.dumps({'clean':h is not None,'why':why}))"
    )
    p = subprocess.run(
        ["python3", "-c", code, str(REPO / "integration"), json.dumps(hdr)],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,  # SANCTIONED-WAIT: one bounded validator readback, hard 120 s ceiling, a failure is named, never a poll
        env=clean_narrowing_env({"PYTHONPATH": str(REPO / "integration")}))
    if p.returncode != 0:
        return None, "validator_process_failed:%s" % (p.stderr or p.stdout)[-200:]
    for line in reversed((p.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                got = json.loads(line)
                return got.get("clean"), got.get("why")
            except ValueError:
                continue
    return None, "validator_produced_no_answer"


# ---------------------------------------------------------------- legs

def _fresh_ledger(name: str) -> Path:
    ledger = Path(str(_TMP)) / ("ledger-" + name)
    ledger.mkdir()
    return ledger


def _leg_a(tree: Path):
    """The planted red: the persisted record answers WHY it was red."""
    ledger = _fresh_ledger("a")
    rc, out, err = _run_round(tree, ledger,
                              env_extra={"SC_T26102615_MODE": "fail"})
    summary = _summary(out)
    ok(summary is not None, "A1 the red round completes and prints a summary",
       "rc=%s | %s" % (rc, out[-400:]))
    if summary is None:
        return
    run_id = summary.get("run_id")
    ok(isinstance(run_id, str) and run_id.strip(),
       "A2 a red round is still a proof: the summary carries a run id",
       repr(run_id))
    hdr, headers = _header(ledger)
    ok(hdr is not None, "A3 exactly one header lands in the run-scoped ledger",
       "headers=%d" % len(headers))
    if hdr is None:
        return
    detail = hdr.get("failed_detail")
    ok(isinstance(detail, dict) and CASE in detail,
       "A4 the persisted header carries per-case detail for the failing case "
       "(read back from the FILE, not from the writer's return value)",
       json.dumps(hdr)[:300])
    if not (isinstance(detail, dict) and CASE in detail):
        return
    entry = detail[CASE]
    ev = entry.get("evidence") if isinstance(entry, dict) else None
    ok(isinstance(ev, str) and ASSERTION in ev,
       "A5 the failing ASSERTION LINE is carried verbatim in the tail",
       repr(ev)[:300])
    ok(isinstance(ev, str) and OBSERVED in ev,
       "A6 the OBSERVED VALUE is carried verbatim in the tail", repr(ev)[:300])
    dur = entry.get("dur_s") if isinstance(entry, dict) else "missing"
    ok(dur is None or (isinstance(dur, (int, float)) and dur >= 0),
       "A7 the case duration is carried (a nonnegative number or honest null)",
       repr(dur))
    clean, why = _validate(hdr)
    ok(clean is True,
       "A8 the REAL header validator accepts a red header with the detail",
       "why=%s" % why)


def _leg_b(tree: Path):
    """The green control: no per-case tails, honest absence."""
    ledger = _fresh_ledger("b")
    rc, out, err = _run_round(tree, ledger,
                              env_extra={"SC_T26102615_MODE": "pass"})
    summary = _summary(out)
    ok(summary is not None, "B1 the green round completes", "rc=%s | %s"
       % (rc, out[-300:]))
    hdr, headers = _header(ledger)
    ok(hdr is not None, "B2 exactly one header lands", "headers=%d" % len(headers))
    if hdr is None:
        return
    ok("failed_detail" not in hdr,
       "B3 the green round's persisted record carries NO per-case tails "
       "(absence, never an empty map)", json.dumps(hdr)[:300])
    clean, why = _validate(hdr)
    ok(clean is True,
       "B4 the REAL validator accepts the green header without the key",
       "why=%s" % why)


def _leg_c(tree: Path):
    """The size bound: a megabyte-printing red contributes its tail, not its log."""
    ledger = _fresh_ledger("c")
    rc, out, err = _run_round(tree, ledger,
                              env_extra={"SC_T26102615_MODE": "mega"})
    summary = _summary(out)
    ok(summary is not None, "C1 the loud red round completes", "rc=%s | %s"
       % (rc, out[-300:]))
    hdr, _headers = _header(ledger)
    ok(hdr is not None, "C2 the header lands", "headers=%d" % len(_headers))
    if hdr is None:
        return
    entry = (hdr.get("failed_detail") or {}).get(CASE)
    ev = entry.get("evidence") if isinstance(entry, dict) else None
    ok(isinstance(ev, str) and 0 < len(ev) <= BOUND,
       "C3 the evidence is a BOUNDED tail (0 < len <= %d), not the whole log "
       "(the case printed megabytes)" % BOUND,
       "len=%s" % (len(ev) if isinstance(ev, str) else repr(ev)))
    ok(isinstance(ev, str) and END_MARK in ev,
       "C4 the tail keeps the END of the output (the failure is at the end)",
       repr(ev)[-200:])
    ok(isinstance(ev, str) and HEAD_MARK not in ev,
       "C5 the tail does NOT carry the megabyte head (a tail, not the log)",
       "")


def main() -> int:
    global _TMP
    if shutil.which("git") is None:
        env_fail(NAME, "git missing — the fixture tree cannot run")
    if shutil.which("python3") is None:
        env_fail(NAME, "python3 missing")
    _TMP = Path(tempfile.mkdtemp(prefix="sc_t26102615_"))
    try:
        tree = _build_tree(_TMP)
        _leg_a(tree)
        _leg_b(tree)
        _leg_c(tree)
    finally:
        _cleanup()
    finish(NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
