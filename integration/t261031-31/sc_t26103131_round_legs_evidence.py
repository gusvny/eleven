#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26103131_round_legs_evidence.py — a REAL round's persisted record
names the failing legs of a red case (ticket t261031-14, KI-439; carried by
ticket t261031-31).
Transplanted to ticket t261031-31 (the re-created workflow of ticket
t261031-14) and moved under its own ticket directory: the own-scenario
derivation is PATH-KEYED (run_scenarios.own_set_entries matches
`integration/<ticket_id>/` in the registry command), so a case living in
the cancelled ticket's directory belongs to nobody (KI-445). The registry
ENTRY NAME stays `t261031-14-...` (other faces anchor it).

Run directly:
python3 integration/t261031-31/sc_t26103131_round_legs_evidence.py
(cwd = repo root).

Grey-box L3. The REAL integration/run_scenarios.py runs as a subprocess over a
private real-git fixture tree with an injected one-entry registry; the
run-scoped ledger is projected through SANDBAR_SCENARIO_LEDGER_DIR and every
assertion is read back FROM THE LEDGER FILE (`scenario-runs.jsonl`), never from
the writer's return value. Offline seconds, zero docker/Temporal-server/browser,
never touches 3099/7233.

Why a real round is needed on top of the write-path proof
(sc_t26103114_failing_leg_record.py): the leg rows live anywhere in a case's
output. The measured t261022-14 round kept only the last 1200 characters —
all "ok" lines — so a builder fed the TAIL would reproduce the incident
byte-for-byte. Only a real round proves the emit site reads the case's FULL
output.

A1  THE INCIDENT SHAPE — a red case prints 8 `FAIL <leg> — <reason>` rows
    FIRST, then 60 ok lines and its SUMMARY. The persisted header's
    failed_detail entry names ALL 8 legs with their reason lines, read back
    from the ledger file, while the evidence tail (still the auxiliary bound)
    holds no leg row at all: the record answers "which legs were red" from a
    round whose tail could not.
A2  THE GREEN CONTROL — the same round with the case passing persists a header
    with NO failed_detail key at all (the t261026-15 absence rule is intact).
A3  THE UNPARSEABLE RED — a red case whose output is prose only (no leg row)
    records that fact BY NAME (legs_parse == "unrecognized" plus its reason
    line); the entry never carries an empty leg list.

