#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101304_line_round_run_record.py — t261013-04: a line round books a proof.

Intent (user-visible behaviour; sources = the ticket acceptance "a full line round
after the landing books a certification row, not could-not-run rows", and the run
record contract in docs/reference/ledger-record-models-v1.md section A):

  A. THE INCIDENT CHAIN, POSITIVE. A round drives the suite exactly as the line
     round drives it — source `lane:line-round`, `SANDBAR_LEDGER_REUSE=0`, the
     declared pool exclusion, a run-scoped ledger — and it must end with a summary
     that carries a run id, one header in the run-scoped ledger whose commit is the
     round's HEAD, and the runner's own read-back
     (`line_round_runner.read_header`) must ACCEPT that summary. This is the chain
     that died as `could-not-run:run_id_missing_from_summary` on every full round.
  B. THE DIAGNOSTIC CONTROL. The same round with `--only` writes no record and the
     summary carries no run id. A narrowed round stays a non-proof, and the skip is
     named on stderr.
  C. THE SCOPE CONTROL. The same exclusion from another source (a ticket) writes no
     record. The caliber exception belongs to the line round, never to an exclusion
     as such.
  D. THE HONESTY CONTROL. With no resolvable commit identity the round writes no
     record and no invented header, and it names the missing identity.
  E. THE INVERTED CONTROL. The same round shape against a copy that carries the
     PRE-FIX order (the kill-switch early return before the commit identity is
     resolved) must reproduce the incident exactly: no run id, no header, and the
     runner's read-back refusing with `run_id_missing_from_summary`. Leg E proves
     leg A is not vacuous.

Layering and intent split (no intent-level duplication):
  * the store and CLI contract (minting, refusals, legacy tolerance, interrupted
    runs) -> t261009-11-run-record-store;
  * the drivers journey (executor as top driver, gate-owned round, legacy rows,
    gate face) -> t261009-11-run-record-drivers;
  * the reuse keys and the kill-switch face -> t260930-01-ledger-reuse-round;
  * the runner-to-header contract, red-is-a-proof, timeout, process-group reclaim
    -> t261009-77-line-round-runner;
  * the conflict plan and the landing decision -> the t261009-30 / t261009-28
    families.
  This entry uniquely owns the ROUND SHAPE join: the line round's own source, the
  killed reuse, and the declared exclusion must still mint a proof the runner can
  relay. The fixture technique (a real git fixture tree plus the real suite entry
  point with an injected one-entry registry) is shared with
  t260930-01-sc_ledger_reuse_round and t261009-11-run-record-drivers; shared steps
  are not shared intent.

Safety: the fixture tree and every ledger live in this scenario's private temp
directory (finally plus atexit reclaim). The real ledger is never written
(`SANDBAR_SCENARIO_LEDGER_DIR` projection). No port, no console (never 3099), no
docker, no Temporal server.

Three states: a missing `git`, `python3`, or suite module = ENV_FAIL exit 2. A
missing relayable proof = FAIL with a named leg (the TDD signal before the landing;
green is required at the integration gate).
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
NAME = "t261013-04-line-round-run-record"
EXCLUDE_POOL = "exclusive"        # the round's declared exclusion
SOURCE = "lane:line-round"        # the round's declared ledger source

sys.path.insert(0, str(REPO / "integration"))
import scenario_ledger as sl  # noqa: E402
from lib_env import clean_narrowing_env  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

# copied into the fixture: the real suite entry, its store, and its helpers
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
    """The fixture round's one scenario: it prints one canonical case line."""
    return (
        "import json\n"
        "print(json.dumps({'name': 't261013-04-fixture-case',\n"
        "                  'suite': 'main', 'status': 'pass', 'cause': None,\n"
        "                  'reason': None, 'evidence': 'fixture', 'dur_s': 0.01,\n"
        "                  'started': '2026-10-13T00:00:00+00:00', 'git_sha': '',\n"
        "                  'attempt': 1}, ensure_ascii=False))\n")


def _build_tree(root: Path, use_git: bool, mutate: bool = False) -> Path:
    """A private tree: the REAL suite with an injected one-entry registry.

    `use_git` False leaves the tree without a repository, which is the honesty
    leg's input: no commit identity is resolvable there. `mutate` True plants the
    PRE-FIX order back into the copy under test — an early return on the reuse kill
    switch that runs before the commit identity is resolved — so the inverted
    control can prove the positive leg is not vacuous.
    """
    tree = root / ("tree-git" if use_git else "tree-nogit") \
        if not mutate else (root / "tree-mutated")
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
    script = fixtures / ("case_%s.py" % ("git" if use_git else "nogit"))
    script.write_text(_fixture_script(), encoding="utf-8")
    # Registry injection: keep the file byte-identical except for the registry
    # body (the same seam the run-record scenarios share).
    text = (integ / "run_scenarios.py").read_text(encoding="utf-8")
    entry = ('    (%r,\n'
             '     "fixture: one minimal round injected by the t261013-04 line-round '
             'run-record scenario (not part of the real registry)",\n'
             '     "python3 %s", "ro"),\n]' % (NAME, script))
    head, sep, _tail = text.partition("\nSCENARIOS = [")
    if not sep:
        env_fail(NAME, "run_scenarios registry anchor missing (SCENARIOS = [ moved)")
    text = head + sep + "\n" + entry + \
        text.split("\nSCENARIOS = [", 1)[1].split("\n]", 1)[1]
    (integ / "run_scenarios.py").write_text(text, encoding="utf-8")
    if mutate:
        text = (integ / "run_scenarios.py").read_text(encoding="utf-8")
        anchor = "    head, dirty = _tree_state(root)\n"
        if anchor not in text:
            env_fail(NAME, "identity anchor moved in the tree under test "
                           "(head, dirty = _tree_state(root) not found) — the "
                           "inverted control cannot be planted")
        planted = (
            "    if str(os.environ.get(LEDGER_REUSE_ENV, \"\")).strip().lower() "
            "in _REUSE_OFF_WORDS:\n"
            "        plan[\"disabled_reason\"] = (\"mutation: identity resolved \"\n"
            "                                   \"after the kill switch\")\n"
            "        return plan\n")
        text = text.replace(anchor, planted + anchor, 1)
        (integ / "run_scenarios.py").write_text(text, encoding="utf-8")
        try:
            compile(text, "run_scenarios.py", "exec")
        except SyntaxError as e:  # noqa: BLE001 — a broken plant is a named stop
            env_fail(NAME, "the planted pre-fix order does not compile: %s" % e)
    (tree / ".gitignore").write_text("out/\n__pycache__/\n", encoding="utf-8")
    (tree / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/run_scenarios.py\n",
        encoding="utf-8")
    if use_git:
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
    """The round's environment, built the way the line round builds it.

    The inherited narrowing knobs are stripped first (house rule L12). A key whose
    value is None is removed, which is how a leg drops the source or the ticket id.
    """
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
    env = clean_narrowing_env(declared)
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
    return env


def _run_round(tree: Path, ledger: Path, argv_extra=None, env_extra=None):
    argv = ["python3", "integration/run_scenarios.py"] + list(argv_extra or [])
    try:
        p = subprocess.run(argv, cwd=str(tree), capture_output=True, text=True,
                           timeout=300, env=_round_env(ledger, env_extra or {}))  # SANCTIONED-WAIT: drives the real suite over a private fixture tree; a hard 300 s outer deadline, expiry returns the named -9 could-not-run, never a poll
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


def _headers(ledger: Path):
    return _jsonl(ledger / RUNS_NAME)


def _rows(ledger: Path):
    return _jsonl(ledger / ROWS_NAME)


READBACK = r"""
import json, sys
sys.path.insert(0, sys.argv[1])          # this checkout's runner (the tree under test)
import line_round_runner as R
header, why = R.read_header(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
print(json.dumps({"header": header, "why": why}, ensure_ascii=False))
"""