Three states: missing git / python3 / a suite module = ENV_FAIL exit 2. A
missing structured leg face = FAIL with a named leg (the TDD signal before the
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
NAME = "t261031-14-round-legs-evidence"
EXCLUDE_POOL = "exclusive"
SOURCE = "lane:line-round"
CASE = NAME
BOUND = 1200  # the tail bound the timings face already uses

LEGS = [
    ("P1/dark md-click opens reviewer", "click did not open the reviewer"),
    ("P3/dark four block kinds persist to lane file", "done=2 expected=4"),
    ("P5/dark edited block: thread survives or is outdated",
     "outdated=0 stillVisible=false"),
    ("P6/dark minimap marks + open counts + click", "nav missing"),
    ("P7/dark TOC lists h1 and h2", "h2 count 0"),
    ("P8/dark lane path + agent notice", "lane path missing from the panel"),
    ("P9/dark rail collapse control", "rail-toggle missing"),
    ("X1 zero pageerror", "pageerror count: 2"),
]
N_OK = 60

sys.path.insert(0, str(REPO / "integration"))
try:
    from lib_env import clean_narrowing_env  # noqa: E402
    from lib_result import ScenarioCheck  # noqa: E402
except Exception as _e:  # noqa: BLE001 — the declared environment face
    print("ENV_FAIL [%s] exit=2 integration libs unimportable: %s: %s"
          % (NAME, type(_e).__name__, _e), flush=True)
    sys.exit(2)

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

LIB_FILES = ("run_scenarios.py", "scenario_ledger.py", "lib_tmp_reclaim.py",
             "lib_env.py", "lib_result.py", "conftest_result_protocol.py",
             "conftest.py")
RUNS_NAME = "scenario-runs.jsonl"

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
    return subprocess.run(["git", *args], cwd=str(cwd),  # SANCTIONED-WAIT: fixture-local git command on a private tree, hard 120 s ceiling, never a poll
                          capture_output=True, text=True, timeout=120)


def _fixture_script() -> str:
    """The fixture round's one scenario, mode-switchable from the child env:
      legs        eight leg rows first, then ok noise and a SUMMARY (the
                  measured incident shape: no leg row survives in the tail);
      prose       prose only, no leg row and no SUMMARY (unparseable);
      pass        the green control.
    The case is red by EXIT CODE (the suite counts exit_code == 0 as pass)."""
    lines = ["  FAIL %s — %s" % (leg, reason) for leg, reason in LEGS]
    body = "\n".join(lines + ["  ok P2/dark row %02d — added blocks: 3" % i
                              for i in range(N_OK)])
    return r'''
import sys
import os
mode = os.environ.get("SC_T26103114_MODE", "legs")
body = %r
summary = "SUMMARY pass=%%d fail=%%d env_fail=0 na=0" %% (%d, %d)
if mode == "pass":
    sys.stdout.write("  ok P1/dark md-click opens reviewer\n")
    green = "SUMMARY pass=1 fail=0 env_fail=0 na=0"
    sys.stdout.write(green + "\n")
    sys.exit(0)
if mode == "prose":
    sys.stdout.write("the panel never became ready\nno row was counted\n")
    sys.exit(1)
sys.stdout.write(body + "\n" + summary + "\n")
sys.exit(1)
''' % (body, N_OK, len(LEGS))


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
    script = fixtures / "case_t26103114.py"
    script.write_text(_fixture_script(), encoding="utf-8")
    text = (integ / "run_scenarios.py").read_text(encoding="utf-8")
    entry = ('    (%r,\n'
             '     "fixture: one mode-switchable round injected by the '
             't261031-14 failing-leg scenario (not part of the real registry)",\n'
             '     "python3 %s", "ro"),\n]' % (NAME, script))
    head, sep, _tail = text.partition("\nSCENARIOS = [")
    if not sep:
        env_fail(NAME, "run_scenarios registry anchor missing "
                       "(SCENARIOS = [ moved)")
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
        p = subprocess.run(argv, cwd=str(tree), capture_output=True,
                           text=True, env=_round_env(ledger, env_extra or {}),
                           timeout=300)  # SANCTIONED-WAIT: drives the real suite over a private fixture tree; a hard 300 s outer deadline, expiry returns the named -9, never a poll
    except subprocess.TimeoutExpired as e:
        return -9, (e.stdout or ""), (e.stderr or "")
    return p.returncode, p.stdout or "", p.stderr or ""


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


def _fresh_ledger(name: str) -> Path:
    ledger = Path(str(_TMP)) / ("ledger-" + name)
    ledger.mkdir()
    return ledger


def main():
    global _TMP
    if shutil.which("git") is None:
        env_fail(NAME, "git is not on PATH (fixture trees need it)")
    _TMP = Path(tempfile.mkdtemp(prefix="sc-t26103114-"))
    tree = _build_tree(_TMP)

    # ---- A1: the incident shape, positive ----
    ledger = _fresh_ledger("legs")
    rc, out, err = _run_round(tree, ledger,
                              env_extra={"SC_T26103114_MODE": "legs"})
    hdr, headers = _header(ledger)
    ok(hdr is not None,
       "A1 exactly one header lands in the run-scoped ledger (rc=%s)" % rc,
       "headers=%d | %s" % (len(headers), (out or err)[-400:]))
    if hdr is None:
        return finish(NAME)
    detail = hdr.get("failed_detail")
    ok(isinstance(detail, dict) and CASE in detail,
       "A1 the red case rides the persisted failed_detail", repr(detail)[:400])
    entry = (detail or {}).get(CASE) or {}
    ok(entry.get("legs_parse") == "parsed",
       "A1 the persisted entry says parsed", repr(entry.get("legs_parse")))
    names = [r.get("leg") for r in entry.get("legs") or []
             if isinstance(r, dict)]
    for leg, _reason in LEGS:
        ok(leg in names,
           "A1 the REAL round's record NAMES the failing leg %r from the "
           "ledger FILE" % (leg[:48],))
    reasons = {r.get("leg"): r.get("reason") for r in entry.get("legs") or []
               if isinstance(r, dict)}
    ok(reasons.get(LEGS[1][0]) == LEGS[1][1],
       "A1 the reason line is the case's own text verbatim")
    evidence = entry.get("evidence") or ""
    ok(0 < len(evidence) <= BOUND,
       "A1 the evidence tail keeps its %d-char bound (got %d)"
       % (BOUND, len(evidence)))
    ok(not any(("FAIL %s" % leg) in evidence for leg, _r in LEGS),
       "A1 the incident is reproduced: NO leg row survives in that tail - the "
       "legs came from the case's full output, not the tail")

    # ---- A2: the green control ----
    g_ledger = _fresh_ledger("green")
    rc2, out2, err2 = _run_round(tree, g_ledger,
                                 env_extra={"SC_T26103114_MODE": "pass"})
    g_hdr, g_headers = _header(g_ledger)
    ok(g_hdr is not None,
       "A2 the green round writes exactly one header (rc=%s)" % rc2,
       "headers=%d | %s" % (len(g_headers), (out2 or err2)[-400:]))
    ok(g_hdr is not None and "failed_detail" not in g_hdr,
       "A2 the green header carries NO failed_detail key (absence, read back "
       "from the FILE)")

    # ---- A3: the unparseable red is NAMED ----
    p_ledger = _fresh_ledger("prose")
    rc3, out3, err3 = _run_round(tree, p_ledger,
                                 env_extra={"SC_T26103114_MODE": "prose"})
    p_hdr, p_headers = _header(p_ledger)
    ok(p_hdr is not None,
       "A3 the unparseable round writes exactly one header (rc=%s)" % rc3,
       "headers=%d | %s" % (len(p_headers), (out3 or err3)[-400:]))
    p_entry = ((p_hdr or {}).get("failed_detail") or {}).get(CASE) or {}
    ok(p_entry.get("legs_parse") == "unrecognized",
       "A3 a red with no parsable leg row records unrecognized by name",
       repr(p_entry.get("legs_parse")))
    ok(isinstance(p_entry.get("legs_note"), str)
       and p_entry["legs_note"].strip(),
       "A3 it carries the reason line naming what was looked for")
    ok("legs" not in p_entry,
       "A3 never a clean-looking empty leg list (no legs key at all)")
    return finish(NAME)


if __name__ == "__main__":
    sys.exit(main())