def _readback(tree: Path, ledger: Path, summary: dict):
    """Read the proof back through the runner's own acceptance face."""
    p = subprocess.run(
        ["python3", "-c", READBACK, str(REPO / "integration"), str(tree),
         str(ledger), json.dumps(summary, ensure_ascii=False)],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,  # SANCTIONED-WAIT: one bounded readback process, hard 120 s ceiling, a failure is named, never a poll
        env=clean_narrowing_env({"PYTHONPATH": str(REPO / "integration")}))
    if p.returncode != 0:
        return None, "readback_process_failed:%s" % (p.stderr or p.stdout)[-200:]
    for line in reversed((p.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                got = json.loads(line)
            except ValueError:
                continue
            return got.get("header"), got.get("why")
    return None, "readback_produced_no_answer"


# ---------------------------------------------------------------- legs

def _fresh_ledger(name: str) -> Path:
    ledger = Path(str(_TMP)) / ("ledger-" + name)
    ledger.mkdir()
    return ledger


def _leg_a(tree: Path, head_sha: str):
    ledger = _fresh_ledger("a")
    rc, out, err = _run_round(tree, ledger,
                              argv_extra=["--exclude-pools", EXCLUDE_POOL])
    summary = _summary(out)
    ok(summary is not None, "A1 the round completes and prints a summary line",
       "rc=%s | %s" % (rc, out[-400:]))
    if summary is None:
        return
    ok(int(summary.get("ran") or 0) >= 1 and int(summary.get("reused") or 0) == 0,
       "A2 the round really ran its case and reused nothing (the kill switch holds)",
       "ran=%s reused=%s" % (summary.get("ran"), summary.get("reused")))
    run_id = summary.get("run_id")
    ok(isinstance(run_id, str) and run_id.strip(),
       "A3 the summary carries a run id (exactly the runner's face)", repr(run_id))
    headers = _headers(ledger)
    ok(len(headers) == 1, "A4 exactly one header lands in the run-scoped ledger",
       str(len(headers)))
    if headers:
        header = headers[0]
        ok(header.get("id") == run_id,
           "A5 the header answers by the summary's run id",
           "%r vs %r" % (header.get("id"), run_id))
        repos = header.get("repos") or []
        revision = str((repos[0] or {}).get("revision") or "") if repos else ""
        ok(revision == head_sha,
           "A6 the header's revision is the round's HEAD although reuse was killed",
           "%r vs %r" % (revision, head_sha))
        ok(str(header.get("source") or "") == SOURCE,
           "A6b the header records the round's declared source",
           repr(header.get("source")))
    rows = [r for r in _rows(ledger) if r.get("run") == run_id]
    ok(bool(rows), "A7 the run's own case rows are in the ledger", str(len(rows)))
    header, why = _readback(tree, ledger, summary)
    ok(why is None,
       "A8 the runner's read-back accepts the summary (never "
       "run_id_missing_from_summary)", str(why))
    ok((header or {}).get("id") == run_id,
       "A9 the relayed header is this round's", json.dumps(header)[:300])


def _leg_b(tree: Path):
    ledger = _fresh_ledger("b")
    rc, out, err = _run_round(tree, ledger,
                              argv_extra=["--only", NAME,
                                          "--exclude-pools", EXCLUDE_POOL])
    summary = _summary(out)
    ok(summary is not None, "B1 the diagnostic round still completes",
       "rc=%s | %s" % (rc, out[-300:]))
    ok(not (summary or {}).get("run_id"),
       "B2 a --only diagnostic round carries NO run id (a narrowed round is not "
       "a proof)", repr((summary or {}).get("run_id")))
    ok(not _headers(ledger), "B3 the diagnostic round lands no header",
       str(len(_headers(ledger))))
    ok(bool((err or "").strip()) and "narrow" in (err or "").lower(),
       "B4 the refusal is named on stderr, never silent", (err or "")[-300:])


def _leg_c(tree: Path):
    ledger = _fresh_ledger("c")
    rc, out, err = _run_round(
        tree, ledger, argv_extra=["--exclude-pools", EXCLUDE_POOL],
        env_extra={"SANDBAR_INTEG_LEDGER_SOURCE": None,
                   "SANDBAR_TICKET_ID": "t261013-04-other-source"})
    summary = _summary(out)
    ok(summary is not None, "C1 the control round completes", "rc=%s" % rc)
    ok(not (summary or {}).get("run_id"),
       "C2 the same exclusion from another source carries NO run id (the caliber "
       "belongs to the line round)", repr((summary or {}).get("run_id")))
    ok(not _headers(ledger), "C3 the control round lands no header",
       str(len(_headers(ledger))))


def _leg_d(tree: Path):
    ledger = _fresh_ledger("d")
    rc, out, err = _run_round(tree, ledger,
                              argv_extra=["--exclude-pools", EXCLUDE_POOL])
    summary = _summary(out)
    ok(summary is not None, "D1 the round completes without a commit identity",
       "rc=%s | %s" % (rc, out[-300:]))
    ok(not (summary or {}).get("run_id"),
       "D2 an unresolvable commit identity yields NO run id",
       repr((summary or {}).get("run_id")))
    ok(not _headers(ledger), "D3 no header is invented",
       str(len(_headers(ledger))))
    ok("HEAD" in (err or "") or "commit" in (err or "").lower()
       or "git" in (err or "").lower(),
       "D4 the missing identity is named on stderr", (err or "")[-300:])


def _leg_e(tree: Path, head_sha: str):
    """The inverted control: the pre-fix order must reproduce the incident.

    The copy under test carries an early return on the reuse kill switch placed
    BEFORE the commit identity is resolved. The same round shape as leg A must then
    die exactly as the line rounds died: no run id, no header, and the runner's
    read-back refusing with its own reason string.
    """
    ledger = _fresh_ledger("e")
    rc, out, err = _run_round(tree, ledger,
                              argv_extra=["--exclude-pools", EXCLUDE_POOL])
    summary = _summary(out)
    ok(summary is not None, "E1 the mutated round still completes (the control "
       "reaches the write path)", "rc=%s | %s" % (rc, out[-300:]))
    ok(not (summary or {}).get("run_id"),
       "E2 the pre-fix order yields NO run id (the incident's shape)",
       repr((summary or {}).get("run_id")))
    ok(not _headers(ledger), "E3 no header is invented either",
       str(len(_headers(ledger))))
    if summary is not None:
        header, why = _readback(tree, ledger, summary)
        ok(why == "run_id_missing_from_summary",
           "E4 the runner refuses with its own incident reason "
           "(run_id_missing_from_summary)", repr(why))
    ok(str(head_sha).strip() != "",
       "E5 the control ran against a real HEAD (the mutation is the only "
       "difference from leg A)", head_sha)


def main() -> int:
    global _TMP
    if shutil.which("git") is None:
        env_fail(NAME, "git missing — the fixture tree and the identity leg "
                       "cannot run")
    if shutil.which("python3") is None:
        env_fail(NAME, "python3 missing")
    _TMP = Path(tempfile.mkdtemp(prefix="sc_t26101304_"))
    try:
        tree = _build_tree(_TMP, use_git=True)
        head = _git("rev-parse", "HEAD", cwd=tree)
        if head.returncode != 0:
            env_fail(NAME, "fixture HEAD unreadable: %s" % head.stderr[-200:])
        head_sha = head.stdout.strip()
        _leg_a(tree, head_sha)
        _leg_b(tree)
        _leg_c(tree)
        _leg_e(_build_tree(_TMP, use_git=True, mutate=True), head_sha)
        _leg_d(_build_tree(_TMP, use_git=False))
    finally:
        _cleanup()
    finish(NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
